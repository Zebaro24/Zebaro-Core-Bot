import json
import logging
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.interfaces.tg.formatters.site_contact import site_contact_to_html  # noqa: E402
from src.interfaces.tg.keyboards.site_contact import get_site_contact_kb  # noqa: E402
from src.interfaces.webhooks.routes import site  # noqa: E402
from src.services.site_contact import ContactRateLimit, SiteContact  # noqa: E402

TOKEN = "site-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SECRET_TEXT = "We have a role for you, write back please"


def _body(**overrides):
    body = {
        "name": "Olena",
        "reply": "@olena_hr",
        "message": SECRET_TEXT,
        "locale": "en",
        "sender": "eff8e7ca506627fe",
        "sentAt": "2026-09-23T10:31:09.710Z",
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _fresh_limit():
    site.rate_limit.reset()
    yield
    site.rate_limit.reset()


@pytest.fixture
def settings(mocker):
    mocked = mocker.patch.object(site, "settings")
    mocked.site_contact_token = TOKEN
    mocked.telegram_admin_id = 42
    return mocked


@pytest.fixture
def bot():
    return MagicMock(send_message=AsyncMock())


@pytest.fixture
def app(settings, bot):
    app = FastAPI()
    app.state.bot = bot
    app.include_router(site.router, prefix="/site")
    return app


@pytest.fixture
def send(app):
    """A real HTTP request through FastAPI; returns the status code."""

    async def _send(content: bytes, headers: dict[str, str]) -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://zebaro-core-bot:8000") as client:
            response = await client.post("/site/contact", content=content, headers=headers)
        return response.status_code

    return _send


@pytest.fixture
def post(send):
    async def _post(headers=None, **overrides):
        headers = AUTH if headers is None else headers
        return await send(json.dumps(_body(**overrides)).encode(), {"Content-Type": "application/json", **headers})

    return _post


@pytest.mark.asyncio
async def test_a_message_goes_to_the_owner(post, bot):
    assert await post() == 202

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 42
    assert "Olena" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://t.me/olena_hr"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}])
@pytest.mark.asyncio
async def test_a_wrong_or_missing_token_is_refused(post, bot, headers):
    assert await post(headers=headers) == 401
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unset_token_closes_the_endpoint(post, settings, bot):
    settings.site_contact_token = ""
    assert await post(headers={"Authorization": "Bearer "}) == 401
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_request_through_the_public_tunnel_does_not_see_the_endpoint(post, bot):
    assert await post(headers={**AUTH, "Cf-Connecting-Ip": "1.2.3.4"}) == 404
    bot.send_message.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [{"message": "short"}, {"locale": "de"}, {"sender": "not-a-hex-hash!!"}, {"name": "x"}, {"reply": "x" * 121}],
)
def test_invalid_fields_are_rejected(overrides):
    # FastAPI answers 422 when the body does not validate against this model.
    with pytest.raises(ValidationError):
        SiteContact(**_body(**overrides))


@pytest.mark.asyncio
async def test_one_sender_gets_five_messages_an_hour(post):
    codes = [await post() for _ in range(6)]
    assert codes == [202] * 5 + [429]


@pytest.mark.asyncio
async def test_everyone_together_gets_thirty_an_hour(post):
    codes = [await post(sender=f"{i:016x}") for i in range(31)]
    assert codes == [202] * 30 + [429]


def test_the_limit_window_slides():
    limit = ContactRateLimit(window_s=3600, per_sender=1)
    assert limit.allow("a", now=0)
    assert not limit.allow("a", now=10)
    assert limit.allow("a", now=3601)


@pytest.mark.asyncio
async def test_telegram_refusing_is_a_503_and_the_text_never_reaches_the_logs(post, bot, caplog):
    bot.send_message.side_effect = RuntimeError("Bad Request: chat not found")

    with caplog.at_level(logging.INFO, logger="webhooks.site"):
        assert await post() == 503

    assert SECRET_TEXT not in caplog.text
    assert "eff8e7ca506627fe" in caplog.text


@pytest.mark.asyncio
async def test_no_bot_yet_is_a_503(app, post):
    app.state.bot = None
    assert await post() == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"{not json", b"{}"])
async def test_outside_requests_get_404_whatever_the_body(send, content):
    # The body used to be parsed first: an empty one answered 422 and showed the path exists.
    assert await send(content, {"Cf-Connecting-Ip": "1.2.3.4", **AUTH}) == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"{not json"])
async def test_a_tokenless_request_gets_401_whatever_the_body(send, content):
    assert await send(content, {"Content-Type": "application/json"}) == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"{not json", json.dumps(_body(message="short")).encode()])
async def test_a_bad_body_with_the_token_is_a_422(send, content):
    assert await send(content, {"Content-Type": "application/json", **AUTH}) == 422


@pytest.mark.asyncio
async def test_the_delivered_log_line_has_no_text(post, caplog):
    with caplog.at_level(logging.INFO, logger="webhooks.site"):
        await post()
    assert "delivered" in caplog.text
    assert SECRET_TEXT not in caplog.text


def test_everything_the_visitor_typed_is_escaped():
    contact = SiteContact(**_body(name="<script>x</script>", message="<b>hi</b> & <i>more text</i>"))
    text = site_contact_to_html(contact)
    assert "<script>" not in text
    assert "&lt;script&gt;x&lt;/script&gt;" in text
    assert "&lt;b&gt;hi&lt;/b&gt; &amp; &lt;i&gt;more text&lt;/i&gt;" in text
    assert "🇬🇧" in text
    assert "23.09 10:31 UTC · eff8e7" in text


@pytest.mark.parametrize(
    "reply,url",
    [
        ("@olena_hr", "https://t.me/olena_hr"),
        ("https://linkedin.com/in/olena", "https://linkedin.com/in/olena"),
        ("olena@example.com", None),
        ("+380 67 123 45 67", None),
        ("@ab", None),  # too short for a Telegram username
    ],
)
def test_reply_button(reply, url):
    keyboard = get_site_contact_kb(reply)
    assert (keyboard.inline_keyboard[0][0].url if keyboard else None) == url

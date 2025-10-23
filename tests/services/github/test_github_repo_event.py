import pytest

from app.services.github.github_repo_event import GithubRepoEvent


@pytest.fixture
def github_event(mocker):
    bot = mocker.MagicMock()
    bot.send_message = mocker.AsyncMock()
    bot.edit_message_text = mocker.AsyncMock()

    return GithubRepoEvent(full_repo_name="user/repo", bot=bot, tg_chat_id=12345)


@pytest.mark.asyncio
async def test_send_message_calls_bot_send(mocker, github_event):
    send_message_mock = mocker.patch.object(github_event.bot, "send_message")
    await github_event.send_message("hello")
    send_message_mock.assert_called_once_with(12345, "hello", message_thread_id=None)


@pytest.mark.asyncio
async def test_send_or_edit_message_new_message(mocker, github_event):
    github_event._messages_cache = {}
    send_message_mock = mocker.patch.object(github_event.bot, "send_message")
    send_message_mock.return_value.message_id = 99

    await github_event.send_or_edit_message("key1", "text")

    send_message_mock.assert_called_once()
    assert github_event._messages_cache["key1"] == 99


@pytest.mark.asyncio
async def test_send_or_edit_message_edit_existing(mocker, github_event):
    github_event._messages_cache = {"key1": 42}
    edit_message_text_mock = mocker.patch.object(github_event.bot, "edit_message_text")
    send_message_mock = mocker.patch.object(github_event.bot, "send_message")

    await github_event.send_or_edit_message("key1", "new text")

    edit_message_text_mock.assert_called_once_with(chat_id=12345, message_id=42, text="new text")
    send_message_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_calls_event_method(mocker, github_event):
    async def custom_event(custom_payload):
        return custom_payload

    custom_mock = mocker.AsyncMock(wraps=custom_event)
    github_event.test_event = custom_mock
    payload = {"a": 1}
    await github_event.handle("test_event", payload)
    custom_mock.assert_called_once_with(payload)


@pytest.mark.asyncio
async def test_handle_logs_warning_for_unknown_event(caplog, github_event):
    caplog.set_level("WARNING")
    await github_event.handle("unknown_event", {})
    assert "No handler for the event: unknown_event" in caplog.text

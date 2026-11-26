import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())

from fake_jobs import SqlJobs, SqlMeta

from src.interfaces.tg.notification import review_summary
from src.interfaces.tg.notification.review_summary import SUMMARY_CHUNK, place


def _doc(n: int, **fields):
    return {
        "_id": f"{n:024x}",
        "title": f"Engineer {n}",
        "company": "Acme",
        "platform_name": "Dou",
        "moderation": "review",
        "user_status": "pending",
        "found_at": datetime(2026, 11, 16),
        **fields,
    }


@pytest.fixture
def stores(sql_db, mocker):
    jobs, meta = SqlJobs(sql_db, mocker), SqlMeta(sql_db)
    mocker.patch.object(review_summary, "today", return_value="2026-11-16")
    return jobs, meta


def _bot(first_id: int = 100):
    bot = MagicMock()
    counter = iter(range(first_id, first_id + 100))

    async def send(**_):
        return MagicMock(chat=MagicMock(id=1), message_id=next(counter))

    bot.send_rich_message = AsyncMock(side_effect=send)
    bot.edit_message_text = AsyncMock()
    return bot


def test_place_fills_the_last_part_and_opens_a_new_one_past_the_chunk():
    parts = place([], [f"id{n}" for n in range(SUMMARY_CHUNK + 3)])
    assert [len(part["ids"]) for part in parts] == [SUMMARY_CHUNK, 3]

    again = place(parts, ["id0", "new"])  # a vacancy already shown is not added twice
    assert [len(part["ids"]) for part in again] == [SUMMARY_CHUNK, 4]
    assert len(parts[-1]["ids"]) == 3  # the input stays as it was


@pytest.mark.asyncio
async def test_a_later_run_edits_the_days_message_instead_of_sending_another(stores):
    jobs, meta = stores
    jobs.docs.extend(_doc(n) for n in range(3))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()

    assert await review_summary.add_to_summary(bot, ids[:2]) == 2
    assert await review_summary.add_to_summary(bot, ids[2:]) == 1

    bot.send_rich_message.assert_awaited_once()
    assert bot.send_rich_message.await_args.kwargs["disable_notification"] is True
    edit = bot.edit_message_text.await_args
    assert edit.kwargs["message_id"] == 100
    assert "Частичные совпадения за 16.11 — 3" in edit.kwargs["rich_message"].html
    assert meta.by_id("review_summary:2026-11-16")["parts"][0]["ids"] == ids
    assert all(doc["review_day"] == "2026-11-16" for doc in jobs.docs)


@pytest.mark.asyncio
async def test_a_new_day_starts_a_new_message(stores, mocker):
    jobs, _ = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()

    await review_summary.add_to_summary(bot, ids[:1])
    mocker.patch.object(review_summary, "today", return_value="2026-11-17")
    await review_summary.add_to_summary(bot, ids[1:])

    assert bot.send_rich_message.await_count == 2
    bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_deleted_message_is_sent_again(stores):
    jobs, meta = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()
    await review_summary.add_to_summary(bot, ids[:1])
    bot.edit_message_text.side_effect = TelegramBadRequest(method=MagicMock(), message="message to edit not found")

    await review_summary.add_to_summary(bot, ids[1:])

    assert bot.send_rich_message.await_count == 2
    assert meta.by_id("review_summary:2026-11-16")["parts"][0]["message_id"] == 101


@pytest.mark.asyncio
async def test_a_decided_vacancy_gets_its_status_mark_on_the_next_sync(stores):
    jobs, _ = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()
    await review_summary.add_to_summary(bot, ids)
    jobs.docs[1].update(user_status="not_interested", status_reason="role", review_stale=True)

    assert await review_summary.refresh_stale_summaries(bot) == 1

    html = bot.edit_message_text.await_args.kwargs["rich_message"].html
    assert "(решено 1)" in html
    assert "<p>2. 👎 <b>Engineer 1</b>" in html
    assert jobs.docs[1].get("review_stale") is None
    bot.send_rich_message.assert_awaited_once()  # a refresh never sends a new message


# --- the day's figures at the head (26.11.2026) ----------------------------------------------


def _stats(**fields):
    board = {"platform": "Dou", "searches": 3, "cards": 60, "failed": 0, "skipped": 0, "new": 6, "repeats": 0,
             "filtered_out": 6, "surfaced": 0}  # fmt: skip
    base = {
        "day": "2026-11-16", "runs": 5, "last_run": "13:05", "browser_down": 0, "home_down": 0,
        "platforms": [board], "cards": 60, "new": 6, "repeats": 0, "filtered_out": 6,
        "reasons": {"not a developer role": 4, "other stack": 1, "lead": 1},
        "by_tier": {"top": 0, "sent": 0, "review": 0},
        "broken": [], "not_searched": [], "skipped": [],
    }  # fmt: skip
    return {**base, **fields}


@pytest.mark.asyncio
async def test_from_ten_the_figures_come_even_with_no_partial_match(stores, mocker):
    _, meta = stores
    mocker.patch.object(review_summary.runs, "day_stats", AsyncMock(return_value=_stats()))
    bot = _bot()
    clock = mocker.patch.object(review_summary, "datetime", wraps=datetime)

    clock.now.return_value = datetime(2026, 11, 16, 9, 5)
    assert await review_summary.add_to_summary(bot, []) == 0
    bot.send_rich_message.assert_not_awaited()  # before ten: nothing to say yet

    clock.now.return_value = datetime(2026, 11, 16, 10, 5)
    await review_summary.add_to_summary(bot, [])

    text = bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert "📊 Поиск за 16.11 · обновлено 13:05" in text
    assert "Просмотрено <b>60</b> карточек · новых <b>6</b> · отсеяно <b>6</b> · прислано <b>0</b>" in text
    assert "Отсеяно: не разработка 4 · другой основной стек 1 · lead / head / architect 1" in text
    assert "✅ Площадки отвечают — под тебя пока ничего нового: это рынок, а не поломка" in text
    assert text.index("📊") < text.index("👀 Частичных совпадений пока нет")
    assert meta.by_id("review_summary:2026-11-16")["parts"][0]["ids"] == []


@pytest.mark.asyncio
async def test_the_figures_head_the_first_part_only_and_follow_each_run(stores, mocker):
    jobs, _ = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    stats = mocker.patch.object(review_summary.runs, "day_stats", AsyncMock(return_value=_stats()))
    bot = _bot()

    await review_summary.add_to_summary(bot, ids[:1])
    stats.return_value = _stats(cards=80, skipped=["LinkedIn"], home_down=5)
    await review_summary.add_to_summary(bot, [])  # a run with nothing new still refreshes the figures

    text = bot.edit_message_text.await_args.kwargs["rich_message"].html
    assert "Просмотрено <b>80</b> карточек" in text and "Частичные совпадения за 16.11 — 1" in text
    assert "🏠 ПК не отвечал весь день — пропущены: LinkedIn" in text
    assert "✅ Остальные площадки отвечают" in text


def test_a_broken_board_and_a_dead_browser_say_so():
    from src.interfaces.tg.formatters.job import day_stats_html, day_stats_plain

    stats = _stats(broken=["No Fluff Jobs"], browser_down=2)
    text = day_stats_html(stats)

    assert "❗ Браузер был недоступен в 2 из 5 прогонов" in text
    assert "❗ <b>No Fluff Jobs</b>: страницы открылись, но без единой карточки" in text
    assert "✅" not in text
    assert "<details><summary>📋 По площадкам и всем фильтрам</summary>" in text
    assert "Dou — 60 карточек · новых 6 · отсеяно 6 · прислано 0" in text
    assert "<blockquote expandable>" in day_stats_plain(stats)


def test_pages_that_never_loaded_are_not_a_broken_parser_nor_a_quiet_market():
    from src.interfaces.tg.formatters.job import day_stats_html

    board = {"platform": "LinkedIn", "searches": 4, "cards": 0, "failed": 4, "skipped": 0, "new": 0, "repeats": 0,
             "filtered_out": 0, "surfaced": 0}  # fmt: skip
    text = day_stats_html(_stats(platforms=[board], broken=[]))

    assert "⚠️ Не открылись страницы: LinkedIn 4" in text
    assert "сломался парсер" not in text and "✅" not in text


def test_a_run_that_crashed_or_opened_nothing_is_never_a_quiet_market():
    from src.interfaces.tg.formatters.job import day_stats_html

    crashed = day_stats_html(_stats(crashed=1))
    nothing = day_stats_html(_stats(platforms=[], cards=0))

    assert "❗ Прогон упал с ошибкой: 1 из 5" in crashed and "✅" not in crashed
    assert "❗ Ни одна площадка сегодня не открылась" in nothing and "✅" not in nothing

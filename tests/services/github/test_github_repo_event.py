import pytest

from app.services.github.github_repo_event import GithubRepoEvent, TelegramBadRequest


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
    send_message_mock.assert_called_once_with(
        12345, "hello", message_thread_id=None, disable_web_page_preview=True, disable_notification=True
    )


@pytest.mark.asyncio
async def test_send_message_uses_thread_id(mocker, github_event):
    # Recreate instance with thread id
    bot = github_event.bot
    event_with_thread = GithubRepoEvent(full_repo_name="user/repo", bot=bot, tg_chat_id=12345, thread_id=777)

    send_message_mock = mocker.patch.object(event_with_thread.bot, "send_message")
    await event_with_thread.send_message("hello")
    send_message_mock.assert_called_once_with(
        12345, "hello", message_thread_id=777, disable_web_page_preview=True, disable_notification=True
    )


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
async def test_send_or_edit_message_edit_fails_fallback_to_send(mocker, github_event):
    github_event._messages_cache = {"k": 7}

    async def raise_bad_request(**_):
        raise TelegramBadRequest(mocker.MagicMock(), "Cannot edit")

    mocker.patch.object(github_event.bot, "edit_message_text", side_effect=raise_bad_request)
    send_message_mock = mocker.patch.object(github_event.bot, "send_message")
    send_message_mock.return_value.message_id = 55

    await github_event.send_or_edit_message("k", "hi")

    send_message_mock.assert_called_once()
    assert github_event._messages_cache["k"] == 55


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
async def test_handle_calls_sync_method(mocker, github_event):
    sync_mock = mocker.MagicMock()
    github_event.sync_event = sync_mock
    payload = {"b": 2}
    await github_event.handle("sync_event", payload)
    sync_mock.assert_called_once_with(payload)


@pytest.mark.asyncio
async def test_handle_logs_warning_for_unknown_event(caplog, github_event):
    caplog.set_level("WARNING")
    await github_event.handle("unknown_event", {})
    assert "No handler for the event: unknown_event" in caplog.text


@pytest.mark.asyncio
async def test_push_no_commits(mocker, github_event):
    payload = {
        "repository": {"full_name": "user/repo"},
        "pusher": {"name": "Alice"},
        "ref": "refs/heads/main",
        "commits": [],
    }

    send_mock = mocker.patch.object(github_event, "send_message", new=mocker.AsyncMock())
    await github_event.push(payload)

    assert send_mock.await_count == 1
    sent_text = send_mock.await_args.args[0]
    assert "GitHub Push" in sent_text
    assert "Alice" in sent_text and "main" in sent_text
    assert "Нет новых коммитов" in sent_text


@pytest.mark.asyncio
async def test_push_with_commits(mocker, github_event):
    payload = {
        "repository": {"full_name": "user/repo"},
        "pusher": {"name": "Bob"},
        "ref": "refs/heads/dev",
        "commits": [
            {
                "id": "abcdef1234567",
                "message": "Initial commit\nWith details",
                "author": {"name": "Bob"},
                "url": "https://example.com/commit/abcdef1",
            },
            {
                "id": "1234567890abcd",
                "message": "Fix bug",
                "author": {"name": "Eve"},
                "url": "https://example.com/commit/1234567",
            },
        ],
    }

    send_mock = mocker.patch.object(github_event, "send_message", new=mocker.AsyncMock())
    await github_event.push(payload)

    sent_text = send_mock.await_args.args[0]
    assert "Bob" in sent_text and "dev" in sent_text
    assert "<code>abcdef1</code>" in sent_text
    assert "Initial commit With details" in sent_text
    assert "(Eve)" in sent_text and "<code>1234567</code>" in sent_text


@pytest.mark.asyncio
async def test_pull_request_merged(mocker, github_event):
    payload = {
        "action": "closed",
        "pull_request": {
            "title": "Add feature",
            "user": {"login": "carol"},
            "html_url": "https://example.com/pr/1",
            "base": {"repo": {"full_name": "user/repo"}, "ref": "main"},
            "head": {"ref": "feature"},
            "merged": True,
            "created_at": "2025-10-20T10:00:00Z",
            "updated_at": "2025-10-21T11:00:00Z",
        },
    }

    send_mock = mocker.patch.object(github_event, "send_message", new=mocker.AsyncMock())
    await github_event.pull_request(payload)

    sent_text = send_mock.await_args.args[0]
    assert "Pull Request CLOSED" in sent_text
    assert "Merged!" in sent_text
    assert "feature" in sent_text and "main" in sent_text
    assert "carol" in sent_text


@pytest.mark.asyncio
async def test_pull_request_not_merged(mocker, github_event):
    payload = {
        "action": "opened",
        "pull_request": {
            "title": "WIP",
            "user": {"login": "dave"},
            "html_url": "https://example.com/pr/2",
            "base": {"repo": {"full_name": "user/repo"}, "ref": "dev"},
            "head": {"ref": "wip"},
            "merged": False,
            "created_at": "2025-10-20T10:00:00Z",
            "updated_at": "2025-10-21T11:00:00Z",
        },
    }

    send_mock = mocker.patch.object(github_event, "send_message", new=mocker.AsyncMock())
    await github_event.pull_request(payload)

    sent_text = send_mock.await_args.args[0]
    assert "Pull Request OPENED" in sent_text
    assert "Merged!" not in sent_text


@pytest.mark.asyncio
async def test_workflow_run_in_progress(mocker, github_event):
    payload = {
        "workflow_run": {
            "id": 101,
            "repository": {"full_name": "user/repo"},
            "name": "CI",
            "status": "in_progress",
            "conclusion": None,
            "actor": {"login": "dev"},
            "html_url": "https://example.com/workflow/101",
            "event": "push",
            "created_at": "2025-10-23T12:34:56Z",
        }
    }

    edit_mock = mocker.patch.object(github_event, "send_or_edit_message", new=mocker.AsyncMock())
    send_mock = mocker.patch.object(github_event, "send_message", new=mocker.AsyncMock())

    await github_event.workflow_run(payload)

    edit_mock.assert_awaited_once()
    key, text = edit_mock.await_args.args
    assert key == 101
    assert "CI" in text and "dev" in text and "push" in text
    assert "12:34" in text  # time parsed from ISO
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_run_success_sends_notification_and_deletes(mocker, github_event):
    payload = {
        "workflow_run": {
            "id": 202,
            "repository": {"full_name": "user/repo"},
            "name": "Build",
            "status": "completed",
            "conclusion": "success",
            "actor": {"login": "qa"},
            "html_url": "https://example.com/workflow/202",
            "event": "workflow_dispatch",
            "created_at": "2025-10-23T08:05:00Z",
        }
    }

    edit_mock = mocker.patch.object(github_event, "send_or_edit_message", new=mocker.AsyncMock())

    message = mocker.MagicMock()
    message.delete = mocker.AsyncMock()
    send_mock = mocker.patch.object(github_event, "send_message", new=mocker.AsyncMock(return_value=message))

    sleep_mock = mocker.patch("app.services.github.github_repo_event.asyncio.sleep", new=mocker.AsyncMock())

    await github_event.workflow_run(payload)

    edit_mock.assert_awaited_once()
    send_mock.assert_awaited_once()
    message.delete.assert_awaited_once()
    sleep_mock.assert_awaited_once_with(10)

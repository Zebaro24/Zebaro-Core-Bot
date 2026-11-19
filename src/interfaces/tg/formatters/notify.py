import html

from src.services.notify import Notice

_ICONS = {"done": "✅", "question": "❓", "plan": "📋", "attention": "🔔"}


def notice_to_html(notice: Notice) -> str:
    """`✅ <b>Zebaro-Core · mcp</b> — готово` and the text under it; everything sent is escaped."""
    where = html.escape(notice.project)
    if notice.repo:
        where += f" · {html.escape(notice.repo)}"
    head = f"{_ICONS[notice.event]} <b>{where}</b> — {html.escape(notice.title)}"
    return f"{head}\n{html.escape(notice.text)}" if notice.text else head

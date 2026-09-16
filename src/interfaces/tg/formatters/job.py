import html
from datetime import datetime

from src.services.job_searcher.container import Job

_MODERATION_BADGE = {
    "sent": "🔥",
    "review": "❓ (проверь сам)",
}


def job_to_html(job: Job) -> str:
    title = html.escape(job.title or "")
    platform = html.escape(job.platform_name or "")
    company = html.escape(job.company or "")

    badge = _MODERATION_BADGE.get(job.moderation or "")
    text = f"{badge} {title} - {platform}\n" if badge else f"{title} - {platform}\n"
    text += f"Company: <b>{company}</b>"

    if job.date:
        date_str = job.date.strftime("%d.%m.%Y") if isinstance(job.date, datetime) else str(job.date)
        text += f" Date: <i>{html.escape(date_str)}</i>"

    if job.similar_to and job.similar_to_platform:
        text += f"\n🔁 Похоже, уже видел на {html.escape(job.similar_to_platform)}"

    if job.description:
        description_text = "\n".join(html.escape(job.description).splitlines())
        text += f"\nDescription:\n<blockquote expandable>{description_text}</blockquote>"

    return text

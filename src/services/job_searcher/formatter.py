import html
from datetime import datetime

from src.services.job_searcher.container import Job


def job_to_html(job: Job) -> str:
    title = html.escape(job.title or "")
    platform = html.escape(job.platform_name or "")
    link = job.link or ""
    company = html.escape(job.company or "")

    text = f'<a href="{link}">{title} - {platform}</a>\n'
    text += f"Company: <b>{company}</b>"

    if job.date:
        date_str = job.date.strftime("%d.%m.%Y") if isinstance(job.date, datetime) else str(job.date)
        text += f" Date: <i>{html.escape(date_str)}</i>"

    if job.description:
        description_text = "\n".join(html.escape(job.description).splitlines())
        text += f"\nDescription:\n<blockquote>{description_text}</blockquote>"

    return text

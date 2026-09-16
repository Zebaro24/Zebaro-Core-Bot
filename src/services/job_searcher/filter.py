import logging
import re
from collections.abc import Iterable

from src.services.job_searcher.container import Job, JobStorage

logger = logging.getLogger("job_searcher.filter")

POSITIVE_TITLE = {  # вес x2 при совпадении в title
    "python": 3,
    "fastapi": 2,
    "typescript": 2,
    "next.js": 2,
    "django": 1,
    "fullstack": 3,
    "full stack": 3,
    "full-stack": 3,
    "ai": 2,
    "llm": 3,
    "agent": 2,
    "agentic": 3,
    "mcp": 2,
    "ai-native": 3,
    "founding engineer": 3,
    "product engineer": 3,
}
POSITIVE_DESCRIPTION = POSITIVE_TITLE  # вес x1, те же ключи, ищем в description

HARD_REJECT_TITLE = ["ai training", "розмітка", "data labeling", "викладач", "тренер", "odoo", "qa", "lead"]
HARD_REJECT_COMPANY = ["фоп", "school"]

FRONTEND_ONLY_HINTS = ["frontend", "front-end", "front end"]
BACKEND_HINTS = ["python", "fastapi", "django", "backend", "fullstack", "full stack", "full-stack"]
AI_HINTS = ["ai", "llm", "ml", "agent", "gpt", "genai", "agentic"]
JUNIOR_HINTS = ["junior", "trainee", "intern"]
SENIOR_HINTS = ["senior"]

SEND_THRESHOLD = 5  # score >= 5 -> moderation="sent"
REVIEW_THRESHOLD = 2  # 2 <= score < 5 -> moderation="review" (label ❓)
# score < 2 -> moderation="rejected_by_filter" (не шлётся)


def _contains(text: str, keyword: str) -> bool:
    # \b по границам слов — иначе короткие токены вроде "ai"/"ml" ловят "email"/"container"/"html" и т.п.
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(_contains(text, keyword) for keyword in keywords)


def _matched_keywords(text: str, keywords: Iterable[str]) -> set[str]:
    return {keyword for keyword in keywords if _contains(text, keyword)}


class JobFilter:
    def __init__(self, job_storage: JobStorage) -> None:
        self.job_storage = job_storage

    def classify_all(self) -> None:
        counts = {"sent": 0, "review": 0, "rejected_by_filter": 0}
        for job in self.job_storage.jobs:
            moderation, score = self.classify_job(job)
            job.moderation = moderation
            job.relevance_score = score
            counts[moderation] += 1
        logger.info(
            "Classified %d jobs: sent=%d review=%d rejected=%d",
            len(self.job_storage.jobs),
            counts["sent"],
            counts["review"],
            counts["rejected_by_filter"],
        )

    @staticmethod
    def classify_job(job: Job) -> tuple[str, int]:
        title = (job.title or "").lower()
        company = (job.company or "").lower()
        description = (job.description or "").lower()

        if _contains_any(title, HARD_REJECT_TITLE) or _contains_any(company, HARD_REJECT_COMPANY):
            return "rejected_by_filter", 0

        if _contains_any(title, FRONTEND_ONLY_HINTS) and not _contains_any(title, BACKEND_HINTS):
            return "rejected_by_filter", 0

        if _contains_any(title, JUNIOR_HINTS) and not _contains(title, "middle"):
            return "rejected_by_filter", 0

        if _contains_any(title, SENIOR_HINTS) and not _contains_any(title, AI_HINTS):
            return "rejected_by_filter", 0

        title_hits = _matched_keywords(title, POSITIVE_TITLE)
        score = sum(POSITIVE_TITLE[word] for word in title_hits) * 2

        description_hits = _matched_keywords(description, POSITIVE_DESCRIPTION)
        score += sum(POSITIVE_DESCRIPTION[word] for word in description_hits)

        if score >= SEND_THRESHOLD:
            return "sent", score
        if score >= REVIEW_THRESHOLD:
            return "review", score
        return "rejected_by_filter", score

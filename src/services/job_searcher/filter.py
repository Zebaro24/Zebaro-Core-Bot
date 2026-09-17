"""Relevance of a vacancy for the owner: skip, "partial match" or "your stack".

Two passes, because the full description costs a page load:

1. `prefilter_all` — title and company only. Seniority that does not fit (senior, lead,
   junior...) and roles that are not development at all (QA, recruiter...) are rejected
   here, and their vacancy pages are never opened.
2. `classify_all` — after the parser fetched full descriptions. Looks for the core stack
   in the title and the whole description and puts the vacancy into a tier.

Tiers (stored in `Job.moderation`, the values stats and the API already use):
  "sent"                🔥 your stack: a backend core (Python / FastAPI) AND a frontend
                        core (React / Next.js) both appear
  "review"              👀 partial: at least one core technology, or two bonus ones
  "rejected_by_filter"  not sent; `Job.filter_reason` says why

`relevance_score` only orders messages inside a tier: more core technologies first, a core
technology in the title counts extra, bonus technologies break ties.
"""

import logging
import re
from dataclasses import dataclass, field

from src.services.job_searcher.container import Job, JobStorage

logger = logging.getLogger("job_searcher.filter")

# The owner's main stack. A vacancy with both sides of it is the one to open first.
CORE_STACK: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "FastAPI": ("fastapi", "fast api"),
    "React": ("react", "react.js", "reactjs"),
    "Next.js": ("next.js", "nextjs"),
}
BACKEND_CORE = ("Python", "FastAPI")
FRONTEND_CORE = ("React", "Next.js")

# Nice to have: raises the order, and two of them make a vacancy worth a look on their own.
BONUS_STACK: dict[str, tuple[str, ...]] = {
    "TypeScript": ("typescript",),
    "Full-stack": ("fullstack", "full stack", "full-stack"),
    "Django": ("django",),
    "PostgreSQL": ("postgresql", "postgres"),
    "Docker": ("docker",),
    "AWS": ("aws",),
    "LLM": ("llm", "llms", "openai", "gpt"),
    "AI agents": ("ai agent", "ai agents", "agentic", "langchain", "langgraph", "mcp"),
    "RAG": ("rag",),
}

# Checked in the title only. The description of almost any vacancy mentions "senior engineers
# on the team", so looking there would reject everything.
SENIOR_WORDS = ("senior", "sr", "сеньйор", "сеньор")
LEAD_WORDS = (
    "lead", "team lead", "tech lead", "head", "principal", "staff", "architect", "director",
    "cto", "vp", "тімлід", "тимлид", "лід", "керівник",
)  # fmt: skip
JUNIOR_WORDS = ("junior", "jr", "trainee", "intern", "internship", "стажер", "стажист", "стажування", "джуніор")
MIDDLE_WORDS = ("middle", "mid", "мідл", "мидл")
WRONG_ROLE_WORDS = (
    "qa", "aqa", "tester", "test engineer", "ai training", "data labeling", "розмітка",
    "викладач", "тренер", "mentor", "ментор", "odoo", "1c", "1с", "recruiter", "рекрутер",
    "sales", "marketing", "project manager", "product manager", "designer", "дизайнер",
)  # fmt: skip
WRONG_COMPANY_WORDS = ("фоп", "school")

SENT = "sent"
REVIEW = "review"
REJECTED = "rejected_by_filter"
TIER_ORDER = {SENT: 0, REVIEW: 1, REJECTED: 2}

# Keywords that need more than a word boundary.
_SPECIAL_PATTERNS = {
    # React Native is mobile development, not the React the owner writes.
    "react": r"\breact\b(?![\s-]*native)",
}


def _pattern(keyword: str) -> str:
    # Word boundaries: short tokens like "ai" or "sr" must not match inside "email" or "srv".
    # A digit may follow ("Python3"), a letter may not.
    return _SPECIAL_PATTERNS.get(keyword, rf"(?<![\w.]){re.escape(keyword)}(?![^\W\d_])")


def _contains(text: str, keyword: str) -> bool:
    return re.search(_pattern(keyword), text) is not None


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains(text, keyword) for keyword in keywords)


def _found(text: str, stack: dict[str, tuple[str, ...]]) -> list[str]:
    return [name for name, keywords in stack.items() if _contains_any(text, keywords)]


@dataclass
class Verdict:
    moderation: str
    score: int = 0
    stack: list[str] = field(default_factory=list)
    bonus: list[str] = field(default_factory=list)
    reason: str | None = None


def title_reject_reason(title: str | None, company: str | None) -> str | None:
    title = (title or "").lower()
    company = (company or "").lower()
    has_middle = _contains_any(title, MIDDLE_WORDS)

    if _contains_any(company, WRONG_COMPANY_WORDS):
        return "company"
    if _contains_any(title, WRONG_ROLE_WORDS):
        return "not a developer role"
    if _contains_any(title, LEAD_WORDS):
        return "lead"
    # "Middle/Senior" and "Junior/Middle" still hire a middle — those stay.
    if _contains_any(title, SENIOR_WORDS) and not has_middle:
        return "senior"
    if _contains_any(title, JUNIOR_WORDS) and not has_middle:
        return "junior"
    return None


def evaluate(job: Job) -> Verdict:
    reason = title_reject_reason(job.title, job.company)
    if reason:
        return Verdict(REJECTED, reason=reason)

    title = (job.title or "").lower()
    text = f"{title}\n{(job.description or '').lower()}"
    stack = _found(text, CORE_STACK)
    bonus = _found(text, BONUS_STACK)
    score = 10 * len(stack) + 5 * len(_found(title, CORE_STACK)) + 2 * len(bonus)

    backend = any(name in stack for name in BACKEND_CORE)
    frontend = any(name in stack for name in FRONTEND_CORE)
    if backend and frontend:
        return Verdict(SENT, score, stack, bonus)
    if stack or len(bonus) >= 2:
        return Verdict(REVIEW, score, stack, bonus)
    return Verdict(REJECTED, score, stack, bonus, reason="no stack match")


class JobFilter:
    def __init__(self, job_storage: JobStorage) -> None:
        self.job_storage = job_storage

    def prefilter_all(self) -> list[Job]:
        """Reject by title and company. Returns the vacancies worth opening."""
        survivors = []
        for job in self.job_storage.jobs:
            reason = title_reject_reason(job.title, job.company)
            if reason:
                job.moderation, job.relevance_score, job.filter_reason = REJECTED, 0, reason
            else:
                survivors.append(job)
        logger.info("Title filter: %d of %d left", len(survivors), len(self.job_storage.jobs))
        return survivors

    def classify_all(self) -> None:
        counts = {SENT: 0, REVIEW: 0, REJECTED: 0}
        for job in self.job_storage.jobs:
            verdict = evaluate(job)
            job.moderation = verdict.moderation
            job.relevance_score = verdict.score
            job.matched_stack = verdict.stack
            job.matched_bonus = verdict.bonus
            job.filter_reason = verdict.reason
            counts[verdict.moderation] += 1
        # Messages go out best first: the tier, then the score inside it.
        self.job_storage.jobs.sort(key=lambda j: (TIER_ORDER.get(j.moderation or REJECTED, 2), -j.relevance_score))
        logger.info(
            "Classified %d jobs: your stack=%d partial=%d rejected=%d",
            len(self.job_storage.jobs),
            counts[SENT],
            counts[REVIEW],
            counts[REJECTED],
        )

    @staticmethod
    def classify_job(job: Job) -> tuple[str, int]:
        verdict = evaluate(job)
        return verdict.moderation, verdict.score

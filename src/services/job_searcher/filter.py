"""Relevance of a vacancy for the owner: skip, "partial", "your stack" or "right on target".

Two passes, because the full description costs a page load:

1. `prefilter_all` — the list card only: title, company, location, date and whatever the board
   shows apart from the text (Djinni's work format, countries, years and English; DOU's
   cities). Seniority that does not fit, internships, roles that are not development, a title
   built on another main stack, military units, an office, a country list without Austria and
   months-old postings are rejected here, and their vacancy pages are never opened.
2. `classify_all` — after the parser fetched full descriptions. Reads what the card did not
   say out of the text (services/job_searcher/extract.py), rejects what asks for too much,
   then looks for the core stack and puts the vacancy into a tier.

Tiers (stored in `Job.moderation`, the values stats and the API use):
  "top"                 🔥🔥🔥 right on target: your stack on both sides, the level fits, and
                        nothing in the conditions needs a second look
  "sent"                🔥 your stack: a backend core (Python / FastAPI) AND a frontend core
                        (React / Next.js) both appear
  "review"              👀 partial: at least one core technology, or two bonus ones
  "rejected_by_filter"  not sent; `Job.filter_reason` says why

`Job.warnings` lists what may not fit and is worth a look before applying — B2 English,
remote without "за кордоном", a line about living in Ukraine. A warning keeps a vacancy out of
"top" but never rejects it.

The owner's limits (06.10.2026): remote only, from Austria; English B1 (B2 in his Djinni
profile); up to three years of experience asked.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from src.services.job_searcher import extract
from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.extract import required_years

logger = logging.getLogger("job_searcher.filter")

__all__ = ["required_years"]  # re-exported: the tests and older callers import it from here

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

AI_TITLE_WORDS = ("ai", "llm", "genai", "agentic", "ml", "machine learning")

# Checked in the title only. The description of almost any vacancy mentions "senior engineers
# on the team", so looking there would reject everything — extract.senior_in_description
# looks only for "we are looking for a senior".
SENIOR_WORDS = ("senior", "sr", "сеньйор", "сеньор")
LEAD_WORDS = (
    "lead", "team lead", "tech lead", "head", "principal", "staff", "architect", "director",
    "cto", "vp", "тімлід", "тимлид", "лід", "керівник", "leader",
)  # fmt: skip
# Juniors are welcome: a strong junior with two years of work is the owner's level. An
# internship or a trainee position is not — "Trainee/Junior" included (06.10.2026).
INTERN_WORDS = (
    "trainee", "intern", "internship", "стажер", "стажёр", "стажист", "стажування", "стажировка",
)  # fmt: skip
JUNIOR_WORDS = ("junior", "jr", "джуніор", "джун")
MIDDLE_WORDS = ("middle", "mid", "мідл", "мидл")
WRONG_ROLE_WORDS = (
    "qa", "aqa", "tester", "test engineer", "sdet", "ai training", "data labeling", "розмітка",
    "annotator", "анотатор", "викладач", "тренер", "mentor", "ментор", "instructor", "інструктор",
    "teacher", "tutor", "for kids", "для дітей", "odoo", "1c", "1с", "recruiter", "рекрутер",
    "sales", "manager", "менеджер", "product owner", "designer", "дизайнер", "business analyst",
    "systems analyst", "data analyst", "аналітик", "analytics engineer", "advocate", "consultant",
    "content", "creator", "writer", "copywriter", "motion", "security", "customer success",
    "growth hacker", "engagement specialist", "бухгалтер", "accountant", "artist", "illustrator",
    "talent acquisition", "hr",
)  # fmt: skip
# "Support Engineer" is a developer when the job is fixing and improving the product, and a
# help desk otherwise — told apart by the description (see _plain_support).
# Whole words: a keyword never matches with a letter after it, so every form is listed.
SUPPORT_WORDS = ("support", "сапорт", "підтримка", "підтримки", "підтримку", "підтримці")
_DEVELOPER_WORK = re.compile(
    r"\b(develop\w*|bug ?fix\w*|fix(ing)? bugs|codebase|pull requests?|розробк\w*|розробля\w*|"
    r"виправля\w*|доробк\w*|implement\w*)\b"
)
# A title that names another main stack. The owner answered none of these in a week of
# decisions (0 of ~25 by 23.09.2026) even with React beside it: "React and C#", "Python &
# Angular". Node.js is not here — "Node + React" full-stack positions he does take.
OTHER_STACK_WORDS = (
    "java", "kotlin", "c#", ".net", "php", "laravel", "angular", "vue", "vue.js",
    "react native", "flutter", "android", "ios", "mobile developer", "ruby", "rails", "golang",
    "wordpress", "webflow",
)  # fmt: skip
WRONG_COMPANY_WORDS = ("фоп", "school")
# Military units hire through the same boards: "Fullstack Developer до 1 окремий медичний
# батальйон", "Інженер БпЛА — 116 ОМБр". Never for the owner.
MILITARY_WORDS = (
    "обр", "омбр", "обтвр", "огшб", "ошб", "батальйон", "бригада", "бригаду", "бригади", "зсу", "тро",
    "бпла", "полк", "нгу", "дшв", "сил оборони",
    "військова", "військовий", "військової", "військову", "військових", "військові", "військовою",
    "штурмова", "штурмовий", "штурмової", "штурмову", "штурмових", "штурмові",
)  # fmt: skip

# Wellfound and the other international boards list vacancies hiring on another continent —
# "Remote only • India" is a job for someone living there, not a remote job for Europe.
FAR_LOCATION_WORDS = (
    "india", "bangalore", "bengaluru", "hyderabad", "mumbai", "delhi", "noida", "gurgaon",
    "chennai", "pune", "kolkata", "ahmedabad", "pakistan", "lahore", "karachi", "bangladesh",
    "dhaka", "nigeria", "lagos", "kenya", "nairobi", "philippines", "manila", "indonesia",
    "jakarta", "vietnam", "hanoi", "argentina", "brazil", "mexico", "colombia", "chile",
    "latam", "latin america", "south america", "south africa", "united states", "usa", "canada",
)  # fmt: skip
# A location line that does not say remote is an office: "Dublin", "In office • London", DOU's
# "Київ, Львів" — all of those were turned down.
REMOTE_WORDS = ("remote", "віддалено", "дистанційно", "удаленно", "relocation", "релокація")

# A vacancy still hanging on the board months later is either filled or never was real.
MAX_AGE_DAYS = 60

# The most experience the owner can show: 4 years asked is already too much (06.10.2026). Of
# the vacancies asking 4+ he applied to 7 and turned down 38.
MAX_YEARS = 3
# His English: B2 is the edge (a warning), anything above is a skip.
MAX_ENGLISH = "B2"
# Less text than this is a page that did not load, not a vacancy without a stack.
MIN_DESCRIPTION = 200

TOP = "top"
SENT = "sent"
REVIEW = "review"
REJECTED = "rejected_by_filter"
TIER_ORDER = {TOP: 0, SENT: 1, REVIEW: 2, REJECTED: 3}
SURFACED = (TOP, SENT, REVIEW)

# Warnings: what to check on the vacancy page before applying.
WARN_ENGLISH = "english"  # B2 asked, the owner has B1
WARN_ABROAD = "abroad"  # remote, but the board does not say a candidate abroad is fine
WARN_UKRAINE = "ukraine"  # the description talks about being in Ukraine
WARN_NO_DESCRIPTION = "no_description"  # the page did not load: judged by the title alone

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
    years: int | None = None
    english: str | None = None
    warnings: list[str] = field(default_factory=list)


_LEVELS = (("Junior", JUNIOR_WORDS), ("Middle", MIDDLE_WORDS), ("Senior", SENIOR_WORDS))


def title_level(title: str | None) -> str | None:
    """The seniority the title names, "Junior/Middle" for a range, None if it says nothing."""
    title = (title or "").lower()
    found = [name for name, words in _LEVELS if _contains_any(title, words)]
    return "/".join(found) or None


def title_reject_reason(title: str | None, company: str | None) -> str | None:
    title = (title or "").lower()
    company = (company or "").lower()
    has_middle = _contains_any(title, MIDDLE_WORDS)

    if _contains_any(title, MILITARY_WORDS) or _contains_any(company, MILITARY_WORDS):
        return "military"
    if _contains_any(company, WRONG_COMPANY_WORDS):
        return "company"
    if _contains_any(title, WRONG_ROLE_WORDS):
        return "not a developer role"
    if _contains_any(title, OTHER_STACK_WORDS):
        return "other stack"
    if _contains_any(title, LEAD_WORDS):
        return "lead"
    # "Middle/Senior" still hires a middle — that stays.
    if _contains_any(title, SENIOR_WORDS) and not has_middle:
        return "senior"
    if _contains_any(title, INTERN_WORDS):
        return "intern"
    return None


def _is_stale(date: str | datetime | None) -> bool:
    # Listeners that could not parse the site's date return its raw string — no way to tell.
    return isinstance(date, datetime) and (datetime.now() - date).days > MAX_AGE_DAYS


def _too_much(years: int | None, english: str | None) -> str | None:
    if years is not None and years > MAX_YEARS:
        return "experience"
    rank, limit = extract.english_rank(english), extract.english_rank(MAX_ENGLISH)
    if rank is not None and limit is not None and rank > limit:
        return "english"
    return None


def reject_before_opening(job: Job) -> str | None:
    """Everything that can be decided from the list card, before the page costs a load."""
    reason = title_reject_reason(job.title, job.company)
    if reason:
        return reason
    location = (job.location or "").lower()
    if _contains_any(location, FAR_LOCATION_WORDS):
        return "location"
    if location and not _contains_any(location, REMOTE_WORDS):
        return "office"
    if job.work_format in ("office", "hybrid"):
        return "office"
    if extract.abroad_ok(job.countries) is False:
        return "country"  # "Україна", "Польща" — Djinni does not let an application from Austria in
    if reason := _too_much(job.required_years, job.english):
        return reason
    if _is_stale(job.date):
        return "stale"
    return None


def _plain_support(title: str, description: str) -> bool:
    return _contains_any(title, SUPPORT_WORDS) and _DEVELOPER_WORK.search(description) is None


def _warnings(job: Job, description: str, english: str | None) -> list[str]:
    warnings = []
    if english == MAX_ENGLISH:
        warnings.append(WARN_ENGLISH)
    if job.platform_name == "Dou" and job.work_format == "remote" and not job.countries:
        warnings.append(WARN_ABROAD)
    if extract.ukraine_only_text(description):
        warnings.append(WARN_UKRAINE)
    return warnings


def _level_fits(job: Job, years: int | None) -> bool:
    """The level is known and is the owner's: years asked, or the title saying junior / middle."""
    if years is not None:
        return years <= MAX_YEARS
    level = title_level(job.title) or ""
    return "Junior" in level or "Middle" in level


def evaluate(job: Job) -> Verdict:
    reason = reject_before_opening(job)
    if reason:
        return Verdict(REJECTED, reason=reason)

    description = (job.description or "").lower()
    title = (job.title or "").lower()
    # The card's figures first: they are the ones the site checks an application against.
    years = job.required_years if job.required_years is not None else required_years(job.description)
    english = job.english or extract.english_level(job.description)

    def rejected(why: str) -> Verdict:
        return Verdict(REJECTED, reason=why, years=years, english=english)

    if reason := _too_much(years, english):
        return rejected(reason)
    if extract.senior_in_description(job.description):
        return rejected("senior")
    if extract.office_only(job.description):
        return rejected("office")
    if _plain_support(title, description):
        return rejected("not a developer role")

    text = f"{title}\n{description}"
    stack = _found(text, CORE_STACK)
    bonus = _found(text, BONUS_STACK)
    backend = any(name in stack for name in BACKEND_CORE)
    frontend = any(name in stack for name in FRONTEND_CORE)
    # Backend first: frontend-only and Node + React positions come last in their tier — the
    # owner takes them, but they are not what he is after.
    score = 10 * len(stack) + 5 * len(_found(title, CORE_STACK)) + 2 * len(bonus) + (5 if backend else 0)
    warnings = _warnings(job, description, english)

    def verdict(moderation: str) -> Verdict:
        return Verdict(moderation, score, stack, bonus, years=years, english=english, warnings=warnings)

    if backend and frontend:
        on_target = not warnings and _level_fits(job, years) and bool(_found(title, CORE_STACK) or "full" in title)
        return verdict(TOP if on_target else SENT)
    # An AI position is worth a look on its title alone: the owner applied to "AI Engineer" and
    # "Agentic AI Engineer" whose text named neither Python nor a framework.
    if stack or len(bonus) >= 2 or _contains_any(title, AI_TITLE_WORDS):
        return verdict(REVIEW)
    if len(description) < MIN_DESCRIPTION and title:
        # The page did not load (a bot check, a timeout): the title passed every rule, so the
        # owner judges it — "no stack match" here used to hide plain "Full Stack Developer".
        warnings.append(WARN_NO_DESCRIPTION)
        return verdict(REVIEW)
    return Verdict(REJECTED, score, stack, bonus, reason="no stack match", years=years, english=english)


class JobFilter:
    def __init__(self, job_storage: JobStorage) -> None:
        self.job_storage = job_storage

    def prefilter_all(self) -> list[Job]:
        """Reject by the list card. Returns the vacancies worth opening."""
        survivors = []
        for job in self.job_storage.jobs:
            reason = reject_before_opening(job)
            if reason:
                job.moderation, job.relevance_score, job.filter_reason = REJECTED, 0, reason
            else:
                survivors.append(job)
        logger.info("Card filter: %d of %d left", len(survivors), len(self.job_storage.jobs))
        return survivors

    def classify_all(self) -> None:
        counts = {TOP: 0, SENT: 0, REVIEW: 0, REJECTED: 0}
        for job in self.job_storage.jobs:
            verdict = evaluate(job)
            apply_verdict(job, verdict)
            counts[verdict.moderation] += 1
        # Messages go out best first: the tier, then the score inside it.
        self.job_storage.jobs.sort(key=lambda j: (TIER_ORDER.get(j.moderation or REJECTED, 3), -j.relevance_score))
        logger.info(
            "Classified %d jobs: on target=%d your stack=%d partial=%d rejected=%d",
            len(self.job_storage.jobs),
            counts[TOP],
            counts[SENT],
            counts[REVIEW],
            counts[REJECTED],
        )

    @staticmethod
    def classify_job(job: Job) -> tuple[str, int]:
        verdict = evaluate(job)
        return verdict.moderation, verdict.score


def apply_verdict(job: Job, verdict: Verdict) -> None:
    job.moderation = verdict.moderation
    job.relevance_score = verdict.score
    job.matched_stack = verdict.stack
    job.matched_bonus = verdict.bonus
    job.required_years = verdict.years if verdict.years is not None else job.required_years
    job.english = verdict.english or job.english
    job.warnings = verdict.warnings
    job.filter_reason = verdict.reason

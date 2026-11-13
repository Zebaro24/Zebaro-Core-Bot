"""The owner's three CVs (09.11.2026) and which one a vacancy gets.

Since 09.11.2026 every application goes out with one of three CVs — Python Backend, Python
Fullstack, AI Engineer — picked by the vacancy (the routing table in the owner's CV plan):

  AI / LLM / GenAI / agents in the title                     → AI Engineer
  full-stack in the title, or React / Next.js required       → Python Fullstack Engineer
  the rest: Python / backend, the frontend absent or a plus  → Python Backend Engineer

Before that day there was one CV, "AI-Native Fullstack Engineer" — `UNIVERSAL`, the CV of every
earlier application in the stats.

A vacancy is judged against the CV it gets: which of the CV's skills it names (`match`), and
which technologies it asks for that the CV does not have (`gaps`; those only "nice to have" are
`gaps_plus` and cost nothing). The skills are the CVs' "Technical skills" as uploaded.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from src.services.job_searcher import extract
from src.services.job_searcher.keywords import contains_any, found

BACKEND = "backend"
FULLSTACK = "fullstack"
AI = "ai"
UNIVERSAL = "universal"
TRACKS = (BACKEND, FULLSTACK, AI)
CV_KEYS = (*TRACKS, UNIVERSAL)

# The three CVs went live on every board this day; earlier applications went with the one CV.
CV_SINCE = datetime(2026, 11, 9)
# The CV Djinni sends unless another is picked in the application (the profile's main one).
DJINNI_MAIN = FULLSTACK
# The lowest monthly figure (USD net, contractor) the owner names; the middle of a vacancy's
# range when it shows one, but never below this.
SALARY_FLOOR = 1500

# Every skill a CV names, and the words a vacancy names it with.
SKILLS: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "FastAPI": ("fastapi", "fast api"),
    "Pydantic": ("pydantic",),
    "asyncio": ("asyncio", "async", "async/await"),
    "Django / DRF": ("django", "drf", "django rest framework"),
    "REST API": ("rest api", "rest apis", "restful", "rest-api"),
    "WebSockets": ("websocket", "websockets", "web sockets"),
    "PostgreSQL": ("postgresql", "postgres"),
    "SQLAlchemy": ("sqlalchemy",),
    "MongoDB": ("mongodb", "mongo"),
    "Docker": ("docker",),
    "CI/CD": ("ci/cd", "github actions", "ci cd"),
    "Google Cloud": ("gcp", "google cloud"),
    "Linux": ("linux",),
    "pytest": ("pytest",),
    "mypy": ("mypy",),
    "TypeScript": ("typescript",),
    "Next.js": ("next.js", "nextjs"),
    "React": ("react", "react.js", "reactjs"),
    "TanStack Query": ("tanstack", "react query", "react-query"),
    "Tailwind": ("tailwind", "tailwindcss"),
    "Three.js": ("three.js", "threejs"),
    "Vitest": ("vitest",),
    "Playwright": ("playwright",),
    "LLM": ("llm", "llms", "openai", "gpt", "anthropic", "claude api", "gemini"),
    "AI agents": ("ai agent", "ai agents", "llm agent", "llm agents", "agentic", "multi-agent", "multi agent"),
    "Structured outputs": ("structured output", "structured outputs", "function calling", "tool calling"),
    "MCP": ("mcp", "model context protocol"),
    "Prompt engineering": ("prompt engineering", "prompting", "prompt design"),
    "AI dev tools": ("claude code", "cursor", "copilot", "ai coding", "ai-assisted", "ai tools"),
}

# What vacancies of the owner's field often ask for and none of the CVs names.
GAPS: dict[str, tuple[str, ...]] = {
    "Celery": ("celery",),
    "Redis": ("redis",),
    "Kafka": ("kafka",),
    "RabbitMQ": ("rabbitmq",),
    "Kubernetes": ("kubernetes", "k8s"),
    "AWS": ("aws",),
    "Azure": ("azure",),
    "Terraform": ("terraform",),
    "Flask": ("flask",),
    "GraphQL": ("graphql",),
    "Node.js": ("node.js", "nodejs", "nestjs", "nest.js"),
    "Vue": ("vue", "vue.js"),
    "Angular": ("angular",),
    "Airflow": ("airflow",),
    "Spark": ("spark", "pyspark"),
    "Elasticsearch": ("elasticsearch", "opensearch"),
    "LangChain": ("langchain",),
    "LangGraph": ("langgraph",),
    "LlamaIndex": ("llamaindex", "llama index", "llama-index"),
    "RAG": ("rag",),
    "Vector DB": ("pinecone", "weaviate", "qdrant", "milvus", "chromadb", "pgvector", "vector database"),
    "PyTorch": ("pytorch",),
    "Fine-tuning": ("fine-tuning", "fine tuning", "finetuning"),
    "Hugging Face": ("hugging face", "huggingface"),
}


@dataclass(frozen=True)
class Cv:
    key: str
    title: str  # the CV's headline — what the owner sees on the vacancy
    short: str  # a word for buttons and charts
    file: str  # the PDF in CV/Upload
    skills: tuple[str, ...] = ()
    salary: int = SALARY_FLOOR  # USD net a month, named when the vacancy shows no range


CVS: dict[str, Cv] = {
    BACKEND: Cv(
        BACKEND, "Python Backend Engineer", "Backend", "Denys_Shcherbatyi_Python_Backend_Engineer.pdf",
        ("Python", "FastAPI", "Pydantic", "asyncio", "Django / DRF", "REST API", "WebSockets", "PostgreSQL",
         "SQLAlchemy", "MongoDB", "Docker", "CI/CD", "Google Cloud", "Linux", "pytest", "mypy", "LLM",
         "AI agents", "Structured outputs", "MCP", "AI dev tools", "TypeScript", "Next.js", "React"),
        1700,
    ),
    FULLSTACK: Cv(
        FULLSTACK, "Python Fullstack Engineer", "Fullstack", "Denys_Shcherbatyi_Python_Fullstack_Engineer.pdf",
        ("Python", "FastAPI", "Pydantic", "Django / DRF", "REST API", "WebSockets", "TypeScript", "Next.js", "React",
         "TanStack Query", "Tailwind", "Three.js", "PostgreSQL", "SQLAlchemy", "MongoDB", "Docker", "CI/CD",
         "Google Cloud", "pytest", "Vitest", "Playwright", "LLM", "AI agents", "MCP", "AI dev tools"),
        1800,
    ),
    AI: Cv(
        AI, "AI Engineer", "AI", "Denys_Shcherbatyi_AI_Engineer.pdf",
        ("LLM", "AI agents", "Structured outputs", "MCP", "Prompt engineering", "AI dev tools", "Python",
         "FastAPI", "Pydantic", "asyncio", "REST API", "MongoDB", "PostgreSQL", "Docker", "CI/CD",
         "Google Cloud", "TypeScript", "Next.js", "React"),
        2200,
    ),
    UNIVERSAL: Cv(
        UNIVERSAL, "AI-Native Fullstack Engineer (одно CV до 09.11)", "Одно CV",
        "Denys_Shcherbatyi_CV_Fullstack_Engineer.pdf",
    ),
}  # fmt: skip

# The title words that send a vacancy to a CV. "ml" alone is not one: a plain ML position is
# skipped by the filter, and "AI/ML" has "ai".
AI_TITLE = (
    "ai",
    "llm",
    "llms",
    "genai",
    "gen ai",
    "gen-ai",
    "agentic",
    "agent",
    "agents",
    "ai-native",
    "prompt engineer",
)
FULLSTACK_TITLE = ("full", "fullstack", "full stack", "full-stack", "фулстек", "фуллстек")
BACKEND_TITLE = ("backend", "back-end", "back end", "бекенд", "бэкенд", "python", "django", "fastapi")
FRONTEND_WORDS = ("react", "react.js", "reactjs", "next.js", "nextjs")
PYTHON_FRAMEWORKS = ("fastapi", "fast api", "django", "flask")
PYTHON_ANY = ("python", *PYTHON_FRAMEWORKS)
_AI_CORE = ("LLM", "AI agents", "Structured outputs", "MCP", "Prompt engineering")


def get(key: str | None) -> Cv | None:
    return CVS.get(key or "")


def _fullstack_title(title: str) -> bool:
    """ "Full Stack Developer", or both sides named: "Python / React Developer"."""
    return contains_any(title, FULLSTACK_TITLE) or (
        contains_any(title, FRONTEND_WORDS) and contains_any(title, PYTHON_ANY)
    )


def route(title: str | None, description: str | None) -> str:
    """The CV a vacancy gets, by its title first and its requirements second."""
    title = (title or "").lower()
    if contains_any(title, AI_TITLE):
        return AI
    if _fullstack_title(title):
        return FULLSTACK
    if contains_any(title, BACKEND_TITLE):
        return BACKEND
    text = (description or "").lower()
    if contains_any(text, FRONTEND_WORDS) and not extract.only_as_plus(description, FRONTEND_WORDS):
        return FULLSTACK
    return BACKEND


@dataclass
class Fit:
    match: list[str] = field(default_factory=list)  # the CV's skills the vacancy names
    gaps: list[str] = field(default_factory=list)  # asked for, and not in the CV
    gaps_plus: list[str] = field(default_factory=list)  # not in the CV, but only "nice to have"


def fit(track: str, title: str | None, description: str | None) -> Fit:
    cv = CVS[track]
    text = f"{(title or '').lower()}\n{(description or '').lower()}"
    named = set(found(text, SKILLS))
    match = [skill for skill in cv.skills if skill in named]
    gaps: list[str] = []
    gaps_plus: list[str] = []
    for name in found(text, GAPS):
        plus = extract.only_as_plus(description, GAPS[name])
        (gaps_plus if plus else gaps).append(name)
    return Fit(match, gaps, gaps_plus)


def core_fits(track: str, title: str | None, description: str | None, match: list[str]) -> bool:
    """The vacancy is this CV's job, not only near it."""
    title = (title or "").lower()
    text = f"{title}\n{(description or '').lower()}"
    if not contains_any(text, PYTHON_ANY):  # FastAPI alone says Python
        return False
    if track == FULLSTACK:
        return "React" in match or "Next.js" in match
    if track == AI:
        return contains_any(title, AI_TITLE) and any(skill in match for skill in _AI_CORE)
    # Backend: a Python position by its title, or a Python framework in the text — "Backend
    # Engineer" over "Python and Go" is someone else's backend with Python on the side.
    return contains_any(title, PYTHON_ANY) or contains_any(text, PYTHON_FRAMEWORKS)


def title_names(track: str, title: str | None) -> bool:
    """The title says this CV's role in its own words — a recruiter reads it as a match."""
    title = (title or "").lower()
    if track == FULLSTACK:
        return _fullstack_title(title)
    return contains_any(title, AI_TITLE if track == AI else BACKEND_TITLE)


_MONEY = re.compile(r"\d[\d\s]{2,6}")


def salary_ask(track: str | None, salary: str | None) -> tuple[int, bool]:
    """What to name if asked: the middle of their range (never below the floor) or the CV's figure.
    The flag says whether it came from their range."""
    if salary and "$" in salary:
        numbers = [int(re.sub(r"\s", "", match)) for match in _MONEY.findall(salary)]
        numbers = [number for number in numbers if 300 <= number <= 50_000]
        if numbers:
            middle = round(sum(numbers) / len(numbers) / 100) * 100
            return max(middle, SALARY_FLOOR), True
    cv = get(track) or CVS[FULLSTACK]
    return cv.salary, False


def sent_with(track: str | None, when: datetime | None) -> str:
    """The CV an application goes out with when nobody picked one: the one it was routed to; one
    made before the three CVs went with the single CV."""
    if isinstance(when, datetime) and when < CV_SINCE:
        return UNIVERSAL
    return track if track in TRACKS else FULLSTACK

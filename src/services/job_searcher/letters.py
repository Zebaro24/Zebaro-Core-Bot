"""The cover letter of each CV, ready to paste into an application (the owner's decision 05.11.2026:
one letter per CV, sent as it is). The source is the owner's cover-letters notes, section 0 —
the facts match the CV the letter goes with. The language follows the vacancy's.
"""

from src.services.job_searcher.cv import AI, BACKEND, FULLSTACK

UK = "uk"
EN = "en"

_CLOSING = {
    UK: "Ремоут з Австрії, CET, можу вийти протягом тижня\nPortfolio: zebaro.dev",
    EN: "Remote from Austria (CET), I can start within a week\nPortfolio: zebaro.dev",
}
_AI_TOOLS = {
    UK: "Щодня працюю з Claude Code та іншими AI-інструментами, знаю, де вони реально пришвидшують роботу",
    EN: "I use Claude Code and other AI tools every day and know where they really speed up the work",
}

_BODIES: dict[str, dict[str, tuple[str, ...]]] = {
    BACKEND: {
        UK: (
            "Останній рік робив production AI-SaaS для контент-креаторів на Python і FastAPI, від першого коміту "
            "до продакшну",
            "Фонові задачі з чергою і ретраями, упала обробка продовжується з місця збою, а не з нуля",
            "Stripe-підписки з квотами, Docker і CI/CD на GitHub Actions з міграціями БД перед кожним деплоєм",
            "Працював з PostgreSQL, SQLAlchemy і MongoDB, API робив на FastAPI і Django REST",
        ),
        EN: (
            "Last year I built a production AI SaaS for content creators on Python and FastAPI, from the first "
            "commit to production",
            "Background jobs with a queue and retries, a failed run continues from where it stopped",
            "Stripe subscriptions with quotas, Docker and CI/CD on GitHub Actions with database migrations "
            "before every deploy",
            "I worked with PostgreSQL, SQLAlchemy and MongoDB, and built APIs on FastAPI and Django REST",
        ),
    },
    FULLSTACK: {
        UK: (
            "Останній рік робив production AI-SaaS від бази даних до інтерфейсу, бекенд на FastAPI, фронт на "
            "Next.js, React і TypeScript",
            "Stripe-підписки, адмінка і прогрес обробки в реальному часі, від API до кнопки в інтерфейсі",
            "Фронт писав на суворому TypeScript зі своєю дизайн-системою, щоб інтерфейс не роз'їжджався від фічі "
            "до фічі",
            "Працював з PostgreSQL, SQLAlchemy і MongoDB, API робив на FastAPI і Django REST",
        ),
        EN: (
            "Last year I built a production AI SaaS from the database to the UI, backend on FastAPI, frontend on "
            "Next.js, React and TypeScript",
            "Stripe subscriptions, an admin panel and real-time progress, from the API to the button in the UI",
            "Frontend on strict TypeScript with a shared design system, so the UI stays consistent from feature "
            "to feature",
            "I worked with PostgreSQL, SQLAlchemy and MongoDB, and built APIs on FastAPI and Django REST",
        ),
    },
    AI: {
        UK: (
            "Останній рік робив production AI-SaaS з мультиагентним LLM-пайплайном на Python і FastAPI",
            "Агенти віддають структуровані відповіді, а неповний результат до користувача не доходить",
            "Упала обробка відновлюється без повторних дорогих викликів LLM",
            "Зробив MCP-сервер з OAuth, щоб продуктом користувались прямо з AI-асистента",
        ),
        EN: (
            "Last year I built a production AI SaaS with a multi-agent LLM pipeline on Python and FastAPI",
            "Agents return structured output, and an incomplete result never reaches the user",
            "A failed run recovers without paying for the expensive LLM calls again",
            "I built an MCP server with OAuth, so users can work with the product from their AI assistant",
        ),
    },
}  # fmt: skip

# Cyrillic letters out of all letters above this: the vacancy is written in Ukrainian (or Russian,
# answered in Ukrainian all the same).
_CYRILLIC_SHARE = 0.3


def language(text: str | None) -> str:
    letters = [char for char in text or "" if char.isalpha()]
    if not letters:
        return EN
    cyrillic = sum("а" <= char.lower() <= "я" or char.lower() in "іїєґё" for char in letters)
    return UK if cyrillic / len(letters) > _CYRILLIC_SHARE else EN


def letter(track: str, lang: str) -> str:
    """The whole letter of a CV, line by line as the boards keep the line breaks."""
    body = _BODIES.get(track, _BODIES[FULLSTACK])[lang]
    return "\n".join((*body, _AI_TOOLS[lang], _CLOSING[lang]))

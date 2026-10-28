"""Where the vacancies come from.

One line per search, grouped by site. Every search is either the owner's stack (Python /
FastAPI on the back, React / Next.js on the front), AI work around it or Python data
engineering (28.10.2026), and is limited to remote — the owner works only remotely, from
abroad. The focus is Ukrainian companies, wherever they are registered (06.10.2026):
international boards brought vacancies he could not take or did not want.

Each vacancy keeps the search that found it (`Job.search_url`), so a search that brings
nothing worth an answer shows up in `scripts/job_stats.py searches`.
"""

# Djinni filters the list by what it checks an application against: remote only, and at most
# three years of experience (no_exp…3y). Fifteen vacancies a page — without these, half of them
# were offices and five-year positions the filter threw away.
_DJINNI_FILTERS = "employment=remote&exp_level=no_exp&exp_level=1y&exp_level=2y&exp_level=3y"

_LINKEDIN = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LINKEDIN_FILTERS = "location=Ukraine&f_WT=2&f_TPR=r86400&sortBy=DD"

urls = [
    # DOU — the main Ukrainian board, 46% of its vacancies answered with an application. Its
    # search matches categories, not the text, so the categories Python work is filed under:
    # Python, full-stack, AI/ML, data engineering. The first page holds 3–7 days of each — plenty
    # with a run every hour. Front End went on 28.10.2026: Python is required, and of its 30
    # vacancies in a month one got an application. The ?relocation searches went on 06.10.2026:
    # a relocation-only vacancy is an office abroad, one that is also remote comes through ?remote.
    "https://jobs.dou.ua/vacancies/?remote&category=Python",
    "https://jobs.dou.ua/vacancies/?remote&category=Fullstack",
    "https://jobs.dou.ua/vacancies/?remote&category=AI%2FML",
    "https://jobs.dou.ua/vacancies/?remote&category=Data%20Engineer",
    # Djinni — the list already carries the whole description and the card the work format,
    # countries, years and English, so these pages cost one load each. keyword-<x>/ pages exist
    # only for real categories; the rest goes through the full-text search.
    # "python" anywhere in the text, not the Python category: the category held ten vacancies
    # in a month, the text search about seven a day — Django, full-stack, AI and data positions
    # filed under other categories (28.10.2026). Two pages: a weekend fills more than one.
    # It is not quite full-text: over two weeks Data Engineer added 7 Python vacancies to it,
    # full-stack 3, "AI engineer" 14 in three weeks. So the stack's own words keep their searches
    # even in a quiet week (FastAPI, Next.js, Django). all_keywords is AND — "AI, LLM, agent"
    # found one vacancy — so every word is a search of its own. A primary_keyword Djinni has no
    # category for ("ML Engineer", "AI/ML") is ignored and shows every vacancy (28.10.2026).
    f"https://djinni.co/jobs/?all_keywords=python&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=python&{_DJINNI_FILTERS}&page=2",
    f"https://djinni.co/jobs/?primary_keyword=Data+Engineer&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/keyword-fullstack/?{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=FastAPI&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=Django&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=Next.js&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=LLM&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=AI+engineer&{_DJINNI_FILTERS}",
    f"https://djinni.co/jobs/?all_keywords=AI+agents&{_DJINNI_FILTERS}",
    # Robota.ua — remote only (scheduleIds=3), Ukraine and abroad. Opened through the home PC.
    # "python", not "python-developer": 56 vacancies instead of a handful, "Data Engineer
    # (Python)" and Python full-stack among them; the full-stack search, 0 applications out of
    # 23 in a month, went with it (28.10.2026).
    "https://robota.ua/zapros/python/ukraine/params;scheduleIds=3",
    "https://robota.ua/zapros/python/other_countries/params;scheduleIds=3",
    # No Fluff Jobs — the Ukrainian section of the Polish board, remote positions. Few, but
    # three of four answered with an application.
    "https://nofluffjobs.com/ua-ru/viddalena-robota?criteria=jobPosition%3D%27python%20developer%27",
    "https://nofluffjobs.com/ua-ru/viddalena-robota?criteria=jobPosition%3D%27fullstack%20developer%27",
    # Work.ua — behind a Cloudflare check that only the home PC gets through. "python" finds all
    # that "python developer" did and more; "AI engineer" adds AI backend positions. Its "data
    # engineer" and "backend developer" are .NET, SQL and data entry — left out (28.10.2026).
    "https://www.work.ua/jobs-remote-python/",
    "https://www.work.ua/jobs-remote-ai+engineer/",
    "https://www.work.ua/jobs-remote-full+stack+developer/",
    "https://happymonday.ua/jobs-search/fullstack-developer",
    # LinkedIn's guest search — Ukrainian companies' postings that never reach DOU or Djinni.
    # Remote only (f_WT=2), the last 24 hours, newest first: with a run every hour one page of
    # ten covers it. Opened through the home PC: LinkedIn answers 429 after a few dozen requests.
    f"{_LINKEDIN}?keywords=python&{_LINKEDIN_FILTERS}",
    f"{_LINKEDIN}?keywords=data%20engineer&{_LINKEDIN_FILTERS}",
    f"{_LINKEDIN}?keywords=AI%20engineer&{_LINKEDIN_FILTERS}",
    # Off since 06.10.2026, the listeners stay ready:
    # BazaIT — eleven vacancies in three weeks, all posted in 2025, nothing since 18.09.
    # Wellfound — European startups, not Ukrainian companies; 7 applications out of 40 answers.
    # Jooble — answers Playwright with a Cloudflare 403 challenge page (checked 16.09.2026).
]

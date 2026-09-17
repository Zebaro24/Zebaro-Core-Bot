"""Where the vacancies come from.

One line per search, grouped by site. Every search is either the owner's stack (Python /
FastAPI on the back, React / Next.js on the front) or AI work around it, and is limited to
remote or relocation — nothing else is worth a page load.
"""

urls = [
    # DOU — the main Ukrainian board. Four categories: the backend half of the stack, the
    # frontend half (this is where React and Next.js live), full-stack, and AI/ML.
    "https://jobs.dou.ua/vacancies/?remote&category=Python",
    "https://jobs.dou.ua/vacancies/?relocation&category=Python",
    "https://jobs.dou.ua/vacancies/?remote&category=Front%20End",
    "https://jobs.dou.ua/vacancies/?remote&category=Fullstack",
    "https://jobs.dou.ua/vacancies/?relocation&category=Fullstack",
    "https://jobs.dou.ua/vacancies/?remote&category=AI%2FML",
    "https://jobs.dou.ua/vacancies/?relocation&category=AI%2FML",
    # Djinni — the list already carries the whole description, so these pages cost one load
    # each. It has no AI category of its own, hence the keyword search.
    "https://djinni.co/jobs/keyword-fullstack/",
    "https://djinni.co/jobs/keyword-react/",
    "https://djinni.co/jobs/?all_keywords=AI%2C+LLM%2C+agent&employment=remote",
    # Robota.ua — remote only (scheduleIds=3), Ukraine and abroad.
    "https://robota.ua/zapros/python-developer/ukraine/params;scheduleIds=3",
    "https://robota.ua/zapros/python-developer/other_countries/params;scheduleIds=3",
    # No Fluff Jobs — Polish board, remote positions.
    "https://nofluffjobs.com/ua-ru/viddalena-robota?criteria=jobPosition%3D%27python%20developer%27",
    # Work.ua — behind a Cloudflare bot check that the server browser has been failing; kept
    # because the search itself is good and the parser now waits the check out (see parser.py).
    "https://www.work.ua/jobs-remote-python+developer/",
    "https://happymonday.ua/jobs-search/fullstack-developer",
    # BazaIT — the positions that match the stack. "Node.js Developer" and "Full Stack Data
    # Analyst" used to be here and brought nothing the filter would keep.
    "https://app.bazait.com/search/jobs?position%5B0%5D=Python+Developer&position%5B1%5D=Full-Stack+Developer"
    "&position%5B2%5D=Backend+Developer&position%5B3%5D=Full-Stack+Web+Developer&page=1",
    # Wellfound — startups. The /role/r/ (remote) pages are worldwide and came back mostly
    # Indian and American, so the searches are the European ones; "Remote only • Everywhere"
    # vacancies show up there too.
    "https://wellfound.com/role/l/python-developer/europe",
    "https://wellfound.com/role/l/full-stack-developer/europe",
    # Jooble: off — the site answers Playwright with a Cloudflare 403 challenge page, checked
    # live 16.09.2026. listeners/jooble.py is fixed and ready if the block ever lifts.
    # "https://ua.jooble.org/SearchResult?date=3&rgns=Віддалено&ukw=python%20developer",
]

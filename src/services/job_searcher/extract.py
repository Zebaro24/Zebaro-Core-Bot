"""Facts about a vacancy read out of its text: experience, English, work format, seniority.

Boards that show these as separate fields (Djinni's card: "Тільки віддалено · Україна ·
2 роки досвіду · Англійська - B2", DOU's cities line) are read by their listeners; this
module is the fallback for the description and the place where both kinds of text are
normalised to the same values:

  work_format  "remote" | "office" | "hybrid" | "office_or_remote" | None
  english      "A1".."C2" | "none" (not needed) | None (not said)
  years        int — the main experience requirement

Every pattern here was checked against the stored vacancies and the owner's answers to
them (06.10.2026): see the numbers next to each rule.
"""

import re
from datetime import datetime, timedelta

# --- experience ---------------------------------------------------------------------------

_YEAR_WORDS = r"(?:years?|yrs?|років|роки|рік|року|лет|года|год)"
_MIN_WORDS = (
    r"(?:at least|minimum|min\.?|starting from|from|від|от|не мен\w+|щонайменш\w*|мінімум|минимум|понад|более|більше)"
)
# Only a figure asked *of the candidate* counts, so it carries a "+", a range, a word of
# minimum, or "N years of experience". "Our team has 5 years on the market" does not.
_YEARS_PATTERNS = (
    re.compile(rf"(\d{{1,2}}(?:[.,]5)?)\s*\+\s*{_YEAR_WORDS}"),  # "5+ years"
    re.compile(rf"(\d{{1,2}})\s*[-–—]\s*\d{{1,2}}\s*{_YEAR_WORDS}"),  # "3-5 years": the bar is 3
    re.compile(rf"{_MIN_WORDS}\s+(\d{{1,2}})(?:-?х|-?ти|-?ох)?\s*\+?\s*{_YEAR_WORDS}"),  # "від 4-х років"
    # "3 years of commercial experience" — only at the start of a point or after a word that
    # asks it of the candidate: "we are on the market for 10 years of experience" is not.
    re.compile(
        rf"(?:^[\W\d]*?|(?:have|having|with|requires?|required|need|must have|маєш|маєте|мати)\s+)"
        rf"(\d{{1,2}})\s*{_YEAR_WORDS}\s+(?:of\s+)?(?:\w+\s+){{0,3}}(?:experience|exp\b|досвід\w*|опыт\w*)"
    ),
)
_EXPERIENCE_WORDS = ("experience", "досвід", "опыт", "exp.")
# "20+ years on the market" sits on an experience line now and then; nobody asks that of a
# candidate.
_MAX_PLAUSIBLE_YEARS = 15


def required_years(description: str | None) -> int | None:
    """The main experience requirement, or None if the description does not name one.

    The highest figure, not the lowest: "5+ years of commercial experience, 3+ with Go" is a
    five-year position — taking the 3 sent it as a fit, and of the twelve vacancies with a 5+
    anywhere in them the owner answered none. A range counts by its lower end.
    """
    years: list[int] = []
    for line in (description or "").lower().split("\n"):
        if not any(word in line for word in _EXPERIENCE_WORDS):
            continue
        for pattern in _YEARS_PATTERNS:
            years += [int(float(match.replace(",", "."))) for match in pattern.findall(line)]
    years = [year for year in years if 0 < year <= _MAX_PLAUSIBLE_YEARS]
    return max(years) if years else None


_CARD_YEARS = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*(?:років|роки|рік|року|years?|лет|года|год)")


def card_years(text: str) -> int | None:
    """ "3 роки досвіду", "0.5 років досвіду", "Без досвіду" → whole years, 0 for none."""
    lowered = text.lower()
    if "без досвіду" in lowered or "no experience" in lowered:
        return 0
    match = _CARD_YEARS.search(lowered)
    return int(float(match.group(1).replace(",", "."))) if match else None


# --- English ------------------------------------------------------------------------------

ENGLISH_ORDER = ("none", "A1", "A2", "B1", "B2", "C1", "C2")
_ENGLISH_WORDS = {
    "a1": "A1", "a2": "A2", "b1": "B1", "b2": "B2", "c1": "C1", "c2": "C2",
    "pre-intermediate": "A2", "pre intermediate": "A2", "intermediate": "B1",
    # "Fluent English" is written loosely on Ukrainian boards — it is the B2 edge, not C1.
    "upper-intermediate": "B2", "upper intermediate": "B2", "advanced": "C1", "fluent": "B2",
    "proficient": "C2", "native": "C2",
    # Djinni's card and its filter names.
    "немає": "none", "не потрібна": "none", "no english": "none", "basic": "A1", "pre": "A2", "upper": "B2",
}  # fmt: skip
_LEVEL = r"(a1|a2|b1|b2|c1|c2|pre[- ]intermediate|upper[- ]intermediate|intermediate|advanced|fluent|proficient|native)"
_ENGLISH = r"(?:english|англ\w*)"
_ENGLISH_PATTERNS = (
    re.compile(rf"{_ENGLISH}\W{{0,3}}[^\n.;]{{0,40}}?\b{_LEVEL}\b"),  # "English: Upper-Intermediate"
    re.compile(rf"\b{_LEVEL}\b[^\n.;]{{0,25}}?{_ENGLISH}"),  # "B2+ English"
)


def english_level(text: str | None) -> str | None:
    """The English level the text asks for, or None.

    A CEFR code wins over a word: "fluent spoken English (B2)" is B2. Otherwise the first one
    named.
    """
    lowered = (text or "").lower()
    found: list[tuple[bool, int, str]] = []
    for pattern in _ENGLISH_PATTERNS:
        for match in pattern.finditer(lowered):
            word = match.group(1)
            found.append((not re.fullmatch(r"[abc][12]", word), match.start(), _ENGLISH_WORDS[word]))
    return min(found)[2] if found else None


def card_english(text: str) -> str | None:
    """ "Англійська - B2", "Англійська - Немає" → "B2", "none"."""
    value = text.split("-", 1)[-1].strip().lower()
    return _ENGLISH_WORDS.get(value) or english_level(f"english {value}")


def english_rank(level: str | None) -> int | None:
    return ENGLISH_ORDER.index(level) if level in ENGLISH_ORDER else None


# --- work format and where the candidate may live -----------------------------------------

_FORMATS = (
    ("office_or_remote", ("офіс або віддалено", "віддалено або офіс", "office or remote", "remote or office")),
    ("hybrid", ("гібрид", "hybrid", "гибрид")),
    ("remote", ("віддалено", "remote", "удаленно", "дистанційно")),
    ("office", ("офіс", "office", "офис", "on-site", "onsite")),
)


def work_format(text: str | None) -> str | None:
    """ "Тільки віддалено", "Тільки офіс", "Гібридний формат роботи"... → one of the values."""
    lowered = (text or "").lower()
    for value, words in _FORMATS:
        if any(word in lowered for word in words):
            return value
    return None


# Strict wording only. "Hybrid" is in fifteen descriptions the owner applied to — mostly as
# "remote or hybrid" — so it is never a reason on its own.
_OFFICE_ONLY = re.compile(
    r"(тільки|лише|only)\s+(в\s+)?(офіс|office|on-?site)|\b(office|onsite|on-site)[- ]only|"
    r"full[- ]time\s+(in[- ])?office|робота в офісі|работа в офисе"
)


def office_only(description: str | None) -> bool:
    return _OFFICE_ONLY.search((description or "").lower()) is not None


# A candidate who has to be in Ukraine. Read from the description it is only a warning: two of
# the four hits were vacancies the owner applied to, where the line was about the team.
_UKRAINE_ONLY = re.compile(
    r"(only|лише|тільки|exclusively)\s+(candidates\s+)?(from|in|з|в|у|із)\s+ukrain|"
    r"(you|candidate\w*|кандидат\w*|must|should|need to|бути|перебува\w*|знаход\w*|проживат\w*|"
    r"located|reside\w*|living)\s+(physically\s+)?(in|в|у|на території)\s+(україн|ukrain)|"
    r"(україн\w*|ukrain\w*)\s+only|в межах україни|within ukraine"
)


def ukraine_only_text(description: str | None) -> bool:
    return _UKRAINE_ONLY.search((description or "").lower()) is not None


# Where the owner can work from: he lives in Austria. A country list that names neither the
# world, Europe nor Austria is a vacancy he cannot get — Djinni refuses the application.
_ABROAD_OK_WORDS = ("світ", "world", "європ", "europe", "єс", "eu", "австрі", "austria", "за кордоном", "abroad")


def abroad_ok(countries: str | None) -> bool | None:
    """Whether a candidate living abroad (in Austria) fits; None when nothing is said."""
    if not countries:
        return None
    lowered = countries.lower()
    return any(re.search(rf"(?<!\w){re.escape(word)}", lowered) for word in _ABROAD_OK_WORDS)


# --- seniority named in the description ---------------------------------------------------

# "Ми шукаємо Senior / Lead Full Stack GenAI Engineer" under the title "Full Stack GenAI
# Engineer". On the stored vacancies: 9 hits the owner answered, 1 applied.
_SENIOR_INTRO = re.compile(
    r"(шукаємо|ищем|looking for|seeking|hiring|we need|потрібен|потрібна|запрошуємо|в пошуках)\s+"
    r"(an?\s+)?(досвідчен\w+\s+|experienced\s+|strong\s+)?"
    r"(senior|lead|сеньйор|синьйор|tech lead|team lead|principal|staff)\b"
)
_LOWER_LEVEL = re.compile(r"\b(middle|mid[- ]level|mid|junior|джуніор|мідл)\b")


def senior_in_description(description: str | None) -> bool:
    """The description hires a senior and never mentions a middle or a junior."""
    lowered = (description or "").lower()
    return _SENIOR_INTRO.search(lowered) is not None and _LOWER_LEVEL.search(lowered) is None


# --- numbers on the card ------------------------------------------------------------------

_APPLICANTS = re.compile(r"(\d+)\s*(?:відгук|відгуки|відгуків|applications?|applicants?|откл)")


def card_applicants(text: str) -> int | None:
    match = _APPLICANTS.search(text.lower())
    return int(match.group(1)) if match else None


# --- dates --------------------------------------------------------------------------------

_RELATIVE = re.compile(r"(\d+)?\s*([^\W\d]+)\s+(?:тому|назад|ago)")


def relative_date(text: str, now: datetime | None = None) -> datetime | None:
    """ "2 дні тому", "19 годин тому", "1 тиждень тому", "3 days ago" → a datetime.

    A number left out means one: "тиждень тому", "a month ago".
    """
    match = _RELATIVE.search(text.lower())
    if not match:
        return None
    amount = int(match.group(1) or 1)
    unit = match.group(2)
    now = now or datetime.now()
    steps = (
        (("хвилин", "minute", "минут"), timedelta(minutes=1)),
        (("годин", "hour", "час"), timedelta(hours=1)),
        (("тижд", "тиж", "week", "недел"), timedelta(weeks=1)),
        (("місяц", "month", "месяц"), timedelta(days=30)),
        (("рік", "рок", "year", "год", "лет"), timedelta(days=365)),
        (("д", "day"), timedelta(days=1)),  # день / дні / днів / day / days
    )
    for prefixes, step in steps:
        if unit.startswith(prefixes):
            return now - amount * step
    return None

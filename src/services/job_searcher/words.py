"""Whole-word search in vacancy texts: `any=ai` finds "AI/ML" and "AI-powered", not "email".

A word matches where the characters around it are not letters or digits. The pattern is built
here once and works the same in Python's `re` (SQLite in the tests) and in PostgreSQL's regexes
(lookbehind, character classes, whitespace), so the tests check what the database runs.

No case-insensitive flag: every letter is spelled in both cases ("[дД][жЖ][уУ][нН]") — the same
on every engine whatever its locale (a habit from MongoDB 4.4, whose PCRE folded only ASCII).
"""

import re
from typing import Any

from sqlalchemy import ColumnElement, func, not_, or_

MAX_WORDS = 20
MAX_WORD_LENGTH = 50

# What counts as a letter or digit next to a word: Latin with its accented letters (No Fluff
# Jobs is Polish) and Cyrillic, both cases.
_WORD_CHARS = "0-9A-Za-z\u00c0-\u024f\u0400-\u04ff"


def parse_words(raw: str | None) -> list[str]:
    """ "ai, LLM,machine  learning" → ["ai", "llm", "machine learning"]; repeats dropped."""
    words: list[str] = []
    for part in (raw or "").split(","):
        word = " ".join(part.split()).lower()
        if word and word not in words:
            words.append(word)
    return words


def case_free(text: str) -> str:
    """A regex for `text` in any case, with every other character literal."""
    parts = []
    for char in text:
        lower, upper = char.lower(), char.upper()
        if char.isspace():
            parts.append(r"\s+")
        elif lower != upper and len(lower) == 1 and len(upper) == 1:
            parts.append(f"[{lower}{upper}]")
        else:
            parts.append(re.escape(char))
    return "".join(parts)


def word_pattern(word: str) -> str:
    return f"(?<![{_WORD_CHARS}]){case_free(word)}(?![{_WORD_CHARS}])"


def has_word(text: str | None, word: str) -> bool:
    return bool(text) and re.search(word_pattern(word), text or "") is not None


WHERE_FIELDS = {"title": ("title",), "description": ("description",), "both": ("title", "description")}


def matches(column: Any, pattern: str) -> ColumnElement[bool]:
    """`column` has a match of `pattern`; a missing text is an empty one (so "none of" holds for it)."""
    result: ColumnElement[bool] = func.coalesce(column, "").regexp_match(pattern)
    return result


def words_query(
    any_words: list[str], all_words: list[str], no_words: list[str], where: str = "both"
) -> list[ColumnElement[bool]]:
    """SQL conditions to AND together: at least one of, each of, none of the words."""
    from src.services.job_searcher.store import J  # words.py is imported where no DB is

    columns = [getattr(J, name) for name in WHERE_FIELDS[where]]

    def anywhere(words: list[str]) -> ColumnElement[bool]:
        return or_(*(matches(column, word_pattern(word)) for word in words for column in columns))

    conditions: list[ColumnElement[bool]] = []
    if any_words:
        conditions.append(anywhere(any_words))
    conditions += [anywhere([word]) for word in all_words]
    if no_words:
        conditions.append(not_(anywhere(no_words)))
    return conditions

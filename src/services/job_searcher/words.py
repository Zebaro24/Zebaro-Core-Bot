"""Whole-word search in vacancy texts: `any=ai` finds "AI/ML" and "AI-powered", not "email".

A word matches where the characters around it are not letters or digits. The pattern is built
here once and works the same in Python's `re` and in MongoDB's PCRE, so the tests check exactly
what the database runs.

The production MongoDB (4.4) folds case only for ASCII unless its PCRE has Unicode properties,
so no "i" option is used: every letter is spelled in both cases ("[дД][жЖ][уУ][нН]").
"""

import re
from typing import Any

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


def words_query(
    any_words: list[str], all_words: list[str], no_words: list[str], where: str = "both"
) -> list[dict[str, Any]]:
    """MongoDB conditions to AND together: at least one of, each of, none of the words."""
    fields = WHERE_FIELDS[where]

    def anywhere(words: list[str]) -> list[dict[str, Any]]:
        return [{field: {"$regex": word_pattern(word)}} for word in words for field in fields]

    conditions: list[dict[str, Any]] = []
    if any_words:
        conditions.append({"$or": anywhere(any_words)})
    conditions += [{"$or": anywhere([word])} for word in all_words]
    if no_words:
        conditions.append({"$nor": anywhere(no_words)})
    return conditions

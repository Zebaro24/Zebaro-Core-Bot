"""How a keyword is looked for in a vacancy: the filter, the CV routing and the formatter agree.

Word boundaries: short tokens like "ai" or "sr" must not match inside "email" or "srv". A digit
may follow ("Python3"), a letter may not.
"""

import re

# Keywords that need more than a word boundary.
_SPECIAL_PATTERNS = {
    # React Native is mobile development, not the React the owner writes.
    "react": r"\breact\b(?![\s-]*native)",
}


def pattern(keyword: str) -> str:
    return _SPECIAL_PATTERNS.get(keyword, rf"(?<![\w.]){re.escape(keyword)}(?![^\W\d_])")


def contains(text: str, keyword: str) -> bool:
    return re.search(pattern(keyword), text) is not None


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(contains(text, keyword) for keyword in keywords)


def found(text: str, stack: dict[str, tuple[str, ...]]) -> list[str]:
    """The names of a {name: keywords} map that the text mentions, in the map's order."""
    return [name for name, keywords in stack.items() if contains_any(text, keywords)]

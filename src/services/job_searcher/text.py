import re

from bs4.element import NavigableString, Tag

# Tags after which the text breaks onto a new line; the rest is inline.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "tr", "blockquote", "pre", "header", "footer",
}  # fmt: skip
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "button"}

BULLET = "• "


def element_text(element: Tag) -> str:
    """Readable text of a vacancy description that keeps its structure.

    `get_text(strip=True)` glues "Requirements" and the first requirement into one word and
    loses every list. Here paragraphs stay separated by a blank line, list items start with
    "• " and headings stand on their own line — enough for the Telegram formatter to rebuild
    paragraphs and lists, without storing site HTML in the database.
    """
    parts: list[str] = []

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
                continue
            if not isinstance(child, Tag) or child.name in _SKIP_TAGS:
                continue
            if child.name == "br":
                parts.append("\n")
            elif child.name == "li":
                # No newline after: the next item or the end of the list supplies it, and a
                # second one would put a blank line between items and split the list in two.
                parts.append("\n" + BULLET)
                walk(child)
            elif child.name in _HEADING_TAGS:
                parts.append("\n\n")
                walk(child)
                parts.append("\n\n")
            elif child.name in _BLOCK_TAGS:
                parts.append("\n\n" if child.name in {"p", "ul", "ol", "table", "blockquote", "pre"} else "\n")
                walk(child)
                parts.append("\n\n" if child.name in {"p", "ul", "ol", "table", "blockquote", "pre"} else "\n")
            else:
                walk(child)

    walk(element)
    return normalize_text("".join(parts))


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    # A bullet whose text landed on the next line ("•\nPython") joins back into one line.
    merged: list[str] = []
    for line in lines:
        if merged and merged[-1] == BULLET.strip() and line:
            merged[-1] = BULLET + line
        else:
            merged.append(line)
    text = "\n".join(line for line in merged if line != BULLET.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def drop_lines(text: str, noise: list[str]) -> str:
    """Remove site chrome that sits inside the description block ("Показать оригинал")."""
    lowered = [n.lower() for n in noise]
    kept = [line for line in text.split("\n") if not any(n in line.lower() for n in lowered)]
    return normalize_text("\n".join(kept))

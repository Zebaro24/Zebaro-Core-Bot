#!/usr/bin/env python3
"""Zebaro-Core-Bot release helper — prepare a deliberate, deployable version.

Pushing a `vX.Y.Z` tag is the only thing that reaches the production server: CD
runs the gate, builds the image, pushes it to GHCR and restarts the compose
stack on server.zebaro.dev. So this is a slow, owner-triggered step, and it does
NOT push — the push is a separate, visible action.

`VERSION` at the root is the source of truth; this script mirrors it into
`pyproject.toml` and `src/config.py` (the version `/health` reports), so they
cannot drift.

What it does:
  1. checks the tree is clean, the branch is main and `## Unreleased` in
     CHANGELOG.md actually says something,
  2. bumps VERSION and mirrors it,
  3. stamps `## Unreleased` as `## vX.Y.Z — date` and opens a new empty one,
  4. commits `chore(release): vX.Y.Z` and tags locally,
  5. mints the one-shot markers .approve-push and .approve-release,
  6. prints the two push commands — /release runs them after the owner's go.

Notes are written BEFORE the release, not after: stamping a placeholder and then
amending the release commit would mean re-pointing a tag, and the tag is the deploy.

Usage:
  python scripts/release.py --bump patch|minor|major
  python scripts/release.py --version 0.6.0
  python scripts/release.py --bump minor --dry-run

Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "VERSION")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
UNRELEASED = re.compile(r"^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)", re.M | re.S)

# Files that must always agree with VERSION.
MIRRORS = [
    ("pyproject.toml", re.compile(r'(^version\s*=\s*")(\d+\.\d+\.\d+)(")', re.M)),
    ("src/config.py", re.compile(r'(^\s*version:\s*str\s*=\s*")(\d+\.\d+\.\d+)(")', re.M)),
]


def git(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def read_version() -> tuple[int, int, int]:
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            raw = f.read().strip().lstrip("v")
    except OSError:
        return (0, 0, 0)
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return (0, 0, 0)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def mirror(new: str) -> list[str]:
    touched = []
    for rel, pattern in MIRRORS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if not pattern.search(text):
            print(f"  ! {rel}: версия не найдена по шаблону — поправь руками")
            continue
        text = pattern.sub(lambda m: f"{m.group(1)}{new}{m.group(3)}", text, count=1)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        touched.append(rel)
    return touched


def unreleased_notes() -> str | None:
    """The text under `## Unreleased`, or None if the section is missing or empty."""
    try:
        with open(CHANGELOG, encoding="utf-8") as f:
            m = UNRELEASED.search(f.read())
    except OSError:
        return None
    notes = m.group(1).strip() if m else ""
    return notes or None


def stamp_changelog(new: str) -> None:
    with open(CHANGELOG, encoding="utf-8") as f:
        text = f.read()
    stamped = f"## Unreleased\n\n## v{new} — {date.today().isoformat()}"
    text = re.sub(r"^## Unreleased[ \t]*$", lambda _m: stamped, text, count=1, flags=re.M)
    with open(CHANGELOG, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--bump", choices=["patch", "minor", "major"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.version and not args.bump:
        print("нужен --version X.Y.Z или --bump patch|minor|major")
        return 2

    cur = read_version()
    if args.version:
        parts = args.version.lstrip("v").split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            print("✗ --version должен быть X.Y.Z")
            return 2
        new_t = (int(parts[0]), int(parts[1]), int(parts[2]))
    else:
        major, minor, patch = cur
        bumps = {"patch": (major, minor, patch + 1), "minor": (major, minor + 1, 0), "major": (major + 1, 0, 0)}
        new_t = bumps[args.bump]

    if new_t <= cur:
        print(f"✗ {'.'.join(map(str, new_t))} не выше текущей {'.'.join(map(str, cur))}")
        return 2

    new = ".".join(map(str, new_t))
    tag = f"v{new}"
    print(f"  Zebaro-Core-Bot: {'.'.join(map(str, cur))} → {new}  (тег {tag})")

    code, branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    if code == 0 and branch.strip() != "main":
        print(f"✗ релиз делается с main, а ты на {branch.strip()}.")
        return 2

    _, dirty = git(["status", "--porcelain"])
    if dirty.strip():
        print("✗ дерево не чистое — сначала закоммить или спрячь:")
        print(dirty)
        return 2

    if unreleased_notes() is None:
        print("✗ в CHANGELOG.md пустой или отсутствует раздел `## Unreleased` — сначала опиши, что выходит.")
        return 2

    code, _ = git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"])
    if code == 0:
        print(f"✗ тег {tag} уже существует.")
        return 2

    if args.dry_run:
        print("  (dry-run) поднял бы VERSION, зеркала, CHANGELOG, коммит, тег, маркеры.")
        print(f"  затем:  git push origin main && git push origin {tag}")
        return 0

    with open(VERSION_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(new + "\n")
    touched = mirror(new)
    stamp_changelog(new)

    for step in (
        ["add", "-A"],
        ["commit", "-m", f"chore(release): {tag}"],
        ["tag", "-a", tag, "-m", f"Zebaro-Core-Bot {tag}"],
    ):
        code, out = git(step)
        if code != 0:
            print(f"✗ git {' '.join(step)} упал:\n{out}")
            return 1

    for marker in (".approve-push", ".approve-release"):
        path = os.path.join(ROOT, ".claude", marker)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(tag)

    print(f"  ✓ VERSION, {', '.join(touched) or 'зеркал нет'}, CHANGELOG, коммит, тег.")
    print("  ✓ одобрение выписано (одноразовое, живёт 15 минут).")
    print("  Выкатывать после «го»:")
    print("    git push origin main")
    print(f"    git push origin {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

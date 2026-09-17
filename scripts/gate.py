#!/usr/bin/env python3
"""Zebaro-Core-Bot quality gate — the single checker, locally and in CI.

Never run black / isort / flake8 / mypy / bandit / pip-audit / pytest by hand:
this script is the one source of truth and exactly what CI runs. A green that
came from a hand-picked subset is not the green CI will give.

Checks (group)
  poetry-lock  poetry check --lock        lock file matches pyproject   (lint)
  black        black --check              formatting                    (lint)
  isort        isort --check-only         import order                  (lint)
  flake8       flake8                     style and simple bugs         (lint)
  mypy         mypy src tests             types                         (lint)
  bandit       bandit -r src              insecure code patterns        (security)
  pip-audit    pip-audit                  known CVEs in dependencies    (security)
  pytest       pytest                     tests; --strict adds coverage (tests)

Usage
  python scripts/gate.py                   # everything, same as CI
  python scripts/gate.py --lint            # lint and types only (fast, while working)
  python scripts/gate.py --tests           # tests only
  python scripts/gate.py --security        # bandit + pip-audit
  python scripts/gate.py --strict          # everything, tests with coverage (release, CI)
  python scripts/gate.py --only mypy
  python scripts/gate.py --only pytest -- tests/interfaces/test_telegram_webhook.py
  python scripts/gate.py --fix             # apply black + isort, then run the gate
  python scripts/gate.py --jobs 1          # one at a time, honest per-check timings
  python scripts/gate.py --list

Exit code is non-zero if any selected check failed. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

# Windows consoles default to cp1251, which cannot print "✓" or Cyrillic.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATHS = ["src", "tests"]


class Spec(NamedTuple):
    name: str
    argv: list[str]  # argv[0] is a tool inside the project virtualenv, or "poetry"
    group: str
    slow: bool


CHECKS = [
    # First: a lock file out of sync with pyproject breaks the Docker build, not a check.
    Spec("poetry-lock", ["poetry", "check", "--lock"], "lint", False),
    Spec("black", ["black", "--check", *PATHS], "lint", False),
    Spec("isort", ["isort", "--check-only", *PATHS], "lint", False),
    Spec("flake8", ["flake8", *PATHS], "lint", False),
    Spec("mypy", ["mypy", *PATHS], "lint", True),
    Spec("bandit", ["bandit", "-r", "src", "-q", "-c", "pyproject.toml"], "security", False),
    # Needs the network (advisory database). A new CVE can turn this red without any
    # change on our side — that is the point of it, not a flake.
    Spec("pip-audit", ["pip-audit", "--progress-spinner", "off"], "security", True),
    Spec("pytest", ["pytest", "-q", "-p", "no:cacheprovider", "--color=no"], "tests", True),
]
STRICT_PYTEST = ["pytest", "-q", "-p", "no:cacheprovider", "--color=no",
                 "--cov=src", "--cov-report=term-missing", "--cov-report=xml"]
FIXERS = [("black", ["black", "--quiet", *PATHS]), ("isort", ["isort", "--quiet", *PATHS])]

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def sh(argv: list[str]) -> tuple[int, str]:
    # shutil.which honours PATHEXT: on Windows `poetry` is poetry.exe/.cmd and
    # CreateProcess alone would not find it.
    exe = shutil.which(argv[0]) or argv[0]
    if not os.path.isfile(exe):
        return 127, f"not found: {argv[0]} — install it (poetry install) and retry."
    try:
        # PYTHONIOENCODING: without it a failing test's Cyrillic message arrives as mojibake.
        p = subprocess.run([exe, *argv[1:]], cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           encoding="utf-8", errors="replace", timeout=1200)
        return p.returncode, ANSI.sub("", (p.stdout or "") + (p.stderr or ""))
    except OSError as e:
        return 127, f"could not start {argv[0]}: {e}"
    except subprocess.TimeoutExpired:
        return 124, "the check did not finish in 1200 s."


_venv_cache: list[str | None] = []


def venv_dir() -> str | None:
    """The project virtualenv, asked from poetry once.

    `poetry run` costs about a second per call — a whole Python start that reads
    pyproject and finds the environment before running the tool. The tool inside
    the virtualenv is the very same executable, so call it directly.
    """
    if not _venv_cache:
        path = None
        if shutil.which("poetry"):
            code, out = sh(["poetry", "env", "info", "--path"])
            candidate = out.strip().splitlines()[-1].strip() if code == 0 and out.strip() else ""
            if candidate and os.path.isdir(candidate):
                path = candidate
        _venv_cache.append(path)
    return _venv_cache[0]


def resolve(argv: list[str]) -> list[str]:
    if argv[0] == "poetry":
        return argv
    venv = venv_dir()
    if venv:
        for sub, suffix in (("Scripts", ".exe"), ("bin", "")):
            tool = os.path.join(venv, sub, argv[0] + suffix)
            if os.path.isfile(tool):
                return [tool, *argv[1:]]
    return ["poetry", "run", *argv]


def dur(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def excerpt(out: str, n: int = 20) -> str:
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    return "\n".join("    " + ln for ln in lines[-n:]) or "    (no output)"


def coverage_percent(out: str) -> str | None:
    m = re.search(r"^TOTAL\s+.*?(\d+)%\s*$", out, re.M)
    return f"{m.group(1)}%" if m else None


class Result(NamedTuple):
    name: str
    code: int
    out: str
    seconds: float


def run_all(specs: list[Spec], jobs: int) -> list[Result]:
    lock = threading.Lock()

    def one(spec: Spec) -> Result:
        t0 = time.perf_counter()
        code, out = sh(resolve(spec.argv))
        seconds = time.perf_counter() - t0
        with lock:
            print(f"  {'✓' if code == 0 else '✗'} {spec.name:<12} {dur(seconds):>6}", flush=True)
        return Result(spec.name, code, out, seconds)

    if jobs <= 1:
        return [one(s) for s in specs]
    # Slow checks first: the pool finishes sooner the earlier the longest work starts.
    queue = sorted(specs, key=lambda s: not s.slow)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return [f.result() for f in [pool.submit(one, s) for s in queue]]


def main() -> int:
    ap = argparse.ArgumentParser(description="Zebaro-Core-Bot quality gate")
    ap.add_argument("--lint", action="store_true", help="lint and types only")
    ap.add_argument("--tests", action="store_true", help="tests only")
    ap.add_argument("--security", action="store_true", help="bandit and pip-audit only")
    ap.add_argument("--strict", action="store_true", help="tests with coverage (+ coverage.xml)")
    ap.add_argument("--only", default="", help="comma-separated check names")
    ap.add_argument("--fix", action="store_true", help="apply black and isort first")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 2))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("extra", nargs="*", help="arguments after -- go to the single --only check")
    args = ap.parse_args()

    names = [s.name for s in CHECKS]
    if args.list:
        for s in CHECKS:
            print(f"  {s.name:<12} [{s.group}]  {' '.join(s.argv)}")
        return 0

    only = [n.strip() for n in args.only.split(",") if n.strip()]
    strangers = [n for n in only if n not in names]
    if strangers:
        # A typo here used to mean "no checks at all" and a green result.
        print(f"✗ no such check: {', '.join(strangers)}. Available: {', '.join(names)}")
        return 2
    if args.extra and len(only) != 1:
        print("✗ arguments after -- need exactly one check in --only")
        return 2

    if args.fix:
        print("── gate --fix ──")
        for label, argv in FIXERS:
            code, out = sh(resolve(argv))
            print(f"  {'✓' if code == 0 else '✗'} {label}")
            if code != 0:
                print(excerpt(out, 6))

    groups = {g for g, on in (("lint", args.lint), ("tests", args.tests), ("security", args.security)) if on}
    specs = []
    for s in CHECKS:
        if only and s.name not in only:
            continue
        if not only and groups and s.group not in groups:
            continue
        argv = STRICT_PYTEST if (s.name == "pytest" and args.strict and not args.extra) else s.argv
        specs.append(s._replace(argv=[*argv, *args.extra]))

    jobs = max(1, args.jobs)
    label = "strict" if args.strict else ", ".join(sorted(groups)) or ", ".join(only) or "all"
    print(f"── gate: {label} · {len(specs)} checks{f' · {jobs} at a time' if jobs > 1 else ''} ──")

    started = time.perf_counter()
    try:
        results = run_all(specs, jobs)
    except KeyboardInterrupt:
        print("\n  interrupted.")
        return 130
    total = time.perf_counter() - started

    order = {n: i for i, n in enumerate(names)}
    failed = sorted((r for r in results if r.code != 0), key=lambda r: order[r.name])

    slowest = sorted(results, key=lambda r: -r.seconds)[:3]
    print("\n  slowest: " + " · ".join(f"{r.name} {dur(r.seconds)}" for r in slowest))
    for r in results:
        if r.name == "pytest" and args.strict and (pct := coverage_percent(r.out)):
            print(f"  coverage: {pct}")

    if failed:
        print("\n── failed ──")
        for r in failed:
            print(f"\n✗ {r.name}:")
            print(excerpt(r.out))
        print(f"\n{len(failed)} of {len(results)} checks red. Total {dur(total)}.")
        return 1

    print(f"\ngreen: {len(results)} checks in {dur(total)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

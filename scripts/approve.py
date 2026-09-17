#!/usr/bin/env python3
"""Mint a one-shot approval marker that unlocks an outward action.

`guard-git` refuses `git push` and refuses pushing a `v*` tag. This script is
what opens them, and it is a separate step on purpose: an approval should be a
deliberate act with a name, not a flag buried in a command line.

  --push      allows one git push                (minted by /push after a green gate)
  --release   allows one tag push = a deploy     (minted by /release)

Markers are consumed on first use and expire in 15 minutes, so an approval
granted for one change can never be spent on the next one.

Usage:  python scripts/approve.py --push
Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--release", action="store_true")
    args = ap.parse_args()

    names = []
    if args.push:
        names.append(".approve-push")
    if args.release:
        names.extend([".approve-push", ".approve-release"])
    if not names:
        print("нужен --push или --release")
        return 2

    for name in dict.fromkeys(names):
        path = os.path.join(ROOT, ".claude", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("ok")
        print(f"  ✓ {name} — одноразовое, живёт 15 минут")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The bot's version: read from pyproject.toml, the one place it lives (the image ships the file).

A module of its own, apart from config.py: config builds the settings at import time and needs
the whole environment, the version needs nothing.
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def project_version() -> str:
    try:
        with PYPROJECT.open("rb") as f:
            return str(tomllib.load(f)["tool"]["poetry"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"

"""The WireGuard MSIs the image downloads are the ones install.bat asks msiexec for."""

import re
from pathlib import Path

from src.services.vpn.installer import WG_VERSION

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_downloads_the_wireguard_version_the_installer_expects():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"ARG WG_VERSION=(\S+)", dockerfile)
    assert match, "Dockerfile has no ARG WG_VERSION"
    assert match.group(1) == WG_VERSION


def test_every_msi_is_pinned_by_sha256():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for arch in ("amd64", "arm64", "x86"):
        assert re.search(rf"[0-9a-f]{{64}}  wireguard-{arch}-\$\{{WG_VERSION\}}\.msi", dockerfile), arch

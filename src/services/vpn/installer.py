"""A one-file Windows installer: Zebaro-VPN-<Name>.exe.

A 7-Zip SFX: 7zSD.sfx + its config + a 7z archive with install.bat, both profiles and the
WireGuard MSIs for x64, ARM64 and x86. Run, it unpacks to a temporary folder, runs install.bat
(installer/install.bat: rights, an existing WireGuard, another active VPN), waits for it and
deletes the folder.

The image carries 7-Zip, 7zSD.sfx from the LZMA SDK and the MSIs, pinned by SHA256 in the
Dockerfile. Without them — a local run — the EXE is simply not offered.
"""

import shutil
import subprocess  # nosec B404 — only 7z, with arguments the bot builds itself
import tempfile
from pathlib import Path

from src.config import settings
from src.services.vpn.profiles import Profile, slug

WG_VERSION = "1.1.1"
ARCHITECTURES = ("amd64", "arm64", "x86")
SFX_MODULE = "7zSD.sfx"

_TEMPLATES = Path(__file__).parent / "installer"
_BUILD_TIMEOUT_S = 120


class InstallerUnavailable(RuntimeError):
    """7-Zip, the SFX module or an MSI is missing — the EXE cannot be built here."""


def _assets() -> Path:
    return Path(settings.vpn_installer_dir)


def _msi(arch: str) -> str:
    return f"wireguard-{arch}-{WG_VERSION}.msi"


def missing_parts() -> list[str]:
    assets = _assets()
    missing = [name for name in (SFX_MODULE, *map(_msi, ARCHITECTURES)) if not (assets / name).is_file()]
    if shutil.which("7z") is None:
        missing.append("7z")
    return missing


def available() -> bool:
    return not missing_parts()


def _crlf(text: str) -> bytes:
    # cmd.exe misreads labels and blocks in a batch file with bare LF line ends.
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def exe_name(name: str) -> str:
    return f"Zebaro-VPN-{slug(name)}.exe"


def build_exe(full: Profile, lan: Profile, activate: Profile | None = None) -> bytes:
    """The installer for one person; `activate` is the profile switched on (the full one by default)."""
    if missing := missing_parts():
        raise InstallerUnavailable(f"нет {', '.join(missing)}")

    script = (
        (_TEMPLATES / "install.bat")
        .read_text(encoding="utf-8")
        .replace("__WG_VERSION__", WG_VERSION)
        .replace("__FULL__", full.tunnel)
        .replace("__LAN__", lan.tunnel)
        .replace("__ACTIVATE__", (activate or full).tunnel)
    )

    with tempfile.TemporaryDirectory(prefix="zebaro-vpn-") as tmp:
        work = Path(tmp)
        (work / "install.bat").write_bytes(_crlf(script))
        for profile in (full, lan):
            (work / profile.filename).write_bytes(_crlf(profile.config))
        for arch in ARCHITECTURES:
            shutil.copyfile(_assets() / _msi(arch), work / _msi(arch))

        files = ["install.bat", full.filename, lan.filename, *map(_msi, ARCHITECTURES)]
        subprocess.run(  # nosec B603 B607 — fixed binary, no shell, names built above
            # -mx=1: the MSIs are compressed already; a harder pass only costs time.
            ["7z", "a", "-t7z", "-mx=1", "-bso0", "-bsp0", "payload.7z", *files],
            cwd=work,
            check=True,
            timeout=_BUILD_TIMEOUT_S,
            capture_output=True,
        )
        return (
            (_assets() / SFX_MODULE).read_bytes()
            + (_TEMPLATES / "sfx-config.txt").read_bytes()
            + (work / "payload.7z").read_bytes()
        )

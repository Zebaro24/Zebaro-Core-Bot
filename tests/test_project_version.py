import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_version_lives_only_in_pyproject():
    # By path: src.version stays importable without the settings' environment (CI has none).
    version = _load("real_version", ROOT / "src" / "version.py")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    declared = re.search(r'^version = "([\d.]+)"', pyproject, re.M)
    assert declared and version.project_version() == declared.group(1)
    assert not (ROOT / "VERSION").exists()
    assert not re.search(r'version: str = "\d', (ROOT / "src" / "config.py").read_text(encoding="utf-8"))


def test_release_reads_and_bumps_pyproject(tmp_path, monkeypatch):
    release = _load("release", ROOT / "scripts" / "release.py")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.poetry]\nversion = "1.2.3"\n\n[tool.ruff]\ntarget-version = "py311"\n', encoding="utf-8"
    )
    monkeypatch.setattr(release, "PYPROJECT", str(pyproject))

    assert release.read_version() == (1, 2, 3)
    release.write_version("1.3.0")
    assert 'version = "1.3.0"' in pyproject.read_text(encoding="utf-8")
    assert 'target-version = "py311"' in pyproject.read_text(encoding="utf-8")

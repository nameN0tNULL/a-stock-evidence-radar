from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script():  # noqa: ANN202
    path = PROJECT_ROOT / "scripts" / "update_workspace.py"
    spec = importlib.util.spec_from_file_location("update_workspace", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_release(root: Path) -> None:
    (root / "src/a_stock_radar").mkdir(parents=True)
    (root / ".github/workflows").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "reports/daily").mkdir(parents=True)
    (root / "data/history").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-radar"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    (root / "src/a_stock_radar/__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
    (root / ".github/workflows/ci.yml").write_text("name: ci\n", encoding="utf-8")
    (root / "reports/daily/release.md").write_text("release report\n", encoding="utf-8")
    (root / "data/history/release.csv").write_text("release\n", encoding="utf-8")


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    module = _load_script()
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "bad")

    with pytest.raises(module.UpdateError):
        module.safe_extract_zip(archive, tmp_path / "out")


def test_workspace_update_replaces_code_and_merges_reports(tmp_path: Path) -> None:
    module = _load_script()
    release = tmp_path / "release"
    workspace = tmp_path / "workspace"
    _make_release(release)

    workspace.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=workspace,
        check=True,
    )

    (workspace / "old_code.txt").write_text("remove me\n", encoding="utf-8")
    (workspace / "reports/daily").mkdir(parents=True)
    (workspace / "reports/daily/existing.md").write_text("existing report\n", encoding="utf-8")
    (workspace / "data/history").mkdir(parents=True)
    (workspace / "data/history/existing.csv").write_text("existing\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=workspace, check=True, capture_output=True)

    options = module.UpdateOptions(
        workspace=workspace,
        source=release,
        archive=None,
        commit_message="apply release",
        remote="origin",
        allow_dirty=False,
        no_push=True,
        skip_tests=True,
        dry_run=False,
        skip_lint=True,
    )
    module.apply_update(options)

    assert not (workspace / "old_code.txt").exists()
    assert (workspace / "src/a_stock_radar/__init__.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (workspace / "reports/daily/release.md").exists()
    assert (workspace / "reports/daily/existing.md").exists()
    assert (workspace / "data/history/release.csv").exists()
    assert (workspace / "data/history/existing.csv").exists()
    assert (workspace / ".env").read_text(encoding="utf-8") == "TOKEN=secret\n"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=workspace,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert log == "apply release"

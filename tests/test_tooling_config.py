from __future__ import annotations

import tomllib
from pathlib import Path


def test_ruff_rules_are_explicit() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["ruff"]["lint"]["select"] == ["E4", "E7", "E9", "F", "I", "UP"]

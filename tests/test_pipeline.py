from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

from a_stock_radar.config import load_settings
from a_stock_radar.guardrails import PROHIBITED_PHRASES, validate_report
from a_stock_radar.pipeline import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_root(tmp_path: Path) -> Path:
    for folder in ["config", "metadata"]:
        shutil.copytree(PROJECT_ROOT / folder, tmp_path / folder)
    return tmp_path


def test_mock_pipeline_generates_deployable_site(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    payload = run_pipeline(load_settings(root), date(2026, 7, 17), "confirmed", "mock")
    assert payload.report_stage == "demo"
    assert payload.sector_states
    assert (root / "site" / "index.html").exists()
    assert (root / "site" / "api" / "v3" / "latest.json").exists()
    latest = json.loads((root / "site" / "api" / "v3" / "latest.json").read_text(encoding="utf-8"))
    assert latest["data_mode"] == "mock"
    assert latest["market_state"]["label"] != "数据不足"


def test_mock_and_live_histories_are_separated(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    run_pipeline(load_settings(root), date(2026, 7, 17), "confirmed", "mock")
    assert (root / "data" / "history" / "mock_etf_history.csv").exists()
    assert not (root / "data" / "history" / "live_etf_history.csv").exists()


def test_report_guardrails(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    run_pipeline(load_settings(root), date(2026, 7, 17), "confirmed", "mock")
    report = (root / "reports" / "latest" / "latest.md").read_text(encoding="utf-8")
    assert validate_report(report) == []
    for phrase in PROHIBITED_PHRASES:
        assert phrase not in report
    assert "不构成投资建议" in report

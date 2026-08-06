from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from a_stock_radar.publish_gate import validate_publishable_payload

SHANGHAI = ZoneInfo("Asia/Shanghai")


def payload(
    *,
    mode: str = "legacy",
    stage: str = "confirmed",
    available: bool = True,
    rows: int = 5534,
    label: str = "广泛改善",
) -> dict:
    source_id = "kaipanla_review" if mode == "curated" else "market_aggregate"
    return {
        "trade_date": "2026-08-06",
        "report_stage": stage,
        "data_mode": mode,
        "market_state": {
            "label": label,
            "metrics": {"market": {"available": available}},
        },
        "source_quality": [
            {
                "source_id": source_id,
                "available": available,
                "row_count": rows,
                "actual_date": "2026-08-06",
                "schema_ok": available,
                "freshness_ok": available,
            }
        ],
    }


def test_publish_gate_accepts_complete_post_close_report() -> None:
    result = validate_publishable_payload(
        payload(),
        expected_stage="confirmed",
        now=datetime(2026, 8, 6, 18, 0, tzinfo=SHANGHAI),
    )
    assert result.publishable
    assert result.errors == ()


def test_publish_gate_rejects_empty_market_report() -> None:
    result = validate_publishable_payload(
        payload(available=False, rows=0, label="数据不足"),
        expected_stage="confirmed",
        now=datetime(2026, 8, 6, 18, 0, tzinfo=SHANGHAI),
    )
    assert not result.publishable
    assert "market metrics are unavailable" in result.errors
    assert any("only 0 rows" in error for error in result.errors)


def test_publish_gate_rejects_same_day_confirmed_report_before_close() -> None:
    result = validate_publishable_payload(
        payload(),
        expected_stage="confirmed",
        now=datetime(2026, 8, 6, 9, 16, tzinfo=SHANGHAI),
    )
    assert not result.publishable
    assert any("before 16:05" in error for error in result.errors)


def test_publish_gate_rejects_mock_report() -> None:
    result = validate_publishable_payload(
        payload(mode="mock", stage="demo"),
        now=datetime(2026, 8, 6, 18, 0, tzinfo=SHANGHAI),
    )
    assert not result.publishable
    assert any("mock/demo" in error for error in result.errors)


def test_publish_gate_uses_kaipanla_for_curated_mode() -> None:
    result = validate_publishable_payload(
        payload(mode="curated", rows=4500),
        expected_stage="confirmed",
        now=datetime(2026, 8, 6, 18, 0, tzinfo=SHANGHAI),
    )
    assert result.publishable

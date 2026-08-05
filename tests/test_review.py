from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from a_stock_radar.models import MarketState, SourceQuality
from a_stock_radar.review import (
    OUTCOME_CONTINUATION,
    OUTCOME_DETERIORATION,
    OUTCOME_ROTATION,
    build_daily_review,
    build_historical_conditionals,
    load_microstructure_summary,
)


THRESHOLDS = {
    "market": {
        "broad_breadth_ratio": 0.60,
        "weak_breadth_ratio": 0.40,
        "weight_gap_pct": 0.80,
    },
    "quality": {"high": 80, "medium": 55},
    "review": {"minimum_scenario_samples": 5},
}


def build_history(periods: int = 60) -> pd.DataFrame:
    start = date(2026, 1, 2)
    rows = []
    for index in range(periods):
        pair = index // 2
        if index % 2 == 0:
            breadth = 0.70
            median_return = 1.0
            cap_return = 1.1
        else:
            outcome = pair % 3
            if outcome == 0:
                breadth = 0.70
                median_return = 0.6
            elif outcome == 1:
                breadth = 0.50
                median_return = 0.1
            else:
                breadth = 0.30
                median_return = -0.6
            cap_return = median_return
        rows.append(
            {
                "trade_date": start + timedelta(days=index),
                "total_amount": 1_000_000_000 + index * 1_000_000,
                "breadth_ratio": breadth,
                "median_return": median_return,
                "cap_weighted_return": cap_return,
            }
        )
    return pd.DataFrame(rows)


def market_state(trade_date: date) -> MarketState:
    return MarketState(
        trade_date=trade_date,
        label="广泛改善",
        confidence_level="high",
        confidence_score=90,
        metrics={
            "market": {
                "available": True,
                "breadth_ratio": 0.70,
                "median_return": 1.0,
                "cap_weighted_return": 1.1,
                "total_amount": 1_200_000_000,
                "limit_up_count": 80,
                "limit_down_count": 2,
            },
            "margin": {
                "available": True,
                "financing_balance": 2_000_000_000,
                "change_ratio_5d": 0.01,
            },
        },
        supporting_evidence=["上涨覆盖率较高。"],
        counter_evidence=[],
        unknowns=[],
    )


def source_qualities(trade_date: date) -> list[SourceQuality]:
    return [
        SourceQuality(
            source_id="market_aggregate",
            display_name="聚合行情",
            trade_date=trade_date,
            expected_date=trade_date,
            actual_date=trade_date,
            available=True,
            freshness_ok=True,
            schema_ok=True,
            row_count=5500,
            official=False,
            evidence_level="L2",
        ),
        SourceQuality(
            source_id="margin_sse_summary",
            display_name="上交所融资汇总",
            trade_date=trade_date,
            expected_date=trade_date,
            actual_date=trade_date,
            available=True,
            freshness_ok=True,
            schema_ok=True,
            row_count=1,
            official=True,
            evidence_level="L1",
        ),
    ]


def test_historical_conditionals_are_empirical_and_sum_to_one() -> None:
    records = build_historical_conditionals(
        build_history(),
        "广泛改善",
        THRESHOLDS,
        minimum_samples=5,
    )

    one_day = [item for item in records if item.horizon == "1d"]
    assert {item.outcome for item in one_day} == {
        OUTCOME_CONTINUATION,
        OUTCOME_ROTATION,
        OUTCOME_DETERIORATION,
    }
    assert all(item.status == "available" for item in one_day)
    assert sum(item.conditional_probability or 0 for item in one_day) == 1
    assert all(item.sample_size >= 5 for item in one_day)


def test_historical_probability_is_hidden_when_samples_are_insufficient() -> None:
    records = build_historical_conditionals(
        build_history(6),
        "广泛改善",
        THRESHOLDS,
        minimum_samples=20,
    )

    assert all(item.status in {"insufficient_samples", "unavailable"} for item in records)
    assert all(item.conditional_probability is None for item in records)


def test_microstructure_summary_reads_only_non_rejected_manifests(tmp_path) -> None:
    trade_date = date(2026, 7, 31)
    base = tmp_path / "data" / "raw" / "tick_trade" / "date=20260731"
    accepted = base / "code=000001.SZ"
    rejected = base / "code=600000.SH"
    accepted.mkdir(parents=True)
    rejected.mkdir(parents=True)
    (accepted / "manifest.json").write_text(
        json.dumps(
            {
                "source": {"source_id": "tick_akshare_tencent_tplus1"},
                "quality": {"status": "confirmed"},
                "features": {
                    "total_notional": 1000,
                    "buy_labeled_notional": 600,
                    "sell_labeled_notional": 300,
                    "closing_auction_notional_share": 0.2,
                },
            }
        ),
        encoding="utf-8",
    )
    (rejected / "manifest.json").write_text(
        json.dumps(
            {
                "source": {"source_id": "tick_akshare_tencent_tplus1"},
                "quality": {"status": "rejected"},
                "features": {"total_notional": 9000},
            }
        ),
        encoding="utf-8",
    )

    result = load_microstructure_summary(tmp_path, trade_date)

    assert result.available is True
    assert result.symbol_count == 1
    assert result.confirmed_symbol_count == 1
    assert result.total_notional == 1000
    assert result.signed_notional_imbalance == 0.3
    assert result.classification_coverage == 0.9
    assert result.closing_auction_notional_share == 0.2


def test_daily_review_contains_layers_hypotheses_scenarios_and_provenance(tmp_path) -> None:
    trade_date = date(2026, 7, 31)
    review = build_daily_review(
        tmp_path,
        trade_date,
        build_history(),
        market_state(trade_date),
        [],
        source_qualities(trade_date),
        THRESHOLDS,
    )

    assert review.market_phase == "广泛改善"
    assert len(review.participant_hypotheses) == 5
    assert len(review.scenario_paths) == 3
    assert any(item.layer_id == "seat_facts" and item.status == "missing" for item in review.evidence_layers)
    assert any(
        item.field_path == "market_state.metrics.market.total_amount"
        for item in review.field_provenance
    )
    assert review.seat_facts == []
    assert review.confirmation_checklist
    assert review.falsification_checklist

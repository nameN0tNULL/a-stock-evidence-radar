from __future__ import annotations

import json
from datetime import date

import pandas as pd

from a_stock_radar.models import (
    DailyReview,
    EvidenceLayerStatus,
    HistoricalConditionalProbability,
    MicrostructureSummary,
    ParticipantHypothesis,
    ScenarioPath,
)
from a_stock_radar.product_io import normalize_kaipanla
from a_stock_radar.product_provider import ProductSourceProvider
from a_stock_radar.review_product import enrich_product_review


class FakeAkshare:
    @staticmethod
    def stock_lhb_detail_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "上榜日": date(2026, 7, 31),
                    "上榜原因": "日涨幅偏离值达到7%",
                    "龙虎榜净买额": 120_000_000,
                }
            ]
        )

    @staticmethod
    def stock_lhb_jgmmtj_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame([{"代码": "000001", "买方机构数": 2, "卖方机构数": 1}])

    @staticmethod
    def stock_lhb_hyyyb_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame([{"营业部名称": "示例营业部", "上榜日": date(2026, 7, 31)}])

    @staticmethod
    def stock_lhb_yybph_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame([{"营业部名称": "示例营业部", "上榜后5天-上涨概率": 55.0}])

    @staticmethod
    def stock_lhb_traderstatistic_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame([{"营业部名称": "示例营业部", "龙虎榜成交金额": 1_000_000}])


def test_normalize_kaipanla_uses_exported_market_rows() -> None:
    frame = pd.DataFrame(
        [
            {
                "代码": "SZ000001",
                "名称": "平安银行",
                "最新价": "12.30",
                "涨跌幅": "2.5%",
                "成交额": "12.5亿",
                "流通市值": "2200亿",
                "换手率": "1.2%",
            }
        ]
    )

    result = normalize_kaipanla(frame, date(2026, 7, 31))

    assert result.iloc[0]["security_code"] == "000001"
    assert result.iloc[0]["amount"] == 1_250_000_000
    assert result.iloc[0]["source_id"] == "kaipanla_review"


def test_product_provider_uses_named_sources_and_writes_artifacts(tmp_path) -> None:
    trade_date = date(2026, 7, 31)
    for folder in ["kaipanla", "dazhihui", "cls", "daily_stock_analysis", "tradingagents_cn"]:
        (tmp_path / "imports" / folder).mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "代码": "000001",
                "名称": "平安银行",
                "最新价": 12.3,
                "涨跌幅": 2.5,
                "成交额": 1_250_000_000,
            }
        ]
    ).to_csv(tmp_path / "imports" / "kaipanla" / "2026-07-31.csv", index=False)
    pd.DataFrame(
        [{"代码": "000001", "DDE净额": 100_000_000, "成交额": 1_000_000_000}]
    ).to_csv(tmp_path / "imports" / "dazhihui" / "2026-07-31.csv", index=False)
    pd.DataFrame(
        [
            {
                "代码": "000001",
                "名称": "平安银行",
                "标题": "财联社龙虎榜快讯",
                "买方席位": "机构专用",
                "净买额": 80_000_000,
            }
        ]
    ).to_csv(tmp_path / "imports" / "cls" / "2026-07-31.csv", index=False)
    (tmp_path / "imports" / "daily_stock_analysis" / "2026-07-31.md").write_text(
        "自动日报摘要", encoding="utf-8"
    )
    (tmp_path / "imports" / "tradingagents_cn" / "2026-07-31.json").write_text(
        json.dumps({"decision": "多空双方对持续性存在分歧"}, ensure_ascii=False),
        encoding="utf-8",
    )

    bundle = ProductSourceProvider(tmp_path, {}, ak_module=FakeAkshare()).fetch(trade_date)

    assert bundle.data_mode == "curated"
    assert len(bundle.market) == 1
    assert {item.source_id for item in bundle.qualities} >= {
        "kaipanla_review",
        "eastmoney_lhb",
        "dazhihui_dde_ace",
        "cls_lhb_authorized",
        "daily_stock_analysis",
        "tradingagents_cn",
    }
    artifact_dir = tmp_path / "data" / "raw" / "product_sources" / "date=20260731"
    facts = json.loads((artifact_dir / "seat_facts.json").read_text(encoding="utf-8"))
    assert {item["source_id"] for item in facts} == {"eastmoney_lhb", "cls_lhb_authorized"}
    assert (artifact_dir / "dde_summary.json").exists()


def _base_review(trade_date: date) -> DailyReview:
    layers = [
        EvidenceLayerStatus(
            layer_id=layer_id,
            display_name=layer_id,
            status="missing",
            summary="",
        )
        for layer_id in ("market_replay", "seat_facts", "microstructure", "automated_report")
    ]
    short = ParticipantHypothesis(
        participant_id="short_horizon_traders",
        display_name="短周期交易资金原型",
        activity="mixed",
        confidence_level="low",
        confidence_score=40,
        observation="市场处于分歧。",
    )
    conditional = HistoricalConditionalProbability(
        condition="市场状态=中性整理",
        outcome="分歧或轮动",
        horizon="1d",
        status="insufficient_samples",
        method="test",
    )
    scenario = ScenarioPath(
        scenario_id="rotation",
        title="分歧轮动",
        narrative="测试",
        probability_status="insufficient_samples",
        probability_source="insufficient_history",
        confidence_level="low",
    )
    return DailyReview(
        review_version="test",
        market_phase="中性整理",
        market_phase_summary="测试",
        evidence_layers=layers,
        participant_hypotheses=[short],
        counterparty_relations=[],
        historical_conditionals=[conditional],
        scenario_paths=[scenario],
        microstructure=MicrostructureSummary(),
    )


def test_enrich_product_review_loads_seats_dde_and_debate(tmp_path) -> None:
    trade_date = date(2026, 7, 31)
    directory = tmp_path / "data" / "raw" / "product_sources" / "date=20260731"
    directory.mkdir(parents=True)
    (directory / "seat_facts.json").write_text(
        json.dumps(
            [
                {
                    "fact_id": "em:1",
                    "security_code": "000001",
                    "fact_type": "龙虎榜上榜",
                    "source_id": "eastmoney_lhb",
                    "source_date": "2026-07-31",
                    "official": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    (directory / "dde_summary.json").write_text(
        json.dumps(
            {
                "source_id": "dazhihui_dde_ace",
                "symbol_count": 10,
                "confirmed_symbol_count": 10,
                "provisional_symbol_count": 0,
                "total_notional": 1_000_000,
                "signed_notional_imbalance": 0.12,
                "classification_coverage": 0.8,
                "limitations": ["不是净流入"],
            }
        ),
        encoding="utf-8",
    )
    (directory / "external_analyses.json").write_text(
        json.dumps(
            [
                {
                    "source_id": "tradingagents_cn",
                    "display_name": "TradingAgents-CN多空辩论",
                    "summary": "多空双方对持续性存在分歧",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = enrich_product_review(tmp_path, trade_date, _base_review(trade_date), [])

    assert len(result.seat_facts) == 1
    assert result.microstructure.source_ids == ["dazhihui_dde_ace"]
    assert "大智慧DDE/ACE" in result.participant_hypotheses[0].observation
    assert "TradingAgents-CN" in result.scenario_paths[0].alternative_explanations[0]

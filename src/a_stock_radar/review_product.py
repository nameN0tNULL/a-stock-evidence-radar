from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .models import DailyReview, FieldProvenance, MicrostructureSummary, SeatFact, SourceQuality


def _directory(root: Path, trade_date: date) -> Path:
    return (
        root
        / "data"
        / "raw"
        / "product_sources"
        / f"date={trade_date.strftime('%Y%m%d')}"
    )


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _quality_ids(qualities: list[SourceQuality], prefix: str) -> list[str]:
    return [item.source_id for item in qualities if item.available and item.source_id.startswith(prefix)]


def enrich_product_review(
    root: Path,
    trade_date: date,
    review: DailyReview,
    qualities: list[SourceQuality],
) -> DailyReview:
    directory = _directory(root, trade_date)
    facts_payload = _read_json(directory / "seat_facts.json", [])
    facts: list[SeatFact] = []
    for item in facts_payload:
        try:
            facts.append(SeatFact.model_validate(item))
        except Exception:
            continue
    review.seat_facts = facts

    dde_payload = _read_json(directory / "dde_summary.json", None)
    if isinstance(dde_payload, dict):
        review.microstructure = MicrostructureSummary(
            available=True,
            symbol_count=int(dde_payload.get("symbol_count") or 0),
            confirmed_symbol_count=int(dde_payload.get("confirmed_symbol_count") or 0),
            provisional_symbol_count=int(dde_payload.get("provisional_symbol_count") or 0),
            total_notional=dde_payload.get("total_notional"),
            signed_notional_imbalance=dde_payload.get("signed_notional_imbalance"),
            classification_coverage=dde_payload.get("classification_coverage"),
            closing_auction_notional_share=dde_payload.get("closing_auction_notional_share"),
            source_ids=[str(dde_payload.get("source_id") or "dazhihui_dde_ace")],
            limitations=list(dde_payload.get("limitations") or []),
        )
        review.field_provenance = [
            item
            for item in review.field_provenance
            if item.field_path != "daily_review.microstructure.signed_notional_imbalance"
        ]
        review.field_provenance.append(
            FieldProvenance(
                field_path="daily_review.microstructure.signed_notional_imbalance",
                display_name="大智慧DDE/ACE订单规模差",
                value=review.microstructure.signed_notional_imbalance,
                unit="ratio",
                source_ids=review.microstructure.source_ids,
                evidence_level="L3",
                official=False,
                as_of_date=trade_date,
                transform="大智慧导出中的DDE净额合计 / 对应成交额合计",
                status="confirmed",
                limitations=review.microstructure.limitations,
            )
        )
        short_horizon = next(
            (
                item
                for item in review.participant_hypotheses
                if item.participant_id == "short_horizon_traders"
            ),
            None,
        )
        if short_horizon and review.microstructure.signed_notional_imbalance is not None:
            ratio = review.microstructure.signed_notional_imbalance
            short_horizon.observation += f" 大智慧DDE/ACE订单规模差为 {ratio:+.1%}。"
            short_horizon.supporting_evidence.append(
                f"大智慧DDE/ACE覆盖 {review.microstructure.symbol_count} 只证券，订单规模差 {ratio:+.1%}。"
            )
            short_horizon.alternative_explanations.append(
                "大单口径可能混合机构、量化、个人大户、做市和拆单执行。"
            )
            short_horizon.source_fields.append(
                "daily_review.microstructure.signed_notional_imbalance"
            )
            short_horizon.confidence_score = min(78, short_horizon.confidence_score + 8)
            short_horizon.confidence_level = (
                "high"
                if short_horizon.confidence_score >= 80
                else "medium"
                if short_horizon.confidence_score >= 55
                else "low"
            )

    analyses = _read_json(directory / "external_analyses.json", [])
    analysis_by_id = {
        str(item.get("source_id")): item
        for item in analyses
        if isinstance(item, dict) and item.get("source_id")
    }
    debate = analysis_by_id.get("tradingagents_cn")
    if debate:
        excerpt = str(debate.get("summary") or "").replace("\n", " ")[:240]
        rotation = next(
            (item for item in review.scenario_paths if item.scenario_id == "rotation"),
            None,
        )
        if rotation and excerpt:
            rotation.alternative_explanations.append(
                "TradingAgents-CN多空辩论参考（非事实源）：" + excerpt
            )

    for layer in review.evidence_layers:
        if layer.layer_id == "market_replay":
            ids = _quality_ids(qualities, "kaipanla")
            layer.status = "available" if ids else "missing"
            layer.source_ids = ids
            layer.summary = (
                "盘面复盘结构来自开盘啦官方产品导出。"
                if ids
                else "缺少开盘啦当日官方产品导出；不回退到腾讯、新浪或自建行情。"
            )
            layer.limitations = [
                "开盘啦分类和复盘标签属于产品口径，不等于交易所事实。",
                "未配置导出时，该层保持缺失。",
            ]
        elif layer.layer_id == "seat_facts":
            source_ids = sorted({item.source_id for item in facts})
            layer.status = "available" if facts else "missing"
            layer.source_ids = source_ids
            layer.summary = (
                f"已载入 {len(facts)} 条东方财富/财联社龙虎榜事实。"
                if facts
                else "东方财富当日无可用龙虎榜记录，且未提供财联社授权导出。"
            )
            layer.limitations = [
                "营业部、机构专用和交易单元不等于最终投资者。",
                "东方财富负责结构化统计，财联社只作授权快讯交叉核实。",
            ]
        elif layer.layer_id == "microstructure":
            layer.status = "available" if review.microstructure.available else "missing"
            layer.source_ids = review.microstructure.source_ids
            layer.summary = (
                f"大智慧DDE/ACE覆盖 {review.microstructure.symbol_count} 只证券。"
                if review.microstructure.available
                else "未提供大智慧DDE/ACE官方导出或授权数据。"
            )
            layer.limitations = review.microstructure.limitations or [
                "不使用免费分笔抓取替代大智慧DDE/ACE。"
            ]
        elif layer.layer_id == "automated_report":
            source_ids = sorted(analysis_by_id)
            layer.source_ids = source_ids
            layer.status = "available" if source_ids else "partial"
            names = [str(analysis_by_id[item].get("display_name") or item) for item in source_ids]
            layer.summary = (
                "已载入外部分析产物：" + "、".join(names) + "。"
                if names
                else "本地证据报告可用；未载入daily_stock_analysis或TradingAgents-CN产物。"
            )
            layer.limitations = [
                "daily_stock_analysis只提供日报、推送和摘要架构参考。",
                "TradingAgents-CN只提供多空辩论参考，不能识别对手盘或充当事实源。",
            ]

    review.field_provenance.append(
        FieldProvenance(
            field_path="daily_review.seat_facts",
            display_name="龙虎榜席位事实数量",
            value=len(facts),
            unit="records",
            source_ids=sorted({item.source_id for item in facts}),
            evidence_level="L2",
            official=False,
            as_of_date=trade_date,
            transform="东方财富结构化记录与财联社授权快讯去身份化归一",
            status="provisional" if facts else "missing",
            limitations=["席位事实不代表最终账户身份。"],
        )
    )
    review.confirmation_checklist.extend(
        [
            "用东方财富个股龙虎榜详情核对财联社快讯中的机构数量和净额。",
            "将营业部当日事实与东方财富近一年后续表现分开保存，禁止把历史标签写成当天身份。",
            "大智慧DDE/ACE只在授权数据覆盖和口径完整时参与行为判断。",
        ]
    )
    review.falsification_checklist.extend(
        [
            "开盘啦导出日期或字段口径不匹配时，撤销市场复盘层结论。",
            "东方财富与财联社席位事实不一致时，标记冲突而不是自动选边。",
            "外部AI报告与结构化事实冲突时，以结构化事实为准。",
        ]
    )
    return review

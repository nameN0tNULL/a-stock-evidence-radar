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
                transform="大智慧授权产物中的DDE净额合计 / 对应成交额合计",
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

    kaipanla_public = _read_json(directory / "kaipanla_public_review.json", None)
    for layer in review.evidence_layers:
        if layer.layer_id == "market_replay":
            export_ids = _quality_ids(qualities, "kaipanla_review")
            public_ids = _quality_ids(qualities, "kaipanla_public_review")
            layer.source_ids = export_ids + public_ids
            if export_ids:
                layer.status = "available"
                layer.summary = "盘面复盘结构来自开盘啦产品导出，并由东方财富全市场快照计算宽度指标。"
            elif public_ids:
                layer.status = "partial"
                title = str((kaipanla_public or {}).get("title") or "公开复盘文章")
                article_date = str((kaipanla_public or {}).get("article_date") or "未知日期")
                layer.summary = (
                    f"已读取开盘啦公开文章《{title}》（{article_date}）；"
                    "结构化市场宽度来自东方财富全市场快照。"
                )
            else:
                layer.status = "partial"
                layer.summary = (
                    "本次未找到可核验的开盘啦公开复盘文章；结构化市场宽度仍来自东方财富全市场快照。"
                )
            layer.limitations = [
                "开盘啦公开文章不等同于登录态内的完整复盘啦、市场情绪或深度龙虎榜数据。",
                "开盘啦的情绪、强度和资金标签属于产品口径，不覆盖结构化市场事实。",
            ]
        elif layer.layer_id == "seat_facts":
            source_ids = sorted({item.source_id for item in facts})
            layer.status = "available" if facts else "missing"
            layer.source_ids = source_ids
            layer.summary = (
                f"已载入 {len(facts)} 条东方财富/财联社龙虎榜事实。"
                if facts
                else "东方财富当日无可用龙虎榜记录，财联社公开页也没有可归一的同日记录。"
            )
            layer.limitations = [
                "营业部、机构专用和交易单元不等于最终投资者。",
                "东方财富负责结构化统计，财联社公开文章只作交叉核实。",
            ]
        elif layer.layer_id == "microstructure":
            layer.status = "available" if review.microstructure.available else "missing"
            layer.source_ids = review.microstructure.source_ids
            layer.summary = (
                f"大智慧DDE/ACE覆盖 {review.microstructure.symbol_count} 只证券。"
                if review.microstructure.available
                else "未取得大智慧DDE/ACE授权产物；GitHub Runner不会伪造该层。"
            )
            layer.limitations = review.microstructure.limitations or [
                "DDE/ACE必须来自拥有相应订阅权限的终端导出或授权数据桥。"
            ]
        elif layer.layer_id == "automated_report":
            source_ids = sorted(analysis_by_id)
            layer.source_ids = source_ids
            layer.status = "available" if source_ids else "partial"
            names = [str(analysis_by_id[item].get("display_name") or item) for item in source_ids]
            layer.summary = (
                "已真实运行或下载外部分析产物：" + "、".join(names) + "。"
                if names
                else "本地证据报告可用；外部开源分析任务未启用或运行失败。"
            )
            layer.limitations = [
                "daily_stock_analysis只提供日报、推送和摘要架构参考。",
                "TradingAgents-CN只提供多空辩论参考，不能识别对手盘或充当事实源。",
            ]

    if isinstance(kaipanla_public, dict):
        review.field_provenance.append(
            FieldProvenance(
                field_path="daily_review.kaipanla_public_review",
                display_name="开盘啦公开复盘文章",
                value=kaipanla_public.get("title"),
                unit=None,
                source_ids=["kaipanla_public_review"],
                evidence_level="L3",
                official=False,
                as_of_date=date.fromisoformat(str(kaipanla_public.get("article_date"))),
                transform="读取开盘啦公开文章标题、正文、图片链接和可明确提取的数字",
                status=(
                    "confirmed"
                    if str(kaipanla_public.get("article_date")) == trade_date.isoformat()
                    else "provisional"
                ),
                limitations=list(kaipanla_public.get("limitations") or []),
            )
        )
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
            transform="东方财富结构化记录与财联社公开/授权文章去身份化归一",
            status="provisional" if facts else "missing",
            limitations=["席位事实不代表最终账户身份。"],
        )
    )
    review.confirmation_checklist.extend(
        [
            "用东方财富个股龙虎榜详情核对财联社文章中的机构数量和净额。",
            "将营业部当日事实与东方财富近一年后续表现分开保存，禁止把历史标签写成当天身份。",
            "大智慧DDE/ACE只在授权数据覆盖和口径完整时参与行为判断。",
            "开盘啦公开文章与结构化行情冲突时，保留冲突并以可计算事实为准。",
        ]
    )
    review.falsification_checklist.extend(
        [
            "开盘啦文章日期不匹配时，只能作为背景，不得写成当日事实。",
            "东方财富与财联社席位事实不一致时，标记冲突而不是自动选边。",
            "外部AI报告与结构化事实冲突时，以结构化事实为准。",
        ]
    )
    return review

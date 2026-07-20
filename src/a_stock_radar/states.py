from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from .models import EvidenceRecord, MarketState, SectorState, SourceQuality


def _direction(value: float | None, positive_threshold: float, negative_threshold: float) -> str:
    if value is None:
        return "unknown"
    if value >= positive_threshold:
        return "positive"
    if value <= negative_threshold:
        return "negative"
    return "neutral"


def confidence_level(score: float, thresholds: dict[str, Any]) -> str:
    if score >= float(thresholds["quality"]["high"]):
        return "high"
    if score >= float(thresholds["quality"]["medium"]):
        return "medium"
    return "low"


def source_quality_score(qualities: list[SourceQuality]) -> float:
    if not qualities:
        return 0.0
    weights = {"L1": 1.0, "L2": 0.7, "L3": 0.4, "L4": 0.2}
    total = 0.0
    achieved = 0.0
    for item in qualities:
        weight = weights[item.evidence_level]
        total += weight
        if item.available and item.schema_ok:
            value = 1.0
            if not item.freshness_ok:
                value *= 0.5
            achieved += weight * value
    return round(100 * achieved / total, 1) if total else 0.0


def classify_market_state(
    trade_date: date,
    market: dict[str, Any],
    margin: dict[str, Any],
    qualities: list[SourceQuality],
    thresholds: dict[str, Any],
) -> MarketState:
    quality_score = source_quality_score(qualities)
    support: list[str] = []
    counter: list[str] = []
    unknowns: list[str] = []
    if not market.get("available"):
        return MarketState(
            trade_date=trade_date,
            label="数据不足",
            confidence_level="low",
            confidence_score=quality_score,
            metrics={"market": market, "margin": margin},
            supporting_evidence=[],
            counter_evidence=[],
            unknowns=["市场宽度数据缺失，无法确认市场参与状态。"],
        )

    breadth = market.get("breadth_ratio")
    median_return = market.get("median_return")
    cap_return = market.get("cap_weighted_return")
    amount_change = market.get("amount_5d_change")
    broad = float(thresholds["market"]["broad_breadth_ratio"])
    weak = float(thresholds["market"]["weak_breadth_ratio"])
    gap = float(thresholds["market"]["weight_gap_pct"])

    if breadth is not None and breadth >= broad and median_return is not None and median_return > 0:
        label = "广泛改善"
        support.append(f"上涨覆盖率为 {breadth:.1%}，中位数涨跌幅为 {median_return:.2f}%。")
    elif (
        cap_return is not None
        and median_return is not None
        and cap_return - median_return >= gap
        and breadth is not None
        and breadth < broad
    ):
        label = "权重主导"
        support.append("市值加权表现明显强于等权中位数，市场改善主要集中在较大市值证券。")
    elif breadth is not None and breadth < weak and amount_change is not None and amount_change < 0:
        label = "参与收缩"
        support.append(f"上涨覆盖率仅为 {breadth:.1%}，近5日成交规模同时收缩。")
    elif breadth is not None and 0.45 <= breadth <= 0.55:
        label = "高度分化"
        support.append("上涨与下跌数量接近，市场缺少一致方向。")
    else:
        label = "中性整理"
        support.append("市场宽度和成交变化未形成足够一致的状态信号。")

    if margin.get("available"):
        change5 = margin.get("change_ratio_5d")
        if change5 is not None:
            if change5 > 0:
                support.append(f"全市场融资余额近5日增加 {change5:.2%}，杠杆参与有所增强。")
            elif change5 < 0:
                counter.append(f"全市场融资余额近5日下降 {abs(change5):.2%}，杠杆参与偏弱。")
    else:
        unknowns.append("融资余额数据缺失，无法确认杠杆资金敞口变化。")

    if market.get("amount_percentile") is None:
        unknowns.append("历史样本不足，成交和市场宽度的长期百分位暂不可用。")
    return MarketState(
        trade_date=trade_date,
        label=label,
        confidence_level=confidence_level(quality_score, thresholds),  # type: ignore[arg-type]
        confidence_score=quality_score,
        metrics={"market": market, "margin": margin},
        supporting_evidence=support,
        counter_evidence=counter,
        unknowns=unknowns,
    )


def _evidence(
    trade_date: date,
    sector_id: str,
    sector_name: str,
    cluster: str,
    metric: str,
    value: float | None,
    direction: str,
    horizon: str,
    percentile: float | None,
    evidence_level: str,
    official: bool,
    source_id: str,
    estimated: bool,
    missing_reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"{trade_date}:{sector_id}:{cluster}:{metric}:{horizon}",
        trade_date=trade_date,
        entity_type="sector",
        entity_id=sector_id,
        entity_name=sector_name,
        cluster=cluster,
        metric=metric,
        value=value,
        direction=direction,  # type: ignore[arg-type]
        horizon=horizon,  # type: ignore[arg-type]
        percentile=percentile,
        evidence_level=evidence_level,  # type: ignore[arg-type]
        official=official,
        source_id=source_id,
        source_date=trade_date,
        retrieved_at=datetime.now(UTC),
        is_estimated=estimated,
        is_missing=value is None,
        missing_reason=missing_reason,
        quality_score=90 if official else 70,
        details=details or {},
    )


def classify_sector_states(
    trade_date: date,
    etf_features: dict[str, dict[str, Any]],
    margin_features: dict[str, dict[str, Any]],
    qualities: list[SourceQuality],
    thresholds: dict[str, Any],
    minimum_samples: int,
) -> list[SectorState]:
    states: list[SectorState] = []
    all_themes = sorted(set(etf_features) | set(margin_features))
    general_quality = source_quality_score(qualities)
    etf_t = thresholds["etf"]
    margin_t = thresholds["margin"]
    confirmation_t = thresholds["confirmation"]

    for theme_id in all_themes:
        etf = etf_features.get(theme_id, {})
        margin = margin_features.get(theme_id, {})
        theme_name = etf.get("theme_name") or margin.get("theme_name") or theme_id
        support: list[str] = []
        counter: list[str] = []
        unknowns: list[str] = []
        next_conditions: list[str] = []
        evidence: list[EvidenceRecord] = []

        etf_samples = int(etf.get("history_samples", 0))
        etf_ratio_5d = etf.get("flow_ratio_5d")
        etf_direction = _direction(
            etf_ratio_5d,
            float(etf_t["positive_flow_ratio_5d"]),
            float(etf_t["negative_flow_ratio_5d"]),
        )
        if etf_samples < minimum_samples:
            etf_direction = "unknown"
            unknowns.append(f"ETF份额历史有效样本为 {etf_samples} 日，尚不足以形成长期百分位判断。")
        evidence.append(
            _evidence(
                trade_date,
                theme_id,
                theme_name,
                "etf_creation",
                "estimated_creation_flow_ratio",
                etf_ratio_5d,
                etf_direction,
                "5d",
                etf.get("flow_percentile"),
                "L1",
                bool(etf.get("official_share_coverage", 0) >= 0.5),
                "sse_etf_shares+szse_etf_shares",
                True,
                "ETF份额或历史数据不足" if etf_direction == "unknown" else None,
                {
                    "estimated_flow_5d": etf.get("estimated_flow_5d"),
                    "positive_coverage": etf.get("positive_coverage"),
                    "valid_funds": etf.get("valid_funds"),
                    "official_share_coverage": etf.get("official_share_coverage"),
                },
            )
        )

        margin_samples = int(margin.get("history_samples", 0))
        margin_ratio_5d = margin.get("change_ratio_5d")
        margin_direction = _direction(
            margin_ratio_5d,
            float(margin_t["positive_change_ratio_5d"]),
            float(margin_t["negative_change_ratio_5d"]),
        )
        if not margin:
            margin_direction = "unknown"
            unknowns.append("该主题缺少证券—板块融资映射，不能把全市场融资变化直接归因到该主题。")
        elif margin_samples < minimum_samples:
            margin_direction = "unknown"
            unknowns.append(f"主题融资历史有效样本为 {margin_samples} 日，暂不输出高置信度方向。")
        evidence.append(
            _evidence(
                trade_date,
                theme_id,
                theme_name,
                "margin_exposure",
                "financing_balance_change_ratio",
                margin_ratio_5d,
                margin_direction,
                "5d",
                margin.get("change_percentile"),
                "L1",
                True,
                "margin_detail",
                False,
                "证券—板块映射或历史数据不足" if margin_direction == "unknown" else None,
                {"mapped_securities": margin.get("mapped_securities")},
            )
        )

        price_breadth = etf.get("price_breadth")
        persistence = max(
            int(etf.get("positive_persistence_days", 0)),
            int(margin.get("positive_persistence_days", 0)),
        )
        etf_positive = etf_direction == "positive"
        etf_negative = etf_direction == "negative"
        margin_positive = margin_direction == "positive"
        margin_negative = margin_direction == "negative"
        conflict = (etf_positive and margin_negative) or (etf_negative and margin_positive)

        if etf_positive:
            support.append(
                f"相关ETF近5日份额变化估算为正，约占前期资产代理值的 {etf_ratio_5d:.2%}。"
            )
        elif etf_negative:
            counter.append(
                f"相关ETF近5日份额变化估算为负，约占前期资产代理值的 {abs(etf_ratio_5d):.2%}。"
            )
        if margin_positive:
            support.append(f"已映射证券的融资余额近5日增加 {margin_ratio_5d:.2%}。")
        elif margin_negative:
            counter.append(f"已映射证券的融资余额近5日下降 {abs(margin_ratio_5d):.2%}。")
        if price_breadth is not None:
            if price_breadth >= float(confirmation_t["positive_price_breadth"]):
                support.append(f"ETF组价格改善覆盖率为 {price_breadth:.1%}。")
            elif price_breadth <= float(confirmation_t["negative_price_breadth"]):
                counter.append(f"ETF组价格改善覆盖率仅为 {price_breadth:.1%}。")

        enough_etf = etf_samples >= minimum_samples
        enough_margin = bool(margin) and margin_samples >= minimum_samples
        if not enough_etf and not enough_margin:
            label = "数据不足"
        elif conflict:
            label = "多证据分歧"
        elif (
            etf_positive
            and margin_positive
            and price_breadth is not None
            and price_breadth >= float(confirmation_t["positive_price_breadth"])
            and persistence >= int(confirmation_t["minimum_persistence_days"])
        ):
            label = "多证据参与增强"
        elif etf_positive and not margin_positive:
            label = "配置型资金改善"
        elif margin_positive and not etf_positive:
            label = "杠杆主导活跃"
        elif etf_negative and margin_negative:
            label = "参与度收缩"
        elif (
            etf.get("turnover_percentile") is not None
            and etf["turnover_percentile"] >= float(etf_t["turnover_pulse_percentile"])
            and not etf_positive
            and not margin_positive
        ):
            label = "成交情绪脉冲"
        else:
            label = "中性观察"

        next_conditions.extend(
            [
                "观察相关ETF份额变化是否在未来3至5个交易日保持同方向。",
                "观察ETF组价格改善覆盖率是否维持，而不是集中于单只产品。",
            ]
        )
        if margin_direction == "unknown":
            next_conditions.append("补全证券—主题映射后，再检查融资余额变化是否与ETF证据一致。")
        else:
            next_conditions.append("观察融资余额在价格回落时是否快速下降。")
        unknowns.extend(
            [
                "无法确认具体交易者身份。",
                "ETF份额变化可能包含申赎套利、做市和对冲活动。",
                "当前状态不能用于推断未来价格必然方向。",
            ]
        )

        score = general_quality
        if etf_samples < minimum_samples:
            score -= 15
        if not margin:
            score -= 12
        if conflict:
            score -= 10
        score = max(0.0, min(100.0, score))
        states.append(
            SectorState(
                trade_date=trade_date,
                sector_id=theme_id,
                sector_name=theme_name,
                state_label=label,
                confidence_level=confidence_level(score, thresholds),  # type: ignore[arg-type]
                internal_confidence_score=score,
                metrics={"etf": etf, "margin": margin, "price_breadth": price_breadth},
                evidence_summary=evidence,
                supporting_evidence=support or ["现有证据未形成明确一致方向。"],
                counter_evidence=counter,
                unknowns=list(dict.fromkeys(unknowns)),
                next_confirmation_conditions=next_conditions,
            )
        )
    return sorted(states, key=lambda item: (item.state_label, item.sector_name))

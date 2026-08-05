from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .models import (
    CounterpartyRelation,
    DailyReview,
    EvidenceLayerStatus,
    FieldProvenance,
    HistoricalConditionalProbability,
    MarketState,
    MicrostructureSummary,
    ParticipantHypothesis,
    ScenarioPath,
    SectorState,
    SourceQuality,
)

REVIEW_VERSION = "daily_review_v1"
OUTCOME_CONTINUATION = "延续或扩散"
OUTCOME_ROTATION = "分歧或轮动"
OUTCOME_DETERIORATION = "退潮或收缩"


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _confidence(score: float, thresholds: dict[str, Any]) -> str:
    if score >= float(thresholds["quality"]["high"]):
        return "high"
    if score >= float(thresholds["quality"]["medium"]):
        return "medium"
    return "low"


def _available_sources(
    qualities: list[SourceQuality],
    prefixes: tuple[str, ...],
) -> list[SourceQuality]:
    return [
        item
        for item in qualities
        if item.available and item.schema_ok and item.source_id.startswith(prefixes)
    ]


def load_microstructure_summary(root: Path, trade_date: date) -> MicrostructureSummary:
    directory = (
        root
        / "data"
        / "raw"
        / "tick_trade"
        / f"date={trade_date.isoformat().replace('-', '')}"
    )
    manifests = sorted(directory.glob("code=*/manifest.json")) if directory.exists() else []
    if not manifests:
        return MicrostructureSummary(
            limitations=[
                "当日没有已保存的免费分笔成交清单。",
                "没有完整逐笔委托时，不能计算真实订单流失衡或撤单失衡。",
            ]
        )

    total_notional = 0.0
    buy_notional = 0.0
    sell_notional = 0.0
    closing_notional = 0.0
    accepted = 0
    confirmed = 0
    provisional = 0
    source_ids: set[str] = set()

    for path in manifests:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        quality = manifest.get("quality") or {}
        if quality.get("status") == "rejected":
            continue
        features = manifest.get("features") or {}
        notional = _as_float(features.get("total_notional"))
        if notional is None or notional <= 0:
            continue
        accepted += 1
        if quality.get("status") == "confirmed":
            confirmed += 1
        else:
            provisional += 1
        total_notional += notional
        buy_notional += _as_float(features.get("buy_labeled_notional")) or 0.0
        sell_notional += _as_float(features.get("sell_labeled_notional")) or 0.0
        closing_share = _as_float(features.get("closing_auction_notional_share")) or 0.0
        closing_notional += notional * closing_share
        source_id = (manifest.get("source") or {}).get("source_id")
        if source_id:
            source_ids.add(str(source_id))

    if accepted == 0 or total_notional <= 0:
        return MicrostructureSummary(
            limitations=["当日分笔成交文件存在，但没有通过基础质量门槛的证券。"]
        )

    classified = buy_notional + sell_notional
    return MicrostructureSummary(
        available=True,
        symbol_count=accepted,
        confirmed_symbol_count=confirmed,
        provisional_symbol_count=provisional,
        total_notional=total_notional,
        signed_notional_imbalance=(buy_notional - sell_notional) / total_notional,
        classification_coverage=classified / total_notional,
        closing_auction_notional_share=closing_notional / total_notional,
        source_ids=sorted(source_ids),
        limitations=[
            "买盘和卖盘方向来自供应方分类，不是交易所确认的交易者身份。",
            "该指标表示分笔成交主动性近似，不是市场净流入。",
            "数据不含完整委托、撤单和连续消息时，不能重建订单簿。",
        ],
    )


def _classify_regime(row: pd.Series, thresholds: dict[str, Any]) -> str:
    breadth = _as_float(row.get("breadth_ratio"))
    median_return = _as_float(row.get("median_return"))
    cap_return = _as_float(row.get("cap_weighted_return"))
    amount_change = _as_float(row.get("amount_5d_change"))
    broad = float(thresholds["market"]["broad_breadth_ratio"])
    weak = float(thresholds["market"]["weak_breadth_ratio"])
    gap = float(thresholds["market"]["weight_gap_pct"])

    if breadth is None or median_return is None:
        return "数据不足"
    if breadth >= broad and median_return > 0:
        return "广泛改善"
    if cap_return is not None and cap_return - median_return >= gap and breadth < broad:
        return "权重主导"
    if breadth < weak and amount_change is not None and amount_change < 0:
        return "参与收缩"
    if 0.45 <= breadth <= 0.55:
        return "高度分化"
    return "中性整理"


def _outcome(return_value: float | None, breadth_value: float | None) -> str | None:
    if return_value is None or breadth_value is None:
        return None
    if return_value > 0 and breadth_value >= 0.55:
        return OUTCOME_CONTINUATION
    if return_value < 0 and breadth_value <= 0.45:
        return OUTCOME_DETERIORATION
    return OUTCOME_ROTATION


def _prepare_regime_history(
    market_history: pd.DataFrame,
    thresholds: dict[str, Any],
) -> pd.DataFrame:
    if market_history.empty:
        return pd.DataFrame()
    required = {"trade_date", "total_amount", "breadth_ratio", "median_return"}
    if not required.issubset(market_history.columns):
        return pd.DataFrame()

    data = market_history.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.date
    data = data.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    for column in [
        "total_amount",
        "breadth_ratio",
        "median_return",
        "cap_weighted_return",
    ]:
        if column not in data.columns:
            data[column] = pd.NA
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["amount_5d_change"] = data["total_amount"] / data["total_amount"].shift(5) - 1
    data["regime"] = data.apply(lambda row: _classify_regime(row, thresholds), axis=1)

    data["forward_1d_return"] = data["median_return"].shift(-1)
    data["forward_1d_breadth"] = data["breadth_ratio"].shift(-1)
    data["outcome_1d"] = [
        _outcome(_as_float(ret), _as_float(breadth))
        for ret, breadth in zip(
            data["forward_1d_return"],
            data["forward_1d_breadth"],
            strict=True,
        )
    ]

    return_columns = [data["median_return"].shift(-step) / 100 for step in range(1, 6)]
    breadth_columns = [data["breadth_ratio"].shift(-step) for step in range(1, 6)]
    future_returns = pd.concat(return_columns, axis=1)
    future_breadth = pd.concat(breadth_columns, axis=1)
    data["forward_5d_return"] = (1 + future_returns).prod(axis=1, min_count=5) - 1
    data["forward_5d_breadth"] = future_breadth.mean(axis=1, skipna=False)
    data["outcome_5d"] = [
        _outcome(_as_float(ret), _as_float(breadth))
        for ret, breadth in zip(
            data["forward_5d_return"],
            data["forward_5d_breadth"],
            strict=True,
        )
    ]
    return data


def build_historical_conditionals(
    market_history: pd.DataFrame,
    current_regime: str,
    thresholds: dict[str, Any],
    minimum_samples: int,
) -> list[HistoricalConditionalProbability]:
    data = _prepare_regime_history(market_history, thresholds)
    outcomes = [OUTCOME_CONTINUATION, OUTCOME_ROTATION, OUTCOME_DETERIORATION]
    records: list[HistoricalConditionalProbability] = []
    method = (
        "按当日市场宽度、中位数收益、市值加权差和5日成交变化重建历史状态；"
        "统计相同状态后1日及5日的宽度—收益联合结果。"
    )

    for horizon in ("1d", "5d"):
        outcome_column = f"outcome_{horizon}"
        valid = data[data[outcome_column].notna()] if not data.empty else pd.DataFrame()
        conditioned = valid[valid["regime"] == current_regime] if not valid.empty else valid
        sample_size = len(conditioned)
        for outcome_name in outcomes:
            if valid.empty:
                status = "unavailable"
                conditional_probability = None
                baseline_probability = None
            elif sample_size < minimum_samples:
                status = "insufficient_samples"
                conditional_probability = None
                baseline_probability = float((valid[outcome_column] == outcome_name).mean())
            else:
                status = "available"
                conditional_probability = float(
                    (conditioned[outcome_column] == outcome_name).mean()
                )
                baseline_probability = float((valid[outcome_column] == outcome_name).mean())
            lift = (
                conditional_probability - baseline_probability
                if conditional_probability is not None and baseline_probability is not None
                else None
            )
            records.append(
                HistoricalConditionalProbability(
                    condition=f"市场状态={current_regime}",
                    outcome=outcome_name,
                    horizon=horizon,
                    status=status,
                    sample_size=sample_size,
                    minimum_samples=minimum_samples,
                    conditional_probability=conditional_probability,
                    baseline_probability=baseline_probability,
                    lift=lift,
                    method=method,
                    limitations=[
                        "历史条件概率描述样本频率，不代表因果关系。",
                        "市场制度、样本来源和交易成本变化可能使历史关系失效。",
                        "使用全市场中位数收益和市场宽度，不等同于任一指数或个股收益。",
                    ],
                )
            )
    return records


def _participant_hypotheses(
    market_state: MarketState,
    sector_states: list[SectorState],
    microstructure: MicrostructureSummary,
    thresholds: dict[str, Any],
) -> list[ParticipantHypothesis]:
    market = market_state.metrics.get("market") or {}
    margin = market_state.metrics.get("margin") or {}
    quality = market_state.confidence_score
    positive_etf_labels = {"多证据参与增强", "配置型资金改善"}
    negative_etf_labels = {"参与度收缩"}
    positive_etf = [item for item in sector_states if item.state_label in positive_etf_labels]
    negative_etf = [item for item in sector_states if item.state_label in negative_etf_labels]
    conflicting = [item for item in sector_states if item.state_label == "多证据分歧"]

    hypotheses: list[ParticipantHypothesis] = []
    if positive_etf or negative_etf or conflicting:
        if positive_etf and not negative_etf:
            activity = "active"
            observation = f"{len(positive_etf)} 个主题出现ETF配置或多证据参与改善。"
        elif negative_etf and not positive_etf:
            activity = "reducing"
            observation = f"{len(negative_etf)} 个主题出现ETF份额参与收缩。"
        else:
            activity = "mixed"
            observation = "不同主题的ETF份额证据方向不一致。"
        score = min(78.0, 45.0 + 5.0 * (len(positive_etf) + len(negative_etf)))
        if conflicting:
            score -= 8
        hypotheses.append(
            ParticipantHypothesis(
                participant_id="passive_and_configuration_funds",
                display_name="被动与配置型资金原型",
                activity=activity,
                confidence_level=_confidence(score, thresholds),
                confidence_score=max(0.0, score),
                observation=observation,
                supporting_evidence=[
                    item.supporting_evidence[0]
                    for item in (positive_etf or negative_etf)[:4]
                    if item.supporting_evidence
                ],
                alternative_explanations=[
                    "ETF份额变化可能由一级市场套利和做市库存调整造成。",
                    "跨市场ETF可能受估值时差和现金替代影响。",
                ],
                cannot_confirm=[
                    "无法确认最终申购人身份。",
                    "无法仅凭份额变化判断其长期方向观点。",
                ],
                source_fields=["sector_states.*.metrics.etf", "sector_states.*.evidence_summary"],
            )
        )
    else:
        hypotheses.append(
            ParticipantHypothesis(
                participant_id="passive_and_configuration_funds",
                display_name="被动与配置型资金原型",
                activity="unknown",
                confidence_level="low",
                confidence_score=20,
                observation="ETF份额历史或主题分类不足，暂不能形成参与判断。",
                alternative_explanations=["当前缺失不等于该类资金没有交易。"],
                cannot_confirm=["无法确认ETF一级市场参与方向。"],
                source_fields=["sector_states.*.metrics.etf"],
            )
        )

    margin_change = _as_float(margin.get("change_ratio_5d")) if margin.get("available") else None
    if margin_change is None:
        margin_activity = "unknown"
        margin_observation = "融资历史不足或口径尚未通过连续性核验。"
        margin_score = 25.0
    elif margin_change > 0:
        margin_activity = "active"
        margin_observation = f"全市场融资余额近5日增加 {margin_change:.2%}。"
        margin_score = min(82.0, quality)
    elif margin_change < 0:
        margin_activity = "reducing"
        margin_observation = f"全市场融资余额近5日下降 {abs(margin_change):.2%}。"
        margin_score = min(82.0, quality)
    else:
        margin_activity = "mixed"
        margin_observation = "融资余额近5日变化接近零。"
        margin_score = min(65.0, quality)
    hypotheses.append(
        ParticipantHypothesis(
            participant_id="leveraged_traders",
            display_name="融资杠杆资金原型",
            activity=margin_activity,
            confidence_level=_confidence(margin_score, thresholds),
            confidence_score=margin_score,
            observation=margin_observation,
            supporting_evidence=[margin_observation] if margin_change is not None else [],
            alternative_explanations=[
                "融资余额变化同时受到融资买入、主动偿还、卖券还款和强制平仓影响。",
                "余额下降不等同于形成看空观点。",
            ],
            cannot_confirm=["无法识别融资账户身份及其持仓成本。"],
            source_fields=["market_state.metrics.margin.change_ratio_5d"],
        )
    )

    breadth = _as_float(market.get("breadth_ratio"))
    limit_up = int(market.get("limit_up_count") or 0)
    limit_down = int(market.get("limit_down_count") or 0)
    if breadth is None:
        short_activity = "unknown"
        short_observation = "市场宽度缺失，无法判断短线交易活跃原型。"
        short_score = 20.0
    elif breadth >= float(thresholds["market"]["broad_breadth_ratio"]) and limit_up > limit_down:
        short_activity = "active"
        short_observation = f"上涨覆盖率 {breadth:.1%}，涨停数量高于跌停数量。"
        short_score = min(76.0, quality)
    elif breadth < float(thresholds["market"]["weak_breadth_ratio"]):
        short_activity = "reducing"
        short_observation = f"上涨覆盖率仅 {breadth:.1%}，短线风险偏好偏弱。"
        short_score = min(76.0, quality)
    else:
        short_activity = "mixed"
        short_observation = f"上涨覆盖率 {breadth:.1%}，短线行为更接近分歧和轮动。"
        short_score = min(68.0, quality)
    if microstructure.available and microstructure.signed_notional_imbalance is not None:
        short_observation += (
            f" 已采集分笔样本的标记成交失衡为 "
            f"{microstructure.signed_notional_imbalance:+.1%}。"
        )
        short_score = min(80.0, short_score + 5)
    hypotheses.append(
        ParticipantHypothesis(
            participant_id="short_horizon_traders",
            display_name="短周期交易资金原型",
            activity=short_activity,
            confidence_level=_confidence(short_score, thresholds),
            confidence_score=short_score,
            observation=short_observation,
            supporting_evidence=market_state.supporting_evidence[:3],
            alternative_explanations=[
                "广泛上涨也可能由被动调仓或系统性风险偏好变化驱动。",
                "分笔买卖标记不能区分游资、量化、机构或个人。",
            ],
            cannot_confirm=["无法确认具体营业部或最终交易账户。"],
            source_fields=[
                "market_state.metrics.market.breadth_ratio",
                "market_state.metrics.market.limit_up_count",
                "daily_review.microstructure.signed_notional_imbalance",
            ],
        )
    )

    median_return = _as_float(market.get("median_return"))
    cap_return = _as_float(market.get("cap_weighted_return"))
    gap = None if median_return is None or cap_return is None else cap_return - median_return
    gap_threshold = float(thresholds["market"]["weight_gap_pct"])
    if gap is None:
        cap_activity = "unknown"
        cap_observation = "缺少市值加权与中位数收益差，无法判断权重配置行为。"
        cap_score = 20.0
    elif gap >= gap_threshold:
        cap_activity = "active"
        cap_observation = f"市值加权收益高于市场中位数 {gap:.2f} 个百分点。"
        cap_score = min(75.0, quality)
    elif gap <= -gap_threshold:
        cap_activity = "reducing"
        cap_observation = f"市值加权收益低于市场中位数 {abs(gap):.2f} 个百分点。"
        cap_score = min(70.0, quality)
    else:
        cap_activity = "mixed"
        cap_observation = "权重股与全市场中位数表现差异不显著。"
        cap_score = min(62.0, quality)
    hypotheses.append(
        ParticipantHypothesis(
            participant_id="large_cap_allocators",
            display_name="权重配置资金原型",
            activity=cap_activity,
            confidence_level=_confidence(cap_score, thresholds),
            confidence_score=cap_score,
            observation=cap_observation,
            supporting_evidence=[cap_observation] if gap is not None else [],
            alternative_explanations=[
                "权重相对强弱也可能由行业事件或少数大市值股票波动造成。"
            ],
            cannot_confirm=["无法确认是否来自指数基金、保险、外资或主动机构。"],
            source_fields=[
                "market_state.metrics.market.cap_weighted_return",
                "market_state.metrics.market.median_return",
            ],
        )
    )

    hypotheses.append(
        ParticipantHypothesis(
            participant_id="liquidity_and_arbitrage",
            display_name="流动性提供与套利资金原型",
            activity="possible" if positive_etf or negative_etf else "unknown",
            confidence_level="low",
            confidence_score=38 if positive_etf or negative_etf else 18,
            observation=(
                "ETF份额变化存在时，一级市场套利、做市库存和现金替代是必须保留的解释。"
                if positive_etf or negative_etf
                else "当前数据不能单独识别流动性提供和套利活动。"
            ),
            supporting_evidence=[],
            alternative_explanations=["同一份额变化也可能由长期配置需求造成。"],
            cannot_confirm=["没有申赎篮子、盘口库存和订单关联数据。"],
            source_fields=["sector_states.*.metrics.etf"],
        )
    )
    return hypotheses


def _counterparty_relations(
    hypotheses: list[ParticipantHypothesis],
    market_state: MarketState,
    thresholds: dict[str, Any],
) -> list[CounterpartyRelation]:
    indexed = {item.participant_id: item for item in hypotheses}
    relations: list[CounterpartyRelation] = []

    etf = indexed["passive_and_configuration_funds"]
    if etf.activity != "unknown":
        score = max(30.0, etf.confidence_score - 12)
        relations.append(
            CounterpartyRelation(
                relation_id="etf_creation_vs_inventory",
                left_archetype="被动与配置型资金",
                right_archetype="现有持有人、做市与套利库存",
                interaction="ETF一级市场敞口变化可能通过申赎篮子传导为成分证券需求或供给。",
                confidence_level=_confidence(score, thresholds),
                confidence_score=score,
                supporting_evidence=etf.supporting_evidence,
                alternative_explanations=etf.alternative_explanations,
                confirmation_conditions=[
                    "ETF份额变化连续3至5日保持方向。",
                    "相关ETF价格改善覆盖率同步，而不是集中在单只产品。",
                    "取得申赎清单后，理论篮子需求与成分股成交方向一致。",
                ],
                invalidation_conditions=[
                    "份额变化次日快速反转。",
                    "价格表现与理论篮子需求长期背离。",
                ],
                source_fields=etf.source_fields,
            )
        )

    leveraged = indexed["leveraged_traders"]
    if leveraged.activity != "unknown":
        score = max(30.0, leveraged.confidence_score - 8)
        relations.append(
            CounterpartyRelation(
                relation_id="leverage_vs_existing_supply",
                left_archetype="融资杠杆资金",
                right_archetype="现有持有人、获利兑现或风险控制卖方",
                interaction="融资敞口变化与二级市场存量持有人形成交易对手关系。",
                confidence_level=_confidence(score, thresholds),
                confidence_score=score,
                supporting_evidence=leveraged.supporting_evidence,
                alternative_explanations=leveraged.alternative_explanations,
                confirmation_conditions=[
                    "融资买入强度与价格、成交宽度同方向。",
                    "价格回落时融资余额没有快速下降。",
                ],
                invalidation_conditions=[
                    "融资余额变化来自口径迁移、标的调整或非连续样本。",
                    "价格下跌同时融资偿还显著加速。",
                ],
                source_fields=leveraged.source_fields,
            )
        )

    short_term = indexed["short_horizon_traders"]
    if short_term.activity != "unknown":
        score = max(28.0, short_term.confidence_score - 15)
        relations.append(
            CounterpartyRelation(
                relation_id="short_horizon_vs_profit_taking",
                left_archetype="短周期主动交易资金",
                right_archetype="前期持有人与短期兑现资金",
                interaction="上涨扩散或退潮过程中，追随型成交与兑现型供给形成主要短周期对手关系。",
                confidence_level=_confidence(score, thresholds),
                confidence_score=score,
                supporting_evidence=short_term.supporting_evidence,
                alternative_explanations=short_term.alternative_explanations,
                confirmation_conditions=[
                    "次日竞价和开盘后30分钟市场宽度延续当前方向。",
                    "核心主题内部上涨覆盖率没有快速塌缩。",
                ],
                invalidation_conditions=[
                    "市场宽度在开盘后迅速反向。",
                    "成交放大但价格冲击快速回撤。",
                ],
                source_fields=short_term.source_fields,
            )
        )
    return relations


def _scenario_paths(
    market_state: MarketState,
    conditionals: list[HistoricalConditionalProbability],
) -> list[ScenarioPath]:
    selected: dict[str, HistoricalConditionalProbability] = {}
    for outcome in [OUTCOME_CONTINUATION, OUTCOME_ROTATION, OUTCOME_DETERIORATION]:
        five_day = next(
            (item for item in conditionals if item.outcome == outcome and item.horizon == "5d"),
            None,
        )
        one_day = next(
            (item for item in conditionals if item.outcome == outcome and item.horizon == "1d"),
            None,
        )
        selected[outcome] = five_day if five_day and five_day.status == "available" else one_day or five_day

    definitions = {
        OUTCOME_CONTINUATION: {
            "id": "continuation",
            "title": "当前状态延续并向更多证券扩散",
            "narrative": "市场宽度和中位数收益继续保持同方向，当前状态获得后续成交与板块覆盖确认。",
            "confirm": [
                "上涨覆盖率保持在60%以上。",
                "中位数收益与市值加权收益没有明显背离。",
                "改善主题的ETF价格覆盖率继续维持。",
            ],
            "invalidate": ["上涨覆盖率跌破50%。", "改善集中到少数权重证券。"],
        },
        OUTCOME_ROTATION: {
            "id": "rotation",
            "title": "指数或成交维持，但内部进入分歧轮动",
            "narrative": "市场总体没有单边恶化，但主题、权重和参与者证据出现方向分化。",
            "confirm": [
                "市场宽度在45%至55%附近。",
                "板块状态中多证据分歧数量上升。",
                "成交额维持但领涨主题发生切换。",
            ],
            "invalidate": ["市场宽度重新站上60%并持续。", "宽度和成交同步快速收缩。"],
        },
        OUTCOME_DETERIORATION: {
            "id": "deterioration",
            "title": "参与收缩或短周期风险偏好退潮",
            "narrative": "市场宽度、中位数收益和参与证据同步走弱，存量持有人供给占优。",
            "confirm": [
                "上涨覆盖率跌破40%。",
                "跌停或大幅下跌数量上升。",
                "融资或ETF份额证据同步转弱。",
            ],
            "invalidate": ["市场宽度快速修复至55%以上。", "核心主题出现广泛价格改善。"],
        },
    }

    paths: list[ScenarioPath] = []
    for outcome, definition in definitions.items():
        conditional = selected[outcome]
        available = conditional is not None and conditional.status == "available"
        score = market_state.confidence_score if available else min(45.0, market_state.confidence_score)
        paths.append(
            ScenarioPath(
                scenario_id=definition["id"],
                title=definition["title"],
                narrative=definition["narrative"],
                probability=conditional.conditional_probability if available else None,
                probability_status=conditional.status if conditional else "unavailable",
                probability_source=(
                    "historical_conditional" if available else "insufficient_history"
                ),
                sample_size=conditional.sample_size if conditional else 0,
                confidence_level=(
                    market_state.confidence_level if available else "low"
                ),
                supporting_evidence=market_state.supporting_evidence[:4],
                alternative_explanations=(
                    market_state.counter_evidence[:3]
                    or ["同一市场状态可能由不同参与者组合造成。"]
                ),
                confirmation_conditions=definition["confirm"],
                invalidation_conditions=definition["invalidate"],
                source_fields=[
                    "market_state.metrics.market.breadth_ratio",
                    "market_state.metrics.market.median_return",
                    "market_history",
                ],
            )
        )
    return paths


def _field_provenance(
    trade_date: date,
    market_state: MarketState,
    sector_states: list[SectorState],
    qualities: list[SourceQuality],
    microstructure: MicrostructureSummary,
) -> list[FieldProvenance]:
    market = market_state.metrics.get("market") or {}
    margin = market_state.metrics.get("margin") or {}
    market_sources = _available_sources(qualities, ("market",))
    margin_sources = _available_sources(qualities, ("margin", "sse_margin", "szse_margin"))
    market_ids = [item.source_id for item in market_sources]
    margin_ids = [item.source_id for item in margin_sources]
    market_date = next((item.actual_date for item in market_sources if item.actual_date), trade_date)
    margin_date = next((item.actual_date for item in margin_sources if item.actual_date), None)
    margin_official = bool(margin_sources) and all(item.official for item in margin_sources)

    records = [
        FieldProvenance(
            field_path="market_state.metrics.market.breadth_ratio",
            display_name="市场上涨覆盖率",
            value=market.get("breadth_ratio"),
            unit="ratio",
            source_ids=market_ids,
            evidence_level="L2",
            official=False,
            as_of_date=market_date,
            transform="上涨证券数 / 有效涨跌幅证券数",
            status="provisional" if market.get("available") else "missing",
            limitations=["聚合行情用于结构观察，盘后应与交易所正式统计核验。"],
        ),
        FieldProvenance(
            field_path="market_state.metrics.market.total_amount",
            display_name="全市场成交额",
            value=market.get("total_amount"),
            unit="CNY",
            source_ids=market_ids,
            evidence_level="L2",
            official=False,
            as_of_date=market_date,
            transform="逐证券成交额求和",
            status="provisional" if market.get("available") else "missing",
            limitations=["成交额表示成交活跃程度，不是净流入或净流出。"],
        ),
        FieldProvenance(
            field_path="market_state.metrics.market.median_return",
            display_name="全市场涨跌幅中位数",
            value=market.get("median_return"),
            unit="percent",
            source_ids=market_ids,
            evidence_level="L2",
            official=False,
            as_of_date=market_date,
            transform="有效证券涨跌幅中位数",
            status="provisional" if market.get("available") else "missing",
            limitations=[],
        ),
        FieldProvenance(
            field_path="market_state.metrics.margin.financing_balance",
            display_name="沪深融资余额",
            value=margin.get("financing_balance"),
            unit="CNY",
            source_ids=margin_ids,
            evidence_level="L1",
            official=margin_official,
            as_of_date=margin_date,
            transform="沪深交易所融资余额汇总并统一为元",
            status=(
                "confirmed" if margin.get("available") and margin_official else
                "provisional" if margin.get("available") else
                "missing"
            ),
            limitations=["余额变化描述已发生的杠杆敞口变化，不代表未来收益。"],
        ),
        FieldProvenance(
            field_path="market_state.metrics.margin.change_ratio_5d",
            display_name="融资余额近5日变化率",
            value=margin.get("change_ratio_5d"),
            unit="ratio",
            source_ids=margin_ids,
            evidence_level="L1",
            official=margin_official,
            as_of_date=margin_date,
            transform="当前融资余额 / 5个交易日前融资余额 - 1",
            status=(
                "confirmed" if margin.get("change_ratio_5d") is not None and margin_official else
                "missing"
            ),
            limitations=["只有连续、同口径历史样本才能计算；不连续样本必须保持缺失。"],
        ),
    ]

    for state in sector_states:
        for evidence in state.evidence_summary:
            records.append(
                FieldProvenance(
                    field_path=(
                        f"sector_states.{state.sector_id}."
                        f"{evidence.cluster}.{evidence.metric}.{evidence.horizon}"
                    ),
                    display_name=f"{state.sector_name}：{evidence.metric}",
                    value=evidence.value,
                    unit=evidence.unit,
                    source_ids=[item for item in evidence.source_id.split("+") if item],
                    evidence_level=evidence.evidence_level,
                    official=evidence.official,
                    as_of_date=evidence.source_date,
                    transform=(
                        "估算或聚合计算" if evidence.is_estimated else "公开披露字段聚合"
                    ),
                    status=(
                        "missing" if evidence.is_missing else
                        "confirmed" if evidence.official else
                        "provisional"
                    ),
                    limitations=[evidence.missing_reason] if evidence.missing_reason else [],
                )
            )

    if microstructure.available:
        records.append(
            FieldProvenance(
                field_path="daily_review.microstructure.signed_notional_imbalance",
                display_name="分笔标记成交金额失衡",
                value=microstructure.signed_notional_imbalance,
                unit="ratio",
                source_ids=microstructure.source_ids,
                evidence_level="L3",
                official=False,
                as_of_date=trade_date,
                transform="(供应方标记买盘额 - 卖盘额) / 全部分笔成交额",
                status=(
                    "confirmed" if microstructure.provisional_symbol_count == 0 else "provisional"
                ),
                limitations=microstructure.limitations,
            )
        )
    return records


def build_daily_review(
    root: Path,
    trade_date: date,
    market_history: pd.DataFrame,
    market_state: MarketState,
    sector_states: list[SectorState],
    qualities: list[SourceQuality],
    thresholds: dict[str, Any],
) -> DailyReview:
    review_settings = thresholds.get("review") or {}
    minimum_samples = int(review_settings.get("minimum_scenario_samples", 20))
    microstructure = load_microstructure_summary(root, trade_date)
    conditionals = build_historical_conditionals(
        market_history,
        market_state.label,
        thresholds,
        minimum_samples,
    )
    participants = _participant_hypotheses(
        market_state,
        sector_states,
        microstructure,
        thresholds,
    )
    relations = _counterparty_relations(participants, market_state, thresholds)
    paths = _scenario_paths(market_state, conditionals)
    provenance = _field_provenance(
        trade_date,
        market_state,
        sector_states,
        qualities,
        microstructure,
    )

    market_sources = _available_sources(qualities, ("market",))
    evidence_layers = [
        EvidenceLayerStatus(
            layer_id="market_replay",
            display_name="盘面复盘结构",
            status="available" if market_state.label != "数据不足" else "missing",
            summary=(
                f"当前市场状态为“{market_state.label}”，以市场宽度、收益中位数、"
                "权重差和成交变化描述盘面。"
            ),
            source_ids=[item.source_id for item in market_sources],
            limitations=["市场状态是规则分类，不是未来方向结论。"],
        ),
        EvidenceLayerStatus(
            layer_id="seat_facts",
            display_name="龙虎榜与席位事实",
            status="missing",
            summary="生产管线尚未接入交易所龙虎榜和营业部统计，因此不输出席位身份判断。",
            source_ids=[],
            limitations=[
                "营业部或交易单元不等于最终投资者。",
                "席位历史标签只能作为行为背景，不能证明当天账户身份。",
            ],
        ),
        EvidenceLayerStatus(
            layer_id="microstructure",
            display_name="微观成交行为",
            status="partial" if microstructure.available else "missing",
            summary=(
                f"已读取 {microstructure.symbol_count} 只证券的分笔成交证据。"
                if microstructure.available
                else "当日没有可用分笔成交清单。"
            ),
            source_ids=microstructure.source_ids,
            limitations=microstructure.limitations,
        ),
        EvidenceLayerStatus(
            layer_id="automated_report",
            display_name="自动证据报告",
            status="available",
            summary="报告由确定性规则和结构化数据生成，所有推断保留替代解释与可证伪条件。",
            source_ids=[item.source_id for item in qualities if item.available],
            limitations=["自动报告不替代人工核验，也不构成交易指令。"],
        ),
    ]

    confirmation = []
    falsification = []
    for path in paths:
        confirmation.extend(path.confirmation_conditions)
        falsification.extend(path.invalidation_conditions)
    confirmation.extend(
        [
            "盘后核对交易所正式成交统计与聚合行情总量。",
            "取得龙虎榜后，仅记录营业部或交易单元事实，不反推最终账户。",
            "ETF份额和融资余额至少连续3至5日同口径后再判断持续性。",
        ]
    )
    falsification.extend(
        [
            "关键来源日期不一致、单位异常或覆盖率不足时，撤销相关推断。",
            "历史条件样本低于最小门槛时，不展示概率。",
            "微观成交与日终成交额偏差超过质量阈值时，不采用分笔方向指标。",
        ]
    )

    summary_parts = market_state.supporting_evidence[:2]
    if market_state.counter_evidence:
        summary_parts.append("同时存在反向证据：" + market_state.counter_evidence[0])
    return DailyReview(
        review_version=REVIEW_VERSION,
        market_phase=market_state.label,
        market_phase_summary=" ".join(summary_parts) or "现有证据未形成明确市场状态。",
        evidence_layers=evidence_layers,
        participant_hypotheses=participants,
        counterparty_relations=relations,
        historical_conditionals=conditionals,
        scenario_paths=paths,
        seat_facts=[],
        microstructure=microstructure,
        field_provenance=provenance,
        confirmation_checklist=list(dict.fromkeys(confirmation)),
        falsification_checklist=list(dict.fromkeys(falsification)),
    )

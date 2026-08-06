from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .config import Settings
from .features import (
    build_etf_theme_features,
    build_margin_market_features,
    build_margin_theme_features,
    build_market_features,
    summarize_market,
)
from .hosted_product_provider import HostedProductSourceProvider
from .models import ReportPayload
from .reporting import ReportRenderer
from .review import build_daily_review
from .review_product import enrich_product_review
from .sources import AkshareProvider, MockProvider, SourceBundle, UnavailableProvider
from .states import classify_market_state, classify_sector_states
from .storage import FileStore
from .taxonomy import ThemeMapper


def previous_business_day(value: date) -> date:
    current = value - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def apply_security_theme_mapping(frame: pd.DataFrame, mapping_path: Path) -> pd.DataFrame:
    if frame.empty:
        return frame
    if "theme_id" in frame.columns and frame["theme_id"].notna().any():
        return frame
    if not mapping_path.exists():
        return frame
    mapping = pd.read_csv(mapping_path, dtype={"security_code": str})
    if mapping.empty:
        return frame
    result = frame.copy()
    result["security_code"] = result["security_code"].astype(str).str.zfill(6)
    mapping["security_code"] = mapping["security_code"].astype(str).str.zfill(6)
    return result.merge(mapping, on="security_code", how="left")


def _select_provider(data_mode: str, mapper: ThemeMapper, settings: Settings):
    if data_mode == "mock":
        return MockProvider()
    if data_mode in {"live", "auto", "curated"}:
        try:
            return HostedProductSourceProvider(settings.root, settings.sources)
        except RuntimeError as exc:
            return UnavailableProvider(f"Hosted product provider initialization failed: {exc}")
    if data_mode == "legacy":
        try:
            return AkshareProvider(mapper)
        except RuntimeError as exc:
            return UnavailableProvider(f"Legacy provider initialization failed: {exc}")
    raise ValueError(f"Unsupported data mode: {data_mode}")


def _save_raw_bundle(store: FileStore, trade_date: date, bundle: SourceBundle) -> None:
    for source_id, frame in [
        ("market", bundle.market),
        ("etf", bundle.etf),
        ("margin", bundle.margin),
        ("margin_detail", bundle.margin_detail),
    ]:
        store.save_raw(trade_date, source_id, frame)


def _seed_mock_history_if_needed(store: FileStore, trade_date: date) -> None:
    if not store.load_history("mock_etf_history").empty:
        return
    mock = MockProvider()
    seeded = mock.seed_history(previous_business_day(trade_date), periods=260)
    for name, frame in seeded.items():
        keys = {
            "market_history": ["trade_date"],
            "etf_history": ["trade_date", "fund_code"],
            "margin_history": ["trade_date", "market"],
            "margin_detail_history": ["trade_date", "security_code"],
        }[name]
        store.replace_date_rows(f"mock_{name}", frame, keys)


def run_pipeline(
    settings: Settings,
    trade_date: date,
    report_stage: str,
    data_mode: str,
) -> ReportPayload:
    mapper = ThemeMapper(settings.taxonomy)
    store = FileStore(settings.root, settings.history_keep_days)
    if data_mode == "mock":
        _seed_mock_history_if_needed(store, trade_date)

    provider = _select_provider(data_mode, mapper, settings)
    bundle = provider.fetch(trade_date)
    if data_mode == "legacy":
        bundle.data_mode = "legacy"
    _save_raw_bundle(store, trade_date, bundle)

    margin_detail = apply_security_theme_mapping(
        bundle.margin_detail,
        settings.root / "metadata" / "security_sector_map.csv",
    )

    history_prefix = bundle.data_mode
    market_summary = summarize_market(bundle.market, trade_date)
    market_history = store.replace_date_rows(
        f"{history_prefix}_market_history",
        market_summary,
        ["trade_date"],
    )
    etf_history = store.replace_date_rows(
        f"{history_prefix}_etf_history",
        bundle.etf,
        ["trade_date", "fund_code"],
    )
    margin_history = store.replace_date_rows(
        f"{history_prefix}_margin_history",
        bundle.margin,
        ["trade_date", "market"],
    )
    margin_detail_history = store.replace_date_rows(
        f"{history_prefix}_margin_detail_history",
        margin_detail,
        ["trade_date", "security_code"],
    )

    market_features = build_market_features(
        market_history,
        trade_date,
        settings.history_window,
        settings.minimum_percentile_samples,
    )
    etf_features = build_etf_theme_features(
        etf_history,
        trade_date,
        settings.history_window,
        settings.minimum_percentile_samples,
    )
    margin_market_features = build_margin_market_features(
        margin_history,
        trade_date,
        settings.history_window,
        settings.minimum_percentile_samples,
    )
    margin_theme_features = build_margin_theme_features(
        margin_detail_history,
        trade_date,
        settings.history_window,
        settings.minimum_percentile_samples,
    )

    market_state = classify_market_state(
        trade_date,
        market_features,
        margin_market_features,
        bundle.qualities,
        settings.thresholds,
    )
    sector_states = classify_sector_states(
        trade_date,
        etf_features,
        margin_theme_features,
        bundle.qualities,
        settings.thresholds,
        settings.minimum_percentile_samples,
    )
    daily_review = build_daily_review(
        settings.root,
        trade_date,
        market_history,
        market_state,
        sector_states,
        bundle.qualities,
        settings.thresholds,
    )
    if bundle.data_mode == "curated":
        daily_review = enrich_product_review(
            settings.root,
            trade_date,
            daily_review,
            bundle.qualities,
        )

    unavailable = [item.display_name for item in bundle.qualities if not item.available]
    global_unknowns = [
        "无法确认具体交易者身份，也无法识别所谓真实意图。",
        "成交额、DDE和分笔成交失衡只描述活跃程度或产品口径下的订单规模差，不能解释为市场净流入。",
        "营业部、机构专用和交易单元不等于最终投资者。",
        "历史席位后续表现和AI多空辩论不代表未来价格结果。",
        "当前版本尚未纳入股指衍生品和公司资本行为证据。",
    ]
    if unavailable:
        global_unknowns.append("以下来源缺失或异常：" + "、".join(unavailable) + "。")
    if bundle.data_mode == "curated":
        global_unknowns.append(
            "GitHub Runner 自动读取开盘啦和财联社公开页面、东方财富现成接口；大智慧DDE/ACE只从授权产物桥接，不逆向专有终端。"
        )
    elif bundle.data_mode == "legacy":
        global_unknowns.append("Legacy模式仅用于兼容，应以正式披露为最终依据。")

    effective_stage = "demo" if bundle.data_mode == "mock" else report_stage
    payload = ReportPayload(
        trade_date=trade_date,
        report_stage=effective_stage,  # type: ignore[arg-type]
        data_mode=bundle.data_mode,
        generated_at=datetime.now(UTC),
        data_version=os.getenv("GITHUB_SHA", "local")[:12],
        market_state=market_state,
        sector_states=sector_states,
        daily_review=daily_review,
        source_quality=bundle.qualities,
        global_unknowns=global_unknowns,
        glossary={
            "参与者原型": "根据公开或授权产品数据推断的行为类别，不是具体账户或自然人身份。",
            "对手关系": "描述可能相互成交的行为类型，不代表已识别真实交易双方。",
            "DDE/ACE": "大智慧基于Level-2数据形成的订单规模行为指标；不是投资者身份或市场净流入。",
            "龙虎榜席位事实": "东方财富结构化记录和财联社公开/授权文章中的营业部、机构专用或交易单元信息。",
            "市场宽度": "东方财富全市场快照中上涨证券占有效证券的比例。",
            "历史条件概率": "历史相同状态下结果出现的样本频率；不是因果结论或保证。",
            "可证伪条件": "出现后应降低置信度或撤销当前假设的观察条件。",
        },
    )
    renderer = ReportRenderer(Path(__file__).parent / "templates")
    markdown, html = renderer.render(payload)
    renderer.save(payload, markdown, html, settings.root)
    return payload

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
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
from .models import ReportPayload
from .reporting import ReportRenderer
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


def _select_provider(data_mode: str, mapper: ThemeMapper):
    if data_mode == "mock":
        return MockProvider()
    if data_mode in {"live", "auto"}:
        try:
            return AkshareProvider(mapper)
        except Exception as exc:
            return UnavailableProvider(f"Live provider initialization failed: {exc}")
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

    provider = _select_provider(data_mode, mapper)
    bundle = provider.fetch(trade_date)
    _save_raw_bundle(store, trade_date, bundle)

    margin_detail = apply_security_theme_mapping(
        bundle.margin_detail,
        settings.root / "metadata" / "security_sector_map.csv",
    )

    history_prefix = "mock" if bundle.data_mode == "mock" else "live"
    market_summary = summarize_market(bundle.market, trade_date)
    market_history = store.replace_date_rows(f"{history_prefix}_market_history", market_summary, ["trade_date"])
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

    unavailable = [item.display_name for item in bundle.qualities if not item.available]
    global_unknowns = [
        "无法确认具体交易者身份，也无法识别所谓真实意图。",
        "成交额只表示成交活跃程度，不能解释为市场净流入或净流出。",
        "ETF份额变化和融资余额变化描述已经发生的敞口变化，不代表未来价格结果。",
        "M1不使用北向日净额，也不包含衍生品和公司资本行为证据。",
    ]
    if unavailable:
        global_unknowns.append("以下来源缺失或异常：" + "、".join(unavailable) + "。")
    if bundle.data_mode == "live":
        global_unknowns.append("行情聚合数据属于结构化接口结果，应以交易所正式披露为最终依据。")

    effective_stage = "demo" if bundle.data_mode == "mock" else report_stage
    payload = ReportPayload(
        trade_date=trade_date,
        report_stage=effective_stage,  # type: ignore[arg-type]
        data_mode=bundle.data_mode,
        generated_at=datetime.now(),
        data_version=os.getenv("GITHUB_SHA", "local")[:12],
        market_state=market_state,
        sector_states=sector_states,
        source_quality=bundle.qualities,
        global_unknowns=global_unknowns,
        glossary={
            "ETF份额变化": "基金日终份额的增减；份额增加通常对应净申购，但可能包含套利和做市。",
            "融资余额": "尚未偿还的融资交易金额，用于描述杠杆交易资金敞口。",
            "市场宽度": "上涨证券数量占有效证券数量的比例。",
            "历史百分位": "当前指标在自身历史样本中的相对位置，不是未来概率。",
        },
    )
    renderer = ReportRenderer(Path(__file__).parent / "templates")
    markdown, html = renderer.render(payload)
    renderer.save(payload, markdown, html, settings.root)
    return payload

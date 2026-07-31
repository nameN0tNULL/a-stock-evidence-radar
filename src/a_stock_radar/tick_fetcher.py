from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, time as dt_time
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

TICK_SCHEMA_VERSION = "trade_print_v1"
SHANGHAI_TZ = "Asia/Shanghai"


class TickCapability(StrEnum):
    TRADE_PRINTS = "trade_prints"
    FULL_L2 = "full_l2"


class CapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class TickSourceProfile:
    source_id: str
    display_name: str
    capability: TickCapability
    authority_level: str
    is_official: bool
    supports_order_events: bool
    supports_order_ids: bool
    supports_book_depth: bool
    license_status: str


AKSHARE_TENCENT_TPLUS1 = TickSourceProfile(
    source_id="tick_akshare_tencent_tplus1",
    display_name="AKShare/Tencent recent-day trade prints",
    capability=TickCapability.TRADE_PRINTS,
    authority_level="D",
    is_official=False,
    supports_order_events=False,
    supports_order_ids=False,
    supports_book_depth=False,
    license_status="upstream_terms_unverified",
)


@dataclass(frozen=True)
class TickQualityReport:
    status: str
    row_count: int
    duplicate_rows: int
    invalid_rows: int
    first_event_time: str | None
    last_event_time: str | None
    calculated_turnover: float
    official_turnover: float | None
    turnover_difference_ratio: float | None
    classification_coverage: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TickBundlePaths:
    data_path: Path
    manifest_path: Path


def normalize_security_symbol(symbol: str) -> tuple[str, str, str]:
    cleaned = symbol.strip().upper().replace("_", ".")
    exchange: str | None = None
    code: str

    if cleaned.startswith(("SH", "SZ", "BJ")) and cleaned[2:].isdigit():
        exchange = cleaned[:2]
        code = cleaned[2:]
    elif "." in cleaned:
        code, suffix = cleaned.split(".", 1)
        suffix_map = {
            "SH": "SH",
            "XSHG": "SH",
            "SS": "SH",
            "SZ": "SZ",
            "XSHE": "SZ",
            "BJ": "BJ",
            "XBSE": "BJ",
        }
        exchange = suffix_map.get(suffix)
    else:
        code = cleaned

    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"Unsupported A-share symbol: {symbol}")

    if exchange is None:
        if code.startswith(("4", "8", "9")):
            exchange = "BJ"
        elif code.startswith(("5", "6", "7")):
            exchange = "SH"
        else:
            exchange = "SZ"

    canonical = f"{code}.{exchange}"
    return code, exchange, canonical


def to_akshare_tencent_symbol(symbol: str) -> str:
    code, exchange, _ = normalize_security_symbol(symbol)
    if exchange not in {"SH", "SZ"}:
        raise ValueError("AKShare/Tencent trade-print endpoint is configured for SH/SZ only")
    return f"{exchange.lower()}{code}"


def classify_tick_capability(columns: Iterable[str]) -> TickCapability:
    normalized = {str(column).strip().lower() for column in columns}
    sequence_fields = {"source_seq", "seq", "sequence", "message_seq"}
    event_fields = {"event_type", "message_type", "order_action", "order_kind"}
    order_id_fields = {"order_id", "buy_order_id", "sell_order_id", "bid_order_id", "ask_order_id"}
    price_fields = {"price", "trade_price", "order_price", "成交价格"}
    size_fields = {"size", "volume", "qty", "quantity", "成交量"}

    has_sequence = bool(normalized & sequence_fields)
    has_event_type = bool(normalized & event_fields)
    has_order_identity = bool(normalized & order_id_fields)
    has_price = bool(normalized & price_fields)
    has_size = bool(normalized & size_fields)

    if has_sequence and has_event_type and has_order_identity and has_price and has_size:
        return TickCapability.FULL_L2
    return TickCapability.TRADE_PRINTS


def require_full_l2(frame: pd.DataFrame) -> None:
    if classify_tick_capability(frame.columns) is not TickCapability.FULL_L2:
        raise CapabilityError(
            "Dataset does not satisfy the full-L2 contract: sequence, event type, "
            "order identity, price and size are all required"
        )


def _combine_trade_datetime(trade_date: date, values: pd.Series) -> pd.Series:
    combined = pd.to_datetime(
        trade_date.isoformat() + " " + values.astype(str).str.strip(),
        errors="coerce",
    )
    return combined.dt.tz_localize(SHANGHAI_TZ, ambiguous="NaT", nonexistent="NaT")


def normalize_tencent_tick_frame(
    frame: pd.DataFrame,
    symbol: str,
    trade_date: date,
) -> pd.DataFrame:
    required = {"成交时间", "成交价格", "价格变动", "成交量", "成交额", "性质"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Tencent tick frame missing columns: {', '.join(missing)}")

    code, exchange, canonical = normalize_security_symbol(symbol)
    result = pd.DataFrame(index=frame.index)
    result["trade_date"] = trade_date.isoformat()
    result["event_time"] = _combine_trade_datetime(trade_date, frame["成交时间"])
    result["security_code"] = code
    result["exchange"] = exchange
    result["symbol"] = canonical
    result["price"] = pd.to_numeric(frame["成交价格"], errors="coerce")
    result["price_change"] = pd.to_numeric(frame["价格变动"], errors="coerce")
    result["volume_lots"] = pd.to_numeric(frame["成交量"], errors="coerce")
    result["volume_shares"] = result["volume_lots"] * 100
    result["notional"] = pd.to_numeric(frame["成交额"], errors="coerce")
    result["vendor_side"] = frame["性质"].astype(str).str.strip()

    side_map = {
        "买盘": "buy",
        "卖盘": "sell",
        "中性盘": "neutral",
        "buy": "buy",
        "sell": "sell",
        "neutral": "neutral",
    }
    result["side"] = result["vendor_side"].str.lower().map(side_map).fillna("unknown")
    result["trade_sign"] = result["side"].map({"buy": 1, "sell": -1}).fillna(0).astype("int8")
    result["classification_method"] = "vendor_buy_sell_flag"
    result["classification_confidence"] = result["side"].map(
        {"buy": 0.55, "sell": 0.55, "neutral": 0.0, "unknown": 0.0}
    )
    result["source_id"] = AKSHARE_TENCENT_TPLUS1.source_id
    result["capability"] = AKSHARE_TENCENT_TPLUS1.capability.value
    result["is_official"] = False
    result["is_provisional"] = True
    result["schema_version"] = TICK_SCHEMA_VERSION

    numeric_columns = [
        "price",
        "price_change",
        "volume_lots",
        "volume_shares",
        "notional",
        "classification_confidence",
    ]
    result[numeric_columns] = result[numeric_columns].apply(pd.to_numeric, errors="coerce")
    return result.reset_index(drop=True)


def assess_tick_quality(
    frame: pd.DataFrame,
    *,
    official_turnover: float | None = None,
    turnover_tolerance: float = 0.03,
    minimum_rows: int = 1,
) -> TickQualityReport:
    required = {
        "event_time",
        "price",
        "volume_shares",
        "notional",
        "trade_sign",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Normalized tick frame missing columns: {', '.join(missing)}")

    duplicate_subset = ["event_time", "price", "volume_shares", "notional", "trade_sign"]
    duplicate_rows = int(frame.duplicated(subset=duplicate_subset).sum())
    invalid_mask = (
        frame["event_time"].isna()
        | frame["price"].isna()
        | frame["volume_shares"].isna()
        | frame["notional"].isna()
        | (frame["price"] <= 0)
        | (frame["volume_shares"] < 0)
        | (frame["notional"] < 0)
    )
    invalid_rows = int(invalid_mask.sum())
    calculated_turnover = float(frame["notional"].fillna(0).sum())
    classifiable_notional = float(
        frame.loc[frame["trade_sign"].isin([-1, 1]), "notional"].fillna(0).sum()
    )
    classification_coverage = (
        classifiable_notional / calculated_turnover if calculated_turnover > 0 else 0.0
    )

    difference_ratio: float | None = None
    reasons: list[str] = []
    rejected = False

    if len(frame) < minimum_rows:
        reasons.append("insufficient_rows")
        rejected = True
    if duplicate_rows:
        reasons.append("duplicate_trade_prints")
    if invalid_rows:
        reasons.append("invalid_trade_print_rows")
        rejected = True
    if official_turnover is not None:
        if official_turnover <= 0:
            reasons.append("invalid_official_turnover")
            rejected = True
        else:
            difference_ratio = abs(calculated_turnover - official_turnover) / official_turnover
            if difference_ratio > turnover_tolerance:
                reasons.append("turnover_mismatch")
                rejected = True
    else:
        reasons.append("official_turnover_missing")

    valid_times = frame["event_time"].dropna()
    first_event = valid_times.min().isoformat() if not valid_times.empty else None
    last_event = valid_times.max().isoformat() if not valid_times.empty else None

    if rejected:
        status = "rejected"
    elif official_turnover is not None:
        status = "confirmed"
    else:
        status = "provisional"

    return TickQualityReport(
        status=status,
        row_count=len(frame),
        duplicate_rows=duplicate_rows,
        invalid_rows=invalid_rows,
        first_event_time=first_event,
        last_event_time=last_event,
        calculated_turnover=calculated_turnover,
        official_turnover=official_turnover,
        turnover_difference_ratio=difference_ratio,
        classification_coverage=classification_coverage,
        reasons=tuple(reasons),
    )


def compute_trade_print_features(frame: pd.DataFrame) -> dict[str, Any]:
    total_notional = float(frame["notional"].fillna(0).sum())
    buy_notional = float(frame.loc[frame["trade_sign"] == 1, "notional"].fillna(0).sum())
    sell_notional = float(frame.loc[frame["trade_sign"] == -1, "notional"].fillna(0).sum())
    neutral_notional = float(frame.loc[frame["trade_sign"] == 0, "notional"].fillna(0).sum())
    signed_imbalance = (buy_notional - sell_notional) / total_notional if total_notional else None
    classification_coverage = (
        (buy_notional + sell_notional) / total_notional if total_notional else 0.0
    )

    positive_notional = frame.loc[frame["notional"] > 0, "notional"]
    large_threshold = float(positive_notional.quantile(0.90)) if not positive_notional.empty else None
    if large_threshold is None or total_notional == 0:
        large_trade_share = 0.0
    else:
        large_trade_share = float(
            frame.loc[frame["notional"] >= large_threshold, "notional"].sum() / total_notional
        )

    valid_times = frame["event_time"].dropna()
    if valid_times.empty or total_notional == 0:
        closing_auction_share = 0.0
    else:
        close_mask = frame["event_time"].dt.time >= dt_time(14, 57)
        closing_auction_share = float(frame.loc[close_mask, "notional"].sum() / total_notional)

    return {
        "total_notional": total_notional,
        "buy_labeled_notional": buy_notional,
        "sell_labeled_notional": sell_notional,
        "neutral_or_unknown_notional": neutral_notional,
        "signed_notional_imbalance": signed_imbalance,
        "classification_coverage": classification_coverage,
        "large_trade_threshold_p90": large_threshold,
        "large_trade_notional_share": large_trade_share,
        "closing_auction_notional_share": closing_auction_share,
        "capability": TickCapability.TRADE_PRINTS.value,
        "supports_true_order_flow_imbalance": False,
        "supports_cancel_imbalance": False,
        "supports_order_book_reconstruction": False,
        "interpretation": (
            "Vendor-labelled trade-print pressure only; not market net inflow and not full Level-2."
        ),
    }


class AkshareTencentTickCollector:
    def __init__(
        self,
        fetcher: Callable[..., pd.DataFrame] | None = None,
        *,
        retries: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if fetcher is None:
            import akshare as ak

            fetcher = ak.stock_zh_a_tick_tx_js
        self.fetcher = fetcher
        self.retries = max(1, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.sleep = sleep

    def collect(self, symbol: str, trade_date: date) -> pd.DataFrame:
        provider_symbol = to_akshare_tencent_symbol(symbol)
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                raw = self.fetcher(symbol=provider_symbol)
                if raw is None or raw.empty:
                    raise RuntimeError(f"Empty trade-print frame for {provider_symbol}")
                normalized = normalize_tencent_tick_frame(raw, symbol, trade_date)
                normalized.attrs["source_profile"] = asdict(AKSHARE_TENCENT_TPLUS1)
                normalized.attrs["provider_symbol"] = provider_symbol
                normalized.attrs["trade_date_is_operator_supplied"] = True
                return normalized
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    self.sleep(self.backoff_seconds * attempt)
        raise RuntimeError(f"Failed to collect trade prints for {provider_symbol}") from last_error


def write_tick_bundle(
    root: str | Path,
    frame: pd.DataFrame,
    quality: TickQualityReport,
    features: dict[str, Any],
    *,
    source_profile: TickSourceProfile = AKSHARE_TENCENT_TPLUS1,
) -> TickBundlePaths:
    if frame.empty:
        raise ValueError("Cannot persist an empty tick frame")
    trade_date = str(frame.iloc[0]["trade_date"])
    symbol = str(frame.iloc[0]["symbol"])
    directory = (
        Path(root)
        / "data"
        / "raw"
        / "tick_trade"
        / f"date={trade_date.replace('-', '')}"
        / f"code={symbol}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    data_path = directory / "trade_prints.csv.gz"
    manifest_path = directory / "manifest.json"

    frame.to_csv(data_path, index=False, compression="gzip", date_format="%Y-%m-%dT%H:%M:%S%z")
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": TICK_SCHEMA_VERSION,
        "trade_date": trade_date,
        "symbol": symbol,
        "source": asdict(source_profile),
        "quality": asdict(quality),
        "features": features,
        "data_file": data_path.name,
        "data_sha256": digest,
        "row_count": len(frame),
        "trade_date_is_operator_supplied": True,
        "limitations": [
            "not_official_exchange_data",
            "vendor_side_is_an_estimate",
            "not_market_net_inflow",
            "no_order_events_or_cancellations",
            "cannot_reconstruct_order_book",
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return TickBundlePaths(data_path=data_path, manifest_path=manifest_path)

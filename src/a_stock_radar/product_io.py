from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

_EXTENSIONS = (".csv", ".json", ".jsonl", ".xlsx", ".xls", ".md", ".txt")


def resolve_product_path(
    root: Path,
    trade_date: date,
    settings: dict[str, Any],
    default_dir: str,
    default_env: str,
) -> Path | None:
    configured = os.getenv(str(settings.get("env_path") or default_env)) or settings.get("path")
    compact = trade_date.strftime("%Y%m%d")
    iso = trade_date.isoformat()
    if configured:
        candidate = Path(str(configured).format(date=iso, compact_date=compact))
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate if candidate.exists() else None
    directory = root / str(settings.get("import_dir") or default_dir)
    for stem in (iso, compact, f"date={compact}", f"date={iso}"):
        for extension in _EXTENSIONS:
            candidate = directory / f"{stem}{extension}"
            if candidate.exists():
                return candidate
    return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "stocks", "items", "records", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            nested = _rows(value)
            if nested:
                return nested
    return []


def read_table(path: Path | None) -> tuple[pd.DataFrame, str | None]:
    if path is None:
        return pd.DataFrame(), "configured export was not found"
    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path), None
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path), None
        if suffix == ".jsonl":
            return pd.read_json(path, lines=True), None
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return pd.DataFrame(_rows(payload)), None
        return pd.DataFrame(), f"unsupported table format: {suffix}"
    except Exception as exc:
        return pd.DataFrame(), f"{type(exc).__name__}: {exc}"


def read_analysis(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, "configured analysis artifact was not found"
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                summary = next(
                    (
                        payload.get(key)
                        for key in (
                            "summary",
                            "market_review",
                            "analysis",
                            "decision",
                            "final_trade_decision",
                            "report",
                        )
                        if payload.get(key)
                    ),
                    None,
                )
                return {"summary": str(summary or payload)[:2000], "path": str(path)}, None
        return {"summary": path.read_text(encoding="utf-8").strip()[:2000], "path": str(path)}, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    raw = str(value).strip().replace(",", "")
    if not raw or raw in {"-", "--", "None", "nan"}:
        return None
    multiplier = 1.0
    for suffix, scale in (("万亿", 1e12), ("亿", 1e8), ("万", 1e4)):
        if raw.endswith(suffix):
            multiplier = scale
            raw = raw[: -len(suffix)]
            break
    raw = raw.removesuffix("%")
    try:
        return float(raw) * multiplier
    except ValueError:
        return None


def first_column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in frame.columns}
    return next((normalized[item.lower()] for item in aliases if item.lower() in normalized), None)


def normalize_kaipanla(frame: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    aliases = {
        "security_code": ("security_code", "code", "symbol", "股票代码", "证券代码", "代码"),
        "security_name": ("security_name", "name", "股票简称", "证券简称", "名称"),
        "close": ("close", "latest", "最新价", "收盘价", "现价"),
        "pct_change": ("pct_change", "change_rate", "涨跌幅", "涨幅"),
        "amount": ("amount", "turnover", "成交额", "成交金额"),
        "float_market_cap": ("float_market_cap", "流通市值"),
        "turnover_rate": ("turnover_rate", "换手率"),
    }
    columns = {name: first_column(frame, values) for name, values in aliases.items()}
    required = ("security_code", "security_name", "close", "pct_change", "amount")
    if any(columns[name] is None for name in required):
        return pd.DataFrame()
    result = pd.DataFrame()
    for name in required + ("float_market_cap", "turnover_rate"):
        source = columns[name]
        result[name] = frame[source] if source else pd.NA
    result["security_code"] = (
        result["security_code"].astype(str).str.extract(r"(\d{6})", expand=False).str.zfill(6)
    )
    result["security_name"] = result["security_name"].astype(str).str.strip()
    for column in ("close", "pct_change", "amount", "float_market_cap", "turnover_rate"):
        result[column] = result[column].map(number)
    result["trade_date"] = trade_date
    result["source_id"] = "kaipanla_review"
    result["source_count"] = 1
    result = result.dropna(subset=["security_code", "close", "pct_change", "amount"])
    return result.drop_duplicates("security_code", keep="last").reset_index(drop=True)


def labels(value: Any) -> list[str]:
    return [item.strip() for item in re.split(r"[、,;；|]", str(value or "")) if item.strip()]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")

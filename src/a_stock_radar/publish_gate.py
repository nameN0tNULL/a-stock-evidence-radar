from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class PublishGateResult:
    publishable: bool
    errors: tuple[str, ...]


def _source(payload: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for item in payload.get("source_quality") or []:
        if item.get("source_id") == source_id:
            return item
    return None


def validate_publishable_payload(
    payload: dict[str, Any],
    *,
    expected_stage: str | None = None,
    minimum_market_rows: int = 4000,
    now: datetime | None = None,
) -> PublishGateResult:
    errors: list[str] = []
    mode = str(payload.get("data_mode") or "")
    stage = str(payload.get("report_stage") or "")

    if mode == "mock" or stage == "demo":
        errors.append("mock/demo report cannot replace the production latest report")
    if expected_stage and stage != expected_stage:
        errors.append(f"report stage mismatch: expected {expected_stage}, got {stage or 'missing'}")

    raw_trade_date = payload.get("trade_date")
    try:
        trade_date = datetime.fromisoformat(str(raw_trade_date)).date()
    except ValueError:
        trade_date = None
        errors.append(f"invalid trade_date: {raw_trade_date!r}")

    clock = now or datetime.now(SHANGHAI)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=SHANGHAI)
    local_now = clock.astimezone(SHANGHAI)
    if trade_date and trade_date > local_now.date():
        errors.append(f"trade_date {trade_date} is in the future")
    if (
        trade_date
        and stage == "confirmed"
        and trade_date == local_now.date()
        and (local_now.hour, local_now.minute) < (16, 5)
    ):
        errors.append("same-day confirmed report was generated before 16:05 Asia/Shanghai")

    market = (payload.get("market_state") or {}).get("metrics", {}).get("market", {})
    if not market.get("available"):
        errors.append("market metrics are unavailable")
    if (payload.get("market_state") or {}).get("label") == "数据不足":
        errors.append("market state is 数据不足")

    source_id = "market_eastmoney_snapshot" if mode == "curated" else "market_aggregate"
    source = _source(payload, source_id)
    if not source:
        errors.append(f"required market source is missing from source_quality: {source_id}")
    else:
        if not source.get("available"):
            errors.append(f"required market source is unavailable: {source_id}")
        row_count = int(source.get("row_count") or 0)
        if row_count < minimum_market_rows:
            errors.append(
                f"required market source has only {row_count} rows; "
                f"minimum is {minimum_market_rows}"
            )
        actual_date = source.get("actual_date")
        if trade_date and actual_date and str(actual_date) != trade_date.isoformat():
            errors.append(
                f"required market source date mismatch: expected {trade_date}, got {actual_date}"
            )
        if source.get("schema_ok") is False:
            errors.append(f"required market source schema is invalid: {source_id}")
        if source.get("freshness_ok") is False:
            errors.append(f"required market source is stale: {source_id}")

    return PublishGateResult(not errors, tuple(errors))

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Direction = Literal["positive", "negative", "neutral", "unknown"]
Confidence = Literal["high", "medium", "low"]
ReportStage = Literal["preliminary", "confirmed", "demo"]


class SourceQuality(BaseModel):
    source_id: str
    display_name: str
    trade_date: date
    available: bool
    expected_date: date
    actual_date: date | None = None
    freshness_ok: bool = False
    schema_ok: bool = False
    row_count: int = 0
    anomaly_count: int = 0
    official: bool = False
    evidence_level: Literal["L1", "L2", "L3", "L4"]
    error_message: str | None = None


class EvidenceRecord(BaseModel):
    evidence_id: str
    trade_date: date
    entity_type: Literal["market", "sector", "fund"]
    entity_id: str
    entity_name: str
    cluster: str
    metric: str
    value: float | None = None
    unit: str | None = None
    direction: Direction
    horizon: Literal["1d", "5d", "20d", "250d"]
    percentile: float | None = None
    evidence_level: Literal["L1", "L2", "L3", "L4"]
    official: bool
    source_id: str
    source_date: date | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_estimated: bool = False
    is_missing: bool = False
    missing_reason: str | None = None
    quality_score: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class MarketState(BaseModel):
    trade_date: date
    label: str
    confidence_level: Confidence
    confidence_score: float
    metrics: dict[str, Any]
    supporting_evidence: list[str]
    counter_evidence: list[str]
    unknowns: list[str]


class SectorState(BaseModel):
    trade_date: date
    sector_id: str
    sector_name: str
    state_label: str
    confidence_level: Confidence
    internal_confidence_score: float
    metrics: dict[str, Any]
    evidence_summary: list[EvidenceRecord]
    supporting_evidence: list[str]
    counter_evidence: list[str]
    unknowns: list[str]
    next_confirmation_conditions: list[str]


class ReportPayload(BaseModel):
    trade_date: date
    report_stage: ReportStage
    data_mode: str
    generated_at: datetime
    data_version: str
    market_state: MarketState
    sector_states: list[SectorState]
    source_quality: list[SourceQuality]
    global_unknowns: list[str]
    glossary: dict[str, str]

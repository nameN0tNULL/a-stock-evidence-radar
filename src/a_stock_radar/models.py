from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Direction = Literal["positive", "negative", "neutral", "unknown"]
Confidence = Literal["high", "medium", "low"]
ReportStage = Literal["preliminary", "confirmed", "demo"]
LayerStatus = Literal["available", "partial", "missing"]
HypothesisActivity = Literal["active", "reducing", "mixed", "possible", "unknown"]
ProbabilityStatus = Literal["available", "insufficient_samples", "unavailable"]
ProvenanceStatus = Literal["confirmed", "provisional", "missing"]


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


class EvidenceLayerStatus(BaseModel):
    layer_id: Literal["market_replay", "seat_facts", "microstructure", "automated_report"]
    display_name: str
    status: LayerStatus
    summary: str
    source_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FieldProvenance(BaseModel):
    field_path: str
    display_name: str
    value: Any = None
    unit: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    evidence_level: Literal["L1", "L2", "L3", "L4"]
    official: bool
    as_of_date: date | None = None
    transform: str = "direct"
    status: ProvenanceStatus
    limitations: list[str] = Field(default_factory=list)


class ParticipantHypothesis(BaseModel):
    participant_id: str
    display_name: str
    activity: HypothesisActivity
    confidence_level: Confidence
    confidence_score: float = Field(ge=0, le=100)
    observation: str
    supporting_evidence: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    cannot_confirm: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)


class CounterpartyRelation(BaseModel):
    relation_id: str
    left_archetype: str
    right_archetype: str
    interaction: str
    confidence_level: Confidence
    confidence_score: float = Field(ge=0, le=100)
    supporting_evidence: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    confirmation_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)


class HistoricalConditionalProbability(BaseModel):
    condition: str
    outcome: str
    horizon: Literal["1d", "5d", "20d"]
    status: ProbabilityStatus
    sample_size: int = 0
    minimum_samples: int = 20
    conditional_probability: float | None = Field(default=None, ge=0, le=1)
    baseline_probability: float | None = Field(default=None, ge=0, le=1)
    lift: float | None = None
    method: str
    limitations: list[str] = Field(default_factory=list)


class ScenarioPath(BaseModel):
    scenario_id: str
    title: str
    narrative: str
    probability: float | None = Field(default=None, ge=0, le=1)
    probability_status: ProbabilityStatus
    probability_source: Literal["historical_conditional", "insufficient_history", "not_estimated"]
    sample_size: int = 0
    confidence_level: Confidence
    supporting_evidence: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    confirmation_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)


class SeatFact(BaseModel):
    fact_id: str
    security_code: str
    security_name: str | None = None
    fact_type: str
    buyer_labels: list[str] = Field(default_factory=list)
    seller_labels: list[str] = Field(default_factory=list)
    net_amount: float | None = None
    source_id: str
    source_date: date
    official: bool
    limitations: list[str] = Field(default_factory=list)


class MicrostructureSummary(BaseModel):
    available: bool = False
    symbol_count: int = 0
    confirmed_symbol_count: int = 0
    provisional_symbol_count: int = 0
    total_notional: float | None = None
    signed_notional_imbalance: float | None = None
    classification_coverage: float | None = None
    closing_auction_notional_share: float | None = None
    source_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DailyReview(BaseModel):
    review_version: str
    market_phase: str
    market_phase_summary: str
    evidence_layers: list[EvidenceLayerStatus]
    participant_hypotheses: list[ParticipantHypothesis]
    counterparty_relations: list[CounterpartyRelation]
    historical_conditionals: list[HistoricalConditionalProbability]
    scenario_paths: list[ScenarioPath]
    seat_facts: list[SeatFact] = Field(default_factory=list)
    microstructure: MicrostructureSummary = Field(default_factory=MicrostructureSummary)
    field_provenance: list[FieldProvenance] = Field(default_factory=list)
    confirmation_checklist: list[str] = Field(default_factory=list)
    falsification_checklist: list[str] = Field(default_factory=list)


class ReportPayload(BaseModel):
    trade_date: date
    report_stage: ReportStage
    data_mode: str
    generated_at: datetime
    data_version: str
    market_state: MarketState
    sector_states: list[SectorState]
    daily_review: DailyReview
    source_quality: list[SourceQuality]
    global_unknowns: list[str]
    glossary: dict[str, str]

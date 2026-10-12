from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from .models import (
    FreshnessStatus,
    OrderFailureReason,
    OrderStatus,
    ProbeStatus,
    RecoveryError,
    RuleKey,
    ScopeType,
    Severity,
    SourceFreshness,
    StrictModel,
)


class EvidenceDetails(StrictModel):
    """Allowlisted, typed evidence fields. Never stores raw upstream JSON."""

    rule_key: RuleKey | None = Field(default=None, alias="ruleKey")
    rule_version: int | None = Field(default=None, alias="ruleVersion", ge=1)
    severity: Severity | None = None
    incident_status: Literal["OPEN", "RESOLVED"] | None = Field(default=None, alias="incidentStatus")
    scope_type: ScopeType | None = Field(default=None, alias="scopeType")
    occurrence_count: int | None = Field(default=None, alias="occurrenceCount", ge=1)
    service_name: Literal["api-gateway", "order-service", "inventory-service", "payment-service"] | None = Field(default=None, alias="serviceName")
    probe_status: ProbeStatus | None = Field(default=None, alias="probeStatus")
    order_status: OrderStatus | None = Field(default=None, alias="orderStatus")
    failure_reason: OrderFailureReason | None = Field(default=None, alias="failureReason")
    recovery_error: RecoveryError | None = Field(default=None, alias="recoveryError")
    recovery_attempts: int | None = Field(default=None, alias="recoveryAttempts", ge=0)
    next_recovery_at: datetime | None = Field(default=None, alias="nextRecoveryAt")
    inventory_released: bool | None = Field(default=None, alias="inventoryReleased")
    trace_id: str | None = Field(default=None, alias="traceId", pattern=r"^[0-9a-f]{32}$")
    service: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    span_id: str | None = Field(default=None, alias="spanId", pattern=r"^[0-9a-f]{16}$")
    parent_span_id: str | None = Field(default=None, alias="parentSpanId", pattern=r"^[0-9a-f]{16}$")
    span_name: str | None = Field(default=None, alias="spanName", max_length=120)
    span_status: Literal["OK", "ERROR", "UNSET"] | None = Field(default=None, alias="spanStatus")
    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] | None = Field(default=None, alias="httpMethod")
    http_route: str | None = Field(default=None, alias="httpRoute", max_length=180, pattern=r"^/[a-zA-Z0-9_./{}-]*$")
    http_status_code: int | None = Field(default=None, alias="httpStatusCode", ge=100, le=599)

    @field_validator("next_recovery_at")
    @classmethod
    def require_aware_recovery_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("evidence timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None

    @field_validator("span_name")
    @classmethod
    def reject_control_characters_in_span_name(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("span names must not contain control characters")
        return value


class InvestigationEvidence(StrictModel):
    evidence_id: str = Field(alias="evidenceId", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9:._-]+$")
    source_type: Literal["INCIDENT", "INCIDENT_SIGNAL", "SERVICE_HEALTH", "ORDER_RECOVERY", "TRACE_SPAN"] = Field(alias="sourceType")
    source_name: Literal["incident-service", "detection-store", "order-service", "tempo-via-gateway"] = Field(alias="sourceName")
    source_id: str = Field(alias="sourceId", min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9:._-]+$")
    observed_at: datetime | None = Field(default=None, alias="observedAt")
    freshness_status: FreshnessStatus | None = Field(default=None, alias="freshnessStatus")
    signal_code: str | None = Field(default=None, alias="signalCode", max_length=64, pattern=r"^[A-Z0-9_]+$")
    summary: str = Field(min_length=1, max_length=280)
    details: EvidenceDetails

    @field_validator("observed_at")
    @classmethod
    def require_aware_observation_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("evidence timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class EvidenceGap(StrictModel):
    source: Literal["SERVICE_HEALTH", "ORDER_RECOVERY", "TRACE"]
    code: Literal[
        "HEALTH_OBSERVATION_MISSING",
        "HEALTH_SOURCE_NOT_CURRENT",
        "ORDER_OBSERVATION_MISSING",
        "ORDER_SOURCE_PARTIAL",
        "ORDER_SOURCE_UNAVAILABLE",
        "NO_TRACE_REFERENCE",
        "TRACE_REFERENCE_LIMIT",
        "TRACE_NOT_FOUND",
        "TRACE_EMPTY",
        "TRACE_SOURCE_UNAVAILABLE",
        "TRACE_RESPONSE_TOO_LARGE",
        "TRACE_RESPONSE_INVALID",
        "TRACE_SPANS_TRUNCATED",
        "CONTRADICTORY_ORDER_STATE",
    ]
    summary: str = Field(min_length=1, max_length=240)
    required: bool


class InvestigationClaim(StrictModel):
    claim_id: str = Field(alias="claimId", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field(min_length=1, max_length=320)
    evidence_ids: list[str] = Field(alias="evidenceIds", min_length=1, max_length=20)


class InvestigationContent(StrictModel):
    summary: str = Field(min_length=1, max_length=320)
    uncertainty: str = Field(min_length=1, max_length=320)
    facts: list[InvestigationClaim] = Field(max_length=20)
    hypotheses: list[InvestigationClaim] = Field(max_length=10)
    recommended_actions: list[InvestigationClaim] = Field(alias="recommendedActions", max_length=10)


class InvestigationResult(InvestigationContent):
    investigation_id: UUID = Field(alias="investigationId")
    incident_id: UUID = Field(alias="incidentId")
    generated_at: datetime = Field(alias="generatedAt")
    status: Literal["COMPLETE", "PARTIAL", "INSUFFICIENT"]
    provider: Literal["deterministic-v1"]
    evidence: list[InvestigationEvidence] = Field(max_length=100)
    evidence_gaps: list[EvidenceGap] = Field(alias="evidenceGaps", max_length=20)
    sources: list[SourceFreshness] = Field(max_length=10)

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generatedAt must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("evidence")
    @classmethod
    def require_unique_evidence_ids(cls, value: list[InvestigationEvidence]) -> list[InvestigationEvidence]:
        if len({item.evidence_id for item in value}) != len(value):
            raise ValueError("evidence identifiers must be unique")
        return value


def validate_citations(content: InvestigationContent, evidence: list[InvestigationEvidence]) -> None:
    evidence_ids = {item.evidence_id for item in evidence}
    if len(evidence_ids) != len(evidence):
        raise ValueError("evidence identifiers must be unique")
    claims = [*content.facts, *content.hypotheses, *content.recommended_actions]
    for claim in claims:
        if not claim.evidence_ids or any(item_id not in evidence_ids for item_id in claim.evidence_ids):
            raise ValueError("investigation claim cites evidence outside the collected set")


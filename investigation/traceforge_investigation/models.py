from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ProbeStatus(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class FreshnessStatus(StrEnum):
    CURRENT = "CURRENT"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class SourceFreshness(StrictModel):
    source: str = Field(min_length=1, max_length=64)
    status: FreshnessStatus
    attempted_at: datetime = Field(alias="attemptedAt")
    last_success_at: datetime | None = Field(default=None, alias="lastSuccessAt")
    item_count: int = Field(default=0, ge=0, alias="itemCount")
    error_code: str | None = Field(default=None, alias="errorCode", max_length=64)

    @field_validator("attempted_at", "last_success_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class HealthObservation(StrictModel):
    service_name: Literal["api-gateway", "order-service", "inventory-service", "payment-service"] = Field(alias="serviceName")
    status: ProbeStatus
    observed_at: datetime = Field(alias="observedAt")
    http_status: int | None = Field(default=None, alias="httpStatus", ge=100, le=599)
    signal_code: Literal[
        "HEALTH_UP",
        "HTTP_NON_200",
        "HEALTH_NON_UP",
        "CONNECT_FAILED",
        "PROBE_TIMEOUT",
        "MALFORMED_HEALTH_RESPONSE",
        "HEALTH_RESPONSE_TOO_LARGE",
    ] = Field(alias="signalCode")

    @field_validator("observed_at")
    @classmethod
    def require_utc_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class ProbeResult(StrictModel):
    observation: HealthObservation
    freshness: SourceFreshness


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"


class OrderFailureReason(StrEnum):
    UNKNOWN_SKU = "UNKNOWN_SKU"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    INVENTORY_UNAVAILABLE = "INVENTORY_UNAVAILABLE"
    PAYMENT_UNAVAILABLE = "PAYMENT_UNAVAILABLE"
    INVENTORY_RESPONSE_MISMATCH = "INVENTORY_RESPONSE_MISMATCH"
    PAYMENT_RESPONSE_MISMATCH = "PAYMENT_RESPONSE_MISMATCH"
    PAYMENT_IDEMPOTENCY_CONFLICT = "PAYMENT_IDEMPOTENCY_CONFLICT"


class RecoveryError(StrEnum):
    INVENTORY_OUTCOME_UNKNOWN = "INVENTORY_OUTCOME_UNKNOWN"
    INVENTORY_RETRY_SCHEDULED = "INVENTORY_RETRY_SCHEDULED"
    PAYMENT_OUTCOME_UNKNOWN = "PAYMENT_OUTCOME_UNKNOWN"
    PAYMENT_RETRY_SCHEDULED = "PAYMENT_RETRY_SCHEDULED"
    COMPENSATION_OUTCOME_UNKNOWN = "COMPENSATION_OUTCOME_UNKNOWN"
    COMPENSATION_RETRY_SCHEDULED = "COMPENSATION_RETRY_SCHEDULED"
    COMPENSATION_RESPONSE_MISMATCH = "COMPENSATION_RESPONSE_MISMATCH"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    AUTOMATIC_RETRIES_EXHAUSTED = "AUTOMATIC_RETRIES_EXHAUSTED"
    RECOVERY_INTERNAL_ERROR = "RECOVERY_INTERNAL_ERROR"


class OrderRecoveryCase(StrictModel):
    order_id: UUID = Field(alias="orderId")
    status: OrderStatus
    failure_reason: OrderFailureReason | None = Field(alias="failureReason")
    recovery_error: RecoveryError | None = Field(alias="recoveryError")
    recovery_attempts: int = Field(alias="recoveryAttempts", ge=0)
    next_recovery_at: datetime = Field(alias="nextRecoveryAt")
    inventory_released: bool = Field(alias="inventoryReleased")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    origin_trace_id: str | None = Field(alias="originTraceId", pattern=r"^[0-9a-f]{32}$")

    @field_validator("next_recovery_at", "created_at", "updated_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class OrderCursor(StrictModel):
    after_created_at: datetime = Field(alias="afterCreatedAt")
    after_id: UUID = Field(alias="afterId")

    @field_validator("after_created_at")
    @classmethod
    def require_cursor_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cursor timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class OrderAttentionPage(StrictModel):
    items: list[OrderRecoveryCase] = Field(max_length=100)
    limit: int = Field(ge=1, le=100)
    next_cursor: OrderCursor | None = Field(alias="nextCursor")

    @model_validator(mode="after")
    def validate_page_contract(self) -> OrderAttentionPage:
        if len(self.items) > self.limit:
            raise ValueError("page contains more items than its declared limit")
        if self.next_cursor is not None and not self.items:
            raise ValueError("a nonterminal page must contain an item")
        return self


class OrderRecoveryObservationPage(StrictModel):
    items: list[OrderRecoveryCase] = Field(max_length=100)
    missing_order_ids: list[UUID] = Field(alias="missingOrderIds", max_length=100)

    @model_validator(mode="after")
    def validate_observation_partition(self) -> OrderRecoveryObservationPage:
        found = [item.order_id for item in self.items]
        if len(set(found)) != len(found) or len(set(self.missing_order_ids)) != len(self.missing_order_ids):
            raise ValueError("observation IDs must be unique")
        if set(found).intersection(self.missing_order_ids):
            raise ValueError("an order cannot be both found and missing")
        return self


class RuleKey(StrEnum):
    SERVICE_NOT_READY = "SERVICE_NOT_READY"
    ORDER_RECOVERY_STALLED = "ORDER_RECOVERY_STALLED"


class DecisionAction(StrEnum):
    NONE = "NONE"
    OPEN_OR_UPDATE = "OPEN_OR_UPDATE"
    RESOLVE = "RESOLVE"


class Severity(StrEnum):
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ScopeType(StrEnum):
    SERVICE = "SERVICE"
    ORDER = "ORDER"


class EvidenceReference(StrictModel):
    source_type: Literal["HEALTH_PROBE", "ORDER_RECOVERY"] = Field(alias="sourceType")
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    observed_at: datetime = Field(alias="observedAt")
    signal_code: str = Field(alias="signalCode", min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    trace_id: str | None = Field(default=None, alias="traceId", pattern=r"^[0-9a-f]{32}$")

    @field_validator("observed_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class RuleFinding(StrictModel):
    rule_key: RuleKey = Field(alias="ruleKey")
    rule_version: int = Field(default=1, alias="ruleVersion", ge=1)
    severity: Severity
    scope_type: ScopeType = Field(alias="scopeType")
    source_reference: str = Field(alias="sourceReference", min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=200)
    evidence: EvidenceReference


class RuleDecision(StrictModel):
    action: DecisionAction
    finding: RuleFinding | None = None
    resolved_rule: RuleKey | None = Field(default=None, alias="resolvedRule")
    resolved_scope_type: ScopeType | None = Field(default=None, alias="resolvedScopeType")
    resolved_source_reference: str | None = Field(default=None, alias="resolvedSourceReference")


class HealthRuleState(StrictModel):
    service_name: Literal["api-gateway", "order-service", "inventory-service", "payment-service"] = Field(alias="serviceName")
    failure_streak: int = Field(default=0, alias="failureStreak", ge=0)
    success_streak: int = Field(default=0, alias="successStreak", ge=0)
    last_status: ProbeStatus | None = Field(default=None, alias="lastStatus")
    last_observed_at: datetime | None = Field(default=None, alias="lastObservedAt")
    incident_open: bool = Field(default=False, alias="incidentOpen")

    @field_validator("last_observed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("state timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class HealthEvaluation(StrictModel):
    state: HealthRuleState
    decision: RuleDecision


class DetectionCycleResult(StrictModel):
    cycle_id: UUID = Field(alias="cycleId")
    status: Literal["COMPLETE", "PARTIAL"]
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime = Field(alias="completedAt")
    health_sources: list[SourceFreshness] = Field(alias="healthSources")
    order_source: SourceFreshness = Field(alias="orderSource")
    findings_opened_or_updated: int = Field(alias="findingsOpenedOrUpdated", ge=0)
    incidents_resolved: int = Field(alias="incidentsResolved", ge=0)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cycle timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class IncidentRecord(StrictModel):
    id: UUID
    rule_key: RuleKey = Field(alias="ruleKey")
    rule_version: int = Field(alias="ruleVersion", ge=1)
    severity: Severity
    status: Literal["OPEN", "RESOLVED"]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_type: ScopeType = Field(alias="scopeType")
    source_reference: str = Field(alias="sourceReference")
    first_seen_at: datetime = Field(alias="firstSeenAt")
    last_seen_at: datetime = Field(alias="lastSeenAt")
    last_evaluated_at: datetime = Field(alias="lastEvaluatedAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")
    occurrence_count: int = Field(alias="occurrenceCount", ge=1)
    summary: str = Field(max_length=200)
    evidence: list[EvidenceReference] = Field(max_length=20)
    origin_trace_id: str | None = Field(default=None, alias="originTraceId", pattern=r"^[0-9a-f]{32}$")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_validator("first_seen_at", "last_seen_at", "last_evaluated_at", "resolved_at", "created_at", "updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("incident timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class DetectionCycleRecord(StrictModel):
    cycle_id: UUID = Field(alias="cycleId")
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    status: Literal["RUNNING", "COMPLETE", "PARTIAL", "FAILED"]
    findings_opened_or_updated: int = Field(default=0, alias="findingsOpenedOrUpdated", ge=0)
    incidents_resolved: int = Field(default=0, alias="incidentsResolved", ge=0)
    failure_code: str | None = Field(default=None, alias="failureCode", max_length=64)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_cycle_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class ServiceHealthSnapshot(StrictModel):
    service_name: Literal["api-gateway", "order-service", "inventory-service", "payment-service"] = Field(alias="serviceName")
    status: ProbeStatus
    observed_at: datetime | None = Field(default=None, alias="observedAt")
    freshness_status: FreshnessStatus = Field(alias="freshnessStatus")
    incident_open: bool = Field(alias="incidentOpen")

    @field_validator("observed_at")
    @classmethod
    def require_utc_observation(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class DetectionStatusResponse(StrictModel):
    status: Literal["NOT_RUN", "CURRENT", "PARTIAL", "STALE", "UNAVAILABLE"]
    latest_cycle: DetectionCycleRecord | None = Field(default=None, alias="latestCycle")
    sources: list[SourceFreshness]
    services: list[ServiceHealthSnapshot]


class IncidentPage(StrictModel):
    items: list[IncidentRecord]
    limit: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(default=None, alias="nextCursor", max_length=256)
    detection_status: DetectionStatusResponse = Field(alias="detectionStatus")

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import (
    DecisionAction,
    EvidenceReference,
    HealthEvaluation,
    HealthObservation,
    HealthRuleState,
    OrderFailureReason,
    OrderRecoveryCase,
    OrderStatus,
    ProbeStatus,
    RuleDecision,
    RuleFinding,
    RuleKey,
    ScopeType,
    Severity,
)


@dataclass(frozen=True)
class HealthRulePolicy:
    failure_threshold: int = 2
    recovery_threshold: int = 2
    stale_after: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if self.failure_threshold < 1 or self.recovery_threshold < 1:
            raise ValueError("health thresholds must be positive")
        if self.stale_after <= timedelta(0):
            raise ValueError("health freshness threshold must be positive")


@dataclass(frozen=True)
class OrderRecoveryPolicy:
    grace_period: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if self.grace_period < timedelta(0):
            raise ValueError("recovery grace period cannot be negative")


def evaluate_health_observation(
    observation: HealthObservation,
    previous: HealthRuleState,
    now: datetime,
    policy: HealthRulePolicy = HealthRulePolicy(),
) -> HealthEvaluation:
    """Purely evaluate one ordered, fresh probe against its durable streak state."""
    _require_aware(now)
    current_time = now.astimezone(timezone.utc)
    if observation.service_name != previous.service_name:
        raise ValueError("health state belongs to a different service")

    age = current_time - observation.observed_at
    if (
        observation.status == ProbeStatus.UNKNOWN
        or age < timedelta(0)
        or age > policy.stale_after
        or (previous.last_observed_at is not None and observation.observed_at <= previous.last_observed_at)
    ):
        return HealthEvaluation(state=previous, decision=RuleDecision(action=DecisionAction.NONE))

    if observation.status in {ProbeStatus.DOWN, ProbeStatus.TIMEOUT}:
        next_state = previous.model_copy(
            update={
                "failure_streak": previous.failure_streak + 1,
                "success_streak": 0,
                "last_status": observation.status,
                "last_observed_at": observation.observed_at,
                "incident_open": previous.incident_open or previous.failure_streak + 1 >= policy.failure_threshold,
            }
        )
        if next_state.failure_streak < policy.failure_threshold:
            return HealthEvaluation(state=next_state, decision=RuleDecision(action=DecisionAction.NONE))

        finding = RuleFinding(
            rule_key=RuleKey.SERVICE_NOT_READY,
            severity=Severity.CRITICAL,
            scope_type=ScopeType.SERVICE,
            source_reference=observation.service_name,
            summary=f"Readiness probe failed for {observation.service_name}",
            evidence=EvidenceReference(
                source_type="HEALTH_PROBE",
                source_id=observation.service_name,
                observed_at=observation.observed_at,
                signal_code=observation.signal_code,
            ),
        )
        return HealthEvaluation(
            state=next_state,
            decision=RuleDecision(action=DecisionAction.OPEN_OR_UPDATE, finding=finding),
        )

    if observation.status == ProbeStatus.UP:
        next_state = previous.model_copy(
            update={
                "failure_streak": 0,
                "success_streak": previous.success_streak + 1,
                "last_status": ProbeStatus.UP,
                "last_observed_at": observation.observed_at,
                "incident_open": previous.incident_open,
            }
        )
        if previous.incident_open and next_state.success_streak >= policy.recovery_threshold:
            next_state = next_state.model_copy(update={"incident_open": False})
            return HealthEvaluation(
                state=next_state,
                decision=RuleDecision(
                    action=DecisionAction.RESOLVE,
                    resolved_rule=RuleKey.SERVICE_NOT_READY,
                    resolved_scope_type=ScopeType.SERVICE,
                    resolved_source_reference=observation.service_name,
                ),
            )
        return HealthEvaluation(state=next_state, decision=RuleDecision(action=DecisionAction.NONE))

    return HealthEvaluation(state=previous, decision=RuleDecision(action=DecisionAction.NONE))


def evaluate_order_recovery(
    case: OrderRecoveryCase,
    now: datetime,
    policy: OrderRecoveryPolicy = OrderRecoveryPolicy(),
) -> RuleDecision:
    """Evaluate only explicit Order state; absence of a case is never a resolution signal."""
    _require_aware(now)
    current_time = now.astimezone(timezone.utc)

    incomplete_compensation = (
        case.status == OrderStatus.COMPENSATION_REQUIRED and not case.inventory_released
    ) or (
        case.status == OrderStatus.FAILED
        and case.failure_reason == OrderFailureReason.PAYMENT_DECLINED
        and not case.inventory_released
    )
    if incomplete_compensation:
        return _order_finding(case, "COMPENSATION_INCOMPLETE", current_time)

    if case.status in {OrderStatus.CONFIRMED, OrderStatus.FAILED}:
        return RuleDecision(
            action=DecisionAction.RESOLVE,
            resolved_rule=RuleKey.ORDER_RECOVERY_STALLED,
            resolved_scope_type=ScopeType.ORDER,
            resolved_source_reference=str(case.order_id),
        )

    if case.recovery_error in {"MANUAL_REVIEW_REQUIRED", "AUTOMATIC_RETRIES_EXHAUSTED"}:
        return _order_finding(case, "RECOVERY_ACTION_REQUIRED", current_time)

    if case.next_recovery_at + policy.grace_period <= current_time:
        return _order_finding(case, "RECOVERY_DEADLINE_EXCEEDED", current_time)

    return RuleDecision(action=DecisionAction.NONE)


def incident_fingerprint(rule_key: RuleKey, scope_type: ScopeType, source_reference: str) -> str:
    """Stable, non-secret deduplication key; trace IDs are deliberately excluded."""
    canonical = f"{rule_key.value}\0{scope_type.value}\0{source_reference}".encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _order_finding(case: OrderRecoveryCase, signal_code: str, observed_at: datetime) -> RuleDecision:
    finding = RuleFinding(
        rule_key=RuleKey.ORDER_RECOVERY_STALLED,
        severity=Severity.HIGH,
        scope_type=ScopeType.ORDER,
        source_reference=str(case.order_id),
        summary="Order recovery requires attention",
        evidence=EvidenceReference(
            source_type="ORDER_RECOVERY",
            source_id=str(case.order_id),
            observed_at=observed_at,
            signal_code=signal_code,
            trace_id=case.origin_trace_id,
        ),
    )
    return RuleDecision(action=DecisionAction.OPEN_OR_UPDATE, finding=finding)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluation time must include a timezone")

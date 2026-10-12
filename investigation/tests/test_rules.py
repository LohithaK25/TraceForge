from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from traceforge_investigation.models import (
    DecisionAction,
    HealthObservation,
    HealthRuleState,
    OrderRecoveryCase,
    ProbeStatus,
    RuleKey,
    ScopeType,
)
from traceforge_investigation.rules import (
    HealthRulePolicy,
    OrderRecoveryPolicy,
    evaluate_health_observation,
    evaluate_order_recovery,
    incident_fingerprint,
)
from .helpers import NOW, TRACE_ID, case_payload


def probe(service: str, status: ProbeStatus, observed_at=NOW, signal_code: str | None = None):
    return HealthObservation(
        serviceName=service,
        status=status,
        observedAt=observed_at,
        httpStatus=200 if status == ProbeStatus.UP else 503 if status == ProbeStatus.DOWN else None,
        signalCode=signal_code or {
            ProbeStatus.UP: "HEALTH_UP",
            ProbeStatus.DOWN: "HTTP_NON_200",
            ProbeStatus.TIMEOUT: "PROBE_TIMEOUT",
            ProbeStatus.UNKNOWN: "MALFORMED_HEALTH_RESPONSE",
        }[status],
    )


def test_one_failure_does_not_open_and_up_resets_failure_streak():
    state = HealthRuleState(serviceName="order-service")
    first = evaluate_health_observation(probe("order-service", ProbeStatus.DOWN), state, NOW)
    assert first.decision.action == DecisionAction.NONE
    assert first.state.failure_streak == 1

    recovered = evaluate_health_observation(
        probe("order-service", ProbeStatus.UP, NOW + timedelta(seconds=1)),
        first.state,
        NOW + timedelta(seconds=1),
    )
    assert recovered.decision.action == DecisionAction.NONE
    assert recovered.state.failure_streak == 0
    assert recovered.state.success_streak == 1


def test_two_consecutive_failures_open_one_service_finding():
    first = evaluate_health_observation(
        probe("inventory-service", ProbeStatus.TIMEOUT),
        HealthRuleState(serviceName="inventory-service"),
        NOW,
    )
    second = evaluate_health_observation(
        probe("inventory-service", ProbeStatus.DOWN, NOW + timedelta(seconds=1)),
        first.state,
        NOW + timedelta(seconds=1),
    )
    assert second.decision.action == DecisionAction.OPEN_OR_UPDATE
    assert second.decision.finding is not None
    assert second.decision.finding.rule_key == "SERVICE_NOT_READY"
    assert second.decision.finding.source_reference == "inventory-service"


def test_two_up_probes_resolve_but_one_up_probe_does_not():
    open_state = HealthRuleState(
        serviceName="payment-service",
        failureStreak=2,
        incidentOpen=True,
    )
    first = evaluate_health_observation(probe("payment-service", ProbeStatus.UP), open_state, NOW)
    assert first.decision.action == DecisionAction.NONE
    assert first.state.incident_open
    second = evaluate_health_observation(
        probe("payment-service", ProbeStatus.UP, NOW + timedelta(seconds=1)),
        first.state,
        NOW + timedelta(seconds=1),
    )
    assert second.decision.action == DecisionAction.RESOLVE
    assert not second.state.incident_open


def test_interleaved_services_keep_independent_streaks():
    gateway = evaluate_health_observation(
        probe("api-gateway", ProbeStatus.DOWN), HealthRuleState(serviceName="api-gateway"), NOW
    )
    inventory = evaluate_health_observation(
        probe("inventory-service", ProbeStatus.UP), HealthRuleState(serviceName="inventory-service"), NOW
    )
    next_gateway = evaluate_health_observation(
        probe("api-gateway", ProbeStatus.DOWN, NOW + timedelta(seconds=1)),
        gateway.state,
        NOW + timedelta(seconds=1),
    )
    assert inventory.state.failure_streak == 0
    assert next_gateway.decision.action == DecisionAction.OPEN_OR_UPDATE


@pytest.mark.parametrize("status", [ProbeStatus.UNKNOWN, ProbeStatus.UP])
def test_unknown_or_stale_observation_does_not_count_as_healthy_or_clear_open_state(status):
    state = HealthRuleState(
        serviceName="order-service",
        failureStreak=2,
        incidentOpen=True,
        lastObservedAt=NOW - timedelta(seconds=1),
    )
    observation_time = NOW - timedelta(minutes=10) if status == ProbeStatus.UP else NOW
    evaluation = evaluate_health_observation(
        probe("order-service", status, observation_time),
        state,
        NOW,
        HealthRulePolicy(stale_after=timedelta(seconds=30)),
    )
    assert evaluation.decision.action == DecisionAction.NONE
    assert evaluation.state == state


def test_unknown_probe_does_not_advance_either_streak():
    state = HealthRuleState(serviceName="api-gateway", failureStreak=1, successStreak=0)
    result = evaluate_health_observation(probe("api-gateway", ProbeStatus.UNKNOWN), state, NOW)
    assert result.state == state
    assert result.decision.action == DecisionAction.NONE


@pytest.mark.parametrize(
    ("deadline_offset", "expected"),
    [(-timedelta(seconds=31), DecisionAction.OPEN_OR_UPDATE), (-timedelta(seconds=30), DecisionAction.OPEN_OR_UPDATE), (-timedelta(seconds=29), DecisionAction.NONE)],
)
def test_order_deadline_grace_boundary(deadline_offset, expected):
    case = OrderRecoveryCase.model_validate(
        case_payload(next_recovery_at=NOW + deadline_offset, recovery_error="INVENTORY_RETRY_SCHEDULED")
    )
    decision = evaluate_order_recovery(case, NOW, OrderRecoveryPolicy(grace_period=timedelta(seconds=30)))
    assert decision.action == expected


def test_explicit_incomplete_compensation_is_immediately_actionable():
    case = OrderRecoveryCase.model_validate(
        case_payload(status="COMPENSATION_REQUIRED", failure_reason="PAYMENT_DECLINED", recovery_error=None)
    )
    decision = evaluate_order_recovery(case, NOW)
    assert decision.action == DecisionAction.OPEN_OR_UPDATE
    assert decision.finding is not None
    assert decision.finding.evidence.signal_code == "COMPENSATION_INCOMPLETE"
    assert decision.finding.evidence.trace_id == TRACE_ID


@pytest.mark.parametrize(
    "payload",
    [
        case_payload(status="CONFIRMED", failure_reason=None, recovery_error=None, inventory_released=False),
        case_payload(status="FAILED", failure_reason="UNKNOWN_SKU", recovery_error=None, inventory_released=False),
        case_payload(status="FAILED", failure_reason="PAYMENT_DECLINED", recovery_error=None, inventory_released=True),
    ],
)
def test_successful_or_fully_compensated_terminal_workflows_are_not_incidents(payload):
    case = OrderRecoveryCase.model_validate(payload)
    decision = evaluate_order_recovery(case, NOW)
    assert decision.action == DecisionAction.RESOLVE
    assert decision.finding is None


def test_terminal_decline_without_required_inventory_release_remains_actionable():
    case = OrderRecoveryCase.model_validate(
        case_payload(status="FAILED", failure_reason="PAYMENT_DECLINED", recovery_error=None, inventory_released=False)
    )
    decision = evaluate_order_recovery(case, NOW)
    assert decision.action == DecisionAction.OPEN_OR_UPDATE
    assert decision.finding is not None
    assert decision.finding.evidence.signal_code == "COMPENSATION_INCOMPLETE"


def test_unknown_or_missing_order_fields_fail_closed():
    payload = case_payload()
    del payload["nextRecoveryAt"]
    with pytest.raises(ValidationError):
        OrderRecoveryCase.model_validate(payload)

    payload = case_payload()
    del payload["recoveryError"]
    with pytest.raises(ValidationError):
        OrderRecoveryCase.model_validate(payload)

    payload = case_payload()
    payload["paymentAmount"] = 123
    with pytest.raises(ValidationError):
        OrderRecoveryCase.model_validate(payload)


def test_fingerprint_is_stable_and_excludes_trace_identifiers():
    key1 = incident_fingerprint(
        RuleKey.ORDER_RECOVERY_STALLED,
        ScopeType.ORDER,
        "2b8a3224-fb83-4757-b503-12f6fdbbd273",
    )
    key2 = incident_fingerprint(
        RuleKey.ORDER_RECOVERY_STALLED,
        ScopeType.ORDER,
        "2b8a3224-fb83-4757-b503-12f6fdbbd273",
    )
    assert key1 == key2
    assert len(key1) == 64

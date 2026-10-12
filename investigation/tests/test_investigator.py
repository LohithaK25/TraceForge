from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from traceforge_investigation.clients import TerminalObservationCollection
from traceforge_investigation.config import Settings
from traceforge_investigation.investigation_clients import TraceFetch
from traceforge_investigation.investigation_models import (
    InvestigationClaim,
    InvestigationContent,
    validate_citations,
)
from traceforge_investigation.investigator import IncidentInvestigator
from traceforge_investigation.models import (
    DetectionStatusResponse,
    EvidenceReference,
    FreshnessStatus,
    IncidentRecord,
    OrderRecoveryCase,
    OrderStatus,
    ProbeStatus,
    RecoveryError,
    RuleKey,
    ScopeType,
    ServiceHealthSnapshot,
    Severity,
    SourceFreshness,
)
from .helpers import NOW, TRACE_ID


PAYMENT_INCIDENT_ID = UUID("8eb4a00e-3c29-49a0-a8ad-452d7ef11001")
ORDER_ID = UUID("ab3163ab-2240-4578-b012-9b8f9226b7f2")


class FakeRepository:
    def __init__(self, incident: IncidentRecord, detection: DetectionStatusResponse | None = None) -> None:
        self.incident = incident
        self.detection = detection
        self.saved = None

    def find_by_id(self, incident_id: UUID) -> IncidentRecord | None:
        return self.incident if self.incident.id == incident_id else None

    def detection_status(self, _now, _stale_after_seconds):
        return self.detection

    def last_successful_source_times(self):
        return {}

    def save_investigation(self, result) -> None:
        self.saved = result


class FakeOrderClient:
    def __init__(self, collection: TerminalObservationCollection | None = None) -> None:
        self.collection = collection
        self.restored = None

    def restore_last_success(self, value) -> None:
        self.restored = value

    def lookup_terminal(self, _ids, _now):
        assert self.collection is not None
        return self.collection

    def close(self) -> None:
        pass


class FakeTraceClient:
    def __init__(self, fetched: TraceFetch | None = None) -> None:
        self.fetched = fetched
        self.requested: list[str] = []

    def fetch(self, trace_id: str, _now):
        self.requested.append(trace_id)
        assert self.fetched is not None
        return self.fetched

    def close(self) -> None:
        pass


def test_health_investigation_cites_persisted_incident_and_signal_and_marks_no_trace_optional():
    incident = _incident(RuleKey.SERVICE_NOT_READY, "payment-service", ScopeType.SERVICE)
    repo = FakeRepository(incident, _detection(FreshnessStatus.CURRENT, ProbeStatus.DOWN))
    order = FakeOrderClient()
    trace = FakeTraceClient()

    result = IncidentInvestigator(Settings(), repo, order, trace).run(incident.id, NOW)

    assert result is not None
    assert result.status == "COMPLETE"
    assert result.provider == "deterministic-v1"
    assert result.evidence_gaps[0].code == "NO_TRACE_REFERENCE"
    assert result.evidence_gaps[0].required is False
    assert result.facts
    validate_citations(result, result.evidence)
    assert repo.saved == result
    assert trace.requested == []


def test_stale_health_is_partial_and_missing_health_is_insufficient():
    incident = _incident(RuleKey.SERVICE_NOT_READY, "payment-service", ScopeType.SERVICE)
    stale = _detection(FreshnessStatus.STALE, ProbeStatus.DOWN)
    partial = IncidentInvestigator(Settings(), FakeRepository(incident, stale), FakeOrderClient(), FakeTraceClient()).run(incident.id, NOW)
    assert partial is not None and partial.status == "PARTIAL"
    assert any(gap.code == "HEALTH_SOURCE_NOT_CURRENT" and gap.required for gap in partial.evidence_gaps)
    assert any(item.source_type == "SERVICE_HEALTH" for item in partial.evidence)

    unavailable = _detection(FreshnessStatus.UNAVAILABLE, ProbeStatus.UNKNOWN, include_snapshot=False)
    insufficient = IncidentInvestigator(Settings(), FakeRepository(incident, unavailable), FakeOrderClient(), FakeTraceClient()).run(incident.id, NOW)
    assert insufficient is not None and insufficient.status == "INSUFFICIENT"
    assert any(gap.code == "HEALTH_OBSERVATION_MISSING" and gap.required for gap in insufficient.evidence_gaps)
    assert not any(item.source_type == "SERVICE_HEALTH" for item in insufficient.evidence)


def test_order_investigation_uses_order_owned_recovery_evidence_without_trusting_trace_availability():
    incident = _incident(RuleKey.ORDER_RECOVERY_STALLED, str(ORDER_ID), ScopeType.ORDER, trace_id=TRACE_ID)
    case = OrderRecoveryCase(
        orderId=ORDER_ID,
        status=OrderStatus.COMPENSATION_REQUIRED,
        failureReason="PAYMENT_UNAVAILABLE",
        recoveryError=RecoveryError.COMPENSATION_RETRY_SCHEDULED,
        recoveryAttempts=3,
        nextRecoveryAt=NOW + timedelta(seconds=15),
        inventoryReleased=False,
        createdAt=NOW - timedelta(minutes=1),
        updatedAt=NOW,
        originTraceId=TRACE_ID,
    )
    order_freshness = SourceFreshness(
        source="order-attention", status=FreshnessStatus.CURRENT,
        attemptedAt=NOW, lastSuccessAt=NOW, itemCount=1,
    )
    order = FakeOrderClient(TerminalObservationCollection((case,), order_freshness, True))
    trace = FakeTraceClient(TraceFetch(None, SourceFreshness(
        source=f"tempo-trace-{TRACE_ID}", status=FreshnessStatus.UNAVAILABLE,
        attemptedAt=NOW, lastSuccessAt=None, itemCount=0, errorCode="TRACE_UPSTREAM_TIMEOUT",
    )))

    result = IncidentInvestigator(Settings(), FakeRepository(incident), order, trace).run(incident.id, NOW)

    assert result is not None and result.status == "PARTIAL"
    assert result.evidence[2].source_type == "ORDER_RECOVERY"
    order_evidence = next(item for item in result.evidence if item.source_type == "ORDER_RECOVERY")
    assert order_evidence.details.inventory_released is False
    assert order_evidence.details.recovery_error == RecoveryError.COMPENSATION_RETRY_SCHEDULED
    assert any(gap.code == "TRACE_SOURCE_UNAVAILABLE" and not gap.required for gap in result.evidence_gaps)
    assert trace.requested == [TRACE_ID]
    validate_citations(result, result.evidence)


def test_missing_order_observation_is_insufficient_not_a_clean_workflow():
    incident = _incident(RuleKey.ORDER_RECOVERY_STALLED, str(ORDER_ID), ScopeType.ORDER)
    order = FakeOrderClient(TerminalObservationCollection((), SourceFreshness(
        source="order-attention", status=FreshnessStatus.PARTIAL,
        attemptedAt=NOW, lastSuccessAt=NOW, itemCount=0, errorCode="ORDER_NOT_FOUND",
    ), True, (str(ORDER_ID),)))
    result = IncidentInvestigator(Settings(), FakeRepository(incident), order, FakeTraceClient()).run(incident.id, NOW)

    assert result is not None and result.status == "INSUFFICIENT"
    assert any(gap.code == "ORDER_OBSERVATION_MISSING" and gap.required for gap in result.evidence_gaps)
    assert not any(item.source_type == "ORDER_RECOVERY" for item in result.evidence)


@pytest.mark.parametrize(
    ("inventory_released", "should_be_terminal"),
    [(False, False), (True, True)],
)
def test_declined_payment_is_not_misreported_as_terminal_before_compensation(
    inventory_released: bool,
    should_be_terminal: bool,
):
    incident = _incident(RuleKey.ORDER_RECOVERY_STALLED, str(ORDER_ID), ScopeType.ORDER)
    case = OrderRecoveryCase(
        orderId=ORDER_ID,
        status=OrderStatus.FAILED,
        failureReason="PAYMENT_DECLINED",
        recoveryError=None,
        recoveryAttempts=0,
        nextRecoveryAt=NOW,
        inventoryReleased=inventory_released,
        createdAt=NOW - timedelta(minutes=1),
        updatedAt=NOW,
        originTraceId=None,
    )
    order = FakeOrderClient(TerminalObservationCollection((case,), SourceFreshness(
        source="order-attention", status=FreshnessStatus.CURRENT,
        attemptedAt=NOW, lastSuccessAt=NOW, itemCount=1,
    ), True))
    result = IncidentInvestigator(Settings(), FakeRepository(incident), order, FakeTraceClient()).run(incident.id, NOW)

    assert result is not None
    contradictory = any(gap.code == "CONTRADICTORY_ORDER_STATE" for gap in result.evidence_gaps)
    assert contradictory is should_be_terminal
    order_evidence = next(item for item in result.evidence if item.source_type == "ORDER_RECOVERY")
    assert order_evidence.details.inventory_released is inventory_released


def test_provider_output_with_uncited_evidence_is_rejected():
    class InvalidProvider:
        name = "deterministic-v1"

        def generate(self, _incident, _evidence, _gaps, _status):
            return InvestigationContent(
                summary="unfounded",
                uncertainty="uncertain",
                facts=[InvestigationClaim(claimId="fact", text="unsupported", evidenceIds=["missing"])],
                hypotheses=[],
                recommendedActions=[],
            )

    incident = _incident(RuleKey.SERVICE_NOT_READY, "payment-service", ScopeType.SERVICE)
    investigator = IncidentInvestigator(
        Settings(), FakeRepository(incident, _detection(FreshnessStatus.CURRENT, ProbeStatus.DOWN)),
        FakeOrderClient(), FakeTraceClient(), InvalidProvider(),
    )
    with pytest.raises(ValueError, match="outside the collected set"):
        investigator.run(incident.id, NOW)


def _incident(rule: RuleKey, reference: str, scope: ScopeType, trace_id: str | None = None) -> IncidentRecord:
    source_type = "HEALTH_PROBE" if rule == RuleKey.SERVICE_NOT_READY else "ORDER_RECOVERY"
    return IncidentRecord(
        id=PAYMENT_INCIDENT_ID,
        ruleKey=rule,
        ruleVersion=1,
        severity=Severity.HIGH,
        status="OPEN",
        fingerprint="f" * 64,
        scopeType=scope,
        sourceReference=reference,
        firstSeenAt=NOW - timedelta(seconds=10),
        lastSeenAt=NOW,
        lastEvaluatedAt=NOW,
        resolvedAt=None,
        occurrenceCount=2,
        summary="Synthetic unit-test incident from an isolated fixture.",
        evidence=[EvidenceReference(
            sourceType=source_type,
            sourceId=reference,
            observedAt=NOW,
            signalCode="HEALTH_NON_UP" if rule == RuleKey.SERVICE_NOT_READY else "RECOVERY_ACTION_REQUIRED",
            traceId=trace_id,
        )],
        originTraceId=trace_id,
        createdAt=NOW - timedelta(seconds=10),
        updatedAt=NOW,
    )


def _detection(
    freshness: FreshnessStatus,
    probe: ProbeStatus,
    *,
    include_snapshot: bool = True,
) -> DetectionStatusResponse:
    source = SourceFreshness(
        source="payment-service", status=freshness, attemptedAt=NOW,
        lastSuccessAt=NOW if freshness != FreshnessStatus.UNAVAILABLE else None,
        itemCount=1 if include_snapshot else 0,
    )
    services = [ServiceHealthSnapshot(
        serviceName="payment-service", status=probe,
        observedAt=NOW if include_snapshot else None,
        freshnessStatus=freshness, incidentOpen=True,
    )] if include_snapshot else []
    return DetectionStatusResponse(status="CURRENT" if freshness == FreshnessStatus.CURRENT else "PARTIAL",
                                   latestCycle=None, sources=[source], services=services)

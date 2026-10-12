from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import psycopg

from traceforge_investigation.clients import TerminalObservationCollection
from traceforge_investigation.config import Settings
from traceforge_investigation.investigation_clients import TraceFetch, TraceSpan, TraceSummary
from traceforge_investigation.investigation_models import InvestigationResult
from traceforge_investigation.main import create_app
from traceforge_investigation.models import (
    DecisionAction,
    DetectionStatusResponse,
    EvidenceReference,
    FreshnessStatus,
    HealthObservation,
    HealthRuleState,
    OrderFailureReason,
    OrderRecoveryCase,
    OrderStatus,
    ProbeStatus,
    RecoveryError,
    RuleFinding,
    RuleKey,
    ScopeType,
    ServiceHealthSnapshot,
    Severity,
    SourceFreshness,
)
from traceforge_investigation.rules import evaluate_health_observation, evaluate_order_recovery
from .helpers import NOW, TRACE_ID


DATASET_VERSION = "traceforge-investigation-phase7-v1"
SPAN_ID = "0123456789abcdef"


@dataclass(frozen=True)
class EvaluationScenario:
    name: str
    incident_id: UUID | None
    detection: DetectionStatusResponse | None = None
    order: TerminalObservationCollection | None = None
    trace: TraceFetch | None = None
    expected_http_status: int = 200
    expected_result_status: str | None = None
    expected_gaps: frozenset[str] = frozenset()
    expected_sources: tuple[tuple[str, str], ...] = ()
    known_root_cause: str | None = None


class ScenarioRepository:
    def __init__(self, repository):
        self.repository = repository
        self.current_detection: DetectionStatusResponse | None = None

    def detection_status(self, _now, _stale_after_seconds):
        if self.current_detection is None:
            raise AssertionError("scenario did not provide a detection snapshot")
        return self.current_detection

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)


class ScenarioOrderClient:
    def __init__(self):
        self.current: TerminalObservationCollection | None = None

    def restore_last_success(self, _last_success):
        pass

    def lookup_terminal(self, _order_ids, _now):
        if self.current is None:
            raise AssertionError("scenario did not provide an Order observation")
        return self.current

    def close(self):
        pass


class ScenarioTraceClient:
    def __init__(self):
        self.current: TraceFetch | None = None

    def fetch(self, trace_id, _now):
        if self.current is None:
            raise AssertionError(f"scenario did not provide a trace result for {trace_id}")
        return self.current

    def close(self):
        pass


def test_phase7_fixed_scenarios_evaluate_real_api_reports_and_persistence(incident_repository, monkeypatch):
    healthy_health_action, healthy_order_action, healthy_order_finding, healthy_order_incident_count = (
        _healthy_detector_actions(incident_repository)
    )
    assert healthy_health_action == DecisionAction.NONE
    assert healthy_order_action == DecisionAction.RESOLVE
    assert healthy_order_finding is None
    assert healthy_order_incident_count == 0
    scenarios = _build_scenarios(incident_repository)
    baseline = _incident_states(incident_repository)
    scenario_repository = ScenarioRepository(incident_repository)
    order_client = ScenarioOrderClient()
    trace_client = ScenarioTraceClient()
    monkeypatch.setattr(
        "traceforge_investigation.main.IncidentRepository",
        lambda _settings: scenario_repository,
    )
    app = create_app(incident_repository._settings, start_scheduler=False)
    app.state.investigator._order_client = order_client
    app.state.investigator._trace_client = trace_client

    async def execute_scenarios():
        measurements: list[tuple[EvaluationScenario, InvestigationResult | None, float]] = []
        repeated_latencies: list[float] = []
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for scenario in scenarios:
                    scenario_repository.current_detection = scenario.detection
                    order_client.current = scenario.order
                    trace_client.current = scenario.trace
                    incident_id = scenario.incident_id or UUID(int=999_999)
                    started = time.perf_counter()
                    response = await client.post(f"/api/v1/incidents/{incident_id}/investigations")
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    assert response.status_code == scenario.expected_http_status, scenario.name
                    if scenario.expected_http_status == 404:
                        assert response.json() == {"detail": {"code": "INCIDENT_NOT_FOUND"}}
                        assert incident_repository.get_investigation(incident_id) is None
                        measurements.append((scenario, None, elapsed_ms))
                        continue

                    result = InvestigationResult.model_validate(response.json())
                    assert result.status == scenario.expected_result_status, scenario.name
                    assert {gap.code for gap in result.evidence_gaps} == set(scenario.expected_gaps), scenario.name
                    assert {source.source: source.status.value for source in result.sources} == dict(scenario.expected_sources), scenario.name
                    assert _uncertainty_matches_status(result), (
                        f"{scenario.name}: status={result.status}, uncertainty={result.uncertainty!r}"
                    )
                    assert incident_repository.get_investigation(incident_id) == result, scenario.name
                    measurements.append((scenario, result, elapsed_ms))

                    if scenario.name == "service_not_ready_current":
                        first_id = result.investigation_id
                        repeat_started = time.perf_counter()
                        repeated = await client.post(f"/api/v1/incidents/{incident_id}/investigations")
                        repeat_elapsed_ms = (time.perf_counter() - repeat_started) * 1000
                        assert repeated.status_code == 200
                        latest = InvestigationResult.model_validate(repeated.json())
                        assert latest.investigation_id != first_id
                        assert incident_repository.get_investigation(incident_id) == latest
                        assert latest.incident_id == incident_id
                        assert repeat_elapsed_ms > 0
                        repeated_latencies.append(repeat_elapsed_ms)
        return measurements, repeated_latencies

    measurements, repeated_latencies = asyncio.run(execute_scenarios())
    results = [(scenario, result) for scenario, result, _ in measurements if result is not None]
    persisted_latencies = [elapsed for scenario, result, elapsed in measurements if result is not None] + repeated_latencies

    factual_claims = [claim for _, result in results for claim in result.facts]
    unsupported = [claim for _, result in results for claim in result.facts if not _fact_is_supported(claim, result)]
    all_claims = [
        claim
        for _, result in results
        for claim in (*result.facts, *result.hypotheses, *result.recommended_actions)
    ]
    evidence_by_result = {result.investigation_id: {item.evidence_id for item in result.evidence} for _, result in results}
    citation_count = sum(len(claim.evidence_ids) for claim in all_claims)
    valid_citations = sum(
        evidence_id in evidence_by_result[result.investigation_id]
        for _, result in results
        for claim in (*result.facts, *result.hypotheses, *result.recommended_actions)
        for evidence_id in claim.evidence_ids
    )

    determinate = [scenario for scenario, _ in results if scenario.known_root_cause is not None]
    # The result contract deliberately has no ranked-root-cause field. Unranked prose is not
    # promoted to a prediction; each determinate case is therefore an explicit abstention.
    root_cause_predictions: dict[str, list[str]] = {scenario.name: [] for scenario in determinate}
    top1_hits = sum(bool(root_cause_predictions[scenario.name]) and
                    root_cause_predictions[scenario.name][0] == scenario.known_root_cause for scenario in determinate)
    top3_hits = sum(scenario.known_root_cause in root_cause_predictions[scenario.name][:3] for scenario in determinate)
    sorted_latencies = sorted(persisted_latencies)

    report = {
        "datasetVersion": DATASET_VERSION,
        "scenarioCount": len(scenarios),
        "investigationRuns": len(results) + 1,
        "latestSnapshotsPersisted": len({result.incident_id for _, result in results}),
        "healthyDetectorNoIncident": {
            "freshUpProbe": healthy_health_action.value,
            "confirmedOrder": healthy_order_action.value,
            "confirmedOrderFinding": "NONE" if healthy_order_finding is None else "PRESENT",
            "confirmedOrderIncidentCount": healthy_order_incident_count,
            "unknownIncidentRequest": "404 INCIDENT_NOT_FOUND; no investigation row written",
        },
        "top1RootCauseAccuracy": top1_hits / len(determinate) if determinate else None,
        "top3RootCauseRecall": top3_hits / len(determinate) if determinate else None,
        "rootCauseScoredCases": len(determinate),
        "rootCauseAbstentions": len(determinate),
        "rootCauseMetricNote": "The API has no ranked-cause output; unranked hypotheses are not treated as root-cause predictions.",
        "citationValidity": valid_citations / citation_count if citation_count else None,
        "citationReferencesValid": valid_citations,
        "citationReferencesReviewed": citation_count,
        "unsupportedClaimRate": len(unsupported) / len(factual_claims) if factual_claims else None,
        "unsupportedFacts": len(unsupported),
        "factualClaimsReviewed": len(factual_claims),
        "factualReviewMethod": "Scenario oracle checks every factual claim against the cited typed evidence fields and exact deterministic wording.",
        "persistedApiLatencyMs": {
            "count": len(sorted_latencies),
            "p50": round(statistics.median(sorted_latencies), 3),
            "p95": round(_nearest_rank(sorted_latencies, 0.95), 3),
            "measurement": "HTTP POST through ASGI to completed PostgreSQL persistence; upstream dependencies are fixed in-process fault fixtures.",
        },
        "costPerInvestigation": None,
        "costNote": "Unavailable: deterministic-v1 makes no metered external provider call.",
        "scenarios": [
            {"name": "unknown_incident_request", "status": "NO_INCIDENT"},
            *[
                {"name": scenario.name, "status": result.status}
                for scenario, result in results
            ],
        ],
    }
    print("PHASE7_EVALUATION=" + json.dumps(report, sort_keys=True))

    assert not unsupported, [(claim.claim_id, claim.text) for claim in unsupported]
    assert citation_count > 0 and valid_citations == citation_count
    assert factual_claims and len(unsupported) == 0
    assert len(determinate) == 1 and top1_hits == 0 and top3_hits == 0
    assert sorted_latencies
    assert all(_hypotheses_are_qualified(result) for _, result in results)
    assert all(_actions_match_incident_lifecycle(result) for _, result in results)
    final_incidents = _incident_states(incident_repository)
    assert final_incidents == baseline
    with psycopg.connect(incident_repository._dsn) as connection:
        investigation_count = connection.execute(
            "SELECT count(*) FROM incident_service.investigations"
        ).fetchone()[0]
    assert investigation_count == len({result.incident_id for _, result in results})


def _build_scenarios(repository) -> list[EvaluationScenario]:
    payment = _open_incident(repository, RuleKey.SERVICE_NOT_READY, "payment-service", TRACE_ID)
    gateway = _open_incident(repository, RuleKey.SERVICE_NOT_READY, "api-gateway")
    inventory = _open_incident(repository, RuleKey.SERVICE_NOT_READY, "inventory-service")
    order_health = _open_incident(repository, RuleKey.SERVICE_NOT_READY, "order-service", TRACE_ID)

    payment_order_id = UUID("c5c9eafd-85aa-4211-94fb-c1e8b7997001")
    partial_order_id = UUID("c5c9eafd-85aa-4211-94fb-c1e8b7997002")
    unavailable_order_id = UUID("c5c9eafd-85aa-4211-94fb-c1e8b7997003")
    declined_order_id = UUID("c5c9eafd-85aa-4211-94fb-c1e8b7997004")
    terminal_order_id = UUID("c5c9eafd-85aa-4211-94fb-c1e8b7997005")
    payment_order = _open_incident(repository, RuleKey.ORDER_RECOVERY_STALLED, str(payment_order_id))
    partial_order = _open_incident(repository, RuleKey.ORDER_RECOVERY_STALLED, str(partial_order_id))
    unavailable_order = _open_incident(repository, RuleKey.ORDER_RECOVERY_STALLED, str(unavailable_order_id))
    declined_order = _open_incident(repository, RuleKey.ORDER_RECOVERY_STALLED, str(declined_order_id))
    terminal_order = _open_incident(repository, RuleKey.ORDER_RECOVERY_STALLED, str(terminal_order_id))
    repository.resolve(RuleKey.ORDER_RECOVERY_STALLED, ScopeType.ORDER, str(terminal_order_id), NOW + timedelta(seconds=1))

    current_payment = _detection("payment-service", FreshnessStatus.CURRENT, ProbeStatus.DOWN)
    stale_gateway = _detection("api-gateway", FreshnessStatus.STALE, ProbeStatus.DOWN, observed_at=NOW - timedelta(minutes=2))
    missing_inventory = _detection("inventory-service", FreshnessStatus.UNAVAILABLE, ProbeStatus.UNKNOWN, include_snapshot=False)
    current_order_health = _detection("order-service", FreshnessStatus.CURRENT, ProbeStatus.UP)

    paying_recovery = _recovery_case(payment_order_id, OrderStatus.COMPENSATION_REQUIRED,
                                     OrderFailureReason.PAYMENT_UNAVAILABLE,
                                     RecoveryError.COMPENSATION_RETRY_SCHEDULED, False)
    partial_recovery = _recovery_case(partial_order_id, OrderStatus.COMPENSATION_REQUIRED,
                                      OrderFailureReason.PAYMENT_UNAVAILABLE,
                                      RecoveryError.COMPENSATION_RETRY_SCHEDULED, False)
    declined_recovery = _recovery_case(declined_order_id, OrderStatus.FAILED,
                                       OrderFailureReason.PAYMENT_DECLINED, None, True)
    terminal_recovery = _recovery_case(terminal_order_id, OrderStatus.FAILED,
                                       OrderFailureReason.PAYMENT_DECLINED, None, True)

    return [
        EvaluationScenario("unknown_incident_request", None, expected_http_status=404),
        EvaluationScenario("service_not_ready_current", payment.id, current_payment,
                           trace=_successful_trace(), expected_result_status="COMPLETE",
                           expected_sources=(("payment-service", "CURRENT"), (f"tempo-trace-{TRACE_ID}", "CURRENT"))),
        EvaluationScenario("service_not_ready_stale", gateway.id, stale_gateway, expected_result_status="PARTIAL",
                           expected_gaps=frozenset({"HEALTH_SOURCE_NOT_CURRENT", "NO_TRACE_REFERENCE"}),
                           expected_sources=(("api-gateway", "STALE"),)),
        EvaluationScenario("service_observation_missing", inventory.id, missing_inventory,
                           expected_result_status="INSUFFICIENT",
                           expected_gaps=frozenset({"HEALTH_OBSERVATION_MISSING", "NO_TRACE_REFERENCE"}),
                           expected_sources=(("inventory-service", "UNAVAILABLE"),)),
        EvaluationScenario("optional_trace_unavailable", order_health.id, current_order_health,
                           trace=TraceFetch(None, _freshness(f"tempo-trace-{TRACE_ID}", FreshnessStatus.UNAVAILABLE,
                                                            error="TRACE_UPSTREAM_TIMEOUT")),
                           expected_result_status="PARTIAL", expected_gaps=frozenset({"TRACE_SOURCE_UNAVAILABLE"}),
                           expected_sources=(("order-service", "CURRENT"), (f"tempo-trace-{TRACE_ID}", "UNAVAILABLE"))),
        EvaluationScenario("payment_unavailable_recovery", payment_order.id, order=_order_observation(paying_recovery),
                           expected_result_status="COMPLETE", expected_gaps=frozenset({"NO_TRACE_REFERENCE"}),
                           expected_sources=(("order-attention", "CURRENT"),),
                           known_root_cause=OrderFailureReason.PAYMENT_UNAVAILABLE.value),
        EvaluationScenario("partial_order_source", partial_order.id,
                           order=_order_observation(partial_recovery, freshness=FreshnessStatus.PARTIAL,
                                                    error="INCOMPLETE_LOOKUP"),
                           expected_result_status="PARTIAL",
                           expected_gaps=frozenset({"ORDER_SOURCE_PARTIAL", "NO_TRACE_REFERENCE"}),
                           expected_sources=(("order-attention", "PARTIAL"),)),
        EvaluationScenario("order_source_unavailable", unavailable_order.id,
                           order=TerminalObservationCollection((), _freshness("order-attention", FreshnessStatus.UNAVAILABLE,
                                                                            error="UPSTREAM_TIMEOUT"), False),
                           expected_result_status="INSUFFICIENT",
                           expected_gaps=frozenset({"ORDER_SOURCE_UNAVAILABLE", "NO_TRACE_REFERENCE"}),
                           expected_sources=(("order-attention", "UNAVAILABLE"),)),
        EvaluationScenario("fully_compensated_decline_is_contradiction_not_finding",
                           declined_order.id, order=_order_observation(declined_recovery),
                           expected_result_status="PARTIAL",
                           expected_gaps=frozenset({"CONTRADICTORY_ORDER_STATE", "NO_TRACE_REFERENCE"}),
                           expected_sources=(("order-attention", "CURRENT"),)),
        EvaluationScenario("resolved_after_explicit_compensation", terminal_order.id,
                           order=_order_observation(terminal_recovery), expected_result_status="COMPLETE",
                           expected_gaps=frozenset({"NO_TRACE_REFERENCE"}),
                           expected_sources=(("order-attention", "CURRENT"),)),
    ]


def _healthy_detector_actions(repository):
    health = evaluate_health_observation(
        HealthObservation(
            serviceName="payment-service",
            status=ProbeStatus.UP,
            observedAt=NOW,
            signalCode="HEALTH_UP",
        ),
        HealthRuleState(serviceName="payment-service"),
        NOW,
    )
    terminal_order_id = UUID("c5c9eafd-85aa-4211-94fb-c1e8b7997010")
    terminal_order = _recovery_case(terminal_order_id,
                                    OrderStatus.CONFIRMED, None, None, False)
    order_decision = evaluate_order_recovery(terminal_order, NOW)
    resolved = repository.resolve(
        RuleKey.ORDER_RECOVERY_STALLED, ScopeType.ORDER, str(terminal_order_id), NOW
    )
    incidents = [*repository.list_incidents("OPEN", 100)[0], *repository.list_incidents("RESOLVED", 100)[0]]
    incident_count = sum(incident.source_reference == str(terminal_order_id) for incident in incidents)
    assert resolved is False
    return health.decision.action, order_decision.action, order_decision.finding, incident_count


def _open_incident(repository, rule: RuleKey, source: str, trace_id: str | None = None):
    order = rule == RuleKey.ORDER_RECOVERY_STALLED
    return repository.open_or_update(
        RuleFinding(
            ruleKey=rule,
            severity=Severity.HIGH,
            scopeType=ScopeType.ORDER if order else ScopeType.SERVICE,
            sourceReference=source,
            summary="Synthetic Phase 7 scenario fixture",
            evidence=EvidenceReference(
                sourceType="ORDER_RECOVERY" if order else "HEALTH_PROBE",
                sourceId=source,
                observedAt=NOW,
                signalCode="RECOVERY_ACTION_REQUIRED" if order else "HEALTH_NON_UP",
                traceId=trace_id,
            ),
        ),
        NOW,
    )


def _incident_states(repository):
    records = [*repository.list_incidents("OPEN", 100)[0], *repository.list_incidents("RESOLVED", 100)[0]]
    return {incident.id: (incident.status, incident.occurrence_count) for incident in records}


def _recovery_case(order_id, status, failure_reason, recovery_error, inventory_released):
    return OrderRecoveryCase(
        orderId=order_id,
        status=status,
        failureReason=failure_reason,
        recoveryError=recovery_error,
        recoveryAttempts=2,
        nextRecoveryAt=NOW + timedelta(seconds=30),
        inventoryReleased=inventory_released,
        createdAt=NOW - timedelta(minutes=1),
        updatedAt=NOW,
        originTraceId=None,
    )


def _order_observation(case, *, freshness=FreshnessStatus.CURRENT, error=None):
    return TerminalObservationCollection(
        (case,),
        _freshness("order-attention", freshness, item_count=1,
                   last_success=NOW if freshness != FreshnessStatus.UNAVAILABLE else None,
                   error=error),
        True,
    )


def _freshness(source, status, *, item_count=1, last_success=NOW, error=None):
    return SourceFreshness(
        source=source,
        status=status,
        attemptedAt=NOW,
        lastSuccessAt=last_success,
        itemCount=item_count,
        errorCode=error,
    )


def _successful_trace() -> TraceFetch:
    summary = TraceSummary(
        traceId=TRACE_ID,
        spans=[TraceSpan(
            service="payment-service",
            spanId=SPAN_ID,
            name="POST /api/v1/payments/authorize",
            startTime=NOW,
            endTime=NOW + timedelta(milliseconds=10),
            status="ERROR",
            httpMethod="POST",
            httpRoute="/api/v1/payments/authorize",
            httpStatusCode=503,
        )],
        truncated=False,
    )
    return TraceFetch(summary, _freshness(f"tempo-trace-{TRACE_ID}", FreshnessStatus.CURRENT))


def _detection(service, freshness, probe, *, observed_at=NOW, include_snapshot=True):
    source = _freshness(service, freshness, item_count=int(include_snapshot),
                        last_success=observed_at if include_snapshot else None)
    services = [ServiceHealthSnapshot(
        serviceName=service,
        status=probe,
        observedAt=observed_at if include_snapshot else None,
        freshnessStatus=freshness,
        incidentOpen=True,
    )] if include_snapshot else []
    return DetectionStatusResponse(
        status="CURRENT" if freshness == FreshnessStatus.CURRENT else "PARTIAL",
        latestCycle=None,
        sources=[source],
        services=services,
    )


def _fact_is_supported(claim, result: InvestigationResult) -> bool:
    evidence = {item.evidence_id: item for item in result.evidence}
    cited = [evidence[item_id] for item_id in claim.evidence_ids if item_id in evidence]
    if len(cited) != len(claim.evidence_ids):
        return False
    if claim.claim_id == "fact-incident":
        item = next((candidate for candidate in cited if candidate.source_type == "INCIDENT"), None)
        if item is None:
            return False
        details = item.details
        return all(value in claim.text for value in (details.rule_key.value, details.incident_status,
                                                      str(details.occurrence_count)))
    if claim.claim_id.startswith("fact-signal-"):
        return len(cited) == 1 and cited[0].source_type == "INCIDENT_SIGNAL" and claim.text == cited[0].summary
    if claim.claim_id == "fact-health":
        item = next((candidate for candidate in cited if candidate.source_type == "SERVICE_HEALTH"), None)
        if item is None or item.details.service_name is None:
            return False
        freshness = item.freshness_status.value if item.freshness_status else "UNAVAILABLE"
        expected = (f"The latest persisted readiness probe for {item.details.service_name} is "
                    f"{item.details.probe_status.value}; its recorded freshness is {freshness}.")
        return claim.text == expected
    if claim.claim_id == "fact-order":
        item = next((candidate for candidate in cited if candidate.source_type == "ORDER_RECOVERY"), None)
        if item is None:
            return False
        details = item.details
        code = details.recovery_error.value if details.recovery_error else (
            details.failure_reason.value if details.failure_reason else "none recorded"
        )
        expected = (f"Order Service reports workflow status {details.order_status.value}, recovery/failure code {code}, "
                    f"and inventoryReleased={str(details.inventory_released).lower()}.")
        return claim.text == expected
    if claim.claim_id.startswith("fact-trace-"):
        item = next((candidate for candidate in cited if candidate.source_type == "TRACE_SPAN"), None)
        if item is None or item.details.trace_id is None or item.details.span_status is None:
            return False
        trace_spans = [candidate for candidate in result.evidence
                       if candidate.source_type == "TRACE_SPAN" and candidate.details.trace_id == item.details.trace_id]
        expected = (f"The sanitized trace summary for {item.details.trace_id} contains {len(trace_spans)} included span(s); "
                    f"the cited span status is {item.details.span_status}.")
        return len(cited) == 1 and claim.text == expected
    return False


def _hypotheses_are_qualified(result: InvestigationResult) -> bool:
    for claim in result.hypotheses:
        if claim.claim_id == "hypothesis-health" and "does not establish its underlying cause" not in claim.text:
            return False
        if claim.claim_id == "hypothesis-order" and "does not identify the downstream root cause" not in claim.text:
            return False
        if claim.claim_id not in {"hypothesis-health", "hypothesis-recovery", "hypothesis-order"}:
            return False
    return True


def _actions_match_incident_lifecycle(result: InvestigationResult) -> bool:
    incident = next((item for item in result.evidence if item.source_type == "INCIDENT"), None)
    if incident is None:
        return False
    for action in result.recommended_actions:
        if action.claim_id != "action-order-reconcile":
            continue
        if incident.details.incident_status == "RESOLVED":
            if "incident record is RESOLVED" not in action.text or "open incident" in action.text:
                return False
        elif incident.details.incident_status == "OPEN" and "open incident" not in action.text:
            return False
    return True


def _uncertainty_matches_status(result: InvestigationResult) -> bool:
    expected = {
        "INSUFFICIENT": "Required owning-service evidence could not be confirmed",
        "PARTIAL": "Some required or referenced evidence is incomplete, stale, contradictory, or unavailable",
    }
    if result.status in expected:
        return expected[result.status] in result.uncertainty
    if any(gap.code == "NO_TRACE_REFERENCE" for gap in result.evidence_gaps):
        return "no trace reference was available" in result.uncertainty and "root cause is not proven" in result.uncertainty
    return (
        "Required owning-service evidence was current when collected" in result.uncertainty
        and "does not prove root cause" in result.uncertainty
    )


def _nearest_rank(values: list[float], quantile: float) -> float:
    return values[max(0, min(len(values) - 1, int((len(values) * quantile) + 0.999999) - 1))]

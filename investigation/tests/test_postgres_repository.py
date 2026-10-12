from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import psycopg

from traceforge_investigation.clients import OrderRecoveryCollection
from traceforge_investigation.engine import InvestigationEngine
from traceforge_investigation.models import (
    DecisionAction,
    EvidenceReference,
    FreshnessStatus,
    HealthObservation,
    HealthRuleState,
    OrderRecoveryCase,
    ProbeResult,
    ProbeStatus,
    RuleFinding,
    RuleKey,
    ScopeType,
    Severity,
    SourceFreshness,
)
from traceforge_investigation.rules import HealthRulePolicy, OrderRecoveryPolicy, incident_fingerprint
from .helpers import NOW, TRACE_ID, case_payload


def finding(source_reference: str, observed_at=NOW, trace_id: str | None = TRACE_ID) -> RuleFinding:
    return RuleFinding(
        ruleKey=RuleKey.ORDER_RECOVERY_STALLED,
        severity=Severity.HIGH,
        scopeType=ScopeType.ORDER,
        sourceReference=source_reference,
        summary="Order recovery requires attention",
        evidence=EvidenceReference(
            sourceType="ORDER_RECOVERY",
            sourceId=source_reference,
            observedAt=observed_at,
            signalCode="RECOVERY_ACTION_REQUIRED",
            traceId=trace_id,
        ),
    )


def test_migration_creates_only_owned_schema_and_expected_indexes(incident_repository):
    with psycopg.connect(incident_repository._dsn, row_factory=psycopg.rows.dict_row) as connection:
        schema = connection.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'incident_service'"
        ).fetchone()
        tables = {
            row["table_name"]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'incident_service'"
            ).fetchall()
        }
        indexes = {
            row["indexname"]
            for row in connection.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'incident_service'"
            ).fetchall()
        }
    assert schema is not None
    assert {"schema_migrations", "incidents", "health_rule_state", "detection_cycles", "detection_source_state"} <= tables
    assert "incidents_one_open_fingerprint_uq" in indexes
    assert incident_repository.applied_migrations() == ["0001", "0002"]


def test_open_incident_persists_safe_evidence_and_optional_trace_id(incident_repository):
    order_id = "c2ac9678-6e03-4b22-a990-2cd9ed90effa"
    saved = incident_repository.open_or_update(finding(order_id))
    loaded = incident_repository.find_by_id(saved.id)
    assert loaded is not None
    assert loaded.status == "OPEN"
    assert loaded.rule_key == RuleKey.ORDER_RECOVERY_STALLED
    assert loaded.evidence[0].trace_id == TRACE_ID
    assert loaded.origin_trace_id == TRACE_ID
    assert loaded.evidence[0].source_id == order_id

    no_trace = incident_repository.open_or_update(finding("c2ac9678-6e03-4b22-a990-2cd9ed90effb", trace_id=None))
    assert no_trace.origin_trace_id is None
    assert no_trace.evidence[0].trace_id is None


def test_repeated_observation_updates_one_open_episode(incident_repository):
    reference = "9dc2e6d9-9e35-4a44-9d42-10fe02635cde"
    first = incident_repository.open_or_update(finding(reference))
    second = incident_repository.open_or_update(finding(reference, NOW + timedelta(seconds=5)))
    assert first.id == second.id
    assert second.occurrence_count == 2
    assert incident_repository.count_open(second.fingerprint) == 1


def test_concurrent_upserts_enforce_one_open_episode_and_count_observations(incident_repository):
    reference = "82999844-2b90-4b12-9817-df12a8bdf9b6"
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: incident_repository.open_or_update(finding(reference)), range(24)))
    assert len({record.id for record in records}) == 1
    final = incident_repository.find_open(RuleKey.ORDER_RECOVERY_STALLED, ScopeType.ORDER, reference)
    assert final is not None
    assert final.occurrence_count == 24
    assert incident_repository.count_open(final.fingerprint) == 1
    assert len(final.evidence) <= 20


def test_resolution_keeps_history_and_recurrence_creates_new_episode(incident_repository):
    reference = "6ff0dfea-9cba-4e1e-a378-67a9e6731667"
    first = incident_repository.open_or_update(finding(reference))
    resolved = incident_repository.resolve(
        RuleKey.ORDER_RECOVERY_STALLED,
        ScopeType.ORDER,
        reference,
        NOW + timedelta(minutes=1),
    )
    assert resolved
    historical = incident_repository.find_by_id(first.id)
    assert historical is not None
    assert historical.status == "RESOLVED"
    assert historical.resolved_at == NOW + timedelta(minutes=1)
    assert incident_repository.find_open(RuleKey.ORDER_RECOVERY_STALLED, ScopeType.ORDER, reference) is None

    recurrence = incident_repository.open_or_update(finding(reference, NOW + timedelta(minutes=2)))
    assert recurrence.id != first.id
    assert recurrence.occurrence_count == 1
    assert recurrence.status == "OPEN"


def test_health_rule_state_and_incident_are_written_atomically(incident_repository, monkeypatch):
    observation1 = HealthObservation(
        serviceName="payment-service", status=ProbeStatus.DOWN, observedAt=NOW, httpStatus=503, signalCode="HTTP_NON_200"
    )
    observation2 = observation1.model_copy(update={"observed_at": NOW + timedelta(seconds=1)})
    incident_repository.apply_health_observation(observation1, NOW, HealthRulePolicy())
    before = incident_repository.health_state("payment-service")
    assert before is not None and before.failure_streak == 1

    def fail_after_state_update(*args, **kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(incident_repository, "_upsert_open_incident", fail_after_state_update)
    try:
        incident_repository.apply_health_observation(observation2, NOW + timedelta(seconds=1), HealthRulePolicy())
        raise AssertionError("expected transaction failure")
    except RuntimeError as error:
        assert str(error) == "simulated persistence failure"

    after = incident_repository.health_state("payment-service")
    assert after == before
    fingerprint = incident_fingerprint(RuleKey.SERVICE_NOT_READY, ScopeType.SERVICE, "payment-service")
    assert incident_repository.count_open(fingerprint) == 0


def test_health_streak_state_persists_and_incident_resolves_after_two_up_probes(incident_repository):
    policy = HealthRulePolicy(failure_threshold=2, recovery_threshold=2)
    service = "inventory-service"

    def observation(status, seconds):
        return HealthObservation(
            serviceName=service,
            status=status,
            observedAt=NOW + timedelta(seconds=seconds),
            httpStatus=200 if status.value == "UP" else 503,
            signalCode="HEALTH_UP" if status.value == "UP" else "HTTP_NON_200",
        )

    first_failure = incident_repository.apply_health_observation(
        observation(ProbeStatus.DOWN, 0),
        NOW,
        policy,
    )
    assert first_failure.decision.action == DecisionAction.NONE
    assert incident_repository.health_state(service).failure_streak == 1

    second_failure = incident_repository.apply_health_observation(
        observation(ProbeStatus.DOWN, 1),
        NOW + timedelta(seconds=1),
        policy,
    )
    assert second_failure.decision.action == DecisionAction.OPEN_OR_UPDATE
    assert incident_repository.find_open(RuleKey.SERVICE_NOT_READY, ScopeType.SERVICE, service) is not None

    first_up = incident_repository.apply_health_observation(
        observation(ProbeStatus.UP, 2),
        NOW + timedelta(seconds=2),
        policy,
    )
    assert first_up.decision.action == DecisionAction.NONE
    second_up = incident_repository.apply_health_observation(
        observation(ProbeStatus.UP, 3),
        NOW + timedelta(seconds=3),
        policy,
    )
    assert second_up.decision.action == DecisionAction.RESOLVE
    assert incident_repository.find_open(RuleKey.SERVICE_NOT_READY, ScopeType.SERVICE, service) is None


def test_terminal_compensated_order_resolves_but_open_episode_is_retained(incident_repository):
    order_id = UUID("4761bef9-2081-49e9-9c89-1284c402d18f")
    existing = incident_repository.open_or_update(finding(str(order_id)))
    terminal = OrderRecoveryCase.model_validate(
        case_payload(
            order_id,
            status="FAILED",
            failure_reason="PAYMENT_DECLINED",
            recovery_error=None,
            inventory_released=True,
            updated_at=NOW + timedelta(minutes=1),
        )
    )
    decision = incident_repository.apply_order_case(
        terminal,
        NOW + timedelta(minutes=1),
        OrderRecoveryPolicy(),
    )
    assert decision.action == DecisionAction.RESOLVE
    history = incident_repository.find_by_id(existing.id)
    assert history is not None and history.status == "RESOLVED"


def test_failed_sources_do_not_resolve_existing_incident(incident_repository):
    order_id = "303fa7b6-1be4-48f5-9888-0a588c7af834"
    existing = incident_repository.open_or_update(finding(order_id))

    class UnknownHealthClient:
        def probe_all(self, now):
            return [
                ProbeResult(
                    observation=HealthObservation(
                        serviceName="api-gateway",
                        status=ProbeStatus.UNKNOWN,
                        observedAt=now,
                        signalCode="MALFORMED_HEALTH_RESPONSE",
                    ),
                    freshness=SourceFreshness(
                        source="api-gateway", status=FreshnessStatus.PARTIAL, attemptedAt=now, errorCode="MALFORMED_HEALTH_RESPONSE"
                    ),
                )
            ]

        def close(self):
            pass

    class FailedOrderClient:
        def collect(self, now):
            return OrderRecoveryCollection(
                cases=(),
                freshness=SourceFreshness(
                    source="order-attention",
                    status=FreshnessStatus.UNAVAILABLE,
                    attemptedAt=now,
                    errorCode="UPSTREAM_TIMEOUT",
                ),
                complete=False,
                page_count=0,
            )

        def close(self):
            pass

    from traceforge_investigation.config import Settings

    engine = InvestigationEngine(Settings(), incident_repository, UnknownHealthClient(), FailedOrderClient())
    result = engine.run_once(NOW)
    assert result.order_source.status == FreshnessStatus.UNAVAILABLE
    assert result.incidents_resolved == 0
    persisted = incident_repository.find_by_id(existing.id)
    assert persisted is not None and persisted.status == "OPEN"


def test_detection_cycle_and_source_freshness_persist_and_become_stale(incident_repository):
    from uuid import uuid4

    cycle_id = uuid4()
    source = SourceFreshness(
        source="order-attention", status=FreshnessStatus.CURRENT, attemptedAt=NOW,
        lastSuccessAt=NOW, itemCount=4,
    )
    incident_repository.begin_cycle(cycle_id, NOW)
    incident_repository.finish_cycle(cycle_id, NOW + timedelta(seconds=1), "COMPLETE", 2, 1, [source])

    status_now = incident_repository.detection_status(NOW + timedelta(seconds=2), 30)
    assert status_now.status == "CURRENT"
    assert status_now.latest_cycle is not None
    assert status_now.latest_cycle.cycle_id == cycle_id
    assert status_now.latest_cycle.findings_opened_or_updated == 2
    assert status_now.sources[0].last_success_at == NOW

    stale = incident_repository.detection_status(NOW + timedelta(seconds=31), 30)
    assert stale.status == "STALE"
    assert stale.sources[0].status == FreshnessStatus.STALE


def test_postgres_advisory_lock_prevents_overlapping_detector_replicas(incident_repository):
    with incident_repository.scheduler_lock() as acquired:
        assert acquired
        with incident_repository.scheduler_lock() as second_acquired:
            assert not second_acquired

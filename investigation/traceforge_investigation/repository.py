from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import Settings
from .models import (
    DecisionAction,
    HealthEvaluation,
    HealthObservation,
    HealthRuleState,
    ProbeStatus,
    ServiceHealthSnapshot,
    IncidentRecord,
    DetectionCycleRecord,
    DetectionStatusResponse,
    FreshnessStatus,
    OrderRecoveryCase,
    RuleDecision,
    RuleFinding,
    RuleKey,
    ScopeType,
    SourceFreshness,
)
from .rules import HealthRulePolicy, OrderRecoveryPolicy, evaluate_health_observation, evaluate_order_recovery, incident_fingerprint


_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_SCHEMA_LOCK_ID = 7_341_027_184
_HEALTH_SERVICES = ("api-gateway", "order-service", "inventory-service", "payment-service")


class IncidentRepository:
    """All SQL is qualified to the service-owned incident_service schema."""

    def __init__(self, settings: Settings, migrations_dir: Path | None = None) -> None:
        self._settings = settings
        self._dsn = make_conninfo(
            host=settings.database_host,
            port=settings.database_port,
            dbname=settings.database_name,
            user=settings.database_user,
            password=settings.database_password,
            connect_timeout=3,
            options="-c statement_timeout=5000",
        )
        self._migrations_dir = migrations_dir or Path(__file__).resolve().parents[1] / "migrations"

    def migrate(self) -> None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
                connection.execute("CREATE SCHEMA IF NOT EXISTS incident_service")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS incident_service.schema_migrations ("
                    "version VARCHAR(32) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                applied = {
                    row["version"]
                    for row in connection.execute(
                        "SELECT version FROM incident_service.schema_migrations"
                    ).fetchall()
                }
                for path in sorted(self._migrations_dir.glob("*.sql")):
                    match = _MIGRATION_NAME.fullmatch(path.name)
                    if match is None:
                        raise RuntimeError("invalid incident migration filename")
                    version = match.group(1)
                    if version in applied:
                        continue
                    sql = path.read_text(encoding="utf-8")
                    connection.execute(sql, prepare=False)
                    connection.execute(
                        "INSERT INTO incident_service.schema_migrations(version) VALUES (%s)",
                        (version,),
                    )

    def check_ready(self) -> bool:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM incident_service.schema_migrations) AS migrated"
            ).fetchone()
            return bool(row["migrated"])

    def applied_migrations(self) -> list[str]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            return [
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM incident_service.schema_migrations ORDER BY version"
                ).fetchall()
            ]

    @contextmanager
    def scheduler_lock(self):
        """A PostgreSQL session lock keeps only one detector replica evaluating at a time."""
        with psycopg.connect(self._dsn, autocommit=True) as connection:
            acquired = bool(connection.execute("SELECT pg_try_advisory_lock(%s)", (_SCHEMA_LOCK_ID + 1,)).fetchone()[0])
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_LOCK_ID + 1,))

    def last_successful_source_times(self) -> dict[str, datetime]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT source, last_success_at FROM incident_service.detection_source_state "
                "WHERE last_success_at IS NOT NULL"
            ).fetchall()
            return {row["source"]: row["last_success_at"] for row in rows}

    def begin_cycle(self, cycle_id: uuid.UUID, started_at: datetime) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                "INSERT INTO incident_service.detection_cycles(cycle_id, started_at, status) "
                "VALUES (%s, %s, 'RUNNING')",
                (cycle_id, started_at),
            )

    def finish_cycle(
        self,
        cycle_id: uuid.UUID,
        completed_at: datetime,
        status: str,
        findings_opened_or_updated: int,
        incidents_resolved: int,
        sources: list[SourceFreshness],
    ) -> None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute(
                    "UPDATE incident_service.detection_cycles SET completed_at = %s, status = %s, "
                    "findings_opened_or_updated = %s, incidents_resolved = %s WHERE cycle_id = %s",
                    (completed_at, status, findings_opened_or_updated, incidents_resolved, cycle_id),
                )
                for source in sources:
                    connection.execute(
                        "INSERT INTO incident_service.detection_source_state AS current_state "
                        "(source, status, attempted_at, last_success_at, item_count, error_code, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source) DO UPDATE SET "
                        "status = EXCLUDED.status, attempted_at = EXCLUDED.attempted_at, "
                        "last_success_at = COALESCE(EXCLUDED.last_success_at, current_state.last_success_at), "
                        "item_count = EXCLUDED.item_count, error_code = EXCLUDED.error_code, updated_at = EXCLUDED.updated_at",
                        (source.source, source.status.value, source.attempted_at, source.last_success_at,
                         source.item_count, source.error_code, completed_at),
                    )

    def fail_cycle(self, cycle_id: uuid.UUID, completed_at: datetime, failure_code: str) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                "UPDATE incident_service.detection_cycles SET completed_at = %s, status = 'FAILED', failure_code = %s "
                "WHERE cycle_id = %s",
                (completed_at, failure_code, cycle_id),
            )

    def open_order_incident_ids(self, limit: int) -> list[uuid.UUID]:
        with psycopg.connect(self._dsn) as connection:
            rows = connection.execute(
                "SELECT source_reference FROM incident_service.incidents WHERE status = 'OPEN' "
                "AND rule_key = 'ORDER_RECOVERY_STALLED' AND scope_type = 'ORDER' "
                "ORDER BY source_reference LIMIT %s",
                (limit,),
            ).fetchall()
            return [uuid.UUID(row[0]) for row in rows]

    def list_incidents(
        self,
        status_filter: str,
        limit: int,
        cursor_seen_at: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
    ) -> tuple[list[IncidentRecord], bool]:
        if (cursor_seen_at is None) != (cursor_id is None):
            raise ValueError("both incident cursor values are required")
        sql = "SELECT * FROM incident_service.incidents WHERE status = %s"
        parameters: list[Any] = [status_filter]
        if cursor_seen_at is not None:
            sql += " AND (last_seen_at < %s OR (last_seen_at = %s AND id < %s))"
            parameters.extend([cursor_seen_at, cursor_seen_at, cursor_id])
        sql += " ORDER BY last_seen_at DESC, id DESC LIMIT %s"
        parameters.append(limit + 1)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        has_more = len(rows) > limit
        return [self._record(row) for row in rows[:limit]], has_more

    def detection_status(self, now: datetime, stale_after_seconds: int) -> DetectionStatusResponse:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            cycle = connection.execute(
                "SELECT cycle_id, started_at, completed_at, status, findings_opened_or_updated, "
                "incidents_resolved, failure_code FROM incident_service.detection_cycles "
                "ORDER BY started_at DESC, cycle_id DESC LIMIT 1"
            ).fetchone()
            source_rows = connection.execute(
                "SELECT source, status, attempted_at, last_success_at, item_count, error_code "
                "FROM incident_service.detection_source_state ORDER BY source"
            ).fetchall()
            health_rows = connection.execute(
                "SELECT service_name, last_status, last_observed_at, incident_open "
                "FROM incident_service.health_rule_state ORDER BY service_name"
            ).fetchall()
        sources = []
        for row in source_rows:
            source = SourceFreshness.model_validate(row)
            if source.last_success_at is not None and now - source.last_success_at > timedelta(seconds=stale_after_seconds):
                source = source.model_copy(update={"status": FreshnessStatus.STALE})
            sources.append(source)
        if cycle is None:
            status = "NOT_RUN"
            latest = None
        else:
            latest = DetectionCycleRecord.model_validate(cycle)
            cycle_age = now - cycle["started_at"]
            if cycle["status"] == "FAILED":
                status = "UNAVAILABLE"
            elif cycle["status"] == "RUNNING" and cycle_age > timedelta(seconds=stale_after_seconds):
                status = "STALE"
            elif cycle["status"] == "RUNNING" or cycle["status"] == "PARTIAL":
                status = "PARTIAL"
            elif cycle_age > timedelta(seconds=stale_after_seconds):
                status = "STALE"
            elif any(source.status == FreshnessStatus.UNAVAILABLE for source in sources):
                status = "UNAVAILABLE"
            elif any(source.status in {FreshnessStatus.STALE, FreshnessStatus.PARTIAL} for source in sources):
                status = "STALE" if any(source.status == FreshnessStatus.STALE for source in sources) else "PARTIAL"
            else:
                status = "CURRENT"
        source_status = {source.source: source.status for source in sources}
        health_by_service = {row["service_name"]: row for row in health_rows}
        services = [
            ServiceHealthSnapshot(
                serviceName=service_name,
                status=(
                    ProbeStatus(health_by_service[service_name]["last_status"])
                    if service_name in health_by_service and health_by_service[service_name]["last_status"]
                    else ProbeStatus.UNKNOWN
                ),
                observedAt=(health_by_service[service_name]["last_observed_at"] if service_name in health_by_service else None),
                freshnessStatus=source_status.get(service_name, FreshnessStatus.UNAVAILABLE),
                incidentOpen=(health_by_service[service_name]["incident_open"] if service_name in health_by_service else False),
            )
            for service_name in _HEALTH_SERVICES
        ]
        return DetectionStatusResponse(status=status, latestCycle=latest, sources=sources, services=services)

    def apply_health_observation(
        self,
        observation: HealthObservation,
        now: datetime,
        policy: HealthRulePolicy,
    ) -> HealthEvaluation:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute(
                    "INSERT INTO incident_service.health_rule_state(service_name) VALUES (%s) "
                    "ON CONFLICT (service_name) DO NOTHING",
                    (observation.service_name,),
                )
                row = connection.execute(
                    "SELECT service_name, failure_streak, success_streak, last_status, last_observed_at, incident_open "
                    "FROM incident_service.health_rule_state WHERE service_name = %s FOR UPDATE",
                    (observation.service_name,),
                ).fetchone()
                state = HealthRuleState(
                    serviceName=row["service_name"],
                    failureStreak=row["failure_streak"],
                    successStreak=row["success_streak"],
                    lastStatus=row["last_status"],
                    lastObservedAt=row["last_observed_at"],
                    incidentOpen=row["incident_open"],
                )
                evaluation = evaluate_health_observation(observation, state, now, policy)
                next_state = evaluation.state
                connection.execute(
                    "UPDATE incident_service.health_rule_state SET failure_streak = %s, success_streak = %s, "
                    "last_status = %s, last_observed_at = %s, incident_open = %s, updated_at = %s "
                    "WHERE service_name = %s",
                    (
                        next_state.failure_streak,
                        next_state.success_streak,
                        next_state.last_status.value if next_state.last_status else None,
                        next_state.last_observed_at,
                        next_state.incident_open,
                        now.astimezone(timezone.utc),
                        observation.service_name,
                    ),
                )
                self._apply_decision(connection, evaluation.decision, now)
                return evaluation

    def apply_order_case(
        self,
        case: OrderRecoveryCase,
        now: datetime,
        policy: OrderRecoveryPolicy,
    ) -> RuleDecision:
        decision = evaluate_order_recovery(case, now, policy)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                self._apply_decision(connection, decision, now)
        return decision

    def open_or_update(self, finding: RuleFinding, observed_at: datetime | None = None) -> IncidentRecord:
        timestamp = (observed_at or finding.evidence.observed_at).astimezone(timezone.utc)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                return self._upsert_open_incident(connection, finding, timestamp)

    def resolve(self, rule_key: RuleKey, scope_type: ScopeType, source_reference: str, resolved_at: datetime) -> bool:
        fingerprint = incident_fingerprint(rule_key, scope_type, source_reference)
        with psycopg.connect(self._dsn) as connection:
            with connection.transaction():
                cursor = connection.execute(
                    "UPDATE incident_service.incidents SET status = 'RESOLVED', resolved_at = %s, "
                    "last_evaluated_at = %s, updated_at = %s WHERE fingerprint = %s AND status = 'OPEN'",
                    (resolved_at, resolved_at, resolved_at, fingerprint),
                )
                return cursor.rowcount == 1

    def find_open(self, rule_key: RuleKey, scope_type: ScopeType, source_reference: str) -> IncidentRecord | None:
        fingerprint = incident_fingerprint(rule_key, scope_type, source_reference)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM incident_service.incidents WHERE fingerprint = %s AND status = 'OPEN'",
                (fingerprint,),
            ).fetchone()
            return self._record(row) if row else None

    def find_by_id(self, incident_id: uuid.UUID) -> IncidentRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM incident_service.incidents WHERE id = %s", (incident_id,)
            ).fetchone()
            return self._record(row) if row else None

    def count_open(self, fingerprint: str) -> int:
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                "SELECT count(*) FROM incident_service.incidents WHERE fingerprint = %s AND status = 'OPEN'",
                (fingerprint,),
            ).fetchone()
            return int(row[0])

    def health_state(self, service_name: str) -> HealthRuleState | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT service_name, failure_streak, success_streak, last_status, last_observed_at, incident_open "
                "FROM incident_service.health_rule_state WHERE service_name = %s",
                (service_name,),
            ).fetchone()
            if row is None:
                return None
            return HealthRuleState(
                serviceName=row["service_name"],
                failureStreak=row["failure_streak"],
                successStreak=row["success_streak"],
                lastStatus=row["last_status"],
                lastObservedAt=row["last_observed_at"],
                incidentOpen=row["incident_open"],
            )

    def _apply_decision(self, connection: psycopg.Connection[Any], decision: RuleDecision, now: datetime) -> None:
        if decision.action == DecisionAction.OPEN_OR_UPDATE:
            if decision.finding is None:
                raise ValueError("open decision has no finding")
            self._upsert_open_incident(connection, decision.finding, now)
        elif decision.action == DecisionAction.RESOLVE:
            if decision.resolved_rule is None or decision.resolved_scope_type is None or not decision.resolved_source_reference:
                raise ValueError("resolution decision is incomplete")
            fingerprint = incident_fingerprint(
                decision.resolved_rule,
                decision.resolved_scope_type,
                decision.resolved_source_reference,
            )
            connection.execute(
                "UPDATE incident_service.incidents SET status = 'RESOLVED', resolved_at = %s, "
                "last_evaluated_at = %s, updated_at = %s WHERE fingerprint = %s AND status = 'OPEN'",
                (now, now, now, fingerprint),
            )

    def _upsert_open_incident(
        self,
        connection: psycopg.Connection[Any],
        finding: RuleFinding,
        observed_at: datetime,
    ) -> IncidentRecord:
        fingerprint = incident_fingerprint(finding.rule_key, finding.scope_type, finding.source_reference)
        evidence = finding.evidence.model_dump(mode="json", by_alias=False)
        row = connection.execute(
            "INSERT INTO incident_service.incidents AS current_incident ("
            "id, rule_key, rule_version, severity, status, fingerprint, scope_type, source_reference, "
            "first_seen_at, last_seen_at, last_evaluated_at, resolved_at, occurrence_count, summary, evidence, "
            "origin_trace_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'OPEN', %s, %s, %s, %s, %s, %s, NULL, 1, %s, %s, %s, %s, %s) "
            "ON CONFLICT (fingerprint) WHERE status = 'OPEN' DO UPDATE SET "
            "severity = EXCLUDED.severity, last_seen_at = GREATEST(current_incident.last_seen_at, EXCLUDED.last_seen_at), "
            "last_evaluated_at = EXCLUDED.last_evaluated_at, occurrence_count = current_incident.occurrence_count + 1, "
            "summary = EXCLUDED.summary, origin_trace_id = COALESCE(EXCLUDED.origin_trace_id, current_incident.origin_trace_id), "
            "evidence = (SELECT COALESCE(jsonb_agg(recent.item ORDER BY recent.item->>'observed_at'), '[]'::jsonb) "
            "FROM (SELECT item FROM jsonb_array_elements(current_incident.evidence || EXCLUDED.evidence) AS evidence(item) "
            "ORDER BY item->>'observed_at' DESC LIMIT 20) AS recent), updated_at = EXCLUDED.updated_at "
            "RETURNING *",
            (
                uuid.uuid4(),
                finding.rule_key.value,
                finding.rule_version,
                finding.severity.value,
                fingerprint,
                finding.scope_type.value,
                finding.source_reference,
                observed_at,
                observed_at,
                observed_at,
                finding.summary,
                Jsonb([evidence]),
                finding.evidence.trace_id,
                observed_at,
                observed_at,
            ),
        ).fetchone()
        return self._record(row)

    @staticmethod
    def _record(row: dict[str, Any]) -> IncidentRecord:
        # Psycopg returns JSONB as a list of safe structured evidence references.
        return IncidentRecord.model_validate(row)

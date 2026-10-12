from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

import psycopg

from .clients import HealthProbeClient, OrderAttentionClient
from .config import Settings
from .models import DecisionAction, DetectionCycleResult, FreshnessStatus
from .repository import IncidentRepository
from .rules import HealthRulePolicy, OrderRecoveryPolicy

logger = logging.getLogger("traceforge.investigation")


class InvestigationEngine:
    """One serialized collection/evaluation cycle; all external work is bounded by client settings."""

    def __init__(
        self,
        settings: Settings,
        repository: IncidentRepository,
        health_client: HealthProbeClient,
        order_client: OrderAttentionClient,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._health_client = health_client
        self._order_client = order_client

    def run_once(self, now: datetime | None = None) -> DetectionCycleResult | None:
        with self._repository.scheduler_lock() as acquired:
            if not acquired:
                logger.info("detection_cycle_skipped reason=another_replica_holds_lock")
                return None
            return self._run_locked(now)

    def _run_locked(self, now: datetime | None) -> DetectionCycleResult:
        started_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cycle_id = uuid4()
        self._repository.begin_cycle(cycle_id, started_at)
        source_results = []
        opened_or_updated = 0
        resolved = 0
        try:
            last_success = self._repository.last_successful_source_times()
            restore_health = getattr(self._health_client, "restore_last_success", None)
            if restore_health is not None:
                restore_health({key: value for key, value in last_success.items() if key in self._settings.service_base_urls})
            restore_order = getattr(self._order_client, "restore_last_success", None)
            if restore_order is not None:
                restore_order(last_success.get("order-attention"))

            health_results = self._health_client.probe_all(started_at)
            health_policy = HealthRulePolicy(
                failure_threshold=2,
                recovery_threshold=2,
                stale_after=timedelta(seconds=self._settings.source_stale_seconds),
            )
            for result in health_results:
                source_results.append(result.freshness)
                evaluation = self._repository.apply_health_observation(
                    result.observation, started_at, health_policy
                )
                if evaluation.decision.action == DecisionAction.OPEN_OR_UPDATE:
                    opened_or_updated += 1
                elif evaluation.decision.action == DecisionAction.RESOLVE:
                    resolved += 1

            active = self._order_client.collect(started_at)
            order_freshness = active.freshness
            if active.complete:
                policy = OrderRecoveryPolicy(
                    grace_period=timedelta(seconds=self._settings.recovery_grace_seconds)
                )
                active_ids = {case.order_id for case in active.cases}
                for case in active.cases:
                    decision = self._repository.apply_order_case(case, started_at, policy)
                    opened_or_updated += decision.action == DecisionAction.OPEN_OR_UPDATE
                    resolved += decision.action == DecisionAction.RESOLVE

                open_ids = self._repository.open_order_incident_ids(self._settings.order_terminal_lookup_limit + 1)
                terminal_ids = [value for value in open_ids if value not in active_ids]
                truncated = len(terminal_ids) > self._settings.order_terminal_lookup_limit
                terminal_ids = terminal_ids[: self._settings.order_terminal_lookup_limit]
                if terminal_ids:
                    terminal = self._order_client.lookup_terminal([str(value) for value in terminal_ids], started_at)
                    if terminal.complete:
                        for case in terminal.cases:
                            decision = self._repository.apply_order_case(case, started_at, policy)
                            opened_or_updated += decision.action == DecisionAction.OPEN_OR_UPDATE
                            resolved += decision.action == DecisionAction.RESOLVE
                    order_freshness = terminal.freshness
                if truncated:
                    order_freshness = order_freshness.model_copy(
                        update={"status": FreshnessStatus.PARTIAL, "error_code": "TERMINAL_LOOKUP_LIMIT"}
                    )
            source_results.append(order_freshness)

            completed_at = datetime.now(timezone.utc)
            partial = any(item.status != FreshnessStatus.CURRENT for item in source_results)
            cycle_status = "PARTIAL" if partial else "COMPLETE"
            self._repository.finish_cycle(
                cycle_id, completed_at, cycle_status, opened_or_updated, resolved, source_results
            )
            logger.info(
                "detection_cycle_completed status=%s sources=%d findings=%d resolved=%d",
                cycle_status, len(source_results), opened_or_updated, resolved,
            )
            return DetectionCycleResult(
                cycleId=cycle_id,
                status=cycle_status,
                startedAt=started_at,
                completedAt=completed_at,
                healthSources=[item for item in source_results if item.source != "order-attention"],
                orderSource=order_freshness,
                findingsOpenedOrUpdated=opened_or_updated,
                incidentsResolved=resolved,
            )
        except Exception as error:
            code = "DATABASE_UNAVAILABLE" if isinstance(error, psycopg.Error) else "CYCLE_FAILED"
            try:
                self._repository.fail_cycle(cycle_id, datetime.now(timezone.utc), code)
            except psycopg.Error:
                logger.error("detection_cycle_status_persistence_failed")
            logger.error("detection_cycle_failed code=%s", code)
            raise

    def close(self) -> None:
        self._health_client.close()
        self._order_client.close()

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from .clients import OrderAttentionClient
from .config import Settings
from .investigation_clients import TraceSummaryClient
from .investigation_models import (
    EvidenceDetails,
    EvidenceGap,
    InvestigationClaim,
    InvestigationContent,
    InvestigationEvidence,
    InvestigationResult,
    validate_citations,
)
from .models import (
    FreshnessStatus,
    IncidentRecord,
    OrderFailureReason,
    OrderRecoveryCase,
    OrderStatus,
    RuleKey,
    SourceFreshness,
)
from .repository import IncidentRepository


MAX_TRACE_REFERENCES = 3
MAX_SPANS_PER_TRACE = 20


class InvestigationProvider(Protocol):
    name: str

    def generate(
        self,
        incident: IncidentRecord,
        evidence: list[InvestigationEvidence],
        gaps: list[EvidenceGap],
        status: str,
    ) -> InvestigationContent: ...


class DeterministicInvestigationProvider:
    """Produces a schema-validated, evidence-cited report without an external model."""

    name = "deterministic-v1"

    def generate(
        self,
        incident: IncidentRecord,
        evidence: list[InvestigationEvidence],
        gaps: list[EvidenceGap],
        status: str,
    ) -> InvestigationContent:
        facts: list[InvestigationClaim] = [
            InvestigationClaim(
                claimId="fact-incident",
                text=(f"The incident record classifies {incident.rule_key.value} as "
                      f"{incident.status} with {incident.occurrence_count} recorded occurrence(s)."),
                evidenceIds=["incident"],
            )
        ]
        signal_items = [item for item in evidence if item.source_type == "INCIDENT_SIGNAL"]
        for index, item in enumerate(signal_items[:8], start=1):
            facts.append(InvestigationClaim(
                claimId=f"fact-signal-{index}",
                text=item.summary,
                evidenceIds=[item.evidence_id],
            ))

        health = next((item for item in evidence if item.source_type == "SERVICE_HEALTH"), None)
        if health is not None:
            facts.append(InvestigationClaim(
                claimId="fact-health",
                text=(f"The latest persisted readiness probe for {health.details.service_name} is "
                      f"{health.details.probe_status}; its recorded freshness is "
                      f"{health.freshness_status.value if health.freshness_status else 'UNAVAILABLE'}."),
                evidenceIds=[health.evidence_id],
            ))

        order = next((item for item in evidence if item.source_type == "ORDER_RECOVERY"), None)
        if order is not None:
            detail = order.details
            code = detail.recovery_error.value if detail.recovery_error else (
                detail.failure_reason.value if detail.failure_reason else "none recorded"
            )
            facts.append(InvestigationClaim(
                claimId="fact-order",
                text=(f"Order Service reports workflow status {detail.order_status}, recovery/failure code {code}, "
                      f"and inventoryReleased={str(detail.inventory_released).lower()}."),
                evidenceIds=[order.evidence_id],
            ))

        traces: dict[str, list[InvestigationEvidence]] = {}
        for item in evidence:
            if item.source_type == "TRACE_SPAN" and item.details.trace_id:
                traces.setdefault(item.details.trace_id, []).append(item)
        for index, (trace_id, spans) in enumerate(sorted(traces.items()), start=1):
            representative = next(
                (item for item in spans if item.details.span_status == "ERROR" or
                 (item.details.http_status_code is not None and item.details.http_status_code >= 400)),
                spans[0],
            )
            facts.append(InvestigationClaim(
                claimId=f"fact-trace-{index}",
                text=(f"The sanitized trace summary for {trace_id} contains {len(spans)} included span(s); "
                      f"the cited span status is {representative.details.span_status}."),
                evidenceIds=[representative.evidence_id],
            ))

        hypotheses: list[InvestigationClaim] = []
        actions: list[InvestigationClaim] = []
        if incident.rule_key == RuleKey.SERVICE_NOT_READY and health is not None:
            status = health.details.probe_status
            if health.freshness_status == FreshnessStatus.CURRENT and status in {"DOWN", "TIMEOUT"}:
                hypotheses.append(InvestigationClaim(
                    claimId="hypothesis-health",
                    text="The current non-UP probe is consistent with the readiness incident; the available evidence does not establish its underlying cause.",
                    evidenceIds=["incident", health.evidence_id],
                ))
                actions.append(InvestigationClaim(
                    claimId="action-health",
                    text="Inspect the affected service's readiness and obtain fresh probes; this rule requires two consecutive UP observations to resolve.",
                    evidenceIds=[health.evidence_id],
                ))
            elif health.freshness_status == FreshnessStatus.CURRENT and status == "UP":
                hypotheses.append(InvestigationClaim(
                    claimId="hypothesis-recovery",
                    text="The latest UP probe may reflect recovery after the incident signal; one observation alone does not satisfy the two-probe resolution rule.",
                    evidenceIds=["incident", health.evidence_id],
                ))
                actions.append(InvestigationClaim(
                    claimId="action-recovery",
                    text="Wait for the detector's second consecutive UP observation before treating the service incident as resolved.",
                    evidenceIds=[health.evidence_id],
                ))
            else:
                actions.append(InvestigationClaim(
                    claimId="action-health-freshness",
                    text="Obtain a fresh readiness observation before making a claim about the service's current health.",
                    evidenceIds=["incident", health.evidence_id],
                ))
        elif incident.rule_key == RuleKey.ORDER_RECOVERY_STALLED and order is not None:
            detail = order.details
            if not _is_terminal_order_fields(
                detail.order_status,
                detail.recovery_error,
                detail.failure_reason,
                detail.inventory_released,
            ):
                hypotheses.append(InvestigationClaim(
                    claimId="hypothesis-order",
                    text="The persisted Order Service state is consistent with recovery still requiring attention; it does not identify the downstream root cause.",
                    evidenceIds=["incident", order.evidence_id],
                ))
                actions.append(InvestigationClaim(
                    claimId="action-order",
                    text="Review the fixed recovery code and confirm required compensation through the Order-owned recovery contract before treating the workflow as terminal.",
                    evidenceIds=[order.evidence_id],
                ))
            else:
                actions.append(InvestigationClaim(
                    claimId="action-order-reconcile",
                    text="The current Order observation is terminal; allow the next deterministic detection cycle to reconcile the open incident, and do not change incident state from this report.",
                    evidenceIds=["incident", order.evidence_id],
                ))

        error_span = next((item for item in evidence if item.source_type == "TRACE_SPAN" and
                           (item.details.span_status == "ERROR" or
                            (item.details.http_status_code is not None and item.details.http_status_code >= 400))), None)
        if error_span is not None and len(actions) < 10:
            actions.append(InvestigationClaim(
                claimId="action-trace",
                text="Correlate this exported error span with other spans in its trace; a span status alone does not establish root cause.",
                evidenceIds=[error_span.evidence_id],
            ))

        if not actions:
            actions.append(InvestigationClaim(
                claimId="action-evidence",
                text="Collect a fresh observation from the incident's owning service before drawing a stronger conclusion.",
                evidenceIds=["incident"],
            ))

        gap_suffix = f" {len(gaps)} evidence gap(s) are recorded." if gaps else " No evidence gaps were recorded."
        summary = (
            f"Deterministic review of {incident.rule_key.value} ({incident.status}) collected "
            f"{len(evidence)} evidence item(s).{gap_suffix}"
        )
        if status == "INSUFFICIENT":
            uncertainty = "Required owning-service evidence could not be confirmed; current cause and workflow state remain unknown."
        elif status == "PARTIAL":
            uncertainty = "Some required or referenced evidence is incomplete, stale, contradictory, or unavailable; this report does not establish root cause."
        elif any(gap.code == "NO_TRACE_REFERENCE" for gap in gaps):
            uncertainty = "Required detection evidence was current when collected, but no trace reference was available; root cause is not proven."
        else:
            uncertainty = "Required owning-service evidence was current when collected; this deterministic review does not prove root cause."
        # Re-validate provider output at the adapter boundary, just as a structured model response would be.
        return InvestigationContent.model_validate({
            "summary": summary,
            "uncertainty": uncertainty,
            "facts": [item.model_dump(mode="json", by_alias=True) for item in facts],
            "hypotheses": [item.model_dump(mode="json", by_alias=True) for item in hypotheses],
            "recommendedActions": [item.model_dump(mode="json", by_alias=True) for item in actions],
        })


class IncidentInvestigator:
    def __init__(
        self,
        settings: Settings,
        repository: IncidentRepository,
        order_client: OrderAttentionClient,
        trace_client: TraceSummaryClient,
        provider: InvestigationProvider | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._order_client = order_client
        self._trace_client = trace_client
        self._provider = provider or DeterministicInvestigationProvider()

    def run(self, incident_id: UUID, now: datetime | None = None) -> InvestigationResult | None:
        generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        incident = self._repository.find_by_id(incident_id)
        if incident is None:
            return None

        evidence = [self._incident_evidence(incident)]
        evidence.extend(self._signal_evidence(incident))
        gaps: list[EvidenceGap] = []
        sources: list[SourceFreshness] = []
        if incident.rule_key == RuleKey.SERVICE_NOT_READY:
            self._collect_health(incident, generated_at, evidence, sources, gaps)
        else:
            self._collect_order(incident, generated_at, evidence, sources, gaps)
        self._collect_traces(incident, generated_at, evidence, sources, gaps)
        status = self._result_status(incident, evidence, sources, gaps)
        content = self._provider.generate(incident, evidence, gaps, status)
        validate_citations(content, evidence)
        result = InvestigationResult.model_validate({
            **content.model_dump(mode="json", by_alias=True),
            "investigationId": uuid4(),
            "incidentId": incident.id,
            "generatedAt": generated_at,
            "status": status,
            "provider": self._provider.name,
            "evidence": [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in evidence],
            "evidenceGaps": [item.model_dump(mode="json", by_alias=True) for item in gaps],
            "sources": [item.model_dump(mode="json", by_alias=True) for item in sources],
        })
        self._repository.save_investigation(result)
        return result

    def close(self) -> None:
        self._order_client.close()
        self._trace_client.close()

    @staticmethod
    def _incident_evidence(incident: IncidentRecord) -> InvestigationEvidence:
        return InvestigationEvidence(
            evidenceId="incident",
            sourceType="INCIDENT",
            sourceName="incident-service",
            sourceId=str(incident.id),
            observedAt=incident.last_evaluated_at,
            freshnessStatus=FreshnessStatus.CURRENT,
            summary=f"Incident record: {incident.rule_key.value}, {incident.status}.",
            details=EvidenceDetails(
                ruleKey=incident.rule_key,
                ruleVersion=incident.rule_version,
                severity=incident.severity,
                incidentStatus=incident.status,
                scopeType=incident.scope_type,
                occurrenceCount=incident.occurrence_count,
            ),
        )

    @staticmethod
    def _signal_evidence(incident: IncidentRecord) -> list[InvestigationEvidence]:
        evidence = []
        for index, reference in enumerate(incident.evidence, start=1):
            evidence.append(InvestigationEvidence(
                evidenceId=f"signal-{index}",
                sourceType="INCIDENT_SIGNAL",
                sourceName="incident-service",
                sourceId=reference.source_id,
                observedAt=reference.observed_at,
                signalCode=reference.signal_code,
                summary=f"The persisted incident references signal {reference.signal_code} from {reference.source_type}.",
                details=EvidenceDetails(traceId=reference.trace_id),
            ))
        return evidence

    def _collect_health(
        self,
        incident: IncidentRecord,
        now: datetime,
        evidence: list[InvestigationEvidence],
        sources: list[SourceFreshness],
        gaps: list[EvidenceGap],
    ) -> None:
        if incident.source_reference not in self._settings.service_base_urls:
            gaps.append(EvidenceGap(source="SERVICE_HEALTH", code="HEALTH_OBSERVATION_MISSING",
                                    summary="The incident does not identify a supported service health source.", required=True))
            return
        detection = self._repository.detection_status(now, self._settings.source_stale_seconds)
        snapshot = next((item for item in detection.services if item.service_name == incident.source_reference), None)
        source = next((item for item in detection.sources if item.source == incident.source_reference), None)
        if source is None:
            source = SourceFreshness(source=incident.source_reference, status=FreshnessStatus.UNAVAILABLE,
                                     attemptedAt=now, lastSuccessAt=None, itemCount=0,
                                     errorCode="NO_RECORDED_HEALTH_SOURCE")
        sources.append(source)
        if snapshot is None:
            gaps.append(EvidenceGap(source="SERVICE_HEALTH", code="HEALTH_OBSERVATION_MISSING",
                                    summary="No persisted service probe snapshot is available.", required=True))
            return
        evidence.append(InvestigationEvidence(
            evidenceId=f"health-{snapshot.service_name}",
            sourceType="SERVICE_HEALTH",
            sourceName="detection-store",
            sourceId=snapshot.service_name,
            observedAt=snapshot.observed_at,
            freshnessStatus=snapshot.freshness_status,
            signalCode=snapshot.status.value if snapshot.status.value != "UNKNOWN" else "HEALTH_OBSERVATION_MISSING",
            summary=f"Last persisted readiness result: {snapshot.status.value}.",
            details=EvidenceDetails(serviceName=snapshot.service_name, probeStatus=snapshot.status),
        ))
        if snapshot.observed_at is None:
            gaps.append(EvidenceGap(source="SERVICE_HEALTH", code="HEALTH_OBSERVATION_MISSING",
                                    summary="No readiness probe has been recorded for the affected service.", required=True))
        elif snapshot.status.value == "UNKNOWN":
            gaps.append(EvidenceGap(source="SERVICE_HEALTH", code="HEALTH_OBSERVATION_MISSING",
                                    summary="The persisted readiness observation has no UP or non-UP result.", required=True))
        elif snapshot.freshness_status != FreshnessStatus.CURRENT:
            gaps.append(EvidenceGap(source="SERVICE_HEALTH", code="HEALTH_SOURCE_NOT_CURRENT",
                                    summary=f"The last service observation is {snapshot.freshness_status.value.lower()}.", required=True))

    def _collect_order(
        self,
        incident: IncidentRecord,
        now: datetime,
        evidence: list[InvestigationEvidence],
        sources: list[SourceFreshness],
        gaps: list[EvidenceGap],
    ) -> None:
        try:
            order_id = UUID(incident.source_reference)
        except ValueError:
            gaps.append(EvidenceGap(source="ORDER_RECOVERY", code="ORDER_SOURCE_UNAVAILABLE",
                                    summary="The incident's order reference is not a valid order identifier.", required=True))
            return
        self._order_client.restore_last_success(self._repository.last_successful_source_times().get("order-attention"))
        observation = self._order_client.lookup_terminal([str(order_id)], now)
        sources.append(observation.freshness)
        if not observation.complete:
            code = "ORDER_SOURCE_UNAVAILABLE" if observation.freshness.status == FreshnessStatus.UNAVAILABLE else "ORDER_SOURCE_PARTIAL"
            gaps.append(EvidenceGap(source="ORDER_RECOVERY", code=code,
                                    summary="Order recovery state could not be collected completely.", required=True))
            return
        case = next((item for item in observation.cases if item.order_id == order_id), None)
        if case is None:
            gaps.append(EvidenceGap(source="ORDER_RECOVERY", code="ORDER_OBSERVATION_MISSING",
                                    summary="Order Service did not return an explicit recovery observation for this order.", required=True))
            return
        evidence.append(self._order_evidence(case))
        terminal = _is_terminal_order_fields(case.status, case.recovery_error, case.failure_reason, case.inventory_released)
        if incident.status == "OPEN" and terminal:
            gaps.append(EvidenceGap(source="ORDER_RECOVERY", code="CONTRADICTORY_ORDER_STATE",
                                    summary="The persisted incident is OPEN while the latest explicit Order observation is terminal; the investigator does not change incident state.", required=True))
        if observation.freshness.status != FreshnessStatus.CURRENT:
            gaps.append(EvidenceGap(source="ORDER_RECOVERY", code="ORDER_SOURCE_PARTIAL",
                                    summary="Order Service marked the observation source as partial.", required=True))

    @staticmethod
    def _order_evidence(case: OrderRecoveryCase) -> InvestigationEvidence:
        code = case.recovery_error.value if case.recovery_error else (
            case.failure_reason.value if case.failure_reason else case.status.value
        )
        return InvestigationEvidence(
            evidenceId=f"order-{case.order_id}",
            sourceType="ORDER_RECOVERY",
            sourceName="order-service",
            sourceId=str(case.order_id),
            observedAt=case.updated_at,
            freshnessStatus=FreshnessStatus.CURRENT,
            signalCode=code,
            summary=f"Order Service reports workflow state {case.status.value} and recovery code {code}.",
            details=EvidenceDetails(
                orderStatus=case.status,
                failureReason=case.failure_reason,
                recoveryError=case.recovery_error,
                recoveryAttempts=case.recovery_attempts,
                nextRecoveryAt=case.next_recovery_at,
                inventoryReleased=case.inventory_released,
                traceId=case.origin_trace_id,
            ),
        )

    def _collect_traces(
        self,
        incident: IncidentRecord,
        now: datetime,
        evidence: list[InvestigationEvidence],
        sources: list[SourceFreshness],
        gaps: list[EvidenceGap],
    ) -> None:
        trace_ids = list(dict.fromkeys(
            [value for value in [incident.origin_trace_id, *(item.trace_id for item in incident.evidence)] if value]
        ))
        if not trace_ids:
            gaps.append(EvidenceGap(source="TRACE", code="NO_TRACE_REFERENCE",
                                    summary="No trace reference was recorded for this incident; traces are optional supporting evidence.", required=False))
            return
        if len(trace_ids) > MAX_TRACE_REFERENCES:
            gaps.append(EvidenceGap(source="TRACE", code="TRACE_REFERENCE_LIMIT",
                                    summary=f"Only the first {MAX_TRACE_REFERENCES} distinct trace references were queried.", required=False))
        for trace_id in trace_ids[:MAX_TRACE_REFERENCES]:
            fetched = self._trace_client.fetch(trace_id, now)
            sources.append(fetched.freshness)
            if fetched.summary is None:
                code = fetched.freshness.error_code or "TRACE_SOURCE_UNAVAILABLE"
                if code == "TRACE_NOT_FOUND":
                    gap_code = "TRACE_NOT_FOUND"
                    summary = "The referenced trace is not present in Tempo through the Gateway API."
                elif code == "TRACE_EMPTY":
                    gap_code = "TRACE_EMPTY"
                    summary = "The Gateway returned no spans for the referenced trace."
                elif code == "TRACE_RESPONSE_TOO_LARGE":
                    gap_code = "TRACE_RESPONSE_TOO_LARGE"
                    summary = "The sanitized trace response exceeded the configured size limit."
                elif code == "TRACE_RESPONSE_INVALID":
                    gap_code = "TRACE_RESPONSE_INVALID"
                    summary = "The Gateway did not return a valid sanitized trace summary."
                else:
                    gap_code = "TRACE_SOURCE_UNAVAILABLE"
                    summary = "Trace evidence could not be confirmed through the Gateway API."
                gaps.append(EvidenceGap(source="TRACE", code=gap_code, summary=summary, required=False))
                continue
            spans = fetched.summary.spans
            for span in spans[:MAX_SPANS_PER_TRACE]:
                evidence.append(InvestigationEvidence(
                    evidenceId=f"trace:{trace_id}:{span.span_id}",
                    sourceType="TRACE_SPAN",
                    sourceName="tempo-via-gateway",
                    sourceId=f"{trace_id}:{span.span_id}",
                    observedAt=span.start_time,
                    freshnessStatus=FreshnessStatus.CURRENT,
                    signalCode=span.status,
                    summary=f"Sanitized span from {span.service} has status {span.status}.",
                    details=EvidenceDetails(
                        traceId=trace_id,
                        service=span.service,
                        spanId=span.span_id,
                        parentSpanId=span.parent_span_id,
                        spanName=span.name,
                        spanStatus=span.status,
                        httpMethod=span.http_method,
                        httpRoute=span.http_route,
                        httpStatusCode=span.http_status_code,
                    ),
                ))
            if fetched.summary.truncated or len(spans) > MAX_SPANS_PER_TRACE:
                gaps.append(EvidenceGap(source="TRACE", code="TRACE_SPANS_TRUNCATED",
                                        summary=f"The trace summary included at most {MAX_SPANS_PER_TRACE} spans for this investigation.", required=False))

    @staticmethod
    def _result_status(
        incident: IncidentRecord,
        evidence: list[InvestigationEvidence],
        sources: list[SourceFreshness],
        gaps: list[EvidenceGap],
    ) -> str:
        required_source = "order-attention" if incident.rule_key == RuleKey.ORDER_RECOVERY_STALLED else incident.source_reference
        matching = [source for source in sources if source.source == required_source]
        required_gaps = [gap for gap in gaps if gap.required]
        required_evidence_type = "ORDER_RECOVERY" if incident.rule_key == RuleKey.ORDER_RECOVERY_STALLED else "SERVICE_HEALTH"
        has_primary_evidence = any(item.source_type == required_evidence_type for item in evidence)
        if not matching:
            return "PARTIAL" if has_primary_evidence else "INSUFFICIENT"
        if matching[0].status != FreshnessStatus.CURRENT or required_gaps:
            return "PARTIAL" if has_primary_evidence else "INSUFFICIENT"
        if any(source.status != FreshnessStatus.CURRENT for source in sources if source.source.startswith("tempo-trace-")):
            return "PARTIAL"
        if any(not gap.required and gap.code not in {"NO_TRACE_REFERENCE"} for gap in gaps):
            return "PARTIAL"
        return "COMPLETE"


def _is_terminal_order_fields(
    status: OrderStatus,
    recovery_error: RecoveryError | None,
    failure_reason: OrderFailureReason | None,
    inventory_released: bool | None,
) -> bool:
    incomplete_compensation = (
        status == "COMPENSATION_REQUIRED" and inventory_released is not True
    ) or (
        status == "FAILED"
        and failure_reason == OrderFailureReason.PAYMENT_DECLINED
        and inventory_released is not True
    )
    return status in {"CONFIRMED", "FAILED"} and recovery_error is None and not incomplete_compensation

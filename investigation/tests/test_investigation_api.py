from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from traceforge_investigation.investigation_models import (
    EvidenceDetails,
    InvestigationClaim,
    InvestigationEvidence,
    InvestigationResult,
)
from traceforge_investigation.main import create_app
from traceforge_investigation.models import (
    EvidenceReference,
    RuleFinding,
    RuleKey,
    ScopeType,
    Severity,
)
from traceforge_investigation.repository import IncidentRepository
from .helpers import NOW


def test_investigation_api_saves_and_reads_latest_result_across_repository_instances(incident_repository, monkeypatch):
    incident = incident_repository.open_or_update(
        RuleFinding(
            ruleKey=RuleKey.ORDER_RECOVERY_STALLED,
            severity=Severity.HIGH,
            scopeType=ScopeType.ORDER,
            sourceReference="ab3163ab-2240-4578-b012-9b8f9226b7f2",
            summary="Order recovery requires attention",
            evidence=EvidenceReference(
                sourceType="ORDER_RECOVERY",
                sourceId="ab3163ab-2240-4578-b012-9b8f9226b7f2",
                observedAt=NOW,
                signalCode="RECOVERY_ACTION_REQUIRED",
            ),
        ),
        NOW,
    )
    evidence = InvestigationEvidence(
        evidenceId="incident",
        sourceType="INCIDENT",
        sourceName="incident-service",
        sourceId=str(incident.id),
        observedAt=NOW,
        freshnessStatus="CURRENT",
        signalCode=None,
        summary="Persisted incident record.",
        details=EvidenceDetails(ruleKey=RuleKey.ORDER_RECOVERY_STALLED, incidentStatus="OPEN"),
    )
    result = InvestigationResult(
        investigationId=UUID("e398d4e2-15b6-4795-9caa-88f16d11d59c"),
        incidentId=incident.id,
        generatedAt=NOW,
        status="INSUFFICIENT",
        provider="deterministic-v1",
        summary="Required recovery evidence is unavailable.",
        uncertainty="Required owning-service evidence could not be confirmed.",
        facts=[InvestigationClaim(claimId="fact-incident", text="The incident is open.", evidenceIds=["incident"])],
        hypotheses=[],
        recommendedActions=[],
        evidence=[evidence],
        evidenceGaps=[],
        sources=[],
    )
    monkeypatch.setattr("traceforge_investigation.main.IncidentRepository", lambda settings: incident_repository)
    app = create_app(incident_repository._settings, start_scheduler=False)

    def save_result(incident_id):
        assert incident_id == incident.id
        incident_repository.save_investigation(result)
        return result

    monkeypatch.setattr(app.state.investigator, "run", save_result)

    async def check_routes():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                absent = await client.get(f"/api/v1/incidents/{incident.id}/investigations/latest")
                generated = await client.post(f"/api/v1/incidents/{incident.id}/investigations")
                latest = await client.get(f"/api/v1/incidents/{incident.id}/investigations/latest")
                missing_incident = await client.get(f"/api/v1/incidents/{UUID(int=999)}/investigations/latest")
                return absent, generated, latest, missing_incident

    absent, generated, latest, missing_incident = asyncio.run(check_routes())
    assert absent.status_code == 404
    assert absent.json() == {"detail": {"code": "INVESTIGATION_NOT_FOUND"}}
    assert generated.status_code == 200
    assert generated.json()["status"] == "INSUFFICIENT"
    assert latest.status_code == 200
    assert latest.json()["investigationId"] == str(result.investigation_id)
    assert latest.json()["evidence"][0]["sourceId"] == str(incident.id)
    assert missing_incident.status_code == 404
    assert missing_incident.json() == {"detail": {"code": "INCIDENT_NOT_FOUND"}}

    reopened_repository = IncidentRepository(incident_repository._settings)
    assert reopened_repository.get_investigation(incident.id) == result

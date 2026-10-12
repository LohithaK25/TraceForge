import asyncio
from datetime import timedelta

import httpx
import pytest
import psycopg
from uuid import UUID

from traceforge_investigation.main import create_app
from traceforge_investigation.models import (
    EvidenceReference,
    FreshnessStatus,
    HealthObservation,
    ProbeStatus,
    RuleFinding,
    RuleKey,
    ScopeType,
    Severity,
    SourceFreshness,
)
from traceforge_investigation.rules import HealthRulePolicy
from .helpers import NOW


def test_liveness_readiness_and_empty_incident_api_are_explicit(incident_repository):
    app = create_app(incident_repository._settings, start_scheduler=False)

    async def check_routes():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return (
                    await client.get("/healthz"),
                    await client.get("/readyz"),
                    await client.get("/api/v1/incidents"),
                    await client.get("/api/v1/detection-status"),
                    await client.get("/openapi.json"),
                )

    live, ready, incident_api, detection_status, openapi = asyncio.run(check_routes())
    assert live.status_code == 200
    assert live.json() == {"status": "ok", "service": "investigation-service"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "service": "investigation-service"}
    assert incident_api.status_code == 200
    assert incident_api.json()["items"] == []
    assert incident_api.json()["detectionStatus"]["status"] == "NOT_RUN"
    assert incident_api.json()["detectionStatus"]["services"] == [
        {"serviceName": name, "status": "UNKNOWN", "observedAt": None,
         "freshnessStatus": "UNAVAILABLE", "incidentOpen": False}
        for name in ("api-gateway", "order-service", "inventory-service", "payment-service")
    ]
    assert detection_status.status_code == 200
    assert detection_status.json()["status"] == "NOT_RUN"
    assert detection_status.json()["services"][0]["status"] == "UNKNOWN"
    assert openapi.status_code == 404


def test_incident_list_filter_cursor_detail_and_invalid_inputs(incident_repository):
    first = incident_repository.open_or_update(_finding("cdb3ab44-25ea-4acf-80c1-6be919254045"), NOW)
    with psycopg.connect(incident_repository._dsn) as connection:
        first_rows = connection.execute("SELECT id, source_reference, status FROM incident_service.incidents").fetchall()
        assert len(first_rows) == 1, first_rows
    second = incident_repository.open_or_update(_finding("cdb3ab44-25ea-4acf-80c1-6be919254046"), NOW)
    assert first.id != second.id
    assert incident_repository.find_by_id(first.id).status == "OPEN"
    with psycopg.connect(incident_repository._dsn) as connection:
        rows = connection.execute("SELECT id, source_reference, status FROM incident_service.incidents ORDER BY source_reference").fetchall()
        assert any(row[0] == second.id for row in rows), rows
    assert incident_repository.find_by_id(second.id).status == "OPEN"
    with psycopg.connect(incident_repository._dsn) as connection:
        assert connection.execute("SELECT count(*) FROM incident_service.incidents WHERE status = 'OPEN'").fetchone()[0] == 2
    assert len(incident_repository.list_incidents("OPEN", 10)[0]) == 2
    app = create_app(incident_repository._settings, start_scheduler=False)

    async def check():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                first_page = await client.get("/api/v1/incidents", params={"status": "OPEN", "limit": 1})
                second_page = await client.get("/api/v1/incidents", params={"status": "OPEN", "limit": 1,
                                                                             "cursor": first_page.json()["nextCursor"]})
                incident_repository.resolve(RuleKey.ORDER_RECOVERY_STALLED, ScopeType.ORDER,
                                            "cdb3ab44-25ea-4acf-80c1-6be919254046", NOW)
                resolved_page = await client.get("/api/v1/incidents", params={"status": "RESOLVED", "limit": 10})
                detail = await client.get(f"/api/v1/incidents/{first.id}")
                invalid_cursor = await client.get("/api/v1/incidents", params={"cursor": "not a cursor"})
                invalid_status = await client.get("/api/v1/incidents", params={"status": "ALL"})
                missing = await client.get(f"/api/v1/incidents/{UUID(int=500)}")
                malformed_id = await client.get("/api/v1/incidents/not-a-uuid")
                return first_page, second_page, resolved_page, detail, invalid_cursor, invalid_status, missing, malformed_id

    first_page, second_page, resolved_page, detail, invalid_cursor, invalid_status, missing, malformed_id = asyncio.run(check())
    assert first_page.status_code == 200 and len(first_page.json()["items"]) == 1
    assert second_page.status_code == 200 and len(second_page.json()["items"]) == 1
    assert resolved_page.status_code == 200 and len(resolved_page.json()["items"]) == 1
    assert resolved_page.json()["items"][0]["status"] == "RESOLVED"
    assert first_page.json()["items"][0]["status"] == "OPEN"
    assert first_page.json()["nextCursor"]
    assert detail.status_code == 200 and detail.json()["id"] == str(first.id)
    assert invalid_cursor.status_code == 400
    assert invalid_status.status_code == 422
    assert missing.status_code == 404
    assert malformed_id.status_code == 422


def test_database_failures_return_safe_503_instead_of_empty_lists(incident_repository, monkeypatch):
    app = create_app(incident_repository._settings, start_scheduler=False)
    monkeypatch.setattr(app.state.repository, "list_incidents", lambda *args, **kwargs: _raise_database_error())

    async def check():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/incidents")

    response = asyncio.run(check())
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "DETECTION_STORE_UNAVAILABLE"}}


def test_detection_status_separates_last_probe_from_collection_freshness(incident_repository, monkeypatch):
    service = "payment-service"
    for second in (0, 1):
        incident_repository.apply_health_observation(
            HealthObservation(
                serviceName=service,
                status=ProbeStatus.DOWN,
                observedAt=NOW.replace(second=second),
                httpStatus=503,
                signalCode="HTTP_NON_200",
            ),
            NOW.replace(second=second),
            HealthRulePolicy(),
        )

    cycle_id = UUID("23761874-53d4-4b7d-a8c5-45d4a99c6010")
    cycle_start = NOW.replace(second=2)
    incident_repository.begin_cycle(cycle_id, cycle_start)
    freshness = SourceFreshness(
        source=service,
        status=FreshnessStatus.CURRENT,
        attemptedAt=cycle_start,
        lastSuccessAt=cycle_start,
        itemCount=1,
        errorCode="HTTP_NON_200",
    )
    incident_repository.finish_cycle(cycle_id, cycle_start, "COMPLETE", 1, 0, [freshness])

    current = incident_repository.detection_status(cycle_start, stale_after_seconds=30)
    payment = next(snapshot for snapshot in current.services if snapshot.service_name == service)
    assert payment.status == ProbeStatus.DOWN
    assert payment.observed_at == NOW.replace(second=1)
    assert payment.freshness_status == FreshnessStatus.CURRENT
    assert payment.incident_open is True

    monkeypatch.setattr(
        "traceforge_investigation.main.IncidentRepository",
        lambda settings: incident_repository,
    )
    app = create_app(incident_repository._settings, start_scheduler=False)
    original_detection_status = incident_repository.detection_status
    monkeypatch.setattr(
        incident_repository,
        "detection_status",
        lambda now, stale_after_seconds: original_detection_status(cycle_start, stale_after_seconds),
    )

    async def read_detection_status():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/detection-status")

    response = asyncio.run(read_detection_status())
    assert response.status_code == 200
    payment_api = next(item for item in response.json()["services"] if item["serviceName"] == service)
    assert payment_api["status"] == "DOWN"
    assert payment_api["freshnessStatus"] == "CURRENT"
    assert payment_api["incidentOpen"] is True

    stale = original_detection_status(cycle_start + timedelta(seconds=60), 30)
    payment_stale = next(snapshot for snapshot in stale.services if snapshot.service_name == service)
    assert payment_stale.status == ProbeStatus.DOWN
    assert payment_stale.freshness_status == FreshnessStatus.STALE


def _raise_database_error():
    raise psycopg.OperationalError("sensitive connection detail")


def _finding(order_id: str) -> RuleFinding:
    return RuleFinding(
        ruleKey=RuleKey.ORDER_RECOVERY_STALLED,
        severity=Severity.HIGH,
        scopeType=ScopeType.ORDER,
        sourceReference=order_id,
        summary="Order recovery requires attention",
        evidence=EvidenceReference(sourceType="ORDER_RECOVERY", sourceId=order_id, observedAt=NOW,
                                  signalCode="RECOVERY_ACTION_REQUIRED"),
    )

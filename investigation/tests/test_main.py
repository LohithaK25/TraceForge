import asyncio

import httpx
import pytest
import psycopg
from uuid import UUID

from traceforge_investigation.main import create_app
from traceforge_investigation.models import EvidenceReference, RuleFinding, RuleKey, ScopeType, Severity
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
    assert detection_status.status_code == 200
    assert detection_status.json()["status"] == "NOT_RUN"
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

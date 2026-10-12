from __future__ import annotations

import asyncio
import base64
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query, status

from .clients import HealthProbeClient, OrderAttentionClient
from .config import Settings
from .engine import InvestigationEngine
from .investigation_clients import TraceSummaryClient
from .investigation_models import InvestigationResult
from .investigator import IncidentInvestigator
from .models import DetectionStatusResponse, IncidentPage, IncidentRecord
from .repository import IncidentRepository
from .scheduler import detection_loop

logger = logging.getLogger("traceforge.investigation")
_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    effective_settings = settings or Settings.from_environment()
    repository = IncidentRepository(effective_settings)
    engine = InvestigationEngine(
        effective_settings,
        repository,
        HealthProbeClient(effective_settings),
        OrderAttentionClient(effective_settings),
    )
    investigator = IncidentInvestigator(
        effective_settings,
        repository,
        OrderAttentionClient(effective_settings),
        TraceSummaryClient(effective_settings),
    )
    scheduler_stop = asyncio.Event()
    scheduler_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal scheduler_task
        try:
            repository.migrate()
        except psycopg.Error:
            logger.error("incident_schema_migration_failed")
            raise RuntimeError("investigation schema migration failed") from None
        if start_scheduler:
            scheduler_task = asyncio.create_task(
                detection_loop(engine.run_once, effective_settings.detection_interval_seconds, scheduler_stop),
                name="traceforge-detection-scheduler",
            )
        try:
            yield
        finally:
            scheduler_stop.set()
            if scheduler_task is not None:
                await scheduler_task
            engine.close()
            investigator.close()

    app = FastAPI(
        title="TraceForge Investigation Service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.repository = repository
    app.state.investigator = investigator

    @app.get("/healthz", include_in_schema=False)
    def liveness() -> dict[str, str]:
        return {"status": "ok", "service": "investigation-service"}

    @app.get("/readyz", include_in_schema=False)
    def readiness() -> dict[str, str]:
        try:
            if repository.check_ready():
                return {"status": "ready", "service": "investigation-service"}
        except psycopg.Error:
            logger.warning("incident_database_readiness_failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "reason": "database_unavailable"},
        )

    @app.get("/api/v1/incidents", response_model=IncidentPage)
    def list_incidents(
        incident_status: str = Query(default="OPEN", alias="status", pattern="^(OPEN|RESOLVED)$"),
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=256),
    ) -> IncidentPage:
        cursor_seen_at = cursor_id = None
        if cursor is not None:
            try:
                cursor_seen_at, cursor_id = _decode_cursor(cursor)
            except ValueError:
                raise HTTPException(status_code=400, detail={"code": "INVALID_CURSOR"}) from None
        try:
            items, has_more = repository.list_incidents(incident_status, limit, cursor_seen_at, cursor_id)
            detection = repository.detection_status(datetime.now(timezone.utc), effective_settings.source_stale_seconds)
        except psycopg.Error:
            logger.warning("incident_list_database_unavailable")
            raise HTTPException(status_code=503, detail={"code": "DETECTION_STORE_UNAVAILABLE"}) from None
        next_cursor = _encode_cursor(items[-1].last_seen_at, items[-1].id) if has_more and items else None
        return IncidentPage(items=items, limit=limit, nextCursor=next_cursor, detectionStatus=detection)

    @app.get("/api/v1/incidents/{incident_id}", response_model=IncidentRecord)
    def get_incident(incident_id: UUID) -> IncidentRecord:
        try:
            incident = repository.find_by_id(incident_id)
        except psycopg.Error:
            logger.warning("incident_detail_database_unavailable")
            raise HTTPException(status_code=503, detail={"code": "DETECTION_STORE_UNAVAILABLE"}) from None
        if incident is None:
            raise HTTPException(status_code=404, detail={"code": "INCIDENT_NOT_FOUND"})
        return incident

    @app.get(
        "/api/v1/incidents/{incident_id}/investigations/latest",
        response_model=InvestigationResult,
    )
    def get_latest_investigation(incident_id: UUID) -> InvestigationResult:
        try:
            if repository.find_by_id(incident_id) is None:
                raise HTTPException(status_code=404, detail={"code": "INCIDENT_NOT_FOUND"})
            result = repository.get_investigation(incident_id)
        except psycopg.Error:
            logger.warning("investigation_read_database_unavailable")
            raise HTTPException(status_code=503, detail={"code": "DETECTION_STORE_UNAVAILABLE"}) from None
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "INVESTIGATION_NOT_FOUND"})
        return result

    @app.post(
        "/api/v1/incidents/{incident_id}/investigations",
        response_model=InvestigationResult,
    )
    def run_investigation(incident_id: UUID) -> InvestigationResult:
        try:
            result = investigator.run(incident_id)
        except psycopg.Error:
            logger.warning("investigation_run_database_unavailable")
            raise HTTPException(status_code=503, detail={"code": "DETECTION_STORE_UNAVAILABLE"}) from None
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "INCIDENT_NOT_FOUND"})
        return result

    @app.get("/api/v1/detection-status", response_model=DetectionStatusResponse)
    def detection_status() -> DetectionStatusResponse:
        try:
            return repository.detection_status(datetime.now(timezone.utc), effective_settings.source_stale_seconds)
        except psycopg.Error:
            logger.warning("detection_status_database_unavailable")
            raise HTTPException(status_code=503, detail={"code": "DETECTION_STORE_UNAVAILABLE"}) from None

    return app


def _encode_cursor(seen_at: datetime, incident_id: UUID) -> str:
    payload = f"{seen_at.astimezone(timezone.utc).isoformat()}|{incident_id}".encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    if not _CURSOR_PATTERN.fullmatch(value):
        raise ValueError("invalid cursor")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii")
        seen_at_raw, incident_id_raw = decoded.split("|", 1)
        seen_at = datetime.fromisoformat(seen_at_raw.replace("Z", "+00:00"))
        incident_id = UUID(incident_id_raw)
        if seen_at.tzinfo is None or seen_at.utcoffset() is None:
            raise ValueError("cursor timestamp must be aware")
        return seen_at.astimezone(timezone.utc), incident_id
    except (UnicodeDecodeError, ValueError):
        raise ValueError("invalid cursor") from None


app = create_app()

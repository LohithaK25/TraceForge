from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Literal

import httpx
from pydantic import Field, ValidationError, field_validator, model_validator

from .clients import _PayloadTooLarge, _new_http_client, _read_limited
from .config import Settings
from .models import FreshnessStatus, SourceFreshness, StrictModel


_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


class TraceSpan(StrictModel):
    service: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    span_id: str = Field(alias="spanId", pattern=r"^[0-9a-f]{16}$")
    parent_span_id: str | None = Field(default=None, alias="parentSpanId", pattern=r"^[0-9a-f]{16}$")
    name: str = Field(min_length=1, max_length=120)
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    status: Literal["OK", "ERROR", "UNSET"]
    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] | None = Field(default=None, alias="httpMethod")
    http_route: str | None = Field(default=None, alias="httpRoute", max_length=180, pattern=r"^/[a-zA-Z0-9_./{}-]*$")
    http_status_code: int | None = Field(default=None, alias="httpStatusCode", ge=100, le=599)

    @field_validator("start_time", "end_time")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("trace timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None

    @field_validator("name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("trace span names must not contain control characters")
        return value

    @model_validator(mode="after")
    def validate_span_interval(self) -> TraceSpan:
        if self.start_time is not None and self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("trace span end precedes its start")
        return self


class TraceSummary(StrictModel):
    trace_id: str = Field(alias="traceId", pattern=r"^[0-9a-f]{32}$")
    spans: list[TraceSpan] = Field(max_length=250)
    truncated: bool


@dataclass(frozen=True)
class TraceFetch:
    summary: TraceSummary | None
    freshness: SourceFreshness


class TraceSummaryClient:
    """Reads only the Gateway's fixed sanitized trace-by-ID API."""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = http_client or _new_http_client(settings)
        self._owns_client = http_client is None

    def fetch(self, trace_id: str, now: datetime | None = None) -> TraceFetch:
        attempted_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if not _TRACE_ID.fullmatch(trace_id):
            return self._failed(trace_id, attempted_at, "INVALID_TRACE_ID")
        url = f"{self._settings.gateway_base_url.rstrip('/')}/api/v1/traces/{trace_id}"
        try:
            with self._client.stream("GET", url, headers={"Accept": "application/json"}) as response:
                if response.status_code == 404:
                    return self._failed(trace_id, attempted_at, "TRACE_NOT_FOUND")
                if response.status_code != 200:
                    return self._failed(trace_id, attempted_at, "TRACE_SOURCE_UNAVAILABLE")
                payload = _read_limited(response, self._settings.trace_response_limit_bytes)
            summary = TraceSummary.model_validate_json(payload)
            if summary.trace_id != trace_id:
                raise ValueError("trace identity does not match request")
            if not summary.spans:
                return self._failed(trace_id, attempted_at, "TRACE_EMPTY")
        except _PayloadTooLarge:
            return self._failed(trace_id, attempted_at, "TRACE_RESPONSE_TOO_LARGE")
        except httpx.TimeoutException:
            return self._failed(trace_id, attempted_at, "TRACE_UPSTREAM_TIMEOUT")
        except httpx.HTTPError:
            return self._failed(trace_id, attempted_at, "TRACE_SOURCE_UNAVAILABLE")
        except (ValidationError, ValueError, UnicodeDecodeError):
            return self._failed(trace_id, attempted_at, "TRACE_RESPONSE_INVALID")

        return TraceFetch(
            summary,
            SourceFreshness(
                source=f"tempo-trace-{trace_id}",
                status=FreshnessStatus.CURRENT,
                attemptedAt=attempted_at,
                lastSuccessAt=attempted_at,
                itemCount=len(summary.spans),
            ),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _failed(trace_id: str, attempted_at: datetime, code: str) -> TraceFetch:
        return TraceFetch(
            None,
            SourceFreshness(
                source=f"tempo-trace-{trace_id[:32]}",
                status=FreshnessStatus.UNAVAILABLE,
                attemptedAt=attempted_at,
                lastSuccessAt=None,
                itemCount=0,
                errorCode=code,
            ),
        )

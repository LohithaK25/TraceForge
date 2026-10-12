from __future__ import annotations

import httpx
import pytest

from traceforge_investigation.config import Settings
from traceforge_investigation.investigation_clients import TraceSummaryClient
from traceforge_investigation.models import FreshnessStatus
from .helpers import NOW, TRACE_ID


SPAN_ID = "0123456789abcdef"


def test_trace_client_reads_only_fixed_trace_path_and_accepts_sanitized_span():
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=_trace_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    trace_client = TraceSummaryClient(Settings(gateway_base_url="http://gateway:8080/"), client)
    result = trace_client.fetch(TRACE_ID, NOW)

    assert requested == [f"http://gateway:8080/api/v1/traces/{TRACE_ID}"]
    assert result.summary is not None
    assert result.summary.trace_id == TRACE_ID
    assert result.summary.spans[0].span_id == SPAN_ID
    assert result.freshness.status == FreshnessStatus.CURRENT
    assert result.freshness.item_count == 1
    client.close()


def test_trace_client_marks_invalid_or_mismatched_responses_unavailable():
    payload = _trace_payload()
    payload["traceId"] = "f" * 32
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)))
    result = TraceSummaryClient(Settings(), client).fetch(TRACE_ID, NOW)
    assert result.summary is None
    assert result.freshness.status == FreshnessStatus.UNAVAILABLE
    assert result.freshness.error_code == "TRACE_RESPONSE_INVALID"
    client.close()


@pytest.mark.parametrize(
    ("handler", "expected_code"),
    [
        (lambda _request: httpx.Response(503, content=b"private upstream detail"), "TRACE_SOURCE_UNAVAILABLE"),
        (lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("private timeout detail")), "TRACE_UPSTREAM_TIMEOUT"),
        (lambda _request: httpx.Response(404), "TRACE_NOT_FOUND"),
    ],
)
def test_trace_client_faults_remain_explicit_unavailable_evidence(handler, expected_code):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = TraceSummaryClient(Settings(), client).fetch(TRACE_ID, NOW)

    assert result.summary is None
    assert result.freshness.status == FreshnessStatus.UNAVAILABLE
    assert result.freshness.error_code == expected_code
    client.close()


def test_trace_client_rejects_control_characters_and_oversized_trace_summaries():
    payload = _trace_payload()
    payload["spans"][0]["name"] = "unsafe\nspan"
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)))
    malformed = TraceSummaryClient(Settings(), client).fetch(TRACE_ID, NOW)
    assert malformed.summary is None
    assert malformed.freshness.error_code == "TRACE_RESPONSE_INVALID"
    client.close()

    large = {"padding": "x" * 1200}
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=large)))
    oversized = TraceSummaryClient(Settings(trace_response_limit_bytes=1024), client).fetch(TRACE_ID, NOW)
    assert oversized.summary is None
    assert oversized.freshness.error_code == "TRACE_RESPONSE_TOO_LARGE"
    client.close()


def _trace_payload() -> dict[str, object]:
    return {
        "traceId": TRACE_ID,
        "truncated": False,
        "spans": [{
            "service": "payment-service",
            "spanId": SPAN_ID,
            "parentSpanId": None,
            "name": "POST /api/v1/payments/authorize",
            "startTime": NOW.isoformat(),
            "endTime": (NOW.replace(microsecond=1000)).isoformat(),
            "status": "ERROR",
            "httpMethod": "POST",
            "httpRoute": "/api/v1/payments/authorize",
            "httpStatusCode": 503,
        }],
    }

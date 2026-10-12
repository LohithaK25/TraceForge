import json
from datetime import timedelta
from uuid import UUID

import httpx
import pytest

from traceforge_investigation.clients import HealthProbeClient, OrderAttentionClient
from traceforge_investigation.config import Settings
from traceforge_investigation.models import FreshnessStatus, ProbeStatus
from .helpers import NOW, case_payload


def response(body, status_code=200, headers=None):
    return httpx.Response(status_code, json=body, headers=headers)


def order_page(items, cursor=None, limit=100):
    return {"items": items, "limit": limit, "nextCursor": cursor}


def cursor_for(item):
    return {"afterCreatedAt": item["createdAt"], "afterId": item["orderId"]}


def test_health_probes_use_actual_actuator_path_and_map_up_and_non_up():
    def handler(request):
        assert request.url.path == "/actuator/health"
        if request.url.host == "inventory.test":
            return response({"status": "DOWN"})
        return response({"status": "UP"})

    settings = Settings(
        gateway_base_url="http://gateway.test",
        order_base_url="http://order.test",
        inventory_base_url="http://inventory.test",
        payment_base_url="http://payment.test",
    )
    client = HealthProbeClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    results = client.probe_all(NOW)
    assert [result.observation.service_name for result in results] == [
        "api-gateway", "order-service", "inventory-service", "payment-service"
    ]
    assert [result.observation.status for result in results] == [
        ProbeStatus.UP, ProbeStatus.UP, ProbeStatus.DOWN, ProbeStatus.UP
    ]
    assert results[2].freshness.status == FreshnessStatus.CURRENT


@pytest.mark.parametrize(
    ("handler", "expected_status", "expected_code"),
    [
        (lambda request: response({"status": "OUT_OF_SERVICE"}), ProbeStatus.DOWN, "HEALTH_NON_UP"),
        (lambda request: response({"state": "UP"}), ProbeStatus.UNKNOWN, "MALFORMED_HEALTH_RESPONSE"),
        (lambda request: httpx.Response(503, content=b"down"), ProbeStatus.DOWN, "HTTP_NON_200"),
        (lambda request: httpx.Response(200, content=b"{bad"), ProbeStatus.UNKNOWN, "MALFORMED_HEALTH_RESPONSE"),
        (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("private detail")), ProbeStatus.TIMEOUT, "PROBE_TIMEOUT"),
        (lambda request: (_ for _ in ()).throw(httpx.ConnectError("private detail")), ProbeStatus.DOWN, "CONNECT_FAILED"),
    ],
)
def test_health_probe_failure_mapping_is_explicit(handler, expected_status, expected_code):
    settings = Settings(
        gateway_base_url="http://gateway.test",
        order_base_url="http://gateway.test",
        inventory_base_url="http://gateway.test",
        payment_base_url="http://gateway.test",
    )
    result = HealthProbeClient(settings, httpx.Client(transport=httpx.MockTransport(handler))).probe_all(NOW)[0]
    assert result.observation.status == expected_status
    assert result.observation.signal_code == expected_code


def test_health_probe_rejects_oversized_response():
    settings = Settings(
        health_response_limit_bytes=128,
        gateway_base_url="http://gateway.test",
        order_base_url="http://gateway.test",
        inventory_base_url="http://gateway.test",
        payment_base_url="http://gateway.test",
    )
    body = b'{"status":"UP","padding":"' + b"x" * 200 + b'"}'
    result = HealthProbeClient(
        settings,
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))),
    ).probe_all(NOW)[0]
    assert result.observation.status == ProbeStatus.UNKNOWN
    assert result.observation.signal_code == "HEALTH_RESPONSE_TOO_LARGE"


def test_health_source_freshness_survives_unknown_and_becomes_stale():
    calls = {}

    def handler(request):
        calls[request.url.host] = calls.get(request.url.host, 0) + 1
        if request.url.host == "gateway.test" and calls[request.url.host] > 1:
            return httpx.Response(200, content=b"{malformed")
        return response({"status": "UP"})

    client = HealthProbeClient(
        Settings(
            gateway_base_url="http://gateway.test",
            order_base_url="http://order.test",
            inventory_base_url="http://inventory.test",
            payment_base_url="http://payment.test",
        ),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = client.probe_all(NOW)[0]
    recent_unknown = client.probe_all(NOW + timedelta(seconds=5))[0]
    stale_unknown = client.probe_all(NOW + timedelta(seconds=31))[0]
    assert first.freshness.status == FreshnessStatus.CURRENT
    assert recent_unknown.freshness.status == FreshnessStatus.PARTIAL
    assert recent_unknown.freshness.last_success_at == NOW
    assert stale_unknown.freshness.status == FreshnessStatus.STALE
    assert stale_unknown.freshness.last_success_at == NOW


def test_order_client_collects_empty_page_as_a_complete_current_source():
    client = OrderAttentionClient(
        Settings(),
        httpx.Client(transport=httpx.MockTransport(lambda request: response(order_page([])))),
    )
    result = client.collect(NOW)
    assert result.complete
    assert result.cases == ()
    assert result.page_count == 1
    assert result.freshness.status == FreshnessStatus.CURRENT
    assert result.freshness.item_count == 0


def test_order_client_paginates_all_pages_at_the_contract_maximum():
    first = [
        case_payload(
            UUID(int=index + 1),
            created_at=NOW + timedelta(seconds=index),
            next_recovery_at=NOW,
        )
        for index in range(100)
    ]
    last = case_payload(
        UUID(int=101),
        created_at=NOW + timedelta(seconds=100),
        next_recovery_at=NOW,
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.params.get("limit") == "100"
        if len(requests) == 1:
            return response(order_page(first, cursor_for(first[-1])))
        assert request.url.params.get("afterId") == first[-1]["orderId"]
        assert request.url.params.get("afterCreatedAt") == first[-1]["createdAt"].replace("+00:00", "Z")
        return response(order_page([last]))

    result = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(handler))).collect(NOW)
    assert result.complete
    assert len(requests) == 2
    assert result.page_count == 2
    assert len(result.cases) == 101
    assert str(result.cases[-1].order_id) == last["orderId"]


def test_order_client_discards_partial_pages_when_a_later_page_fails():
    item = case_payload()
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response(order_page([item], cursor_for(item)))
        return httpx.Response(503, content=b"sensitive upstream body")

    result = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(handler))).collect(NOW)
    assert not result.complete
    assert result.cases == ()
    assert result.freshness.status == FreshnessStatus.UNAVAILABLE
    assert result.freshness.error_code == "UPSTREAM_HTTP_ERROR"
    assert result.freshness.item_count == 1


def test_order_client_rejects_repeated_cursor_and_duplicate_page_state():
    item = case_payload()

    def handler(request):
        return response(order_page([item], cursor_for(item)))

    client = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.collect(NOW)
    assert not result.complete
    assert result.freshness.error_code == "REPEATED_CURSOR"


def test_order_client_rejects_malformed_cursor_and_unallowlisted_fields():
    item = case_payload()

    def bad_cursor(request):
        return response(order_page([item], {"afterCreatedAt": item["createdAt"]}))

    result = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(bad_cursor))).collect(NOW)
    assert not result.complete
    assert result.freshness.error_code == "MALFORMED_RESPONSE"

    secret_field = dict(item, paymentAmount=20)
    result = OrderAttentionClient(
        Settings(),
        httpx.Client(transport=httpx.MockTransport(lambda request: response(order_page([secret_field])))),
    ).collect(NOW)
    assert not result.complete
    assert result.cases == ()


@pytest.mark.parametrize(
    ("handler", "code"),
    [
        (lambda request: httpx.Response(502, content=b"do not echo"), "UPSTREAM_HTTP_ERROR"),
        (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("secret")), "UPSTREAM_TIMEOUT"),
        (lambda request: httpx.Response(200, content=json.dumps(order_page([])).encode(), headers={"content-length": "9999999"}), "RESPONSE_TOO_LARGE"),
    ],
)
def test_order_client_reports_safe_upstream_failure_code_without_partial_success(handler, code):
    result = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(handler))).collect(NOW)
    assert not result.complete
    assert result.cases == ()
    assert result.freshness.error_code == code


def test_order_client_marks_last_success_stale_after_bounded_failure():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return response(order_page([])) if calls == 1 else httpx.Response(503)

    client = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.collect(NOW).freshness.status == FreshnessStatus.CURRENT
    failed = client.collect(NOW + timedelta(seconds=31))
    assert not failed.complete
    assert failed.freshness.status == FreshnessStatus.STALE


def test_terminal_lookup_accounts_for_every_requested_order_and_missing_ids():
    found = case_payload(UUID(int=202), status="FAILED", failure_reason="PAYMENT_DECLINED", inventory_released=True)
    absent = str(UUID(int=203))

    def handler(request):
        assert request.url.path == "/internal/v1/orders/recovery-observations"
        assert request.url.params.get_list("orderIds") == [found["orderId"], absent]
        return response({"items": [found], "missingOrderIds": [absent]})

    client = OrderAttentionClient(Settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.lookup_terminal([found["orderId"], absent], NOW)
    assert result.complete
    assert [str(case.order_id) for case in result.cases] == [found["orderId"]]
    assert result.missing_order_ids == (absent,)
    assert result.freshness.status == FreshnessStatus.PARTIAL


def test_terminal_lookup_failure_or_incomplete_partition_never_returns_cases():
    found = case_payload(UUID(int=204), status="FAILED", failure_reason="PAYMENT_DECLINED", inventory_released=True)
    malformed = {"items": [found], "missingOrderIds": []}
    result = OrderAttentionClient(
        Settings(), httpx.Client(transport=httpx.MockTransport(lambda request: response(malformed)))
    ).lookup_terminal([found["orderId"], str(UUID(int=205))], NOW)
    assert not result.complete
    assert result.cases == ()
    assert result.freshness.error_code == "INCOMPLETE_LOOKUP"

    result = OrderAttentionClient(
        Settings(), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    ).lookup_terminal([found["orderId"]], NOW)
    assert not result.complete
    assert result.cases == ()
    assert result.freshness.status == FreshnessStatus.UNAVAILABLE

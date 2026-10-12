from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from pydantic import ValidationError

from .config import Settings
from .models import (
    FreshnessStatus,
    HealthObservation,
    OrderAttentionPage,
    OrderCursor,
    OrderRecoveryCase,
    OrderRecoveryObservationPage,
    ProbeResult,
    ProbeStatus,
    SourceFreshness,
)


class HealthProbeClient:
    """Fixed-path, bounded probes for the four Compose service readiness endpoints."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.Client | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._client = http_client or _new_http_client(settings)
        self._owns_client = http_client is None
        self._last_success_at: dict[str, datetime] = {}

    def probe_all(self, now: datetime | None = None) -> list[ProbeResult]:
        observed_at = (now or self._clock()).astimezone(timezone.utc)
        results = []
        for service_name, base_url in self._settings.service_base_urls.items():
            results.append(self._probe(service_name, base_url, observed_at))
        return results

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def restore_last_success(self, values: dict[str, datetime]) -> None:
        self._last_success_at.update(values)

    def _probe(self, service_name: str, base_url: str, observed_at: datetime) -> ProbeResult:
        status_code: int | None = None
        signal_code: str
        try:
            with self._client.stream(
                "GET",
                f"{base_url}/actuator/health",
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response:
                status_code = response.status_code
                if status_code != 200:
                    probe_status = ProbeStatus.DOWN
                    signal_code = "HTTP_NON_200"
                else:
                    body = _read_limited(response, self._settings.health_response_limit_bytes)
                    payload = json.loads(body)
                    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
                        probe_status = ProbeStatus.UNKNOWN
                        signal_code = "MALFORMED_HEALTH_RESPONSE"
                    elif payload["status"] == "UP":
                        probe_status = ProbeStatus.UP
                        signal_code = "HEALTH_UP"
                    elif payload["status"]:
                        probe_status = ProbeStatus.DOWN
                        signal_code = "HEALTH_NON_UP"
                    else:
                        probe_status = ProbeStatus.UNKNOWN
                        signal_code = "MALFORMED_HEALTH_RESPONSE"
        except _PayloadTooLarge:
            probe_status = ProbeStatus.UNKNOWN
            signal_code = "HEALTH_RESPONSE_TOO_LARGE"
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError):
            probe_status = ProbeStatus.UNKNOWN
            signal_code = "MALFORMED_HEALTH_RESPONSE"
        except httpx.TimeoutException:
            probe_status = ProbeStatus.TIMEOUT
            signal_code = "PROBE_TIMEOUT"
        except httpx.HTTPError:
            probe_status = ProbeStatus.DOWN
            signal_code = "CONNECT_FAILED"

        observation = HealthObservation(
            serviceName=service_name,
            status=probe_status,
            observedAt=observed_at,
            httpStatus=status_code,
            signalCode=signal_code,
        )
        if probe_status != ProbeStatus.UNKNOWN:
            self._last_success_at[service_name] = observed_at
        last_success_at = self._last_success_at.get(service_name)
        if probe_status == ProbeStatus.UNKNOWN:
            if last_success_at is None:
                freshness_status = FreshnessStatus.UNAVAILABLE
            elif observed_at - last_success_at > timedelta(seconds=self._settings.source_stale_seconds):
                freshness_status = FreshnessStatus.STALE
            else:
                freshness_status = FreshnessStatus.PARTIAL
        else:
            freshness_status = FreshnessStatus.CURRENT
        freshness = SourceFreshness(
            source=service_name,
            status=freshness_status,
            attemptedAt=observed_at,
            lastSuccessAt=last_success_at,
            itemCount=1 if probe_status != ProbeStatus.UNKNOWN else 0,
            errorCode=signal_code if probe_status != ProbeStatus.UP else None,
        )
        return ProbeResult(observation=observation, freshness=freshness)


class OrderAttentionClient:
    """Collects every bounded keyset page; partial data is never returned as complete."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.Client | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._client = http_client or _new_http_client(settings)
        self._owns_client = http_client is None
        self._last_success_at: datetime | None = None

    def collect(self, now: datetime | None = None) -> OrderRecoveryCollection:
        attempted_at = (now or self._clock()).astimezone(timezone.utc)
        cursor: OrderCursor | None = None
        seen_cursors: set[tuple[datetime, int]] = set()
        seen_order_ids: set[str] = set()
        all_items: list[OrderRecoveryCase] = []
        successful_pages = 0
        last_item_key: tuple[datetime, int] | None = None

        for _ in range(self._settings.order_max_pages):
            params: dict[str, str | int] = {"limit": self._settings.order_page_size}
            if cursor is not None:
                params["afterCreatedAt"] = _format_timestamp(cursor.after_created_at)
                params["afterId"] = str(cursor.after_id)

            try:
                response_body = _get_limited_body(
                    self._client,
                    f"{self._settings.order_base_url.rstrip('/')}/internal/v1/orders/attention",
                    params,
                    self._settings.order_response_limit_bytes,
                )
                page = OrderAttentionPage.model_validate_json(response_body)
            except _PayloadTooLarge:
                return self._failed_collection(attempted_at, "RESPONSE_TOO_LARGE", successful_pages, all_items)
            except httpx.TimeoutException:
                return self._failed_collection(attempted_at, "UPSTREAM_TIMEOUT", successful_pages, all_items)
            except httpx.HTTPStatusError:
                return self._failed_collection(attempted_at, "UPSTREAM_HTTP_ERROR", successful_pages, all_items)
            except httpx.HTTPError:
                return self._failed_collection(attempted_at, "UPSTREAM_UNAVAILABLE", successful_pages, all_items)
            except (ValidationError, ValueError, UnicodeDecodeError):
                return self._failed_collection(attempted_at, "MALFORMED_RESPONSE", successful_pages, all_items)

            if page.limit != self._settings.order_page_size:
                return self._failed_collection(attempted_at, "MALFORMED_RESPONSE", successful_pages, all_items)
            successful_pages += 1
            if page.next_cursor is not None:
                requested_cursor = _cursor_tuple(cursor) if cursor is not None else None
                next_key = _cursor_tuple(page.next_cursor)
                if requested_cursor is not None and next_key <= requested_cursor:
                    return self._failed_collection(attempted_at, "REPEATED_CURSOR", successful_pages, all_items)
                if next_key in seen_cursors:
                    return self._failed_collection(attempted_at, "REPEATED_CURSOR", successful_pages, all_items)

            for item in page.items:
                item_id = str(item.order_id)
                if item_id in seen_order_ids:
                    return self._failed_collection(attempted_at, "DUPLICATE_ORDER", successful_pages, all_items)
                item_key = (item.created_at, item.order_id.int)
                if last_item_key is not None and item_key <= last_item_key:
                    return self._failed_collection(attempted_at, "NON_DETERMINISTIC_ORDER", successful_pages, all_items)
                seen_order_ids.add(item_id)
                all_items.append(item)
                last_item_key = item_key
                if len(all_items) > self._settings.order_max_cases:
                    return self._failed_collection(attempted_at, "CASE_LIMIT_EXCEEDED", successful_pages, all_items)

            next_cursor = page.next_cursor
            if next_cursor is None:
                self._last_success_at = attempted_at
                return OrderRecoveryCollection(
                    cases=tuple(all_items),
                    freshness=SourceFreshness(
                        source="order-attention",
                        status=FreshnessStatus.CURRENT,
                        attemptedAt=attempted_at,
                        lastSuccessAt=attempted_at,
                        itemCount=len(all_items),
                    ),
                    complete=True,
                    page_count=successful_pages,
                )

            cursor_key = _cursor_tuple(next_cursor)
            if not page.items:
                return self._failed_collection(attempted_at, "REPEATED_CURSOR", successful_pages, all_items)
            last_item = page.items[-1]
            expected_cursor = (last_item.created_at, last_item.order_id.int)
            if cursor_key != expected_cursor:
                return self._failed_collection(attempted_at, "MALFORMED_CURSOR", successful_pages, all_items)
            seen_cursors.add(cursor_key)
            cursor = next_cursor

        return self._failed_collection(attempted_at, "PAGE_LIMIT_EXCEEDED", successful_pages, all_items)

    def lookup_terminal(self, order_ids: list[str], now: datetime | None = None) -> TerminalObservationCollection:
        attempted_at = (now or self._clock()).astimezone(timezone.utc)
        requested = [str(value) for value in order_ids]
        if len(requested) > self._settings.order_terminal_lookup_limit or len(set(requested)) != len(requested):
            return self._failed_terminal(attempted_at, "LOOKUP_LIMIT_EXCEEDED", 0)
        all_cases: list[OrderRecoveryCase] = []
        missing: list[str] = []
        count = 0
        for offset in range(0, len(requested), 100):
            chunk = requested[offset:offset + 100]
            try:
                params = [("orderIds", order_id) for order_id in chunk]
                body = _get_limited_body(
                    self._client,
                    f"{self._settings.order_base_url.rstrip('/')}/internal/v1/orders/recovery-observations",
                    params,
                    self._settings.order_response_limit_bytes,
                )
                page = OrderRecoveryObservationPage.model_validate_json(body)
            except _PayloadTooLarge:
                return self._failed_terminal(attempted_at, "RESPONSE_TOO_LARGE", count)
            except httpx.TimeoutException:
                return self._failed_terminal(attempted_at, "UPSTREAM_TIMEOUT", count)
            except httpx.HTTPStatusError:
                return self._failed_terminal(attempted_at, "UPSTREAM_HTTP_ERROR", count)
            except httpx.HTTPError:
                return self._failed_terminal(attempted_at, "UPSTREAM_UNAVAILABLE", count)
            except (ValidationError, ValueError, UnicodeDecodeError):
                return self._failed_terminal(attempted_at, "MALFORMED_RESPONSE", count)
            found = {str(case.order_id) for case in page.items}
            absent = {str(value) for value in page.missing_order_ids}
            if found | absent != set(chunk) or found & absent:
                return self._failed_terminal(attempted_at, "INCOMPLETE_LOOKUP", count)
            all_cases.extend(page.items)
            missing.extend(str(value) for value in page.missing_order_ids)
            count += len(page.items)

        self._last_success_at = attempted_at
        freshness = SourceFreshness(
            source="order-attention",
            status=FreshnessStatus.PARTIAL if missing else FreshnessStatus.CURRENT,
            attemptedAt=attempted_at,
            lastSuccessAt=attempted_at,
            itemCount=count,
            errorCode="ORDER_NOT_FOUND" if missing else None,
        )
        return TerminalObservationCollection(tuple(all_cases), freshness, True, tuple(missing))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def restore_last_success(self, value: datetime | None) -> None:
        if value is not None:
            self._last_success_at = value

    def _failed_collection(
        self,
        attempted_at: datetime,
        code: str,
        successful_pages: int,
        partial_items: list[OrderRecoveryCase],
    ) -> OrderRecoveryCollection:
        last_success = self._last_success_at
        if last_success is None:
            freshness_status = FreshnessStatus.UNAVAILABLE
        elif attempted_at - last_success > timedelta(seconds=self._settings.source_stale_seconds):
            freshness_status = FreshnessStatus.STALE
        else:
            freshness_status = FreshnessStatus.PARTIAL
        return OrderRecoveryCollection(
            cases=(),
            freshness=SourceFreshness(
                source="order-attention",
                status=freshness_status,
                attemptedAt=attempted_at,
                lastSuccessAt=last_success,
                itemCount=len(partial_items),
                errorCode=code,
            ),
            complete=False,
            page_count=successful_pages,
        )

    def _failed_terminal(self, attempted_at: datetime, code: str, item_count: int) -> TerminalObservationCollection:
        last_success = self._last_success_at
        freshness_status = (
            FreshnessStatus.UNAVAILABLE if last_success is None
            else FreshnessStatus.STALE if attempted_at - last_success > timedelta(seconds=self._settings.source_stale_seconds)
            else FreshnessStatus.PARTIAL
        )
        return TerminalObservationCollection(
            (), SourceFreshness(
                source="order-attention", status=freshness_status, attemptedAt=attempted_at,
                lastSuccessAt=last_success, itemCount=item_count, errorCode=code,
            ), False,
        )


class OrderRecoveryCollection:
    """Explicit all-pages result; an incomplete read intentionally carries no usable cases."""

    __slots__ = ("cases", "freshness", "complete", "page_count")

    def __init__(
        self,
        cases: tuple[OrderRecoveryCase, ...],
        freshness: SourceFreshness,
        complete: bool,
        page_count: int,
    ) -> None:
        if not complete and cases:
            raise ValueError("partial Order collection must not expose a misleading partial case set")
        self.cases = cases
        self.freshness = freshness
        self.complete = complete
        self.page_count = page_count


class TerminalObservationCollection:
    __slots__ = ("cases", "freshness", "complete", "missing_order_ids")

    def __init__(
        self,
        cases: tuple[OrderRecoveryCase, ...],
        freshness: SourceFreshness,
        complete: bool,
        missing_order_ids: tuple[str, ...] = (),
    ) -> None:
        if not complete and cases:
            raise ValueError("partial terminal observation must not expose cases as complete")
        self.cases = cases
        self.freshness = freshness
        self.complete = complete
        self.missing_order_ids = missing_order_ids


class _PayloadTooLarge(Exception):
    pass


def _new_http_client(settings: Settings) -> httpx.Client:
    timeout = httpx.Timeout(
        settings.request_timeout_seconds,
        connect=settings.connect_timeout_seconds,
    )
    return httpx.Client(timeout=timeout, follow_redirects=False, headers={"Accept-Encoding": "identity"})


def _read_limited(response: httpx.Response, limit: int) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise _PayloadTooLarge
        except ValueError:
            raise _PayloadTooLarge from None
    body = bytearray()
    for chunk in response.iter_bytes(chunk_size=4096):
        body.extend(chunk)
        if len(body) > limit:
            raise _PayloadTooLarge
    return bytes(body)


def _get_limited_body(
    client: httpx.Client,
    url: str,
    params: dict[str, str | int],
    limit: int,
) -> bytes:
    with client.stream(
        "GET",
        url,
        params=params,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    ) as response:
        if response.status_code != 200:
            response.raise_for_status()
        return _read_limited(response, limit)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cursor_tuple(cursor: OrderCursor) -> tuple[datetime, int]:
    return (cursor.after_created_at, cursor.after_id.int)

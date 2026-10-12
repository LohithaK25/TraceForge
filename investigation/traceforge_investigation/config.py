from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_host: str = "postgres"
    database_port: int = 5432
    database_name: str = "traceforge"
    database_user: str = "traceforge"
    database_password: str = field(default="traceforge-local-only", repr=False)
    gateway_base_url: str = "http://api-gateway:8080"
    order_base_url: str = "http://order-service:8082"
    inventory_base_url: str = "http://inventory-service:8081"
    payment_base_url: str = "http://payment-service:8083"
    request_timeout_seconds: float = 2.0
    connect_timeout_seconds: float = 0.5
    health_response_limit_bytes: int = 8192
    order_response_limit_bytes: int = 1_048_576
    order_page_size: int = 100
    order_max_pages: int = 500
    order_max_cases: int = 50_000
    source_stale_seconds: int = 30
    recovery_grace_seconds: int = 30
    detection_interval_seconds: int = 5
    order_terminal_lookup_limit: int = 500

    def __post_init__(self) -> None:
        if not self.database_password:
            raise ValueError("DATABASE_PASSWORD must be configured")
        if not 1 <= self.database_port <= 65535:
            raise ValueError("DATABASE_PORT is out of range")
        if not 0.1 <= self.request_timeout_seconds <= 10:
            raise ValueError("TRACEFORGE_REQUEST_TIMEOUT_SECONDS must be between 0.1 and 10")
        if not 0.1 <= self.connect_timeout_seconds <= self.request_timeout_seconds:
            raise ValueError("TRACEFORGE_CONNECT_TIMEOUT_SECONDS must be positive and no greater than request timeout")
        if self.health_response_limit_bytes < 128 or self.order_response_limit_bytes < 1024:
            raise ValueError("response size bounds are too small")
        if self.order_page_size != 100 or not 1 <= self.order_max_pages <= 1000:
            raise ValueError("Order pagination bounds are invalid")
        if self.order_max_cases < self.order_page_size:
            raise ValueError("TRACEFORGE_ORDER_MAX_CASES must accommodate at least one page")
        if not 1 <= self.source_stale_seconds <= 3600:
            raise ValueError("TRACEFORGE_SOURCE_STALE_SECONDS is out of range")
        if not 0 <= self.recovery_grace_seconds <= 3600:
            raise ValueError("TRACEFORGE_RECOVERY_GRACE_SECONDS is out of range")
        if not 5 <= self.detection_interval_seconds <= 3600:
            raise ValueError("TRACEFORGE_DETECTION_INTERVAL_SECONDS must be between 5 and 3600")
        if not 1 <= self.order_terminal_lookup_limit <= self.order_max_cases:
            raise ValueError("TRACEFORGE_ORDER_TERMINAL_LOOKUP_LIMIT is out of range")
        for value in self.service_base_urls.values():
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("service base URLs must be absolute HTTP(S) URLs without embedded credentials")
            if parsed.query or parsed.fragment:
                raise ValueError("service base URLs must not contain a query or fragment")

    @property
    def service_base_urls(self) -> dict[str, str]:
        return {
            "api-gateway": self.gateway_base_url.rstrip("/"),
            "order-service": self.order_base_url.rstrip("/"),
            "inventory-service": self.inventory_base_url.rstrip("/"),
            "payment-service": self.payment_base_url.rstrip("/"),
        }

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            database_host=os.environ.get("DATABASE_HOST", "postgres"),
            database_port=_int_env("DATABASE_PORT", 5432),
            database_name=os.environ.get("DATABASE_NAME", "traceforge"),
            database_user=os.environ.get("DATABASE_USER", "traceforge"),
            database_password=os.environ.get("DATABASE_PASSWORD", "traceforge-local-only"),
            gateway_base_url=os.environ.get("GATEWAY_BASE_URL", "http://api-gateway:8080"),
            order_base_url=os.environ.get("ORDER_BASE_URL", "http://order-service:8082"),
            inventory_base_url=os.environ.get("INVENTORY_BASE_URL", "http://inventory-service:8081"),
            payment_base_url=os.environ.get("PAYMENT_BASE_URL", "http://payment-service:8083"),
            request_timeout_seconds=_float_env("TRACEFORGE_REQUEST_TIMEOUT_SECONDS", 2.0),
            connect_timeout_seconds=_float_env("TRACEFORGE_CONNECT_TIMEOUT_SECONDS", 0.5),
            health_response_limit_bytes=_int_env("TRACEFORGE_HEALTH_RESPONSE_LIMIT_BYTES", 8192),
            order_response_limit_bytes=_int_env("TRACEFORGE_ORDER_RESPONSE_LIMIT_BYTES", 1_048_576),
            order_page_size=100,
            order_max_pages=_int_env("TRACEFORGE_ORDER_MAX_PAGES", 500),
            order_max_cases=_int_env("TRACEFORGE_ORDER_MAX_CASES", 50_000),
            source_stale_seconds=_int_env("TRACEFORGE_SOURCE_STALE_SECONDS", 30),
            recovery_grace_seconds=_int_env("TRACEFORGE_RECOVERY_GRACE_SECONDS", 30),
            detection_interval_seconds=_int_env("TRACEFORGE_DETECTION_INTERVAL_SECONDS", 5),
            order_terminal_lookup_limit=_int_env("TRACEFORGE_ORDER_TERMINAL_LOOKUP_LIMIT", 500),
        )


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    try:
        return default if value is None else int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    try:
        return default if value is None else float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error

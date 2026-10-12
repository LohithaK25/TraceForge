CREATE TABLE incident_service.incidents (
    id UUID PRIMARY KEY,
    rule_key VARCHAR(64) NOT NULL CHECK (rule_key IN ('SERVICE_NOT_READY', 'ORDER_RECOVERY_STALLED')),
    rule_version INTEGER NOT NULL CHECK (rule_version > 0),
    severity VARCHAR(16) NOT NULL CHECK (severity IN ('HIGH', 'CRITICAL')),
    status VARCHAR(16) NOT NULL CHECK (status IN ('OPEN', 'RESOLVED')),
    fingerprint CHAR(64) NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    scope_type VARCHAR(16) NOT NULL CHECK (scope_type IN ('SERVICE', 'ORDER')),
    source_reference VARCHAR(64) NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    last_evaluated_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count >= 1),
    summary VARCHAR(200) NOT NULL,
    evidence JSONB NOT NULL CHECK (
        jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) <= 20
    ),
    origin_trace_id VARCHAR(32) CHECK (origin_trace_id IS NULL OR origin_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'OPEN' AND resolved_at IS NULL) OR (status = 'RESOLVED' AND resolved_at IS NOT NULL))
);

CREATE UNIQUE INDEX incidents_one_open_fingerprint_uq
    ON incident_service.incidents (fingerprint)
    WHERE status = 'OPEN';
CREATE INDEX incidents_status_last_seen_idx
    ON incident_service.incidents (status, last_seen_at DESC);
CREATE INDEX incidents_source_history_idx
    ON incident_service.incidents (rule_key, scope_type, source_reference, created_at DESC);

CREATE TABLE incident_service.health_rule_state (
    service_name VARCHAR(32) PRIMARY KEY CHECK (
        service_name IN ('api-gateway', 'order-service', 'inventory-service', 'payment-service')
    ),
    failure_streak INTEGER NOT NULL DEFAULT 0 CHECK (failure_streak >= 0),
    success_streak INTEGER NOT NULL DEFAULT 0 CHECK (success_streak >= 0),
    last_status VARCHAR(16) CHECK (last_status IS NULL OR last_status IN ('UP', 'DOWN', 'TIMEOUT', 'UNKNOWN')),
    last_observed_at TIMESTAMPTZ,
    incident_open BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

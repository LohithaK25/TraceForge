CREATE TABLE incident_service.detection_cycles (
    cycle_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL CHECK (status IN ('RUNNING', 'COMPLETE', 'PARTIAL', 'FAILED')),
    findings_opened_or_updated INTEGER NOT NULL DEFAULT 0 CHECK (findings_opened_or_updated >= 0),
    incidents_resolved INTEGER NOT NULL DEFAULT 0 CHECK (incidents_resolved >= 0),
    failure_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX detection_cycles_started_at_idx
    ON incident_service.detection_cycles (started_at DESC, cycle_id DESC);

CREATE TABLE incident_service.detection_source_state (
    source VARCHAR(64) PRIMARY KEY,
    status VARCHAR(16) NOT NULL CHECK (status IN ('CURRENT', 'PARTIAL', 'STALE', 'UNAVAILABLE')),
    attempted_at TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    error_code VARCHAR(64),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

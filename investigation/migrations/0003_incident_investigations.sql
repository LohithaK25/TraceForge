CREATE TABLE incident_service.investigations (
    incident_id UUID PRIMARY KEY REFERENCES incident_service.incidents(id) ON DELETE CASCADE,
    investigation_id UUID NOT NULL UNIQUE,
    generated_at TIMESTAMPTZ NOT NULL,
    result JSONB NOT NULL CHECK (
        jsonb_typeof(result) = 'object' AND octet_length(result::text) <= 262144
    ),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX investigations_generated_at_idx
    ON incident_service.investigations (generated_at DESC, investigation_id DESC);

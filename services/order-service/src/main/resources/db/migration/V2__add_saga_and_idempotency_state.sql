ALTER TABLE orders
    ADD COLUMN idempotency_key VARCHAR(128),
    ADD COLUMN payment_authorization_id UUID,
    ADD COLUMN inventory_released BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN recovery_error VARCHAR(64),
    ADD COLUMN recovery_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_recovery_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE orders
SET idempotency_key = id::text,
    status = CASE status
        WHEN 'PENDING_INVENTORY' THEN 'PENDING'
        WHEN 'REJECTED' THEN 'FAILED'
        ELSE status
    END;

ALTER TABLE orders
    ALTER COLUMN idempotency_key SET NOT NULL,
    ADD CONSTRAINT orders_idempotency_key_unique UNIQUE (idempotency_key),
    ADD CONSTRAINT orders_status_check CHECK (status IN (
        'PENDING', 'INVENTORY_RESERVED', 'PAYMENT_AUTHORIZED', 'CONFIRMED', 'FAILED', 'COMPENSATION_REQUIRED'
    ));

CREATE INDEX orders_recoverable_idx ON orders (next_recovery_at, created_at)
    WHERE status IN ('PENDING', 'INVENTORY_RESERVED', 'PAYMENT_AUTHORIZED', 'COMPENSATION_REQUIRED');

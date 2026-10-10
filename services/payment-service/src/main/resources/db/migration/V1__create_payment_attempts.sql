CREATE TABLE payment_attempts (
    authorization_id UUID UNIQUE,
    order_id UUID NOT NULL UNIQUE,
    idempotency_key VARCHAR(128) PRIMARY KEY,
    amount_minor INTEGER NOT NULL CHECK (amount_minor BETWEEN 1 AND 100000000),
    status VARCHAR(16) NOT NULL CHECK (status IN ('AUTHORIZED', 'DECLINED')),
    failure_reason VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL,
    CHECK ((status = 'AUTHORIZED' AND authorization_id IS NOT NULL AND failure_reason IS NULL)
        OR (status = 'DECLINED' AND authorization_id IS NULL AND failure_reason IS NOT NULL))
);

CREATE TABLE orders (
    id UUID PRIMARY KEY,
    sku VARCHAR(32) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(32) NOT NULL,
    failure_reason VARCHAR(64),
    inventory_reservation_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX orders_created_at_idx ON orders (created_at DESC);

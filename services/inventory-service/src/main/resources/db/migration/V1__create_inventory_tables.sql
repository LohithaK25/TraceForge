CREATE TABLE inventory_items (
    sku VARCHAR(32) PRIMARY KEY,
    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inventory_reservations (
    reservation_id UUID PRIMARY KEY,
    order_id UUID NOT NULL UNIQUE,
    sku VARCHAR(32) NOT NULL REFERENCES inventory_items (sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    created_at TIMESTAMPTZ NOT NULL
);

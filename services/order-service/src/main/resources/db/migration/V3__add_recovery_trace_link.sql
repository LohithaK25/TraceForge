ALTER TABLE orders
    ADD COLUMN origin_trace_id varchar(32),
    ADD COLUMN origin_span_id varchar(16);

ALTER TABLE orders
    ADD CONSTRAINT orders_origin_trace_context_check CHECK (
        (origin_trace_id IS NULL AND origin_span_id IS NULL)
        OR (
            origin_trace_id ~ '^[0-9a-f]{32}$'
            AND origin_span_id ~ '^[0-9a-f]{16}$'
        )
    );

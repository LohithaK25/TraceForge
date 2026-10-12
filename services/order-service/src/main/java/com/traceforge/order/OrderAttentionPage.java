package com.traceforge.order;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record OrderAttentionPage(List<OrderAttention> items, int limit, Cursor nextCursor) {
    public OrderAttentionPage {
        items = List.copyOf(items);
    }

    public record Cursor(Instant afterCreatedAt, UUID afterId) {}
}

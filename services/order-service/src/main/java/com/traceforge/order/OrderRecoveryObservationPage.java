package com.traceforge.order;

import java.util.List;
import java.util.UUID;

/** A bounded allowlisted lookup result for Order IDs already known to the internal detector. */
public record OrderRecoveryObservationPage(List<OrderAttention> items, List<UUID> missingOrderIds) {
    public OrderRecoveryObservationPage {
        items = List.copyOf(items);
        missingOrderIds = List.copyOf(missingOrderIds);
    }
}

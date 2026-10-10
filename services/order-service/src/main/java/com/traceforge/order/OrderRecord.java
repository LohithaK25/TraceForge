package com.traceforge.order;

import java.time.Instant;
import java.util.UUID;

public record OrderRecord(
        UUID id,
        String sku,
        int quantity,
        OrderStatus status,
        String failureReason,
        String recoveryError,
        UUID inventoryReservationId,
        UUID paymentAuthorizationId,
        boolean inventoryReleased,
        Instant createdAt,
        Instant updatedAt) {}

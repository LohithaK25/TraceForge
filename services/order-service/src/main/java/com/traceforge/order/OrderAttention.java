package com.traceforge.order;

import java.time.Instant;
import java.util.UUID;

/** An allowlisted view of a persisted order that may need recovery attention. */
public record OrderAttention(
        UUID orderId,
        OrderStatus status,
        String failureReason,
        String recoveryError,
        int recoveryAttempts,
        Instant nextRecoveryAt,
        boolean inventoryReleased,
        Instant createdAt,
        Instant updatedAt,
        String originTraceId) {}

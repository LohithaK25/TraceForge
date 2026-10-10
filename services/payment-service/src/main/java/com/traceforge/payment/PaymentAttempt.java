package com.traceforge.payment;

import java.time.Instant;
import java.util.UUID;

public record PaymentAttempt(
        UUID authorizationId,
        UUID orderId,
        String idempotencyKey,
        int amountMinor,
        PaymentStatus status,
        String failureReason,
        Instant createdAt) {}

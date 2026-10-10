package com.traceforge.payment;

import java.util.UUID;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

public record PaymentAuthorizationRequest(
        @NotNull UUID orderId,
        @NotNull @Min(1) @Max(100_000_000) Integer amountMinor) {}

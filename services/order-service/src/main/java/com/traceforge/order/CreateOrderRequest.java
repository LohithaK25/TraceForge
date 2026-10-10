package com.traceforge.order;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;

public record CreateOrderRequest(
        @NotBlank @Pattern(regexp = "[A-Z0-9][A-Z0-9-]{0,31}") String sku,
        @NotNull @Min(1) @Max(1000) Integer quantity) {}

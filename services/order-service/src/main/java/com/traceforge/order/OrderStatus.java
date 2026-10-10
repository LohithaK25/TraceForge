package com.traceforge.order;

public enum OrderStatus {
    PENDING,
    INVENTORY_RESERVED,
    PAYMENT_AUTHORIZED,
    CONFIRMED,
    FAILED,
    COMPENSATION_REQUIRED
}

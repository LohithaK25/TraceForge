package com.traceforge.order;

import java.util.Optional;

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import org.springframework.stereotype.Component;

@Component
public class OrderTracing {
    private final Tracer tracer;

    public OrderTracing() {
        this(GlobalOpenTelemetry.getTracer("com.traceforge.order", "0.1.0"));
    }

    OrderTracing(Tracer tracer) {
        this.tracer = tracer;
    }

    public Span startCreateSpan() {
        return tracer.spanBuilder("order.create").setSpanKind(SpanKind.INTERNAL).startSpan();
    }

    public Span startRecoverySpan(boolean scheduled, Optional<SpanContext> origin) {
        var builder = tracer.spanBuilder(scheduled ? "order.recovery.worker" : "order.recovery");
        if (scheduled) {
            builder.setNoParent();
        } else {
            builder.setParent(Context.current());
        }
        origin.filter(SpanContext::isValid).ifPresent(builder::addLink);
        return builder.setSpanKind(SpanKind.INTERNAL).startSpan();
    }

    public void recordResult(Span span, OrderRecord order) {
        span.setAttribute("order.id", order.id().toString());
        span.setAttribute("order.state", order.status().name());
        if (order.inventoryReservationId() != null) {
            span.setAttribute("inventory.reservation.id", order.inventoryReservationId().toString());
        }
        if (order.paymentAuthorizationId() != null) {
            span.setAttribute("payment.authorization.id", order.paymentAuthorizationId().toString());
        }
        String outcome = switch (order.status()) {
            case CONFIRMED -> "confirmed";
            case FAILED -> "failed";
            case COMPENSATION_REQUIRED -> "compensation_pending";
            case PENDING, INVENTORY_RESERVED, PAYMENT_AUTHORIZED -> "recovery_pending";
        };
        span.setAttribute("order.outcome", outcome);
        if (order.failureReason() != null) {
            span.setAttribute("order.failure.reason", order.failureReason());
        }
        if (order.recoveryError() != null) {
            span.setAttribute("order.recovery.error", order.recoveryError());
        }
        if ("confirmed".equals(outcome)) {
            span.setStatus(StatusCode.OK);
        } else if ("failed".equals(outcome) || "compensation_pending".equals(outcome)
                || order.recoveryError() != null) {
            span.setStatus(StatusCode.ERROR, order.failureReason() != null
                    ? order.failureReason() : order.recoveryError());
        }
    }

    public void recordException(Span span, RuntimeException exception) {
        span.setStatus(StatusCode.ERROR, "ORDER_OPERATION_FAILED");
        // Keep the exception type, but omit free-form messages that might contain request data.
        span.addEvent("exception", io.opentelemetry.api.common.Attributes.of(
                io.opentelemetry.api.common.AttributeKey.stringKey("exception.type"),
                exception.getClass().getName()));
    }

    public static SpanContext remoteSpanContext(String traceId, String spanId) {
        if (traceId == null || spanId == null) {
            return SpanContext.getInvalid();
        }
        return SpanContext.create(traceId, spanId, TraceFlags.getSampled(), TraceState.getDefault());
    }
}

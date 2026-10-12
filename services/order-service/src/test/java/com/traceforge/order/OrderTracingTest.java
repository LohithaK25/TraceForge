package com.traceforge.order;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class OrderTracingTest {
    private InMemorySpanExporter exporter;
    private SdkTracerProvider tracerProvider;
    private OrderTracing tracing;

    @BeforeEach
    void setUp() {
        exporter = InMemorySpanExporter.create();
        tracerProvider = SdkTracerProvider.builder()
                .addSpanProcessor(SimpleSpanProcessor.create(exporter))
                .build();
        tracing = new OrderTracing(tracerProvider.get("traceforge-order-test"));
    }

    @AfterEach
    void tearDown() {
        tracerProvider.close();
    }

    @Test
    void scheduledRecoveryStartsANewTraceAndLinksTheOriginatingOperation() {
        SpanContext origin = SpanContext.create(
                "0123456789abcdef0123456789abcdef",
                "0123456789abcdef",
                TraceFlags.getSampled(),
                TraceState.getDefault());

        Span recovery = tracing.startRecoverySpan(true, Optional.of(origin));
        recovery.setAttribute("order.id", "b2d62203-cc85-4d80-8e94-540bb3e56cb8");
        recovery.end();

        SpanData data = exporter.getFinishedSpanItems().getFirst();
        assertEquals("order.recovery.worker", data.getName());
        assertFalse(data.getParentSpanContext().isValid());
        assertEquals(1, data.getLinks().size());
        assertEquals(origin.getTraceId(), data.getLinks().getFirst().getSpanContext().getTraceId());
        assertEquals(origin.getSpanId(), data.getLinks().getFirst().getSpanContext().getSpanId());
    }

    @Test
    void manualRecoveryKeepsItsRequestParentAndAddsOriginLink() {
        var tracer = tracerProvider.get("traceforge-order-test");
        Span request = tracer.spanBuilder("http.server").startSpan();
        SpanContext origin = SpanContext.create(
                "1123456789abcdef0123456789abcdef",
                "1123456789abcdef",
                TraceFlags.getSampled(),
                TraceState.getDefault());

        try (var scope = request.makeCurrent()) {
            Span recovery = tracing.startRecoverySpan(false, Optional.of(origin));
            recovery.end();
        } finally {
            request.end();
        }

        SpanData data = exporter.getFinishedSpanItems().stream()
                .filter(span -> span.getName().equals("order.recovery"))
                .findFirst()
                .orElseThrow();
        assertTrue(data.getParentSpanContext().isValid());
        assertEquals(request.getSpanContext().getSpanId(), data.getParentSpanContext().getSpanId());
        assertEquals(origin.getTraceId(), data.getLinks().getFirst().getSpanContext().getTraceId());
    }
}

package com.traceforge.gateway;

import java.util.List;

public record TraceSummary(String traceId, List<SpanSummary> spans, boolean truncated) {
    public TraceSummary {
        spans = List.copyOf(spans);
    }

    public record SpanSummary(
            String service,
            String spanId,
            String parentSpanId,
            String name,
            String startTime,
            String endTime,
            String status,
            String httpMethod,
            String httpRoute,
            Integer httpStatusCode) {}
}

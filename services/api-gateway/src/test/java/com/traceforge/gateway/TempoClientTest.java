package com.traceforge.gateway;

import tools.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class TempoClientTest {
    private static final String TRACE_ID = "0123456789abcdef0123456789abcdef";

    @Test
    void returnsOnlyAllowlistedSpanFieldsFromTempoTrace() {
        String payload = """
                {"trace":{"resourceSpans":[{"resource":{"attributes":[
                  {"key":"service.name","value":{"stringValue":"payment-service"}}]},
                  "scopeSpans":[{"spans":[{"traceId":"%s","spanId":"0123456789abcdef",
                    "parentSpanId":"fedcba9876543210","name":"payment.authorize",
                    "startTimeUnixNano":"1791633600000000000","endTimeUnixNano":"1791633600001000000",
                    "status":{"code":2},"attributes":[
                      {"key":"http.method","value":{"stringValue":"POST"}},
                      {"key":"http.route","value":{"stringValue":"/api/v1/payments/authorize"}},
                      {"key":"http.response.status_code","value":{"intValue":"402"}},
                      {"key":"payment.card","value":{"stringValue":"never expose"}}]}]}]}]}}
                """.formatted(TRACE_ID);
        var fixture = mockServer(payload, 200);

        TraceSummary summary = fixture.client.getTrace(TRACE_ID);

        assertEquals(TRACE_ID, summary.traceId());
        assertFalse(summary.truncated());
        assertEquals(1, summary.spans().size());
        TraceSummary.SpanSummary span = summary.spans().getFirst();
        assertEquals("payment-service", span.service());
        assertEquals("payment.authorize", span.name());
        assertEquals("ERROR", span.status());
        assertEquals("POST", span.httpMethod());
        assertEquals("/api/v1/payments/authorize", span.httpRoute());
        assertEquals(402, span.httpStatusCode());
        assertTrue(span.startTime().startsWith("2026-"));
        assertFalse(JsonMapper.builder().build().valueToTree(summary).toString().contains("never expose"));
        fixture.server.verify();
    }

    @Test
    void supportsTempoLegacyBatchesAndConvertsBase64Ids() {
        byte[] traceId = java.util.HexFormat.of().parseHex(TRACE_ID);
        String base64TraceId = java.util.Base64.getEncoder().encodeToString(traceId);
        String payload = """
                {"batches":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"order-service"}}]},
                "spans":[{"traceId":"%s","spanId":"%s","name":"order.create","status":{"code":"1"}}]}]}
                """.formatted(base64TraceId, java.util.Base64.getEncoder().encodeToString(new byte[8]));
        var fixture = mockServer(payload, 200);

        TraceSummary summary = fixture.client.getTrace(TRACE_ID);

        assertEquals("0000000000000000", summary.spans().getFirst().spanId());
        assertEquals("order-service", summary.spans().getFirst().service());
        assertEquals("OK", summary.spans().getFirst().status());
        assertNull(summary.spans().getFirst().parentSpanId());
        fixture.server.verify();
    }

    @Test
    void doesNotReturnOtherTraceIdsAndHandlesMissingOrUnavailableTempo() {
        var mismatch = mockServer("""
                {"resourceSpans":[{"resource":{"attributes":[]},"scopeSpans":[{"spans":[
                  {"traceId":"ffffffffffffffffffffffffffffffff","spanId":"0123456789abcdef","name":"other"}]}]}]}
                """ , 200);
        assertEquals(HttpStatus.NOT_FOUND,
                assertThrows(ResponseStatusException.class, () -> mismatch.client.getTrace(TRACE_ID)).getStatusCode());
        mismatch.server.verify();

        var missing = mockServer("", 404);
        assertEquals(HttpStatus.NOT_FOUND,
                assertThrows(ResponseStatusException.class, () -> missing.client.getTrace(TRACE_ID)).getStatusCode());
        missing.server.verify();

        var unavailable = mockServer("", 503);
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE,
                assertThrows(ResponseStatusException.class, () -> unavailable.client.getTrace(TRACE_ID)).getStatusCode());
        unavailable.server.verify();
    }

    @Test
    void boundsSpanCountAndResponseBytes() {
        StringBuilder spans = new StringBuilder();
        for (int index = 0; index < 251; index++) {
            if (index > 0) spans.append(',');
            spans.append("{\"traceId\":\"").append(TRACE_ID)
                    .append("\",\"spanId\":\"").append(String.format("%016x", index))
                    .append("\",\"name\":\"span\"}");
        }
        String trace = "{\"resourceSpans\":[{\"resource\":{\"attributes\":[]},\"scopeSpans\":[{\"spans\":["
                + spans + "]}]}]}";
        var bounded = mockServer(trace, 200);
        TraceSummary summary = bounded.client.getTrace(TRACE_ID);
        assertEquals(250, summary.spans().size());
        assertTrue(summary.truncated());
        bounded.server.verify();

        var oversized = mockServer(" ".repeat(1_048_577), 200);
        assertEquals(HttpStatus.BAD_GATEWAY,
                assertThrows(ResponseStatusException.class, () -> oversized.client.getTrace(TRACE_ID)).getStatusCode());
        oversized.server.verify();
    }

    private static Fixture mockServer(String payload, int status) {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        var response = status == 200
                ? withSuccess(payload, MediaType.APPLICATION_JSON)
                : withStatus(HttpStatus.valueOf(status));
        server.expect(requestTo("http://tempo:3200/api/v2/traces/" + TRACE_ID)).andRespond(response);
        return new Fixture(server, new TempoClient("http://tempo:3200", builder.build(), JsonMapper.builder().build()));
    }

    private record Fixture(MockRestServiceServer server, TempoClient client) {}
}

package com.traceforge.gateway;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

@Component
public class TempoClient {
    private static final int MAX_RESPONSE_BYTES = 1_048_576;
    private static final int MAX_SPANS = 250;

    private final String baseUrl;
    private final RestClient restClient;
    private final JsonMapper objectMapper;

    @Autowired
    public TempoClient(
            @Value("${traceforge.tempo.base-url}") String baseUrl,
            @Value("${traceforge.tempo.connect-timeout:1s}") Duration connectTimeout,
            @Value("${traceforge.tempo.read-timeout:3s}") Duration readTimeout,
            JsonMapper objectMapper) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(connectTimeout);
        requestFactory.setReadTimeout(readTimeout);
        this.baseUrl = baseUrl;
        this.restClient = RestClient.builder().requestFactory(requestFactory).build();
        this.objectMapper = objectMapper;
    }

    TempoClient(String baseUrl, RestClient restClient, JsonMapper objectMapper) {
        this.baseUrl = baseUrl;
        this.restClient = restClient;
        this.objectMapper = objectMapper;
    }

    public TraceSummary getTrace(String traceId) {
        try {
            return restClient.get()
                    .uri(URI.create(baseUrl + "/api/v2/traces/" + traceId))
                    .accept(MediaType.APPLICATION_JSON)
                    .exchange((request, response) -> {
                        if (response.getStatusCode().value() == 404) {
                            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Trace is not available in Tempo");
                        }
                        if (!response.getStatusCode().is2xxSuccessful()) {
                            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Tempo trace storage is unavailable");
                        }
                        return parse(traceId, readLimited(response.getBody()));
                    });
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Tempo trace storage is unavailable");
        }
    }

    private TraceSummary parse(String traceId, byte[] payload) {
        final JsonNode root;
        try {
            root = objectMapper.readTree(payload);
        } catch (JacksonException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Tempo returned an unreadable trace response");
        }
        if (root == null || !root.isObject()) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Tempo returned an unexpected trace response");
        }

        JsonNode trace = root.has("trace") && root.get("trace").isObject() ? root.get("trace") : root;
        List<TraceSummary.SpanSummary> spans = new ArrayList<>();
        int[] matchingSpanCount = {0};
        JsonNode resourceSpans = trace.path("resourceSpans");
        if (resourceSpans.isArray()) {
            resourceSpans.forEach(resourceSpan -> {
                String service = attribute(resourceSpan.path("resource").path("attributes"), "service.name");
                JsonNode scopeSpans = resourceSpan.path("scopeSpans");
                if (scopeSpans.isArray()) scopeSpans.forEach(scope -> addSpans(scope.path("spans"), service, traceId, spans, matchingSpanCount));
            });
        }
        JsonNode batches = trace.path("batches");
        if (batches.isArray()) {
            batches.forEach(batch -> {
                String service = attribute(batch.path("resource").path("attributes"), "service.name");
                JsonNode scopeSpans = batch.path("scopeSpans");
                if (scopeSpans.isArray()) {
                    scopeSpans.forEach(scope -> addSpans(scope.path("spans"), service, traceId, spans, matchingSpanCount));
                } else {
                    addSpans(batch.path("spans"), service, traceId, spans, matchingSpanCount);
                }
            });
        }
        if (matchingSpanCount[0] == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Trace is not available in Tempo");
        }
        return new TraceSummary(traceId, spans, matchingSpanCount[0] > MAX_SPANS);
    }

    private static void addSpans(
            JsonNode spanNodes,
            String service,
            String requestedTraceId,
            List<TraceSummary.SpanSummary> spans,
            int[] matchingSpanCount) {
        if (!spanNodes.isArray()) return;
        spanNodes.forEach(span -> {
            String actualTraceId = normalizeId(text(span.get("traceId")));
            if (!requestedTraceId.equals(actualTraceId)) return;
            String spanId = normalizeId(text(span.get("spanId")));
            if (spanId == null) return;
            matchingSpanCount[0]++;
            if (spans.size() >= MAX_SPANS) return;
            JsonNode attrs = span.path("attributes");
            spans.add(new TraceSummary.SpanSummary(
                    safeServiceName(service),
                    spanId,
                    normalizeId(text(span.get("parentSpanId"))),
                    safeName(text(span.get("name"))),
                    toTimestamp(span.get("startTimeUnixNano")),
                    toTimestamp(span.get("endTimeUnixNano")),
                    spanStatus(span.path("status").path("code")),
                    safeHttpMethod(firstAttribute(attrs, "http.request.method", "http.method")),
                    safeHttpRoute(firstAttribute(attrs, "http.route")),
                    integerAttribute(attrs, "http.response.status_code", "http.status_code")));
        });
    }

    private static String attribute(JsonNode attributes, String key) {
        if (!attributes.isArray()) return null;
        for (JsonNode item : attributes) {
            if (key.equals(text(item.get("key")))) return attributeValue(item.path("value"));
        }
        return null;
    }

    private static String firstAttribute(JsonNode attrs, String... keys) {
        for (String key : keys) {
            String value = attribute(attrs, key);
            if (value != null) return value;
        }
        return null;
    }

    private static Integer integerAttribute(JsonNode attrs, String... keys) {
        String value = firstAttribute(attrs, keys);
        if (value == null) return null;
        try {
            int result = Integer.parseInt(value);
            return result >= 100 && result <= 599 ? result : null;
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static String attributeValue(JsonNode value) {
        for (String key : List.of("stringValue", "intValue", "boolValue", "doubleValue")) {
            JsonNode field = value.get(key);
            if (field != null && !field.isNull()) return field.asText();
        }
        return null;
    }

    private static String text(JsonNode node) {
        return node == null || node.isNull() ? null : node.asText();
    }

    private static String normalizeId(String value) {
        if (value == null || value.isBlank()) return null;
        String normalized = value.toLowerCase(Locale.ROOT);
        if (normalized.matches("[0-9a-f]{16}|[0-9a-f]{32}")) return normalized;
        try {
            byte[] bytes = Base64.getDecoder().decode(value);
            if (bytes.length != 8 && bytes.length != 16) return null;
            StringBuilder hex = new StringBuilder(bytes.length * 2);
            for (byte item : bytes) hex.append(String.format(Locale.ROOT, "%02x", item));
            return hex.toString();
        } catch (IllegalArgumentException ignored) {
            return null;
        }
    }

    private static String toTimestamp(JsonNode value) {
        String raw = text(value);
        if (raw == null || !raw.matches("[0-9]{1,24}")) return null;
        try {
            long nanos = Long.parseLong(raw);
            long seconds = Math.floorDiv(nanos, 1_000_000_000L);
            long remainder = Math.floorMod(nanos, 1_000_000_000L);
            return Instant.ofEpochSecond(seconds, remainder).toString();
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    private static String spanStatus(JsonNode value) {
        String code = text(value);
        if ("1".equals(code) || "OK".equalsIgnoreCase(code) || "STATUS_CODE_OK".equalsIgnoreCase(code)) return "OK";
        if ("2".equals(code) || "ERROR".equalsIgnoreCase(code) || "STATUS_CODE_ERROR".equalsIgnoreCase(code)) return "ERROR";
        return "UNSET";
    }

    private static String safeName(String value) {
        if (value == null || value.isBlank()) return "unnamed";
        return value.length() <= 120 ? value : value.substring(0, 120);
    }

    private static String safeServiceName(String value) {
        if (value == null || value.length() > 64 || !value.matches("[a-zA-Z0-9._-]+")) return "unknown";
        return value;
    }

    private static String safeHttpMethod(String value) {
        if (value == null) return null;
        String method = value.toUpperCase(Locale.ROOT);
        return List.of("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS").contains(method) ? method : null;
    }

    private static String safeHttpRoute(String value) {
        if (value == null || value.length() > 180 || !value.startsWith("/") || value.contains("?") || value.contains("#")) return null;
        return value.matches("/[a-zA-Z0-9_./{}-]*") ? value : null;
    }

    private static byte[] readLimited(InputStream input) {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int total = 0;
        int read;
        try {
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > MAX_RESPONSE_BYTES) {
                    throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Tempo trace response exceeded the size limit");
                }
                output.write(buffer, 0, read);
            }
        } catch (IOException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Tempo trace response could not be read");
        }
        return output.toByteArray();
    }
}

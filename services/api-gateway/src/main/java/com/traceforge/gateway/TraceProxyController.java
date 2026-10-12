package com.traceforge.gateway;

import java.util.regex.Pattern;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class TraceProxyController {
    private static final Pattern TRACE_ID = Pattern.compile("^[0-9a-f]{32}$");
    private final TempoClient tempoClient;

    public TraceProxyController(TempoClient tempoClient) {
        this.tempoClient = tempoClient;
    }

    @GetMapping("/api/v1/traces/{traceId}")
    public TraceSummary getTrace(@PathVariable String traceId) {
        if (!TRACE_ID.matcher(traceId).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Trace ID must be 32 lowercase hexadecimal characters");
        }
        return tempoClient.getTrace(traceId);
    }
}

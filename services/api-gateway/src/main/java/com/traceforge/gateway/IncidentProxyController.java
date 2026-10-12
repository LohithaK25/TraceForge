package com.traceforge.gateway;

import java.util.UUID;
import java.util.regex.Pattern;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class IncidentProxyController {
    private static final Pattern CURSOR = Pattern.compile("[A-Za-z0-9_-]{1,256}");
    private final InvestigationClient investigationClient;

    public IncidentProxyController(InvestigationClient investigationClient) {
        this.investigationClient = investigationClient;
    }

    @GetMapping("/incidents")
    public ResponseEntity<byte[]> list(
            @RequestParam(defaultValue = "OPEN") String status,
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(required = false) String cursor) {
        if (!(status.equals("OPEN") || status.equals("RESOLVED"))) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "Unsupported incident status filter");
        }
        if (limit < 1 || limit > 100) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "limit must be between 1 and 100");
        }
        if (cursor != null && !CURSOR.matcher(cursor).matches()) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "Invalid incident cursor");
        }
        return toResponse(investigationClient.list(status, limit, cursor));
    }

    @GetMapping("/incidents/{id}")
    public ResponseEntity<byte[]> get(@PathVariable UUID id) {
        return toResponse(investigationClient.get(id));
    }

    @GetMapping("/detection-status")
    public ResponseEntity<byte[]> detectionStatus() {
        return toResponse(investigationClient.detectionStatus());
    }

    private static ResponseEntity<byte[]> toResponse(InvestigationClient.ForwardedResponse forwarded) {
        ResponseEntity.BodyBuilder response = ResponseEntity.status(forwarded.status());
        if (forwarded.contentType() != null) response.contentType(forwarded.contentType());
        return response.body(forwarded.body());
    }
}

package com.traceforge.gateway;

import java.util.UUID;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderProxyController {
    private final OrderClient orderClient;

    public OrderProxyController(OrderClient orderClient) {
        this.orderClient = orderClient;
    }

    @PostMapping
    public ResponseEntity<byte[]> create(
            @RequestBody OrderCreateRequest request,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader(name = "X-TraceForge-Failure", required = false) String failureScenario) {
        return toResponse(orderClient.create(request, idempotencyKey, failureScenario));
    }

    @GetMapping("/{id}")
    public ResponseEntity<byte[]> get(@PathVariable UUID id) {
        return toResponse(orderClient.get(id));
    }

    @PostMapping("/{id}/recover")
    public ResponseEntity<byte[]> recover(@PathVariable UUID id) {
        return toResponse(orderClient.recover(id));
    }

    private static ResponseEntity<byte[]> toResponse(OrderClient.ForwardedResponse forwarded) {
        ResponseEntity.BodyBuilder response = ResponseEntity.status(forwarded.status());
        if (forwarded.contentType() != null) {
            response.contentType(forwarded.contentType());
        }
        return response.body(forwarded.body());
    }

    public record OrderCreateRequest(String sku, Integer quantity) {}
}

package com.traceforge.order;

import java.util.UUID;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import jakarta.validation.Valid;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/v1/orders")
public class OrderController {
    private static final Pattern IDEMPOTENCY_KEY = Pattern.compile("[A-Za-z0-9._:-]{1,128}");
    private static final int DEFAULT_ATTENTION_PAGE_SIZE = 50;
    private static final int MAX_ATTENTION_PAGE_SIZE = 100;
    private static final List<String> LOCAL_FAILURES = List.of(
            "inventory-unavailable",
            "inventory-timeout-after-commit",
            "payment-decline",
            "payment-unavailable",
            "payment-timeout-after-commit",
            "payment-decline-compensation-unavailable");

    private final OrderApplicationService orderService;
    private final Environment environment;

    public OrderController(OrderApplicationService orderService, Environment environment) {
        this.orderService = orderService;
        this.environment = environment;
    }

    @PostMapping
    public ResponseEntity<OrderRecord> create(
            @Valid @RequestBody CreateOrderRequest request,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader(name = "X-TraceForge-Failure", required = false) String failureScenario) {
        if (!IDEMPOTENCY_KEY.matcher(idempotencyKey).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key has invalid syntax");
        }
        validateFailureScenario(failureScenario);

        return toCreateResponse(orderService.create(request, idempotencyKey, failureScenario));
    }

    @GetMapping("/{id}")
    public OrderRecord get(@PathVariable UUID id) {
        return orderService.get(id);
    }

    @GetMapping("/attention")
    public OrderAttentionPage attention(
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(required = false) Instant afterCreatedAt,
            @RequestParam(required = false) UUID afterId) {
        if (limit < 1 || limit > MAX_ATTENTION_PAGE_SIZE) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "limit must be between 1 and " + MAX_ATTENTION_PAGE_SIZE);
        }
        if ((afterCreatedAt == null) != (afterId == null)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "afterCreatedAt and afterId must be provided together");
        }
        return orderService.findRecoveryAttention(limit, afterCreatedAt, afterId);
    }

    @GetMapping("/recovery-observations")
    public OrderRecoveryObservationPage recoveryObservations(@RequestParam List<UUID> orderIds) {
        if (orderIds.isEmpty() || orderIds.size() > 100 || new HashSet<>(orderIds).size() != orderIds.size()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "orderIds must contain 1 to 100 unique UUIDs");
        }
        List<OrderAttention> items = orderService.findRecoveryObservations(orderIds);
        Set<UUID> found = new HashSet<>();
        items.forEach(item -> found.add(item.orderId()));
        List<UUID> missing = new ArrayList<>();
        for (UUID orderId : orderIds) {
            if (!found.contains(orderId)) missing.add(orderId);
        }
        return new OrderRecoveryObservationPage(items, missing);
    }

    @PostMapping("/{id}/recover")
    public OrderRecord recover(@PathVariable UUID id) {
        if (!environment.acceptsProfiles(Profiles.of("local"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Manual recovery is available only in the local profile");
        }
        return orderService.recover(id);
    }

    private void validateFailureScenario(String failureScenario) {
        if (failureScenario == null) return;
        if (!environment.acceptsProfiles(Profiles.of("local"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Failure injection is available only in the local profile");
        }
        if (!LOCAL_FAILURES.contains(failureScenario)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unsupported local failure scenario");
        }
    }

    private static ResponseEntity<OrderRecord> toCreateResponse(OrderRecord order) {
        return switch (order.status()) {
            case CONFIRMED -> ResponseEntity.status(HttpStatus.CREATED).body(order);
            case FAILED -> ResponseEntity.status(switch (order.failureReason()) {
                case "UNKNOWN_SKU" -> HttpStatus.NOT_FOUND;
                case "INSUFFICIENT_STOCK" -> HttpStatus.CONFLICT;
                case "PAYMENT_DECLINED" -> HttpStatus.PAYMENT_REQUIRED;
                default -> HttpStatus.INTERNAL_SERVER_ERROR;
            }).body(order);
            case PENDING, INVENTORY_RESERVED, PAYMENT_AUTHORIZED, COMPENSATION_REQUIRED ->
                    ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(order);
        };
    }
}

package com.traceforge.inventory;

import java.util.UUID;
import java.util.regex.Pattern;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class InventoryController {
    private static final Tracer TRACER = GlobalOpenTelemetry.getTracer("com.traceforge.inventory", "0.1.0");
    private static final Pattern SKU_PATTERN = Pattern.compile("[A-Z0-9][A-Z0-9-]{0,31}");
    private static final String INVENTORY_UNAVAILABLE = "inventory-unavailable";
    private static final String INVENTORY_TIMEOUT_AFTER_COMMIT = "inventory-timeout-after-commit";
    private static final String COMPENSATION_UNAVAILABLE = "compensation-unavailable";

    private final InventoryOperations inventoryOperations;
    private final Environment environment;

    public InventoryController(InventoryOperations inventoryOperations, Environment environment) {
        this.inventoryOperations = inventoryOperations;
        this.environment = environment;
    }

    @GetMapping("/internal/v1/inventory/{sku}")
    public InventoryOperations.InventoryAvailability getAvailability(@PathVariable String sku) {
        validateSku(sku);
        return inventoryOperations.getAvailability(sku);
    }

    @PostMapping("/internal/v1/inventory/reservations")
    public InventoryOperations.ReservationResponse reserve(
            @Valid @RequestBody ReservationRequest request,
            @RequestHeader(name = "X-TraceForge-Failure", required = false) String failureScenario) {
        Span span = TRACER.spanBuilder("inventory.reserve").startSpan();
        span.setAttribute("order.id", request.orderId().toString());
        span.setAttribute("inventory.operation", "reserve");
        try (Scope scope = span.makeCurrent()) {
            validateFailureScenario(failureScenario, INVENTORY_UNAVAILABLE, INVENTORY_TIMEOUT_AFTER_COMMIT);
            if (INVENTORY_UNAVAILABLE.equals(failureScenario)) {
                // This controlled failure occurs before the transactional reservation can change stock.
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Controlled local inventory failure");
            }
            validateSku(request.sku());
            InventoryOperations.ReservationResponse reservation = inventoryOperations.reserve(request);
            span.setAttribute("inventory.reservation.id", reservation.reservationId().toString());
            span.setAttribute("inventory.outcome", "reserved");
            span.setStatus(StatusCode.OK);
            if (INVENTORY_TIMEOUT_AFTER_COMMIT.equals(failureScenario)) {
                delayPastClientTimeout();
            }
            return reservation;
        } catch (RuntimeException exception) {
            recordError(span, exception);
            throw exception;
        } finally {
            span.end();
        }
    }

    @PostMapping("/internal/v1/inventory/reservations/{orderId}/release")
    public InventoryOperations.ReservationResponse release(
            @PathVariable UUID orderId,
            @RequestHeader(name = "X-TraceForge-Failure", required = false) String failureScenario) {
        Span span = TRACER.spanBuilder("inventory.release").startSpan();
        span.setAttribute("order.id", orderId.toString());
        span.setAttribute("inventory.operation", "release");
        try (Scope scope = span.makeCurrent()) {
            validateFailureScenario(failureScenario, COMPENSATION_UNAVAILABLE);
            if (COMPENSATION_UNAVAILABLE.equals(failureScenario)) {
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Controlled local compensation failure");
            }
            InventoryOperations.ReservationResponse reservation = inventoryOperations.release(orderId);
            span.setAttribute("inventory.reservation.id", reservation.reservationId().toString());
            span.setAttribute("inventory.released", reservation.released());
            span.setAttribute("inventory.outcome", "released");
            span.setStatus(StatusCode.OK);
            return reservation;
        } catch (RuntimeException exception) {
            recordError(span, exception);
            throw exception;
        } finally {
            span.end();
        }
    }

    private static void recordError(Span span, RuntimeException exception) {
        int statusCode = exception instanceof ResponseStatusException responseStatusException
                ? responseStatusException.getStatusCode().value() : HttpStatus.INTERNAL_SERVER_ERROR.value();
        span.setAttribute("http.response.status_code", statusCode);
        span.setAttribute("inventory.outcome", statusCode == HttpStatus.SERVICE_UNAVAILABLE.value()
                ? "unavailable" : "rejected");
        span.setStatus(StatusCode.ERROR, "INVENTORY_OPERATION_FAILED");
        span.addEvent("exception", io.opentelemetry.api.common.Attributes.of(
                AttributeKey.stringKey("exception.type"), exception.getClass().getName()));
    }

    private void validateFailureScenario(String failureScenario, String... supported) {
        if (failureScenario == null) {
            return;
        }
        if (!environment.acceptsProfiles(Profiles.of("local"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Failure injection is available only in the local profile");
        }
        if (!java.util.Arrays.asList(supported).contains(failureScenario)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unsupported local failure scenario");
        }
    }

    private static void delayPastClientTimeout() {
        try {
            Thread.sleep(5_000);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
    }

    private static void validateSku(String sku) {
        if (!SKU_PATTERN.matcher(sku).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "SKU must use uppercase letters, digits, and hyphens");
        }
    }

    public record ReservationRequest(
            @NotNull UUID orderId,
            @NotBlank @jakarta.validation.constraints.Pattern(regexp = "[A-Z0-9][A-Z0-9-]{0,31}") String sku,
            @NotNull @Min(1) @Max(1000) Integer quantity) {}
}

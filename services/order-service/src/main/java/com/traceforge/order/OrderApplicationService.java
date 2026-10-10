package com.traceforge.order;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class OrderApplicationService {
    private static final Logger log = LoggerFactory.getLogger(OrderApplicationService.class);
    private static final String INVENTORY_UNAVAILABLE = "INVENTORY_UNAVAILABLE";
    private static final String PAYMENT_UNAVAILABLE = "PAYMENT_UNAVAILABLE";
    private static final String PAYMENT_DECLINED = "PAYMENT_DECLINED";

    private final OrderRepository orderRepository;
    private final InventoryClient inventoryClient;
    private final PaymentClient paymentClient;

    public OrderApplicationService(
            OrderRepository orderRepository,
            InventoryClient inventoryClient,
            PaymentClient paymentClient) {
        this.orderRepository = orderRepository;
        this.inventoryClient = inventoryClient;
        this.paymentClient = paymentClient;
    }

    public OrderRecord create(CreateOrderRequest request, String idempotencyKey, String failureScenario) {
        OrderRepository.OrderCreation creation = orderRepository.createOrFind(
                idempotencyKey, request.sku(), request.quantity());
        if (!creation.created()) {
            return creation.order();
        }
        return advance(creation.order().id(), failureScenario);
    }

    public OrderRecord get(UUID id) {
        return orderRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Order not found"));
    }

    public OrderRecord recover(UUID id) {
        if (orderRepository.findById(id).isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Order not found");
        }
        return advance(id, null);
    }

    public void recoverPending() {
        for (UUID id : orderRepository.findRecoverableIds(100)) {
            try {
                OrderRecord order = advance(id, null);
                log.info("order recovery checked id={} status={} recoveryError={}", id, order.status(), order.recoveryError());
            } catch (RuntimeException exception) {
                // One failed item must not prevent recovery attempts for the remaining durable work.
                orderRepository.findById(id).ifPresent(order -> {
                    if (order.status() != OrderStatus.CONFIRMED && order.status() != OrderStatus.FAILED) {
                        orderRepository.transition(
                                id, order.status(), order.status(), order.failureReason(), "RECOVERY_INTERNAL_ERROR",
                                null, null, order.inventoryReleased());
                    }
                });
                log.warn("order recovery attempt failed id={} exceptionType={}", id, exception.getClass().getSimpleName());
            }
        }
    }

    private OrderRecord advance(UUID id, String failureScenario) {
        for (int step = 0; step < 8; step++) {
            OrderRecord order = get(id);
            switch (order.status()) {
                case PENDING -> {
                    InventoryClient.InventoryOutcome outcome = inventoryClient.reserve(
                            new InventoryClient.InventoryReservationRequest(order.id(), order.sku(), order.quantity()),
                            inventoryFailure(failureScenario));
                    if (outcome.unavailable()) {
                        String recoveryError = outcome.outcomeUnknown()
                                ? "INVENTORY_OUTCOME_UNKNOWN" : "INVENTORY_RETRY_SCHEDULED";
                        return orderRepository.transition(
                                id, OrderStatus.PENDING, OrderStatus.PENDING, INVENTORY_UNAVAILABLE,
                                recoveryError, null, null, false);
                    }
                    if (outcome.rejectionReason() != null) {
                        return orderRepository.transition(
                                id, OrderStatus.PENDING, OrderStatus.FAILED, outcome.rejectionReason(),
                                null, null, null, false);
                    }
                    var reservation = outcome.reservation();
                    if (!id.equals(reservation.orderId())
                            || !order.sku().equals(reservation.sku())
                            || order.quantity() != reservation.quantity()) {
                        return orderRepository.transition(
                                id, OrderStatus.PENDING, OrderStatus.PENDING, "INVENTORY_RESPONSE_MISMATCH",
                                "INVENTORY_OUTCOME_UNKNOWN", null, null, false);
                    }
                    orderRepository.transition(
                            id, OrderStatus.PENDING, OrderStatus.INVENTORY_RESERVED, null,
                            null, reservation.reservationId(), null, false);
                }
                case INVENTORY_RESERVED -> {
                    PaymentClient.PaymentOutcome outcome = paymentClient.authorize(
                            id, order.quantity(), paymentFailure(failureScenario));
                    if (outcome.unavailable()) {
                        String recoveryError = outcome.outcomeUnknown()
                                ? "PAYMENT_OUTCOME_UNKNOWN" : "PAYMENT_RETRY_SCHEDULED";
                        return orderRepository.transition(
                                id, OrderStatus.INVENTORY_RESERVED, OrderStatus.INVENTORY_RESERVED,
                                PAYMENT_UNAVAILABLE, recoveryError, null, null, false);
                    }
                    if (outcome.failureReason() != null) {
                        // A conflicting durable payment key may refer to an authorization; releasing stock could create a worse mismatch.
                        return orderRepository.transition(
                                id, OrderStatus.INVENTORY_RESERVED, OrderStatus.INVENTORY_RESERVED,
                                outcome.failureReason(), "MANUAL_REVIEW_REQUIRED", null, null, false);
                    }
                    var attempt = outcome.attempt();
                    if (attempt == null || !id.equals(attempt.orderId())) {
                        return orderRepository.transition(
                                id, OrderStatus.INVENTORY_RESERVED, OrderStatus.INVENTORY_RESERVED,
                                "PAYMENT_RESPONSE_MISMATCH", "PAYMENT_OUTCOME_UNKNOWN", null, null, false);
                    }
                    if ("DECLINED".equals(attempt.status())) {
                        orderRepository.transition(
                                id, OrderStatus.INVENTORY_RESERVED, OrderStatus.COMPENSATION_REQUIRED,
                                PAYMENT_DECLINED, null, null, null, false);
                    } else if ("AUTHORIZED".equals(attempt.status()) && attempt.authorizationId() != null) {
                        orderRepository.transition(
                                id, OrderStatus.INVENTORY_RESERVED, OrderStatus.PAYMENT_AUTHORIZED,
                                null, null, null, attempt.authorizationId(), false);
                    } else {
                        return orderRepository.transition(
                                id, OrderStatus.INVENTORY_RESERVED, OrderStatus.INVENTORY_RESERVED,
                                "PAYMENT_RESPONSE_MISMATCH", "PAYMENT_OUTCOME_UNKNOWN", null, null, false);
                    }
                }
                case PAYMENT_AUTHORIZED -> orderRepository.transition(
                        id, OrderStatus.PAYMENT_AUTHORIZED, OrderStatus.CONFIRMED,
                        null, null, null, null, false);
                case COMPENSATION_REQUIRED -> {
                    InventoryClient.ReleaseOutcome outcome = inventoryClient.release(
                            id, compensationFailure(failureScenario));
                    if (outcome.unavailable()) {
                        String recoveryError = outcome.outcomeUnknown()
                                ? "COMPENSATION_OUTCOME_UNKNOWN" : "COMPENSATION_RETRY_SCHEDULED";
                        return orderRepository.transition(
                                id, OrderStatus.COMPENSATION_REQUIRED, OrderStatus.COMPENSATION_REQUIRED,
                                order.failureReason(), recoveryError, null, null, false);
                    }
                    if (outcome.reservation() == null
                            || !id.equals(outcome.reservation().orderId())
                            || !order.inventoryReservationId().equals(outcome.reservation().reservationId())) {
                        return orderRepository.transition(
                                id, OrderStatus.COMPENSATION_REQUIRED, OrderStatus.COMPENSATION_REQUIRED,
                                order.failureReason(), "COMPENSATION_RESPONSE_MISMATCH", null, null, false);
                    }
                    return orderRepository.transition(
                            id, OrderStatus.COMPENSATION_REQUIRED, OrderStatus.FAILED,
                            order.failureReason(), null, null, null, true);
                }
                case CONFIRMED, FAILED -> {
                    return order;
                }
            }
        }
        return get(id);
    }

    private static String inventoryFailure(String scenario) {
        return switch (scenario == null ? "" : scenario) {
            case "inventory-unavailable", "inventory-timeout-after-commit" -> scenario;
            default -> null;
        };
    }

    private static String paymentFailure(String scenario) {
        return switch (scenario == null ? "" : scenario) {
            case "payment-decline", "payment-unavailable", "payment-timeout-after-commit" -> scenario;
            case "payment-decline-compensation-unavailable" -> "payment-decline";
            default -> null;
        };
    }

    private static String compensationFailure(String scenario) {
        return "payment-decline-compensation-unavailable".equals(scenario) ? "compensation-unavailable" : null;
    }
}

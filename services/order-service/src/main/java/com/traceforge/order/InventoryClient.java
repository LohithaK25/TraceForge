package com.traceforge.order;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

@Component
public class InventoryClient {
    private final RestClient restClient;

    public InventoryClient(
            @Value("${traceforge.inventory.base-url}") String baseUrl,
            @Value("${traceforge.inventory.connect-timeout:1s}") Duration connectTimeout,
            @Value("${traceforge.inventory.read-timeout:2s}") Duration readTimeout) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(connectTimeout);
        requestFactory.setReadTimeout(readTimeout);
        this.restClient = RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
    }

    public InventoryOutcome reserve(InventoryReservationRequest request, String failureScenario) {
        try {
            var requestSpec = restClient.post()
                    .uri("/internal/v1/inventory/reservations")
                    .body(request);
            if (failureScenario != null) {
                requestSpec.header("X-TraceForge-Failure", failureScenario);
            }
            InventoryReservationResponse response = requestSpec.retrieve().body(InventoryReservationResponse.class);
            if (response == null) {
                return InventoryOutcome.serviceUnavailable(true);
            }
            if (response.released()) {
                return InventoryOutcome.serviceUnavailable(true);
            }
            return InventoryOutcome.reserved(response);
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().value() == HttpStatus.NOT_FOUND.value()) {
                return InventoryOutcome.rejected("UNKNOWN_SKU");
            }
            if (exception.getStatusCode().value() == HttpStatus.CONFLICT.value()) {
                return InventoryOutcome.rejected("INSUFFICIENT_STOCK");
            }
            return InventoryOutcome.serviceUnavailable(
                    !("inventory-unavailable".equals(failureScenario)
                            && exception.getStatusCode().value() == HttpStatus.SERVICE_UNAVAILABLE.value()));
        } catch (RestClientException exception) {
            return InventoryOutcome.serviceUnavailable(true);
        }
    }

    public ReleaseOutcome release(java.util.UUID orderId, String failureScenario) {
        try {
            var requestSpec = restClient.post().uri("/internal/v1/inventory/reservations/{orderId}/release", orderId);
            if (failureScenario != null) requestSpec.header("X-TraceForge-Failure", failureScenario);
            InventoryReservationResponse response = requestSpec.retrieve().body(InventoryReservationResponse.class);
            if (response == null || !orderId.equals(response.orderId()) || !response.released()) {
                return ReleaseOutcome.unavailable(true);
            }
            return ReleaseOutcome.released(response);
        } catch (RestClientResponseException exception) {
            return ReleaseOutcome.unavailable(
                    !("compensation-unavailable".equals(failureScenario)
                            && exception.getStatusCode().value() == HttpStatus.SERVICE_UNAVAILABLE.value()));
        } catch (RestClientException exception) {
            return ReleaseOutcome.unavailable(true);
        }
    }

    public record InventoryReservationRequest(java.util.UUID orderId, String sku, int quantity) {}

    public record InventoryReservationResponse(
            java.util.UUID reservationId,
            java.util.UUID orderId,
            String sku,
            int quantity,
            int availableQuantity,
            boolean released) {}

    public record InventoryOutcome(InventoryReservationResponse reservation, String rejectionReason, boolean unavailable, boolean outcomeUnknown) {
        static InventoryOutcome reserved(InventoryReservationResponse reservation) {
            return new InventoryOutcome(reservation, null, false, false);
        }

        static InventoryOutcome rejected(String reason) {
            return new InventoryOutcome(null, reason, false, false);
        }

        static InventoryOutcome serviceUnavailable(boolean outcomeUnknown) {
            return new InventoryOutcome(null, null, true, outcomeUnknown);
        }
    }

    public record ReleaseOutcome(InventoryReservationResponse reservation, boolean unavailable, boolean outcomeUnknown) {
        static ReleaseOutcome released(InventoryReservationResponse response) {
            return new ReleaseOutcome(response, false, false);
        }

        static ReleaseOutcome unavailable(boolean outcomeUnknown) {
            return new ReleaseOutcome(null, true, outcomeUnknown);
        }
    }
}

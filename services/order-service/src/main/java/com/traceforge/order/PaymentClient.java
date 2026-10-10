package com.traceforge.order;

import java.time.Duration;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

@Component
public class PaymentClient {
    private static final int DEMO_MINOR_UNITS_PER_ITEM = 100;

    private final RestClient restClient;

    public PaymentClient(
            @Value("${traceforge.payment.base-url}") String baseUrl,
            @Value("${traceforge.payment.connect-timeout:1s}") Duration connectTimeout,
            @Value("${traceforge.payment.read-timeout:2s}") Duration readTimeout) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(connectTimeout);
        requestFactory.setReadTimeout(readTimeout);
        this.restClient = RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
    }

    public PaymentOutcome authorize(UUID orderId, int quantity, String failureScenario) {
        String idempotencyKey = orderId.toString();
        try {
            var request = restClient.post()
                    .uri("/internal/v1/payments/authorizations")
                    .header("Idempotency-Key", idempotencyKey);
            if (failureScenario != null) request.header("X-TraceForge-Failure", failureScenario);
            PaymentAuthorizationResponse response = request.body(new PaymentAuthorizationRequest(
                            orderId, Math.multiplyExact(quantity, DEMO_MINOR_UNITS_PER_ITEM)))
                    .retrieve()
                    .body(PaymentAuthorizationResponse.class);
            if (response == null || !orderId.equals(response.orderId())) return PaymentOutcome.unavailable(true);
            return PaymentOutcome.recorded(response);
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().value() == HttpStatus.CONFLICT.value()) {
                return PaymentOutcome.permanentFailure("PAYMENT_IDEMPOTENCY_CONFLICT");
            }
            return PaymentOutcome.unavailable(
                    !("payment-unavailable".equals(failureScenario)
                            && exception.getStatusCode().value() == HttpStatus.SERVICE_UNAVAILABLE.value()));
        } catch (RestClientException exception) {
            return PaymentOutcome.unavailable(true);
        }
    }

    public record PaymentAuthorizationRequest(UUID orderId, int amountMinor) {}

    public record PaymentAuthorizationResponse(
            UUID authorizationId,
            UUID orderId,
            int amountMinor,
            String status,
            String failureReason) {}

    public record PaymentOutcome(PaymentAuthorizationResponse attempt, String failureReason, boolean unavailable, boolean outcomeUnknown) {
        static PaymentOutcome recorded(PaymentAuthorizationResponse response) {
            return new PaymentOutcome(response, null, false, false);
        }

        static PaymentOutcome permanentFailure(String reason) {
            return new PaymentOutcome(null, reason, false, false);
        }

        static PaymentOutcome unavailable(boolean outcomeUnknown) {
            return new PaymentOutcome(null, null, true, outcomeUnknown);
        }
    }
}

package com.traceforge.gateway;

import java.time.Duration;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

@Component
public class OrderClient {
    private final RestClient restClient;

    public OrderClient(
            @Value("${traceforge.order.base-url}") String baseUrl,
            @Value("${traceforge.order.connect-timeout:1s}") Duration connectTimeout,
            @Value("${traceforge.order.read-timeout:4s}") Duration readTimeout) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(connectTimeout);
        requestFactory.setReadTimeout(readTimeout);
        this.restClient = RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
    }

    public ForwardedResponse create(
            OrderProxyController.OrderCreateRequest request,
            String idempotencyKey,
            String failureScenario) {
        try {
            var requestSpec = restClient.post().uri("/internal/v1/orders")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("Idempotency-Key", idempotencyKey);
            if (failureScenario != null) {
                requestSpec.header("X-TraceForge-Failure", failureScenario);
            }
            return requestSpec.body(request).exchange((httpRequest, response) -> new ForwardedResponse(
                    response.getStatusCode(),
                    response.getHeaders().getContentType(),
                    StreamUtils.copyToByteArray(response.getBody())));
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Order service is unavailable");
        }
    }

    public ForwardedResponse get(UUID id) {
        try {
            return restClient.get().uri("/internal/v1/orders/{id}", id)
                    .exchange((httpRequest, response) -> new ForwardedResponse(
                            response.getStatusCode(),
                            response.getHeaders().getContentType(),
                            StreamUtils.copyToByteArray(response.getBody())));
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Order service is unavailable");
        }
    }

    public ForwardedResponse recover(UUID id) {
        try {
            return restClient.post().uri("/internal/v1/orders/{id}/recover", id)
                    .exchange((httpRequest, response) -> new ForwardedResponse(
                            response.getStatusCode(),
                            response.getHeaders().getContentType(),
                            StreamUtils.copyToByteArray(response.getBody())));
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Order service is unavailable");
        }
    }

    public record ForwardedResponse(org.springframework.http.HttpStatusCode status, MediaType contentType, byte[] body) {}
}

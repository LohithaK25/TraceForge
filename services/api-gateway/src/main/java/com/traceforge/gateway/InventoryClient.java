package com.traceforge.gateway;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

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
        this.restClient = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(requestFactory)
                .build();
    }

    public InventoryAvailability getAvailability(String sku) {
        try {
            InventoryAvailability response = restClient.get()
                    .uri("/internal/v1/inventory/{sku}", sku)
                    .retrieve()
                    .body(InventoryAvailability.class);
            if (response == null) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Inventory service returned an empty response");
            }
            return response;
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().value() == HttpStatus.NOT_FOUND.value()) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown SKU");
            }
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Inventory service returned an error");
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Inventory service is unavailable");
        }
    }
}

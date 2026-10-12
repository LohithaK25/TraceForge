package com.traceforge.gateway;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.time.Duration;
import java.net.URI;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.util.UriBuilder;
import org.springframework.web.server.ResponseStatusException;

@Component
public class InvestigationClient {
    private static final int MAX_RESPONSE_BYTES = 1_048_576;
    private final RestClient restClient;

    public InvestigationClient(
            @Value("${traceforge.investigation.base-url}") String baseUrl,
            @Value("${traceforge.investigation.connect-timeout:1s}") Duration connectTimeout,
            @Value("${traceforge.investigation.read-timeout:4s}") Duration readTimeout) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(connectTimeout);
        requestFactory.setReadTimeout(readTimeout);
        this.restClient = RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
    }

    public ForwardedResponse list(String status, int limit, String cursor) {
        return forward(uri -> {
            var builder = uri.path("/api/v1/incidents").queryParam("status", status).queryParam("limit", limit);
            if (cursor != null) builder.queryParam("cursor", cursor);
            return builder.build();
        });
    }

    public ForwardedResponse get(UUID id) {
        return forward(uri -> uri.path("/api/v1/incidents/{id}").build(id));
    }

    public ForwardedResponse detectionStatus() {
        return forward(uri -> uri.path("/api/v1/detection-status").build());
    }

    private ForwardedResponse forward(java.util.function.Function<UriBuilder, URI> uriFactory) {
        try {
            return restClient.get().uri(uriFactory)
                    .accept(MediaType.APPLICATION_JSON)
                    .exchange((request, response) -> new ForwardedResponse(
                            response.getStatusCode(), response.getHeaders().getContentType(), readLimited(response.getBody())));
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Investigation service is unavailable");
        }
    }

    private static byte[] readLimited(InputStream input) {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int total = 0;
        int read;
        try {
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > MAX_RESPONSE_BYTES) {
                    throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Investigation response exceeded the size limit");
                }
                output.write(buffer, 0, read);
            }
        } catch (java.io.IOException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Investigation response could not be read");
        }
        return output.toByteArray();
    }

    public record ForwardedResponse(org.springframework.http.HttpStatusCode status, MediaType contentType, byte[] body) {}
}

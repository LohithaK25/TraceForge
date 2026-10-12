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
            @Value("${traceforge.investigation.read-timeout:10s}") Duration readTimeout) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(connectTimeout);
        requestFactory.setReadTimeout(readTimeout);
        this.restClient = RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
    }

    public ForwardedResponse list(String status, int limit, String cursor) {
        return forwardGet(uri -> {
            var builder = uri.path("/api/v1/incidents").queryParam("status", status).queryParam("limit", limit);
            if (cursor != null) builder.queryParam("cursor", cursor);
            return builder.build();
        });
    }

    public ForwardedResponse get(UUID id) {
        return forwardGet(uri -> uri.path("/api/v1/incidents/{id}").build(id));
    }

    public ForwardedResponse latestInvestigation(UUID id) {
        return forwardGet(uri -> uri.path("/api/v1/incidents/{id}/investigations/latest").build(id));
    }

    public ForwardedResponse runInvestigation(UUID id) {
        return forwardPost(uri -> uri.path("/api/v1/incidents/{id}/investigations").build(id));
    }

    public ForwardedResponse detectionStatus() {
        return forwardGet(uri -> uri.path("/api/v1/detection-status").build());
    }

    private ForwardedResponse forwardGet(java.util.function.Function<UriBuilder, URI> uriFactory) {
        try {
            return forward(restClient.get().uri(uriFactory).accept(MediaType.APPLICATION_JSON));
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Investigation service is unavailable");
        }
    }

    private ForwardedResponse forwardPost(java.util.function.Function<UriBuilder, URI> uriFactory) {
        try {
            return forward(restClient.post().uri(uriFactory).accept(MediaType.APPLICATION_JSON));
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientException exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Investigation service is unavailable");
        }
    }

    private ForwardedResponse forward(RestClient.RequestHeadersSpec<?> request) {
        return request.exchange((outgoingRequest, response) -> new ForwardedResponse(
                response.getStatusCode(), response.getHeaders().getContentType(), readLimited(response.getBody())));
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

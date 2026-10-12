package com.traceforge.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class IncidentProxyControllerTest {
    private final InvestigationClient client = mock(InvestigationClient.class);
    private final IncidentProxyController controller = new IncidentProxyController(client);

    @Test
    void forwardsOnlyBoundedIncidentFiltersAndSafeResponse() {
        byte[] body = "{\"items\":[]}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        when(client.list("OPEN", 50, "YWJj")).thenReturn(
                new InvestigationClient.ForwardedResponse(HttpStatus.OK, MediaType.APPLICATION_JSON, body));

        var response = controller.list("OPEN", 50, "YWJj");

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(body.length, response.getBody().length);
        verify(client).list("OPEN", 50, "YWJj");
    }

    @Test
    void rejectsUnsupportedStatusPageSizeAndCursorBeforeCallingUpstream() {
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class, () -> controller.list("ALL", 50, null))
                        .getStatusCode());
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class, () -> controller.list("OPEN", 101, null))
                        .getStatusCode());
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class, () -> controller.list("OPEN", 50, "bad cursor"))
                        .getStatusCode());
        verifyNoInteractions(client);
    }

    @Test
    void proxiesInvestigationReadAndRunForFixedIncidentRoutes() {
        var id = java.util.UUID.fromString("a8d7f65a-2a91-4be2-9231-09bdc4e7440c");
        byte[] body = "{\"status\":\"INSUFFICIENT\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        when(client.latestInvestigation(id)).thenReturn(
                new InvestigationClient.ForwardedResponse(HttpStatus.OK, MediaType.APPLICATION_JSON, body));
        when(client.runInvestigation(id)).thenReturn(
                new InvestigationClient.ForwardedResponse(HttpStatus.OK, MediaType.APPLICATION_JSON, body));

        assertEquals(HttpStatus.OK, controller.latestInvestigation(id).getStatusCode());
        assertEquals(HttpStatus.OK, controller.runInvestigation(id).getStatusCode());
        verify(client).latestInvestigation(id);
        verify(client).runInvestigation(id);
    }
}

package com.traceforge.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

class TraceProxyControllerTest {
    private final TempoClient client = mock(TempoClient.class);
    private final TraceProxyController controller = new TraceProxyController(client);

    @Test
    void acceptsOnlyLowercaseW3cTraceIdsBeforeQueryingTempo() {
        String id = "0123456789abcdef0123456789abcdef";
        var expected = new TraceSummary(id, java.util.List.of(), false);
        when(client.getTrace(id)).thenReturn(expected);

        assertEquals(expected, controller.getTrace(id));
        verify(client).getTrace(id);
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class, () -> controller.getTrace("../api"))
                        .getStatusCode());
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class, () -> controller.getTrace(id.toUpperCase()))
                        .getStatusCode());
        verifyNoMoreInteractions(client);
    }
}

package com.traceforge.payment;

import java.util.UUID;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("local")
class PaymentControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private String testRunId;

    @BeforeEach
    void startTestDataScope() {
        testRunId = UUID.randomUUID().toString();
    }

    @AfterEach
    void removeTestPaymentAttempts() {
        String keyPattern = "payment-test-" + testRunId + "-%";
        jdbcTemplate.update("DELETE FROM payment_attempts WHERE idempotency_key LIKE ?", keyPattern);
        assertEquals(0, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM payment_attempts WHERE idempotency_key LIKE ?", Integer.class, keyPattern));
    }

    @Test
    void authorizationIsPersistedAndIdempotentByKey() throws Exception {
        String key = paymentKey();
        UUID orderId = UUID.randomUUID();
        String body = "{\"orderId\":\"" + orderId + "\",\"amountMinor\":300}";
        var first = mockMvc.perform(post("/internal/v1/payments/authorizations")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("AUTHORIZED"))
                .andReturn();
        String authorizationId = com.jayway.jsonpath.JsonPath.read(first.getResponse().getContentAsString(), "$.authorizationId");

        mockMvc.perform(post("/internal/v1/payments/authorizations")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.authorizationId").value(authorizationId));
        assertEquals(1, count(key));

        mockMvc.perform(post("/internal/v1/payments/authorizations")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content("{\"orderId\":\"" + orderId + "\",\"amountMinor\":400}"))
                .andExpect(status().isConflict());
        assertEquals(1, count(key));
    }

    @Test
    void deterministicDeclineIsStoredAndUnavailableDoesNotCreateAnAttempt() throws Exception {
        String declineKey = paymentKey();
        mockMvc.perform(post("/internal/v1/payments/authorizations")
                        .header("Idempotency-Key", declineKey)
                        .header("X-TraceForge-Failure", "payment-decline")
                        .contentType("application/json")
                        .content("{\"orderId\":\"" + UUID.randomUUID() + "\",\"amountMinor\":100}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DECLINED"))
                .andExpect(jsonPath("$.authorizationId").isEmpty());
        assertEquals(1, count(declineKey));

        String unavailableKey = paymentKey();
        mockMvc.perform(post("/internal/v1/payments/authorizations")
                        .header("Idempotency-Key", unavailableKey)
                        .header("X-TraceForge-Failure", "payment-unavailable")
                        .contentType("application/json")
                        .content("{\"orderId\":\"" + UUID.randomUUID() + "\",\"amountMinor\":100}"))
                .andExpect(status().isServiceUnavailable());
        assertEquals(0, count(unavailableKey));
    }

    @Test
    void validatesAuthorizationInput() throws Exception {
        mockMvc.perform(post("/internal/v1/payments/authorizations")
                        .header("Idempotency-Key", "invalid-amount")
                        .contentType("application/json")
                        .content("{\"orderId\":\"" + UUID.randomUUID() + "\",\"amountMinor\":0}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void failureInjectionIsRejectedOutsideLocalProfile() {
        PaymentController productionController = new PaymentController(
                org.mockito.Mockito.mock(PaymentApplicationService.class), new MockEnvironment());
        var exception = assertThrows(
                org.springframework.web.server.ResponseStatusException.class,
                () -> productionController.authorize(
                        new PaymentAuthorizationRequest(UUID.randomUUID(), 100), "local-test", "payment-decline"));
        assertEquals(403, exception.getStatusCode().value());
    }

    private int count(String key) {
        return jdbcTemplate.queryForObject(
                "SELECT count(*) FROM payment_attempts WHERE idempotency_key = ?", Integer.class, key);
    }

    private String paymentKey() {
        return "payment-test-" + testRunId + "-" + UUID.randomUUID();
    }
}

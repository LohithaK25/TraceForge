package com.traceforge.order;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.nullValue;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "traceforge.recovery.enabled=false")
@AutoConfigureMockMvc
@ActiveProfiles("local")
@Transactional
class OrderAttentionControllerTest {
    private static final Instant FIXTURE_TIME = Instant.parse("2099-01-01T00:00:00Z");
    private static final Instant FUTURE_CURSOR = Instant.parse("9999-01-01T00:00:00Z");

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void returnsAnEmptyPageAfterTheLastCursor() throws Exception {
        mockMvc.perform(get("/internal/v1/orders/attention")
                        .queryParam("afterCreatedAt", FUTURE_CURSOR.toString())
                        .queryParam("afterId", "ffffffff-ffff-ffff-ffff-ffffffffffff"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items").isEmpty())
                .andExpect(jsonPath("$.limit").value(50))
                .andExpect(jsonPath("$.nextCursor").value(nullValue()));
    }

    @Test
    void includesDueRecoveryWithOnlyTheAllowlistedFieldsAndNullableTraceId() throws Exception {
        UUID orderId = UUID.randomUUID();
        insert(orderId, "PENDING", "INVENTORY_UNAVAILABLE", "INVENTORY_RETRY_SCHEDULED", 1,
                Instant.parse("2098-12-31T00:00:00Z"), false, FIXTURE_TIME, null);

        MvcResult result = mockMvc.perform(attentionFromStart(10))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].orderId").value(orderId.toString()))
                .andExpect(jsonPath("$.items[0].status").value("PENDING"))
                .andExpect(jsonPath("$.items[0].failureReason").value("INVENTORY_UNAVAILABLE"))
                .andExpect(jsonPath("$.items[0].recoveryError").value("INVENTORY_RETRY_SCHEDULED"))
                .andExpect(jsonPath("$.items[0].recoveryAttempts").value(1))
                .andExpect(jsonPath("$.items[0].inventoryReleased").value(false))
                .andExpect(jsonPath("$.items[0].originTraceId").value(nullValue()))
                .andExpect(jsonPath("$.items[0].sku").doesNotExist())
                .andExpect(jsonPath("$.items[0].quantity").doesNotExist())
                .andExpect(jsonPath("$.items[0].inventoryReservationId").doesNotExist())
                .andExpect(jsonPath("$.items[0].paymentAuthorizationId").doesNotExist())
                .andReturn();

        String json = result.getResponse().getContentAsString();
        assertTrue(json.contains("nextRecoveryAt"));
        assertTrue(json.contains("createdAt"));
        assertTrue(json.contains("updatedAt"));
        assertTrue(json.contains("\"originTraceId\":null"));
    }

    @Test
    void includesAnOverdueActiveOrderEvenWhenNoFailureCodeWasPersisted() throws Exception {
        UUID orderId = UUID.randomUUID();
        // Keep the row inside an isolated future cursor range while exercising the SQL due-time predicate.
        insert(orderId, "PENDING", null, null, 0,
                Instant.parse("2000-01-01T00:00:00Z"), false, FIXTURE_TIME, null);

        mockMvc.perform(attentionFromStart(10))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].orderId").value(orderId.toString()))
                .andExpect(jsonPath("$.items[0].failureReason").value(nullValue()))
                .andExpect(jsonPath("$.items[0].recoveryError").value(nullValue()));
    }

    @Test
    void excludesHealthyOrdersAndFullyCompensatedBusinessRejections() throws Exception {
        insert(UUID.randomUUID(), "CONFIRMED", null, null, 0,
                FIXTURE_TIME.plusSeconds(30), false, FIXTURE_TIME, null);
        insert(UUID.randomUUID(), "FAILED", "PAYMENT_DECLINED", null, 0,
                FIXTURE_TIME.plusSeconds(30), true, FIXTURE_TIME.plusSeconds(1), null);

        mockMvc.perform(attentionFromStart(10))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items").isEmpty())
                .andExpect(jsonPath("$.nextCursor").value(nullValue()));
    }

    @Test
    void paginatesWithStableCreatedAtAndIdOrderingAndAcceptsNullableTraceValues() throws Exception {
        UUID first = UUID.fromString("00000000-0000-0000-0000-000000000001");
        UUID second = UUID.fromString("00000000-0000-0000-0000-000000000002");
        UUID third = UUID.fromString("00000000-0000-0000-0000-000000000003");
        String traceId = "1234567890abcdef1234567890abcdef";
        insert(first, "INVENTORY_RESERVED", null, "PAYMENT_RETRY_SCHEDULED", 2,
                FIXTURE_TIME.plusSeconds(15), false, FIXTURE_TIME, traceId);
        insert(second, "COMPENSATION_REQUIRED", "PAYMENT_DECLINED", "COMPENSATION_RETRY_SCHEDULED", 3,
                FIXTURE_TIME.plusSeconds(15), false, FIXTURE_TIME, null);
        insert(third, "PENDING", null, "INVENTORY_RETRY_SCHEDULED", 1,
                FIXTURE_TIME.plusSeconds(15), false, FIXTURE_TIME.plusSeconds(1), null);

        MvcResult firstPage = mockMvc.perform(attentionFromStart(2))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[0].orderId").value(first.toString()))
                .andExpect(jsonPath("$.items[0].originTraceId").value(traceId))
                .andExpect(jsonPath("$.items[1].orderId").value(second.toString()))
                .andExpect(jsonPath("$.items[1].originTraceId").value(nullValue()))
                .andExpect(jsonPath("$.nextCursor.afterId").value(second.toString()))
                .andReturn();

        String nextCreatedAt = com.jayway.jsonpath.JsonPath.read(
                firstPage.getResponse().getContentAsString(), "$.nextCursor.afterCreatedAt");
        mockMvc.perform(get("/internal/v1/orders/attention")
                        .queryParam("limit", "2")
                        .queryParam("afterCreatedAt", nextCreatedAt)
                        .queryParam("afterId", second.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].orderId").value(third.toString()))
                .andExpect(jsonPath("$.nextCursor").value(nullValue()));
    }

    @Test
    void rejectsInvalidPageSizesAndIncompleteCursorsAndAcceptsTheMaximum() throws Exception {
        mockMvc.perform(get("/internal/v1/orders/attention").queryParam("limit", "0"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/internal/v1/orders/attention").queryParam("limit", "101"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/internal/v1/orders/attention")
                        .queryParam("afterId", UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/internal/v1/orders/attention")
                        .queryParam("limit", "100")
                        .queryParam("afterCreatedAt", FUTURE_CURSOR.toString())
                        .queryParam("afterId", "ffffffff-ffff-ffff-ffff-ffffffffffff"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.limit", equalTo(100)))
                .andExpect(jsonPath("$.items").isEmpty());
    }

    @Test
    void recoveryObservationLookupReturnsTerminalFieldsAndMarksMissingOrdersExplicitly() throws Exception {
        UUID terminal = UUID.randomUUID();
        UUID missing = UUID.randomUUID();
        insert(terminal, "FAILED", "PAYMENT_DECLINED", null, 2,
                FIXTURE_TIME.plusSeconds(15), true, FIXTURE_TIME, null);

        MvcResult result = mockMvc.perform(get("/internal/v1/orders/recovery-observations")
                        .queryParam("orderIds", terminal.toString(), missing.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items", hasSize(1)))
                .andExpect(jsonPath("$.items[0].orderId").value(terminal.toString()))
                .andExpect(jsonPath("$.items[0].status").value("FAILED"))
                .andExpect(jsonPath("$.items[0].inventoryReleased").value(true))
                .andExpect(jsonPath("$.items[0].originTraceId").value(nullValue()))
                .andExpect(jsonPath("$.items[0].sku").doesNotExist())
                .andExpect(jsonPath("$.items[0].quantity").doesNotExist())
                .andExpect(jsonPath("$.missingOrderIds[0]").value(missing.toString()))
                .andReturn();
        assertTrue(result.getResponse().getContentAsString().contains("nextRecoveryAt"));
    }

    @Test
    void recoveryObservationLookupRejectsEmptyDuplicateAndOversizedIdLists() throws Exception {
        mockMvc.perform(get("/internal/v1/orders/recovery-observations"))
                .andExpect(status().isBadRequest());
        String repeatedId = UUID.randomUUID().toString();
        mockMvc.perform(get("/internal/v1/orders/recovery-observations")
                        .queryParam("orderIds", repeatedId, repeatedId))
                .andExpect(status().isBadRequest());
        List<String> ids = new ArrayList<>();
        for (int index = 0; index < 101; index++) ids.add(UUID.randomUUID().toString());
        mockMvc.perform(get("/internal/v1/orders/recovery-observations")
                        .queryParam("orderIds", ids.toArray(String[]::new)))
                .andExpect(status().isBadRequest());
    }

    private org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder attentionFromStart(int limit) {
        return get("/internal/v1/orders/attention")
                .queryParam("limit", Integer.toString(limit))
                .queryParam("afterCreatedAt", FIXTURE_TIME.minusSeconds(1).toString())
                .queryParam("afterId", "00000000-0000-0000-0000-000000000000");
    }

    private void insert(
            UUID id,
            String status,
            String failureReason,
            String recoveryError,
            int recoveryAttempts,
            Instant nextRecoveryAt,
            boolean inventoryReleased,
            Instant createdAt,
            String originTraceId) {
        String originSpanId = originTraceId == null ? null : "abcdef0123456789";
        jdbcTemplate.update(
                "INSERT INTO orders (id, idempotency_key, sku, quantity, status, failure_reason, recovery_error, "
                        + "inventory_released, recovery_attempts, next_recovery_at, origin_trace_id, origin_span_id, "
                        + "created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                id,
                "attention-test-" + UUID.randomUUID(),
                "SKU-ATTENTION-TEST",
                status,
                failureReason,
                recoveryError,
                inventoryReleased,
                recoveryAttempts,
                Timestamp.from(nextRecoveryAt),
                originTraceId,
                originSpanId,
                Timestamp.from(createdAt),
                Timestamp.from(createdAt));
    }
}

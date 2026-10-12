package com.traceforge.order;

import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

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
import org.springframework.test.web.servlet.MvcResult;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "traceforge.recovery.enabled=false")
@AutoConfigureMockMvc
@ActiveProfiles("local")
class OrderControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private String testRunId;
    private String testOrderSku;
    private String testTinySku;

    @BeforeEach
    void createIsolatedIntegrationInventory() {
        testRunId = UUID.randomUUID().toString();
        String suffix = testRunId.substring(0, 8).toUpperCase();
        testOrderSku = "SKU-ORD-" + suffix;
        testTinySku = "SKU-TNY-" + suffix;
        jdbcTemplate.update(
                "INSERT INTO inventory_service.inventory_items (sku, available_quantity) VALUES (?, 100)", testOrderSku);
        jdbcTemplate.update(
                "INSERT INTO inventory_service.inventory_items (sku, available_quantity) VALUES (?, 1)", testTinySku);
    }

    @AfterEach
    void removeIsolatedIntegrationData() {
        if (testRunId == null) return;
        String keyPattern = "order-test-" + testRunId + "-%";
        int orderTotal = available(testOrderSku) + jdbcTemplate.queryForObject(
                "SELECT COALESCE(SUM(quantity), 0) FROM inventory_service.inventory_reservations "
                        + "WHERE sku = ? AND released_at IS NULL",
                Integer.class,
                testOrderSku);
        int tinyTotal = available(testTinySku) + jdbcTemplate.queryForObject(
                "SELECT COALESCE(SUM(quantity), 0) FROM inventory_service.inventory_reservations "
                        + "WHERE sku = ? AND released_at IS NULL",
                Integer.class,
                testTinySku);
        int testPaymentAttempts = count(
                "SELECT count(*) FROM payment_service.payment_attempts WHERE order_id IN "
                        + "(SELECT id FROM order_service.orders WHERE idempotency_key LIKE ?)",
                keyPattern);
        int deletedPaymentAttempts;
        try {
            deletedPaymentAttempts = jdbcTemplate.update(
                    "DELETE FROM payment_service.payment_attempts WHERE order_id IN "
                            + "(SELECT id FROM order_service.orders WHERE idempotency_key LIKE ?)",
                    keyPattern);
            jdbcTemplate.update(
                    "DELETE FROM inventory_service.inventory_reservations WHERE order_id IN "
                            + "(SELECT id FROM order_service.orders WHERE idempotency_key LIKE ?)",
                    keyPattern);
            jdbcTemplate.update("DELETE FROM order_service.orders WHERE idempotency_key LIKE ?", keyPattern);
            jdbcTemplate.update("DELETE FROM inventory_service.inventory_reservations WHERE sku IN (?, ?)", testOrderSku, testTinySku);
            jdbcTemplate.update("DELETE FROM inventory_service.inventory_items WHERE sku IN (?, ?)", testOrderSku, testTinySku);
        } finally {
            testRunId = null;
        }
        assertEquals(100, orderTotal, "test SKU quantity must equal its initial stock plus active reservations");
        assertEquals(1, tinyTotal, "test SKU quantity must equal its initial stock plus active reservations");
        assertEquals(testPaymentAttempts, deletedPaymentAttempts, "all payment attempts for this test order scope must be removed");
        assertEquals(0, count("SELECT count(*) FROM order_service.orders WHERE idempotency_key LIKE ?", keyPattern));
        assertEquals(0, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM inventory_service.inventory_reservations WHERE sku IN (?, ?)",
                Integer.class,
                testOrderSku,
                testTinySku));
        assertEquals(0, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM inventory_service.inventory_items WHERE sku IN (?, ?)",
                Integer.class,
                testOrderSku,
                testTinySku));
    }

    @Test
    void createsAndRetrievesPersistentOrderAndRepeatingKeyDoesNotRepeatEffects() throws Exception {
        String key = key();
        MvcResult created = create(key, testOrderSku, 2, null);
        var body = created.getResponse().getContentAsString();
        String orderId = com.jayway.jsonpath.JsonPath.read(body, "$.id");
        String authorizationId = com.jayway.jsonpath.JsonPath.read(body, "$.paymentAuthorizationId");
        assertEquals(201, created.getResponse().getStatus());
        assertEquals("CONFIRMED", com.jayway.jsonpath.JsonPath.read(body, "$.status"));

        mockMvc.perform(post("/internal/v1/orders")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content("{\"sku\":\"" + testOrderSku + "\",\"quantity\":2}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(orderId))
                .andExpect(jsonPath("$.paymentAuthorizationId").value(authorizationId));

        mockMvc.perform(get("/internal/v1/orders/{id}", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CONFIRMED"));
        assertEquals(98, available(testOrderSku));
        assertEquals(1, count("SELECT count(*) FROM orders WHERE idempotency_key = ?", key));
        assertEquals(1, count("SELECT count(*) FROM payment_service.payment_attempts WHERE order_id = ?::uuid", orderId));
    }

    @Test
    void rejectsInvalidPayloadBeforePersistingOrCallingDownstream() throws Exception {
        String key = key();
        int initialOrders = jdbcTemplate.queryForObject("SELECT count(*) FROM orders", Integer.class);
        mockMvc.perform(post("/internal/v1/orders")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content("{\"sku\":\"sku-alpha\",\"quantity\":0}"))
                .andExpect(status().isBadRequest());
        assertEquals(initialOrders, jdbcTemplate.queryForObject("SELECT count(*) FROM orders", Integer.class));
        assertEquals(100, available(testOrderSku));
    }

    @Test
    void rejectsReuseOfAnOrderKeyWithDifferentPayload() throws Exception {
        String key = key();
        create(key, testOrderSku, 1, null);
        mockMvc.perform(post("/internal/v1/orders")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content("{\"sku\":\"" + testOrderSku + "\",\"quantity\":2}"))
                .andExpect(status().isConflict());
        assertEquals(99, available(testOrderSku));
    }

    @Test
    void concurrentFirstRequestsWithTheSameKeyCreateOneOrderAndReservation() throws Exception {
        String key = key();
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            var request = (java.util.concurrent.Callable<MvcResult>) () -> {
                ready.countDown();
                start.await();
                return mockMvc.perform(post("/internal/v1/orders")
                                .header("Idempotency-Key", key)
                                .contentType("application/json")
                                .content("{\"sku\":\"" + testOrderSku + "\",\"quantity\":1}"))
                        .andReturn();
            };
            Future<MvcResult> first = executor.submit(request);
            Future<MvcResult> second = executor.submit(request);
            assertEquals(true, ready.await(10, TimeUnit.SECONDS));
            start.countDown();
            MvcResult firstResult = first.get(30, TimeUnit.SECONDS);
            MvcResult secondResult = second.get(30, TimeUnit.SECONDS);
            String firstId = com.jayway.jsonpath.JsonPath.read(firstResult.getResponse().getContentAsString(), "$.id");
            String secondId = com.jayway.jsonpath.JsonPath.read(secondResult.getResponse().getContentAsString(), "$.id");
            assertEquals(firstId, secondId);
            assertEquals(1, count("SELECT count(*) FROM orders WHERE idempotency_key = ?", key));
            assertEquals(99, available(testOrderSku));
            assertEquals(1, count("SELECT count(*) FROM inventory_service.inventory_reservations WHERE order_id = ?::uuid", firstId));
            assertEquals(1, count("SELECT count(*) FROM payment_service.payment_attempts WHERE order_id = ?::uuid", firstId));
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void persistsUnknownSkuAndInsufficientStockFailures() throws Exception {
        MvcResult unknown = create(key(), "SKU-NOT-SEEDED-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase(), 1, null);
        assertEquals(404, unknown.getResponse().getStatus());
        assertEquals("FAILED", com.jayway.jsonpath.JsonPath.read(unknown.getResponse().getContentAsString(), "$.status"));
        assertEquals("UNKNOWN_SKU", com.jayway.jsonpath.JsonPath.read(unknown.getResponse().getContentAsString(), "$.failureReason"));

        MvcResult insufficient = create(key(), testTinySku, 2, null);
        assertEquals(409, insufficient.getResponse().getStatus());
        assertEquals("INSUFFICIENT_STOCK", com.jayway.jsonpath.JsonPath.read(insufficient.getResponse().getContentAsString(), "$.failureReason"));
        assertEquals(1, available(testTinySku));
    }

    @Test
    void paymentDeclineReleasesTheCommittedInventoryReservation() throws Exception {
        MvcResult result = create(key(), testOrderSku, 3, "payment-decline");
        assertEquals(402, result.getResponse().getStatus());
        String body = result.getResponse().getContentAsString();
        assertEquals("FAILED", com.jayway.jsonpath.JsonPath.read(body, "$.status"));
        assertEquals("PAYMENT_DECLINED", com.jayway.jsonpath.JsonPath.read(body, "$.failureReason"));
        assertEquals(true, com.jayway.jsonpath.JsonPath.read(body, "$.inventoryReleased"));
        assertEquals(100, available(testOrderSku));
    }

    @Test
    void preMutationInventoryFailureStaysPendingAndCanBeRetried() throws Exception {
        MvcResult pending = create(key(), testOrderSku, 1, "inventory-unavailable");
        String orderId = com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.id");
        assertEquals(503, pending.getResponse().getStatus());
        assertEquals("PENDING", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.status"));
        assertEquals("INVENTORY_RETRY_SCHEDULED", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.recoveryError"));
        assertNull(com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.inventoryReservationId"));
        assertEquals(100, available(testOrderSku));

        mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CONFIRMED"));
        assertEquals(99, available(testOrderSku));
    }

    @Test
    void paymentOutageLeavesRecoverableReservedOrderAndRecoveryIsIdempotent() throws Exception {
        String key = key();
        MvcResult pending = create(key, testOrderSku, 1, "payment-unavailable");
        String orderId = com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.id");
        assertEquals(503, pending.getResponse().getStatus());
        assertEquals("INVENTORY_RESERVED", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.status"));
        assertEquals(99, available(testOrderSku));

        mockMvc.perform(post("/internal/v1/orders")
                        .header("Idempotency-Key", key)
                        .contentType("application/json")
                        .content("{\"sku\":\"" + testOrderSku + "\",\"quantity\":1}"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.id").value(orderId));
        assertEquals(99, available(testOrderSku));

        MvcResult recovered = mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk()).andReturn();
        String authorizationId = com.jayway.jsonpath.JsonPath.read(recovered.getResponse().getContentAsString(), "$.paymentAuthorizationId");
        assertEquals("CONFIRMED", com.jayway.jsonpath.JsonPath.read(recovered.getResponse().getContentAsString(), "$.status"));
        mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.paymentAuthorizationId").value(authorizationId));
        assertEquals(99, available(testOrderSku));
    }

    @Test
    void failedCompensationStaysVisibleAndRecoveryCanFinishItOnlyOnce() throws Exception {
        MvcResult pending = create(key(), testOrderSku, 2, "payment-decline-compensation-unavailable");
        String orderId = com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.id");
        assertEquals(503, pending.getResponse().getStatus());
        assertEquals("COMPENSATION_REQUIRED", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.status"));
        assertEquals("PAYMENT_DECLINED", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.failureReason"));
        assertEquals(98, available(testOrderSku));

        mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("FAILED"))
                .andExpect(jsonPath("$.inventoryReleased").value(true));
        mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("FAILED"));
        assertEquals(100, available(testOrderSku));
    }

    @Test
    void recoversReservationWhoseCommitWasHiddenByAClientTimeout() throws Exception {
        MvcResult pending = create(key(), testOrderSku, 1, "inventory-timeout-after-commit");
        String orderId = com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.id");
        assertEquals(503, pending.getResponse().getStatus());
        assertEquals("PENDING", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.status"));
        assertEquals(99, available(testOrderSku));

        mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CONFIRMED"));
        assertEquals(99, available(testOrderSku));
        assertEquals(1, count("SELECT count(*) FROM inventory_service.inventory_reservations WHERE order_id = ?::uuid", orderId));
    }

    @Test
    void recoversAuthorizationCommittedBeforeThePaymentResponseTimedOut() throws Exception {
        MvcResult pending = create(key(), testOrderSku, 1, "payment-timeout-after-commit");
        String orderId = com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.id");
        assertEquals(503, pending.getResponse().getStatus());
        assertEquals("INVENTORY_RESERVED", com.jayway.jsonpath.JsonPath.read(pending.getResponse().getContentAsString(), "$.status"));
        assertEquals(1, count("SELECT count(*) FROM payment_service.payment_attempts WHERE order_id = ?::uuid AND status = 'AUTHORIZED'", orderId));
        assertEquals(99, available(testOrderSku));

        mockMvc.perform(post("/internal/v1/orders/{id}/recover", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CONFIRMED"));
        assertEquals(99, available(testOrderSku));
        assertEquals(1, count("SELECT count(*) FROM payment_service.payment_attempts WHERE order_id = ?::uuid", orderId));
    }

    @Test
    void failureInjectionIsRejectedOutsideLocalProfile() {
        OrderController productionController = new OrderController(
                mock(OrderApplicationService.class), new MockEnvironment());
        var exception = assertThrows(
                org.springframework.web.server.ResponseStatusException.class,
                () -> productionController.create(new CreateOrderRequest(testOrderSku, 1), key(), "payment-decline"));
        assertEquals(403, exception.getStatusCode().value());
    }

    private MvcResult create(String key, String sku, int quantity, String failureScenario) throws Exception {
        var request = post("/internal/v1/orders")
                .header("Idempotency-Key", key)
                .contentType("application/json")
                .content("{\"sku\":\"" + sku + "\",\"quantity\":" + quantity + "}");
        if (failureScenario != null) request.header("X-TraceForge-Failure", failureScenario);
        return mockMvc.perform(request).andReturn();
    }

    private int available(String sku) {
        return jdbcTemplate.queryForObject(
                "SELECT available_quantity FROM inventory_service.inventory_items WHERE sku = ?", Integer.class, sku);
    }

    private int count(String sql, String key) {
        return jdbcTemplate.queryForObject(sql, Integer.class, key);
    }

    private String key() {
        return "order-test-" + testRunId + "-" + UUID.randomUUID();
    }
}

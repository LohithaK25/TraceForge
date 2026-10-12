package com.traceforge.inventory;

import java.util.UUID;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("local")
class InventoryControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private String testOrderSku;
    private String testTinySku;

    @BeforeEach
    void createIsolatedTestInventory() {
        String suffix = UUID.randomUUID().toString().substring(0, 8).toUpperCase();
        testOrderSku = "SKU-INV-" + suffix;
        testTinySku = "SKU-TNY-" + suffix;
        jdbcTemplate.update("INSERT INTO inventory_items (sku, available_quantity) VALUES (?, 100)", testOrderSku);
        jdbcTemplate.update("INSERT INTO inventory_items (sku, available_quantity) VALUES (?, 1)", testTinySku);
    }

    @AfterEach
    void removeIsolatedTestInventory() {
        int orderStockWithReservations = stockPlusActiveReservations(testOrderSku);
        int tinyStockWithReservations = stockPlusActiveReservations(testTinySku);
        jdbcTemplate.update("DELETE FROM inventory_reservations WHERE sku IN (?, ?)", testOrderSku, testTinySku);
        jdbcTemplate.update("DELETE FROM inventory_items WHERE sku IN (?, ?)", testOrderSku, testTinySku);
        assertEquals(100, orderStockWithReservations, "test inventory stock must reconcile with active reservations");
        assertEquals(1, tinyStockWithReservations, "test inventory stock must reconcile with active reservations");
        assertEquals(0, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM inventory_reservations WHERE sku IN (?, ?)",
                Integer.class,
                testOrderSku,
                testTinySku));
        assertEquals(0, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM inventory_items WHERE sku IN (?, ?)",
                Integer.class,
                testOrderSku,
                testTinySku));
    }

    @Test
    void returnsPersistentDemoInventory() throws Exception {
        mockMvc.perform(get("/internal/v1/inventory/SKU-ALPHA"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sku").value("SKU-ALPHA"))
                .andExpect(jsonPath("$.availableQuantity").isNumber());
    }

    @Test
    void returnsNotFoundForUnknownSku() throws Exception {
        mockMvc.perform(get("/internal/v1/inventory/SKU-BETA"))
                .andExpect(status().isNotFound());
    }

    @Test
    void rejectsMalformedSku() throws Exception {
        mockMvc.perform(get("/internal/v1/inventory/sku-alpha"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void reservationDecrementsStockAndIsIdempotentForAnOrderId() throws Exception {
        UUID orderId = UUID.randomUUID();
        String body = "{\"orderId\":\"" + orderId + "\",\"sku\":\"" + testOrderSku + "\",\"quantity\":3}";

        mockMvc.perform(post("/internal/v1/inventory/reservations").contentType("application/json").content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.orderId").value(orderId.toString()))
                .andExpect(jsonPath("$.availableQuantity").value(97));

        mockMvc.perform(post("/internal/v1/inventory/reservations").contentType("application/json").content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(97));

        mockMvc.perform(get("/internal/v1/inventory/" + testOrderSku))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(97));
    }

    @Test
    void rejectsInsufficientStockWithoutChangingQuantity() throws Exception {
        String body = "{\"orderId\":\"" + UUID.randomUUID() + "\",\"sku\":\"" + testTinySku + "\",\"quantity\":2}";

        mockMvc.perform(post("/internal/v1/inventory/reservations").contentType("application/json").content(body))
                .andExpect(status().isConflict());

        mockMvc.perform(get("/internal/v1/inventory/" + testTinySku))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(1));
    }

    @Test
    void controlledLocalFailureDoesNotReserveStock() throws Exception {
        String body = "{\"orderId\":\"" + UUID.randomUUID() + "\",\"sku\":\"" + testOrderSku + "\",\"quantity\":3}";

        mockMvc.perform(post("/internal/v1/inventory/reservations")
                        .header("X-TraceForge-Failure", "inventory-unavailable")
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isServiceUnavailable());

        mockMvc.perform(get("/internal/v1/inventory/" + testOrderSku))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(100));
    }

    @Test
    void releasesReservationExactlyOnce() throws Exception {
        UUID orderId = UUID.randomUUID();
        String body = "{\"orderId\":\"" + orderId + "\",\"sku\":\"" + testOrderSku + "\",\"quantity\":4}";
        mockMvc.perform(post("/internal/v1/inventory/reservations")
                        .contentType("application/json").content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(96));

        mockMvc.perform(post("/internal/v1/inventory/reservations/{orderId}/release", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.released").value(true))
                .andExpect(jsonPath("$.availableQuantity").value(100));
        mockMvc.perform(post("/internal/v1/inventory/reservations/{orderId}/release", orderId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(100));
        mockMvc.perform(get("/internal/v1/inventory/" + testOrderSku))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(100));
        assertEquals(1, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM inventory_reservations WHERE order_id = ? AND released_at IS NOT NULL",
                Integer.class, orderId));
    }

    @Test
    void controlledCompensationFailureLeavesTheReservationHeld() throws Exception {
        UUID orderId = UUID.randomUUID();
        String body = "{\"orderId\":\"" + orderId + "\",\"sku\":\"" + testOrderSku + "\",\"quantity\":4}";
        mockMvc.perform(post("/internal/v1/inventory/reservations")
                        .contentType("application/json").content(body))
                .andExpect(status().isOk());

        mockMvc.perform(post("/internal/v1/inventory/reservations/{orderId}/release", orderId)
                        .header("X-TraceForge-Failure", "compensation-unavailable"))
                .andExpect(status().isServiceUnavailable());
        mockMvc.perform(get("/internal/v1/inventory/" + testOrderSku))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(96));
    }

    private int stockPlusActiveReservations(String sku) {
        int available = jdbcTemplate.queryForObject(
                "SELECT available_quantity FROM inventory_items WHERE sku = ?", Integer.class, sku);
        int activeReservations = jdbcTemplate.queryForObject(
                "SELECT COALESCE(SUM(quantity), 0) FROM inventory_reservations WHERE sku = ? AND released_at IS NULL",
                Integer.class,
                sku);
        return available + activeReservations;
    }
}

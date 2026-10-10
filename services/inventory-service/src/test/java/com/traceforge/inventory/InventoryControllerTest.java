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

    @BeforeEach
    void resetIsolatedTestInventory() {
        jdbcTemplate.update("UPDATE inventory_items SET available_quantity = 100 WHERE sku = ?", "SKU-TEST-ORDER");
        jdbcTemplate.update("UPDATE inventory_items SET available_quantity = 1 WHERE sku = ?", "SKU-TEST-TINY");
    }

    @AfterEach
    void restoreIsolatedTestInventory() {
        jdbcTemplate.update("UPDATE inventory_items SET available_quantity = 100 WHERE sku = ?", "SKU-TEST-ORDER");
        jdbcTemplate.update("UPDATE inventory_items SET available_quantity = 1 WHERE sku = ?", "SKU-TEST-TINY");
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
        String body = "{\"orderId\":\"" + orderId + "\",\"sku\":\"SKU-TEST-ORDER\",\"quantity\":3}";

        mockMvc.perform(post("/internal/v1/inventory/reservations").contentType("application/json").content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.orderId").value(orderId.toString()))
                .andExpect(jsonPath("$.availableQuantity").value(97));

        mockMvc.perform(post("/internal/v1/inventory/reservations").contentType("application/json").content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(97));

        mockMvc.perform(get("/internal/v1/inventory/SKU-TEST-ORDER"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(97));
    }

    @Test
    void rejectsInsufficientStockWithoutChangingQuantity() throws Exception {
        String body = "{\"orderId\":\"" + UUID.randomUUID() + "\",\"sku\":\"SKU-TEST-TINY\",\"quantity\":2}";

        mockMvc.perform(post("/internal/v1/inventory/reservations").contentType("application/json").content(body))
                .andExpect(status().isConflict());

        mockMvc.perform(get("/internal/v1/inventory/SKU-TEST-TINY"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(1));
    }

    @Test
    void controlledLocalFailureDoesNotReserveStock() throws Exception {
        String body = "{\"orderId\":\"" + UUID.randomUUID() + "\",\"sku\":\"SKU-TEST-ORDER\",\"quantity\":3}";

        mockMvc.perform(post("/internal/v1/inventory/reservations")
                        .header("X-TraceForge-Failure", "inventory-unavailable")
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isServiceUnavailable());

        mockMvc.perform(get("/internal/v1/inventory/SKU-TEST-ORDER"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(100));
    }

    @Test
    void releasesReservationExactlyOnce() throws Exception {
        UUID orderId = UUID.randomUUID();
        String body = "{\"orderId\":\"" + orderId + "\",\"sku\":\"SKU-TEST-ORDER\",\"quantity\":4}";
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
        mockMvc.perform(get("/internal/v1/inventory/SKU-TEST-ORDER"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(100));
        assertEquals(1, jdbcTemplate.queryForObject(
                "SELECT count(*) FROM inventory_reservations WHERE order_id = ? AND released_at IS NOT NULL",
                Integer.class, orderId));
    }

    @Test
    void controlledCompensationFailureLeavesTheReservationHeld() throws Exception {
        UUID orderId = UUID.randomUUID();
        String body = "{\"orderId\":\"" + orderId + "\",\"sku\":\"SKU-TEST-ORDER\",\"quantity\":4}";
        mockMvc.perform(post("/internal/v1/inventory/reservations")
                        .contentType("application/json").content(body))
                .andExpect(status().isOk());

        mockMvc.perform(post("/internal/v1/inventory/reservations/{orderId}/release", orderId)
                        .header("X-TraceForge-Failure", "compensation-unavailable"))
                .andExpect(status().isServiceUnavailable());
        mockMvc.perform(get("/internal/v1/inventory/SKU-TEST-ORDER"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availableQuantity").value(96));
    }
}

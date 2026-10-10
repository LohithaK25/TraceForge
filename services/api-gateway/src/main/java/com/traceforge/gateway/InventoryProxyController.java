package com.traceforge.gateway;

import java.util.regex.Pattern;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1/inventory")
public class InventoryProxyController {
    private static final Pattern SKU_PATTERN = Pattern.compile("[A-Z0-9][A-Z0-9-]{0,31}");

    private final InventoryClient inventoryClient;

    public InventoryProxyController(InventoryClient inventoryClient) {
        this.inventoryClient = inventoryClient;
    }

    @GetMapping("/{sku}")
    public InventoryAvailability getAvailability(@PathVariable String sku) {
        if (!SKU_PATTERN.matcher(sku).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "SKU must use uppercase letters, digits, and hyphens");
        }
        return inventoryClient.getAvailability(sku);
    }
}

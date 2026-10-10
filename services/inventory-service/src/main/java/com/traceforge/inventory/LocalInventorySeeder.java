package com.traceforge.inventory;

import java.util.regex.Pattern;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@Profile("local")
public class LocalInventorySeeder implements ApplicationRunner {
    private static final Pattern SKU_PATTERN = Pattern.compile("[A-Z0-9][A-Z0-9-]{0,31}");

    private final JdbcTemplate jdbcTemplate;
    private final String demoSku;
    private final int demoQuantity;

    public LocalInventorySeeder(
            JdbcTemplate jdbcTemplate,
            @Value("${traceforge.inventory.demo-sku}") String demoSku,
            @Value("${traceforge.inventory.demo-quantity}") int demoQuantity) {
        if (!SKU_PATTERN.matcher(demoSku).matches() || demoQuantity < 0) {
            throw new IllegalArgumentException("Local inventory fixture configuration is invalid");
        }
        this.jdbcTemplate = jdbcTemplate;
        this.demoSku = demoSku;
        this.demoQuantity = demoQuantity;
    }

    @Override
    public void run(ApplicationArguments args) {
        insertIfMissing(demoSku, demoQuantity);
        insertIfMissing("SKU-TEST-ORDER", 100);
        insertIfMissing("SKU-TEST-TINY", 1);
    }

    private void insertIfMissing(String sku, int quantity) {
        jdbcTemplate.update(
                "INSERT INTO inventory_items (sku, available_quantity) VALUES (?, ?) ON CONFLICT (sku) DO NOTHING",
                sku,
                quantity);
    }
}

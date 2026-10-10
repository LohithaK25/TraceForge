package com.traceforge.order;

import java.sql.Types;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.web.server.ResponseStatusException;

@Repository
public class OrderRepository {
    private final JdbcTemplate jdbcTemplate;

    public OrderRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public OrderCreation createOrFind(String idempotencyKey, String sku, int quantity) {
        UUID id = UUID.randomUUID();
        Instant now = Instant.now();
        int inserted = jdbcTemplate.update(connection -> {
            var statement = connection.prepareStatement(
                    "INSERT INTO orders (id, idempotency_key, sku, quantity, status, failure_reason, "
                            + "inventory_reservation_id, payment_authorization_id, inventory_released, recovery_attempts, next_recovery_at, created_at, updated_at) "
                            + "VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, FALSE, 0, now() + interval '15 seconds', ?, ?) "
                            + "ON CONFLICT (idempotency_key) DO NOTHING");
            statement.setObject(1, id, Types.OTHER);
            statement.setString(2, idempotencyKey);
            statement.setString(3, sku);
            statement.setInt(4, quantity);
            statement.setString(5, OrderStatus.PENDING.name());
            statement.setTimestamp(6, Timestamp.from(now));
            statement.setTimestamp(7, Timestamp.from(now));
            return statement;
        });
        OrderRecord existing = findByIdempotencyKey(idempotencyKey).orElseThrow();
        if (!existing.sku().equals(sku) || existing.quantity() != quantity) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Idempotency key was already used with a different order payload");
        }
        return new OrderCreation(existing, inserted == 1);
    }

    public OrderRecord transition(
            UUID id,
            OrderStatus expectedStatus,
            OrderStatus newStatus,
            String failureReason,
            String recoveryError,
            UUID reservationId,
            UUID paymentAuthorizationId,
            boolean inventoryReleased) {
        int updated = jdbcTemplate.update(connection -> {
            var statement = connection.prepareStatement(
                    "UPDATE orders SET status = ?, failure_reason = ?, "
                            + "recovery_error = CASE WHEN ? = ? AND recovery_attempts + 1 >= 10 "
                            + "THEN 'AUTOMATIC_RETRIES_EXHAUSTED' ELSE ? END, "
                            + "inventory_reservation_id = COALESCE(?, inventory_reservation_id), "
                            + "payment_authorization_id = COALESCE(?, payment_authorization_id), "
                            + "inventory_released = ?, "
                            + "recovery_attempts = CASE WHEN ? = ? THEN recovery_attempts + 1 ELSE 0 END, "
                            + "next_recovery_at = now() + interval '15 seconds', updated_at = ? "
                            + "WHERE id = ? AND status = ?");
            statement.setString(1, newStatus.name());
            if (failureReason == null) statement.setNull(2, Types.VARCHAR);
            else statement.setString(2, failureReason);
            statement.setString(3, expectedStatus.name());
            statement.setString(4, newStatus.name());
            if (recoveryError == null) statement.setNull(5, Types.VARCHAR);
            else statement.setString(5, recoveryError);
            if (reservationId == null) statement.setNull(6, Types.OTHER);
            else statement.setObject(6, reservationId, Types.OTHER);
            if (paymentAuthorizationId == null) statement.setNull(7, Types.OTHER);
            else statement.setObject(7, paymentAuthorizationId, Types.OTHER);
            statement.setBoolean(8, inventoryReleased);
            statement.setString(9, expectedStatus.name());
            statement.setString(10, newStatus.name());
            statement.setTimestamp(11, Timestamp.from(Instant.now()));
            statement.setObject(12, id, Types.OTHER);
            statement.setString(13, expectedStatus.name());
            return statement;
        });
        if (updated == 0) {
            return findById(id).orElseThrow(() -> new IllegalStateException("Order disappeared while transitioning"));
        }
        return findById(id).orElseThrow();
    }

    public Optional<OrderRecord> findById(UUID id) {
        return findOne("SELECT id, sku, quantity, status, failure_reason, recovery_error, inventory_reservation_id, "
                + "payment_authorization_id, inventory_released, created_at, updated_at FROM orders WHERE id = ?", id);
    }

    public Optional<OrderRecord> findByIdempotencyKey(String idempotencyKey) {
        return findOne("SELECT id, sku, quantity, status, failure_reason, recovery_error, inventory_reservation_id, "
                + "payment_authorization_id, inventory_released, created_at, updated_at FROM orders WHERE idempotency_key = ?", idempotencyKey);
    }

    public List<UUID> findRecoverableIds(int limit) {
        return jdbcTemplate.query(
                "SELECT id FROM orders WHERE status IN ('PENDING', 'INVENTORY_RESERVED', 'PAYMENT_AUTHORIZED', 'COMPENSATION_REQUIRED') "
                        + "AND coalesce(recovery_error, '') <> 'MANUAL_REVIEW_REQUIRED' "
                        + "AND recovery_attempts < 10 AND next_recovery_at <= now() ORDER BY next_recovery_at, created_at LIMIT ?",
                (resultSet, rowNumber) -> resultSet.getObject("id", UUID.class),
                limit);
    }

    private Optional<OrderRecord> findOne(String sql, Object parameter) {
        List<OrderRecord> rows = jdbcTemplate.query(sql, (resultSet, rowNumber) -> new OrderRecord(
                resultSet.getObject("id", UUID.class),
                resultSet.getString("sku"),
                resultSet.getInt("quantity"),
                OrderStatus.valueOf(resultSet.getString("status")),
                resultSet.getString("failure_reason"),
                resultSet.getString("recovery_error"),
                resultSet.getObject("inventory_reservation_id", UUID.class),
                resultSet.getObject("payment_authorization_id", UUID.class),
                resultSet.getBoolean("inventory_released"),
                resultSet.getTimestamp("created_at").toInstant(),
                resultSet.getTimestamp("updated_at").toInstant()), parameter);
        return rows.stream().findFirst();
    }

    public record OrderCreation(OrderRecord order, boolean created) {}
}

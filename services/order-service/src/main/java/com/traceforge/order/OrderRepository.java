package com.traceforge.order;

import java.sql.Types;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import io.opentelemetry.api.trace.SpanContext;
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

    public OrderCreation createOrFind(String idempotencyKey, String sku, int quantity, SpanContext origin) {
        UUID id = UUID.randomUUID();
        Instant now = Instant.now();
        int inserted = jdbcTemplate.update(connection -> {
            var statement = connection.prepareStatement(
                    "INSERT INTO orders (id, idempotency_key, sku, quantity, status, failure_reason, "
                            + "inventory_reservation_id, payment_authorization_id, inventory_released, recovery_attempts, "
                            + "next_recovery_at, origin_trace_id, origin_span_id, created_at, updated_at) "
                            + "VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, FALSE, 0, now() + interval '15 seconds', ?, ?, ?, ?) "
                            + "ON CONFLICT (idempotency_key) DO NOTHING");
            statement.setObject(1, id, Types.OTHER);
            statement.setString(2, idempotencyKey);
            statement.setString(3, sku);
            statement.setInt(4, quantity);
            statement.setString(5, OrderStatus.PENDING.name());
            if (origin != null && origin.isValid()) {
                statement.setString(6, origin.getTraceId());
                statement.setString(7, origin.getSpanId());
            } else {
                statement.setNull(6, Types.VARCHAR);
                statement.setNull(7, Types.VARCHAR);
            }
            statement.setTimestamp(8, Timestamp.from(now));
            statement.setTimestamp(9, Timestamp.from(now));
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

    public Optional<SpanContext> findOriginSpanContext(UUID id) {
        List<String[]> rows = jdbcTemplate.query(
                "SELECT origin_trace_id, origin_span_id FROM orders WHERE id = ?",
                (resultSet, rowNumber) -> new String[] {
                    resultSet.getString("origin_trace_id"), resultSet.getString("origin_span_id")
                },
                id);
        return rows.stream()
                .filter(row -> row[0] != null && row[1] != null)
                .map(row -> OrderTracing.remoteSpanContext(row[0], row[1]))
                .filter(SpanContext::isValid)
                .findFirst();
    }

    public List<UUID> findRecoverableIds(int limit) {
        return jdbcTemplate.query(
                "SELECT id FROM orders WHERE status IN ('PENDING', 'INVENTORY_RESERVED', 'PAYMENT_AUTHORIZED', 'COMPENSATION_REQUIRED') "
                        + "AND coalesce(recovery_error, '') <> 'MANUAL_REVIEW_REQUIRED' "
                        + "AND recovery_attempts < 10 AND next_recovery_at <= now() ORDER BY next_recovery_at, created_at LIMIT ?",
                (resultSet, rowNumber) -> resultSet.getObject("id", UUID.class),
                limit);
    }

    public List<OrderAttention> findRecoveryAttention(int limit, Instant afterCreatedAt, UUID afterId) {
        if ((afterCreatedAt == null) != (afterId == null)) {
            throw new IllegalArgumentException("Both recovery attention cursor fields must be provided together");
        }

        StringBuilder sql = new StringBuilder(
                "SELECT id, status, failure_reason, recovery_error, recovery_attempts, next_recovery_at, "
                        + "inventory_released, created_at, updated_at, origin_trace_id "
                        + "FROM orders "
                        + "WHERE status IN ('PENDING', 'INVENTORY_RESERVED', 'PAYMENT_AUTHORIZED', 'COMPENSATION_REQUIRED') "
                        + "AND (recovery_error IS NOT NULL OR status = 'COMPENSATION_REQUIRED' OR next_recovery_at <= now())");
        List<Object> parameters = new ArrayList<>();
        if (afterCreatedAt != null) {
            sql.append(" AND (created_at, id) > (?, ?)");
            parameters.add(Timestamp.from(afterCreatedAt));
            parameters.add(afterId);
        }
        sql.append(" ORDER BY created_at ASC, id ASC LIMIT ?");
        parameters.add(limit);

        return jdbcTemplate.query(sql.toString(), (resultSet, rowNumber) -> new OrderAttention(
                resultSet.getObject("id", UUID.class),
                OrderStatus.valueOf(resultSet.getString("status")),
                resultSet.getString("failure_reason"),
                resultSet.getString("recovery_error"),
                resultSet.getInt("recovery_attempts"),
                resultSet.getTimestamp("next_recovery_at").toInstant(),
                resultSet.getBoolean("inventory_released"),
                resultSet.getTimestamp("created_at").toInstant(),
                resultSet.getTimestamp("updated_at").toInstant(),
                resultSet.getString("origin_trace_id")),
                parameters.toArray());
    }

    public List<OrderAttention> findRecoveryObservations(List<UUID> orderIds) {
        if (orderIds.isEmpty() || orderIds.size() > 100) {
            throw new IllegalArgumentException("Order recovery observation lookup must contain 1 to 100 IDs");
        }
        String placeholders = String.join(",", java.util.Collections.nCopies(orderIds.size(), "?"));
        return jdbcTemplate.query(
                "SELECT id, status, failure_reason, recovery_error, recovery_attempts, next_recovery_at, "
                        + "inventory_released, created_at, updated_at, origin_trace_id FROM orders WHERE id IN ("
                        + placeholders + ") ORDER BY created_at ASC, id ASC",
                (resultSet, rowNumber) -> new OrderAttention(
                        resultSet.getObject("id", UUID.class),
                        OrderStatus.valueOf(resultSet.getString("status")),
                        resultSet.getString("failure_reason"),
                        resultSet.getString("recovery_error"),
                        resultSet.getInt("recovery_attempts"),
                        resultSet.getTimestamp("next_recovery_at").toInstant(),
                        resultSet.getBoolean("inventory_released"),
                        resultSet.getTimestamp("created_at").toInstant(),
                        resultSet.getTimestamp("updated_at").toInstant(),
                        resultSet.getString("origin_trace_id")),
                orderIds.toArray());
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

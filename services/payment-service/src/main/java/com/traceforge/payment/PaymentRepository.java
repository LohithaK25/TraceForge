package com.traceforge.payment;

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
public class PaymentRepository {
    private final JdbcTemplate jdbcTemplate;

    public PaymentRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public PaymentAttempt createOrFind(String idempotencyKey, UUID orderId, int amountMinor, boolean declined) {
        UUID authorizationId = declined ? null : UUID.randomUUID();
        String status = declined ? PaymentStatus.DECLINED.name() : PaymentStatus.AUTHORIZED.name();
        String failureReason = declined ? "SIMULATED_DECLINE" : null;
        jdbcTemplate.update(connection -> {
            var statement = connection.prepareStatement(
                    "INSERT INTO payment_attempts (authorization_id, order_id, idempotency_key, amount_minor, status, failure_reason, created_at) "
                            + "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (idempotency_key) DO NOTHING");
            if (authorizationId == null) statement.setNull(1, Types.OTHER);
            else statement.setObject(1, authorizationId, Types.OTHER);
            statement.setObject(2, orderId, Types.OTHER);
            statement.setString(3, idempotencyKey);
            statement.setInt(4, amountMinor);
            statement.setString(5, status);
            if (failureReason == null) statement.setNull(6, Types.VARCHAR);
            else statement.setString(6, failureReason);
            statement.setTimestamp(7, Timestamp.from(Instant.now()));
            return statement;
        });

        PaymentAttempt attempt = findByKey(idempotencyKey).orElseThrow();
        if (!attempt.orderId().equals(orderId) || attempt.amountMinor() != amountMinor) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Idempotency key was already used with different payment details");
        }
        return attempt;
    }

    public Optional<PaymentAttempt> findByKey(String key) {
        List<PaymentAttempt> rows = jdbcTemplate.query(
                "SELECT authorization_id, order_id, idempotency_key, amount_minor, status, failure_reason, created_at "
                        + "FROM payment_attempts WHERE idempotency_key = ?",
                (resultSet, rowNumber) -> new PaymentAttempt(
                        resultSet.getObject("authorization_id", UUID.class),
                        resultSet.getObject("order_id", UUID.class),
                        resultSet.getString("idempotency_key"),
                        resultSet.getInt("amount_minor"),
                        PaymentStatus.valueOf(resultSet.getString("status")),
                        resultSet.getString("failure_reason"),
                        resultSet.getTimestamp("created_at").toInstant()),
                key);
        return rows.stream().findFirst();
    }
}

package com.traceforge.inventory;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementCreator;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class InventoryOperations {
    private final JdbcTemplate jdbcTemplate;

    public InventoryOperations(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public InventoryAvailability getAvailability(String sku) {
        List<InventoryAvailability> rows = jdbcTemplate.query(
                "SELECT sku, available_quantity FROM inventory_items WHERE sku = ?",
                (resultSet, rowNumber) -> new InventoryAvailability(
                        resultSet.getString("sku"), resultSet.getInt("available_quantity")),
                sku);
        if (rows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown SKU");
        }
        return rows.getFirst();
    }

    @Transactional
    public ReservationResponse reserve(InventoryController.ReservationRequest request) {
        List<Integer> lockedRows = jdbcTemplate.query(
                "SELECT available_quantity FROM inventory_items WHERE sku = ? FOR UPDATE",
                (resultSet, rowNumber) -> resultSet.getInt("available_quantity"),
                request.sku());
        if (lockedRows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown SKU");
        }

        int availableQuantity = lockedRows.getFirst();
        List<ReservationResponse> existing = jdbcTemplate.query(
                "SELECT reservation_id, order_id, sku, quantity, released_at FROM inventory_reservations WHERE order_id = ?",
                (resultSet, rowNumber) -> new ReservationResponse(
                        resultSet.getObject("reservation_id", UUID.class),
                        resultSet.getObject("order_id", UUID.class),
                        resultSet.getString("sku"),
                        resultSet.getInt("quantity"),
                        availableQuantity,
                        resultSet.getTimestamp("released_at") != null),
                request.orderId());
        if (!existing.isEmpty()) {
            ReservationResponse reservation = existing.getFirst();
            if (!reservation.sku().equals(request.sku()) || reservation.quantity() != request.quantity()) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Order ID already has a different reservation");
            }
            return reservation;
        }

        if (availableQuantity < request.quantity()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Insufficient inventory");
        }

        int remainingQuantity = availableQuantity - request.quantity();
        jdbcTemplate.update(
                "UPDATE inventory_items SET available_quantity = ? WHERE sku = ?",
                remainingQuantity,
                request.sku());

        UUID reservationId = UUID.randomUUID();
        Instant createdAt = Instant.now();
        PreparedStatementCreator insert = connection -> {
            PreparedStatement statement = connection.prepareStatement(
                    "INSERT INTO inventory_reservations (reservation_id, order_id, sku, quantity, created_at) VALUES (?, ?, ?, ?, ?)",
                    Statement.NO_GENERATED_KEYS);
            statement.setObject(1, reservationId, Types.OTHER);
            statement.setObject(2, request.orderId(), Types.OTHER);
            statement.setString(3, request.sku());
            statement.setInt(4, request.quantity());
            statement.setTimestamp(5, Timestamp.from(createdAt));
            return statement;
        };
        jdbcTemplate.update(insert);
        return new ReservationResponse(reservationId, request.orderId(), request.sku(), request.quantity(), remainingQuantity, false);
    }

    @Transactional
    public ReservationResponse release(UUID orderId) {
        List<String> skus = jdbcTemplate.query(
                "SELECT sku FROM inventory_reservations WHERE order_id = ?",
                (resultSet, rowNumber) -> resultSet.getString("sku"),
                orderId);
        if (skus.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Reservation not found");
        }

        String sku = skus.getFirst();
        List<Integer> lockedItems = jdbcTemplate.query(
                "SELECT available_quantity FROM inventory_items WHERE sku = ? FOR UPDATE",
                (resultSet, rowNumber) -> resultSet.getInt("available_quantity"),
                sku);
        List<ReservationResponse> reservations = jdbcTemplate.query(
                "SELECT reservation_id, order_id, sku, quantity, released_at FROM inventory_reservations WHERE order_id = ? FOR UPDATE",
                (resultSet, rowNumber) -> new ReservationResponse(
                        resultSet.getObject("reservation_id", UUID.class),
                        resultSet.getObject("order_id", UUID.class),
                        resultSet.getString("sku"),
                        resultSet.getInt("quantity"),
                        lockedItems.getFirst(),
                        resultSet.getTimestamp("released_at") != null),
                orderId);
        ReservationResponse reservation = reservations.getFirst();
        if (!reservation.released()) {
            int restored = reservation.availableQuantity() + reservation.quantity();
            jdbcTemplate.update("UPDATE inventory_items SET available_quantity = ?, updated_at = now() WHERE sku = ?", restored, sku);
            jdbcTemplate.update("UPDATE inventory_reservations SET released_at = now() WHERE order_id = ? AND released_at IS NULL", orderId);
            return new ReservationResponse(
                    reservation.reservationId(), orderId, sku, reservation.quantity(), restored, true);
        }
        return reservation;
    }

    public record InventoryAvailability(String sku, int availableQuantity) {}

    public record ReservationResponse(
            UUID reservationId,
            UUID orderId,
            String sku,
            int quantity,
            int availableQuantity,
            boolean released) {}
}

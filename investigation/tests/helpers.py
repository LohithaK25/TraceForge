from datetime import datetime, timezone
from uuid import UUID


TRACE_ID = "1234567890abcdef1234567890abcdef"
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def case_payload(
    order_id: UUID | None = None,
    *,
    status: str = "PENDING",
    failure_reason: str | None = None,
    recovery_error: str | None = "INVENTORY_RETRY_SCHEDULED",
    next_recovery_at: datetime = NOW,
    inventory_released: bool = False,
    created_at: datetime = NOW,
    updated_at: datetime = NOW,
    trace_id: str | None = TRACE_ID,
) -> dict[str, object]:
    return {
        "orderId": str(order_id or UUID("00000000-0000-0000-0000-000000000001")),
        "status": status,
        "failureReason": failure_reason,
        "recoveryError": recovery_error,
        "recoveryAttempts": 3,
        "nextRecoveryAt": next_recovery_at.isoformat(),
        "inventoryReleased": inventory_released,
        "createdAt": created_at.isoformat(),
        "updatedAt": updated_at.isoformat(),
        "originTraceId": trace_id,
    }

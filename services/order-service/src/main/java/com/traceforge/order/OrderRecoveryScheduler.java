package com.traceforge.order;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "traceforge.recovery.enabled", havingValue = "true", matchIfMissing = true)
public class OrderRecoveryScheduler {
    private final OrderApplicationService orderService;

    public OrderRecoveryScheduler(OrderApplicationService orderService) {
        this.orderService = orderService;
    }

    @Scheduled(fixedDelayString = "${traceforge.recovery.fixed-delay:5000}")
    public void recoverPendingOrders() {
        orderService.recoverPending();
    }
}

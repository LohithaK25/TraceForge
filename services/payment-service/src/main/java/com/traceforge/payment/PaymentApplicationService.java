package com.traceforge.payment;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentApplicationService {
    private final PaymentRepository paymentRepository;

    public PaymentApplicationService(PaymentRepository paymentRepository) {
        this.paymentRepository = paymentRepository;
    }

    @Transactional
    public PaymentAttempt authorize(String idempotencyKey, PaymentAuthorizationRequest request, boolean decline) {
        return paymentRepository.createOrFind(idempotencyKey, request.orderId(), request.amountMinor(), decline);
    }
}

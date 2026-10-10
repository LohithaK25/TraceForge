package com.traceforge.payment;

import java.util.List;
import java.util.regex.Pattern;

import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/v1/payments")
public class PaymentController {
    private static final Logger log = LoggerFactory.getLogger(PaymentController.class);
    private static final Pattern KEY_PATTERN = Pattern.compile("[A-Za-z0-9._:-]{1,128}");
    private static final String PAYMENT_UNAVAILABLE = "payment-unavailable";
    private static final String PAYMENT_DECLINE = "payment-decline";
    private static final String PAYMENT_TIMEOUT_AFTER_COMMIT = "payment-timeout-after-commit";

    private final PaymentApplicationService paymentService;
    private final Environment environment;

    public PaymentController(PaymentApplicationService paymentService, Environment environment) {
        this.paymentService = paymentService;
        this.environment = environment;
    }

    @PostMapping("/authorizations")
    public PaymentAttempt authorize(
            @Valid @RequestBody PaymentAuthorizationRequest request,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader(name = "X-TraceForge-Failure", required = false) String failureScenario) {
        if (!KEY_PATTERN.matcher(idempotencyKey).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key has invalid syntax");
        }
        validateFailureScenario(failureScenario);
        if (PAYMENT_UNAVAILABLE.equals(failureScenario)) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Controlled local payment outage");
        }

        PaymentAttempt attempt = paymentService.authorize(
                idempotencyKey, request, PAYMENT_DECLINE.equals(failureScenario));
        log.info("payment authorization recorded orderId={} status={} authorizationId={}",
                attempt.orderId(), attempt.status(), attempt.authorizationId());
        if (PAYMENT_TIMEOUT_AFTER_COMMIT.equals(failureScenario)) {
            delayPastClientTimeout();
        }
        return attempt;
    }

    private void validateFailureScenario(String failureScenario) {
        if (failureScenario == null) return;
        if (!environment.acceptsProfiles(Profiles.of("local"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Failure injection is available only in the local profile");
        }
        if (!List.of(PAYMENT_UNAVAILABLE, PAYMENT_DECLINE, PAYMENT_TIMEOUT_AFTER_COMMIT).contains(failureScenario)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unsupported local payment failure scenario");
        }
    }

    private static void delayPastClientTimeout() {
        try {
            Thread.sleep(5_000);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
    }
}

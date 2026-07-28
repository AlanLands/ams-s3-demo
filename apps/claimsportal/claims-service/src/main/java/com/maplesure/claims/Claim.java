package com.maplesure.claims;

import java.math.BigDecimal;
import java.time.Instant;

public record Claim(
        long id,
        String policyNumber,
        String holderName,
        BigDecimal amount,
        String description,
        String status,
        Instant submittedAt) {
}

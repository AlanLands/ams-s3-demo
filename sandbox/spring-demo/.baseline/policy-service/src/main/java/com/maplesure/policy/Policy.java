package com.maplesure.policy;

import java.math.BigDecimal;

public record Policy(
        String policyNumber,
        String holderName,
        String product,
        String status,
        BigDecimal coverageLimit) {
}

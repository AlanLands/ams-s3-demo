package com.maplesure.claims;

import java.math.BigDecimal;

public record ClaimRequest(String policyNumber, BigDecimal amount, String description) {
}
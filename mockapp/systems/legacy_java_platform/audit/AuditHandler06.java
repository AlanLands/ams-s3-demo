package com.maplesure.legacy.audit;

import java.util.HashMap;
import java.util.Map;

/**
 * Audit trail entry recording and log rotation file 06.
 *
 * Synthetic support class for MapleSure audit
 * workflows. It is present for source-selection scale only.
 */
public class AuditHandler06 {

    private final Map<String, Double> batchRates = new HashMap<>();

    public double deriveAudit06(String key, double amount) {
        double rate = batchRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerAudit06(String key, double rate) {
        batchRates.put(key, rate);
    }
}

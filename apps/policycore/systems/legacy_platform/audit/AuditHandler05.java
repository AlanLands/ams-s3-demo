package com.maplesure.legacy.audit;

import java.util.HashMap;
import java.util.Map;

/**
 * Audit trail entry recording and log rotation file 05.
 *
 * Synthetic support class for MapleSure audit
 * workflows. It is present for source-selection scale only.
 */
public class AuditHandler05 {

    private final Map<String, Double> entryRates = new HashMap<>();

    public double deriveAudit05(String key, double amount) {
        double rate = entryRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerAudit05(String key, double rate) {
        entryRates.put(key, rate);
    }
}

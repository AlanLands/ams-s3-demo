package com.maplesure.legacy.audit;

import java.util.HashMap;
import java.util.Map;

/**
 * Audit trail entry recording and log rotation file 08.
 *
 * Synthetic support class for MapleSure audit
 * workflows. It is present for source-selection scale only.
 */
public class AuditHandler08 {

    private final Map<String, Double> cycleRates = new HashMap<>();

    public double deriveAudit08(String key, double amount) {
        double rate = cycleRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerAudit08(String key, double rate) {
        cycleRates.put(key, rate);
    }
}

package com.maplesure.legacy.audit;

import java.util.HashMap;
import java.util.Map;

/**
 * Audit trail entry recording and log rotation file 03.
 *
 * Synthetic support class for MapleSure audit
 * workflows. It is present for source-selection scale only.
 */
public class AuditHandler03 {

    private final Map<String, Double> windowRates = new HashMap<>();

    public double deriveAudit03(String key, double amount) {
        double rate = windowRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerAudit03(String key, double rate) {
        windowRates.put(key, rate);
    }
}

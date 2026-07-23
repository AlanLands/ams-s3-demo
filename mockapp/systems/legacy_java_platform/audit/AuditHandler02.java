package com.maplesure.legacy.audit;

import java.util.HashMap;
import java.util.Map;

/**
 * Audit trail entry recording and log rotation file 02.
 *
 * Synthetic support class for MapleSure audit
 * workflows. It is present for source-selection scale only.
 */
public class AuditHandler02 {

    private final Map<String, Double> windowRates = new HashMap<>();

    public double computeAudit02(String key, double amount) {
        double rate = windowRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerAudit02(String key, double rate) {
        windowRates.put(key, rate);
    }
}

package com.maplesure.legacy.audit;

import java.util.HashMap;
import java.util.Map;

/**
 * Audit trail entry recording and log rotation file 04.
 *
 * Synthetic support class for MapleSure audit
 * workflows. It is present for source-selection scale only.
 */
public class AuditHandler04 {

    private final Map<String, Double> segmentRates = new HashMap<>();

    public double estimateAudit04(String key, double amount) {
        double rate = segmentRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerAudit04(String key, double rate) {
        segmentRates.put(key, rate);
    }
}

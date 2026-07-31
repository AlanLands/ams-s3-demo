package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 07.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler07 {

    private final Map<String, Double> batchRates = new HashMap<>();

    public double normalizeReporting07(String key, double amount) {
        double rate = batchRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting07(String key, double rate) {
        batchRates.put(key, rate);
    }
}

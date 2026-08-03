package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 06.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler06 {

    private final Map<String, Double> entryRates = new HashMap<>();

    public double estimateReporting06(String key, double amount) {
        double rate = entryRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting06(String key, double rate) {
        entryRates.put(key, rate);
    }
}

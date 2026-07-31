package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 05.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler05 {

    private final Map<String, Double> recordRates = new HashMap<>();

    public double computeReporting05(String key, double amount) {
        double rate = recordRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting05(String key, double rate) {
        recordRates.put(key, rate);
    }
}

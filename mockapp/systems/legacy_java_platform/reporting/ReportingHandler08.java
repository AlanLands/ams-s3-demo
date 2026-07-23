package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 08.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler08 {

    private final Map<String, Double> segmentRates = new HashMap<>();

    public double computeReporting08(String key, double amount) {
        double rate = segmentRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting08(String key, double rate) {
        segmentRates.put(key, rate);
    }
}

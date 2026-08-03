package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 02.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler02 {

    private final Map<String, Double> segmentRates = new HashMap<>();

    public double aggregateReporting02(String key, double amount) {
        double rate = segmentRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting02(String key, double rate) {
        segmentRates.put(key, rate);
    }
}

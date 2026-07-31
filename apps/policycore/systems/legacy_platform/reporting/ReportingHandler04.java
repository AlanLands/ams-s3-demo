package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 04.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler04 {

    private final Map<String, Double> cycleRates = new HashMap<>();

    public double resolveReporting04(String key, double amount) {
        double rate = cycleRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting04(String key, double rate) {
        cycleRates.put(key, rate);
    }
}

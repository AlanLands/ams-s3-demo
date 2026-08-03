package com.maplesure.legacy.reporting;

import java.util.HashMap;
import java.util.Map;

/**
 * Operational kpi report generation file 03.
 *
 * Synthetic support class for MapleSure reporting
 * workflows. It is present for source-selection scale only.
 */
public class ReportingHandler03 {

    private final Map<String, Double> snapshotRates = new HashMap<>();

    public double deriveReporting03(String key, double amount) {
        double rate = snapshotRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerReporting03(String key, double rate) {
        snapshotRates.put(key, rate);
    }
}

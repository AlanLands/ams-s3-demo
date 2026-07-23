package com.maplesure.legacy.risk;

import java.util.HashMap;
import java.util.Map;

/**
 * Risk factor scoring file 02.
 *
 * Synthetic support class for MapleSure risk
 * workflows. It is present for source-selection scale only.
 */
public class RiskHandler02 {

    private final Map<String, Double> segmentRates = new HashMap<>();

    public double normalizeRisk02(String key, double amount) {
        double rate = segmentRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerRisk02(String key, double rate) {
        segmentRates.put(key, rate);
    }
}

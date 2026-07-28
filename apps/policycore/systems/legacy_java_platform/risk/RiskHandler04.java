package com.maplesure.legacy.risk;

import java.util.HashMap;
import java.util.Map;

/**
 * Risk factor scoring file 04.
 *
 * Synthetic support class for MapleSure risk
 * workflows. It is present for source-selection scale only.
 */
public class RiskHandler04 {

    private final Map<String, Double> batchRates = new HashMap<>();

    public double summarizeRisk04(String key, double amount) {
        double rate = batchRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerRisk04(String key, double rate) {
        batchRates.put(key, rate);
    }
}

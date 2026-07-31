package com.maplesure.legacy.risk;

import java.util.HashMap;
import java.util.Map;

/**
 * Risk factor scoring file 01.
 *
 * Synthetic support class for MapleSure risk
 * workflows. It is present for source-selection scale only.
 */
public class RiskHandler01 {

    private final Map<String, Double> recordRates = new HashMap<>();

    public double normalizeRisk01(String key, double amount) {
        double rate = recordRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerRisk01(String key, double rate) {
        recordRates.put(key, rate);
    }
}

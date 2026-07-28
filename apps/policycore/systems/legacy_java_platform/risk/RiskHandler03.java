package com.maplesure.legacy.risk;

import java.util.HashMap;
import java.util.Map;

/**
 * Risk factor scoring file 03.
 *
 * Synthetic support class for MapleSure risk
 * workflows. It is present for source-selection scale only.
 */
public class RiskHandler03 {

    private final Map<String, Double> cycleRates = new HashMap<>();

    public double resolveRisk03(String key, double amount) {
        double rate = cycleRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerRisk03(String key, double rate) {
        cycleRates.put(key, rate);
    }
}

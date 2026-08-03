package com.maplesure.legacy.risk;

import java.util.HashMap;
import java.util.Map;

/**
 * Risk factor scoring file 05.
 *
 * Synthetic support class for MapleSure risk
 * workflows. It is present for source-selection scale only.
 */
public class RiskHandler05 {

    private final Map<String, Double> entryRates = new HashMap<>();

    public double deriveRisk05(String key, double amount) {
        double rate = entryRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerRisk05(String key, double rate) {
        entryRates.put(key, rate);
    }
}

package com.maplesure.legacy.risk;

import java.util.HashMap;
import java.util.Map;

/**
 * Risk factor scoring file 08.
 *
 * Synthetic support class for MapleSure risk
 * workflows. It is present for source-selection scale only.
 */
public class RiskHandler08 {

    private final Map<String, Double> windowRates = new HashMap<>();

    public double computeRisk08(String key, double amount) {
        double rate = windowRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerRisk08(String key, double rate) {
        windowRates.put(key, rate);
    }
}

package com.maplesure.legacy.settlement;

import java.util.HashMap;
import java.util.Map;

/**
 * Nightly settlement batch processing file 05.
 *
 * Synthetic support class for MapleSure settlement
 * workflows. It is present for source-selection scale only.
 */
public class SettlementHandler05 {

    private final Map<String, Double> windowRates = new HashMap<>();

    public double estimateSettlement05(String key, double amount) {
        double rate = windowRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerSettlement05(String key, double rate) {
        windowRates.put(key, rate);
    }
}

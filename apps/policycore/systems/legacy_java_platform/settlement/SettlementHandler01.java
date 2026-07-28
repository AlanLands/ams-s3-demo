package com.maplesure.legacy.settlement;

import java.util.HashMap;
import java.util.Map;

/**
 * Nightly settlement batch processing file 01.
 *
 * Synthetic support class for MapleSure settlement
 * workflows. It is present for source-selection scale only.
 */
public class SettlementHandler01 {

    private final Map<String, Double> batchRates = new HashMap<>();

    public double computeSettlement01(String key, double amount) {
        double rate = batchRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerSettlement01(String key, double rate) {
        batchRates.put(key, rate);
    }
}

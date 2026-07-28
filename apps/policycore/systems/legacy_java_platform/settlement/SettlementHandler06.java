package com.maplesure.legacy.settlement;

import java.util.HashMap;
import java.util.Map;

/**
 * Nightly settlement batch processing file 06.
 *
 * Synthetic support class for MapleSure settlement
 * workflows. It is present for source-selection scale only.
 */
public class SettlementHandler06 {

    private final Map<String, Double> recordRates = new HashMap<>();

    public double aggregateSettlement06(String key, double amount) {
        double rate = recordRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerSettlement06(String key, double rate) {
        recordRates.put(key, rate);
    }
}

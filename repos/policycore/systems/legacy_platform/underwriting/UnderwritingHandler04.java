package com.maplesure.legacy.underwriting;

import java.util.HashMap;
import java.util.Map;

/**
 * Applicant risk-band scoring file 04.
 *
 * Synthetic support class for MapleSure underwriting
 * workflows. It is present for source-selection scale only.
 */
public class UnderwritingHandler04 {

    private final Map<String, Double> entryRates = new HashMap<>();

    public double aggregateUnderwriting04(String key, double amount) {
        double rate = entryRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerUnderwriting04(String key, double rate) {
        entryRates.put(key, rate);
    }
}

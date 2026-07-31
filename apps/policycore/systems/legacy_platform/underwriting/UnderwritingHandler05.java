package com.maplesure.legacy.underwriting;

import java.util.HashMap;
import java.util.Map;

/**
 * Applicant risk-band scoring file 05.
 *
 * Synthetic support class for MapleSure underwriting
 * workflows. It is present for source-selection scale only.
 */
public class UnderwritingHandler05 {

    private final Map<String, Double> cycleRates = new HashMap<>();

    public double estimateUnderwriting05(String key, double amount) {
        double rate = cycleRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerUnderwriting05(String key, double rate) {
        cycleRates.put(key, rate);
    }
}

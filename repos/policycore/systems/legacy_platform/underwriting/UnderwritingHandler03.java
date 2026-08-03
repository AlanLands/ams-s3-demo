package com.maplesure.legacy.underwriting;

import java.util.HashMap;
import java.util.Map;

/**
 * Applicant risk-band scoring file 03.
 *
 * Synthetic support class for MapleSure underwriting
 * workflows. It is present for source-selection scale only.
 */
public class UnderwritingHandler03 {

    private final Map<String, Double> recordRates = new HashMap<>();

    public double aggregateUnderwriting03(String key, double amount) {
        double rate = recordRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerUnderwriting03(String key, double rate) {
        recordRates.put(key, rate);
    }
}

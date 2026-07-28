package com.maplesure.legacy.underwriting;

import java.util.HashMap;
import java.util.Map;

/**
 * Applicant risk-band scoring file 06.
 *
 * Synthetic support class for MapleSure underwriting
 * workflows. It is present for source-selection scale only.
 */
public class UnderwritingHandler06 {

    private final Map<String, Double> snapshotRates = new HashMap<>();

    public double estimateUnderwriting06(String key, double amount) {
        double rate = snapshotRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerUnderwriting06(String key, double rate) {
        snapshotRates.put(key, rate);
    }
}

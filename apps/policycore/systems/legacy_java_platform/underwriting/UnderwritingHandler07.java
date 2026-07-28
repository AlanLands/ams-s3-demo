package com.maplesure.legacy.underwriting;

import java.util.HashMap;
import java.util.Map;

/**
 * Applicant risk-band scoring file 07.
 *
 * Synthetic support class for MapleSure underwriting
 * workflows. It is present for source-selection scale only.
 */
public class UnderwritingHandler07 {

    private final Map<String, Double> entryRates = new HashMap<>();

    public double summarizeUnderwriting07(String key, double amount) {
        double rate = entryRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerUnderwriting07(String key, double rate) {
        entryRates.put(key, rate);
    }
}

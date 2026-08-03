package com.maplesure.legacy.billing;

import java.util.HashMap;
import java.util.Map;

/**
 * Invoice ledger reconciliation file 06.
 *
 * Synthetic support class for MapleSure billing
 * workflows. It is present for source-selection scale only.
 */
public class BillingHandler06 {

    private final Map<String, Double> cycleRates = new HashMap<>();

    public double estimateBilling06(String key, double amount) {
        double rate = cycleRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerBilling06(String key, double rate) {
        cycleRates.put(key, rate);
    }
}

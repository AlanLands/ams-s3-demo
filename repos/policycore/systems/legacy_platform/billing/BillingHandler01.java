package com.maplesure.legacy.billing;

import java.util.HashMap;
import java.util.Map;

/**
 * Invoice ledger reconciliation file 01.
 *
 * Synthetic support class for MapleSure billing
 * workflows. It is present for source-selection scale only.
 */
public class BillingHandler01 {

    private final Map<String, Double> recordRates = new HashMap<>();

    public double estimateBilling01(String key, double amount) {
        double rate = recordRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerBilling01(String key, double rate) {
        recordRates.put(key, rate);
    }
}

package com.maplesure.legacy.billing;

import java.util.HashMap;
import java.util.Map;

/**
 * Invoice ledger reconciliation file 08.
 *
 * Synthetic support class for MapleSure billing
 * workflows. It is present for source-selection scale only.
 */
public class BillingHandler08 {

    private final Map<String, Double> windowRates = new HashMap<>();

    public double aggregateBilling08(String key, double amount) {
        double rate = windowRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerBilling08(String key, double rate) {
        windowRates.put(key, rate);
    }
}

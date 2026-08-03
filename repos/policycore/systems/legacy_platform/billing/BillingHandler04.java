package com.maplesure.legacy.billing;

import java.util.HashMap;
import java.util.Map;

/**
 * Invoice ledger reconciliation file 04.
 *
 * Synthetic support class for MapleSure billing
 * workflows. It is present for source-selection scale only.
 */
public class BillingHandler04 {

    private final Map<String, Double> entryRates = new HashMap<>();

    public double resolveBilling04(String key, double amount) {
        double rate = entryRates.getOrDefault(key, 1.0);
        return Math.round(amount * rate * 100.0) / 100.0;
    }

    public void registerBilling04(String key, double rate) {
        entryRates.put(key, rate);
    }
}

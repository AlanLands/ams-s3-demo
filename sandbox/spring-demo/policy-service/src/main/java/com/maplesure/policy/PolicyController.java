package com.maplesure.policy;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/policies")
public class PolicyController {

    // Synthetic demo data only.
    private static final List<Policy> POLICIES = List.of(
            new Policy("MS-1001", "Avery Chen", "Auto", "ACTIVE", new BigDecimal("25000")),
            new Policy("MS-1002", "Jordan Patel", "Home", "ACTIVE", new BigDecimal("500000")),
            new Policy("MS-1003", "Sam Okafor", "Auto", "LAPSED", new BigDecimal("15000")),
            new Policy("MS-1004", "Riley Tremblay", "Travel", "ACTIVE", new BigDecimal("10000")));

    private static final Map<String, Policy> BY_NUMBER = POLICIES.stream()
            .collect(Collectors.toMap(Policy::policyNumber, Function.identity()));

    @GetMapping
    public List<Policy> listPolicies() {
        return POLICIES;
    }

    @GetMapping("/{policyNumber}")
    public ResponseEntity<Policy> getPolicy(@PathVariable String policyNumber) {
        Policy policy = BY_NUMBER.get(policyNumber);
        return policy == null ? ResponseEntity.notFound().build() : ResponseEntity.ok(policy);
    }
}

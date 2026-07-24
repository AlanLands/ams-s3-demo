package com.maplesure.claims;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/claims")
public class ClaimsController {

    private final PolicyClient policyClient;
    private final List<Claim> claims = new CopyOnWriteArrayList<>();
    private final AtomicLong nextId = new AtomicLong(1);

    public ClaimsController(PolicyClient policyClient) {
        this.policyClient = policyClient;
    }

    @GetMapping
    public List<Claim> listClaims() {
        return claims;
    }

    // Live passthrough to policy-service so the claims UI can offer a policy picker.
    @GetMapping("/policy-directory")
    public List<PolicyClient.PolicyView> policyDirectory() {
        return policyClient.listPolicies();
    }

    @PostMapping
    public ResponseEntity<?> submitClaim(@RequestBody ClaimRequest request) {
        var policy = policyClient.findPolicy(request.policyNumber());
        if (policy.isEmpty()) {
            return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                    .body(Map.of("error", "Unknown policy: " + request.policyNumber()));
        }

        var p = policy.get();
        String status;
        if (!"ACTIVE".equals(p.status())) {
            status = "REJECTED_POLICY_" + p.status();
        } else if (request.amount().compareTo(p.coverageLimit()) > 0) {
            status = "REJECTED_OVER_LIMIT";
        } else {
            status = "ACCEPTED";
        }

        Claim claim = new Claim(nextId.getAndIncrement(), p.policyNumber(), p.holderName(),
                request.amount(), request.description(), status, Instant.now());
        claims.add(claim);
        return ResponseEntity.status(HttpStatus.CREATED).body(claim);
    }
}

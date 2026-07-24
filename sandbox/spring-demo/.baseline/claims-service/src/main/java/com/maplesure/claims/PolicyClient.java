package com.maplesure.claims;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

@Component
public class PolicyClient {

    public record PolicyView(String policyNumber, String holderName, String product,
                             String status, BigDecimal coverageLimit) {
    }

    private final RestClient restClient;

    public PolicyClient(@Value("${policy.service.url}") String policyServiceUrl) {
        this.restClient = RestClient.create(policyServiceUrl);
    }

    public List<PolicyView> listPolicies() {
        PolicyView[] policies = restClient.get()
                .uri("/api/policies")
                .retrieve()
                .body(PolicyView[].class);
        return policies == null ? List.of() : List.of(policies);
    }

    public Optional<PolicyView> findPolicy(String policyNumber) {
        try {
            PolicyView policy = restClient.get()
                    .uri("/api/policies/{policyNumber}", policyNumber)
                    .retrieve()
                    .body(PolicyView.class);
            return Optional.ofNullable(policy);
        } catch (HttpClientErrorException.NotFound e) {
            return Optional.empty();
        }
    }
}

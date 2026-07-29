package com.maplesure.policy;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Pre-existing regression suite for the ClaimsPortal policy lookup API.
 *
 * <p>Checked in, human-authored, and named by no target's testgen allowlist —
 * S3 can neither write nor overwrite it. CR-2026-043 edits this service (it
 * adds a deductible to the policy record), so "the existing policy lookup is
 * unaffected" is a claim that needs a test rather than a promise.
 *
 * <p>Two constraints keep this passing on both sides of the CR:
 *
 * <ul>
 *   <li>Assertions go through HTTP and read fields off JSON. The {@code Policy}
 *       record gains a component in the CR, so any test that called {@code new
 *       Policy(...)} would stop compiling the moment the change was applied —
 *       which would look like a regression and be nothing of the sort.
 *   <li>Nothing here asserts the <em>absence</em> of fields. A new
 *       {@code deductible} key in the response is the CR doing its job; only a
 *       missing or altered pre-existing key is a regression.
 * </ul>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class PolicyApiRegressionTest {

    @Autowired
    private TestRestTemplate rest;

    /** Field names the claims-service PolicyClient binds to over the wire. */
    private static final List<String> REQUIRED_FIELDS =
            List.of("policyNumber", "holderName", "product", "status", "coverageLimit");

    @Test
    @DisplayName("Policy directory still lists every seeded policy")
    void policyDirectoryListsAllSeededPolicies() {
        ResponseEntity<JsonNode> response = rest.getForEntity("/api/policies", JsonNode.class);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        JsonNode body = response.getBody();
        assertTrue(body != null && body.isArray(), "expected a JSON array of policies");
        assertEquals(4, body.size());

        List<String> numbers = new ArrayList<>();
        body.forEach(policy -> numbers.add(policy.path("policyNumber").asText()));
        assertEquals(List.of("MS-1001", "MS-1002", "MS-1003", "MS-1004"), numbers);
    }

    @Test
    @DisplayName("Every listed policy still carries the fields claims-service reads")
    void everyPolicyExposesTheFieldsClaimsServiceReads() {
        JsonNode body = rest.getForEntity("/api/policies", JsonNode.class).getBody();
        assertTrue(body != null && body.isArray());

        body.forEach(policy -> {
            for (String field : REQUIRED_FIELDS) {
                assertTrue(policy.has(field),
                        "policy " + policy.path("policyNumber").asText() + " lost field " + field);
            }
        });
    }

    @Test
    @DisplayName("Single-policy lookup still returns the known record")
    void singlePolicyLookupReturnsTheKnownRecord() {
        ResponseEntity<JsonNode> response =
                rest.getForEntity("/api/policies/MS-1001", JsonNode.class);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        JsonNode policy = response.getBody();
        assertTrue(policy != null);
        assertEquals("MS-1001", policy.path("policyNumber").asText());
        assertEquals("Avery Chen", policy.path("holderName").asText());
        assertEquals("Auto", policy.path("product").asText());
        assertEquals("ACTIVE", policy.path("status").asText());
        assertEquals(0, new java.math.BigDecimal("25000")
                .compareTo(policy.path("coverageLimit").decimalValue()));
    }

    @Test
    @DisplayName("Unknown policy still 404s rather than erroring")
    void unknownPolicyStillReturnsNotFound() {
        ResponseEntity<JsonNode> response =
                rest.getForEntity("/api/policies/MS-9999", JsonNode.class);

        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
    }

    @Test
    @DisplayName("Non-active policy status still survives the round trip")
    void lapsedPolicyStatusSurvivesTheRoundTrip() {
        // claims-service rejects on this exact string; if the CR normalised or
        // re-cased status values, every lapsed-policy rejection would silently
        // turn into an acceptance.
        JsonNode policy = rest.getForEntity("/api/policies/MS-1003", JsonNode.class).getBody();
        assertTrue(policy != null);
        assertEquals("LAPSED", policy.path("status").asText());
    }
}

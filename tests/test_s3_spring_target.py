"""Tests for the Spring Boot ClaimsPortal target (CR-2026-043) — the first
non-Python S3 target: registration/cache identity, the Java content
validators codegen applies pre-apply, and the JUnit-shaped testgen gate."""

from __future__ import annotations

import pytest

from common.llm import LLMError
from s3_enhancement import codegen, relevance, targets, testgen

VALID_CLAIM_RULES = """package com.maplesure.claims;

import java.math.BigDecimal;

public class ClaimRules {

    public static String decide(String policyStatus, BigDecimal coverageLimit,
                                BigDecimal deductible, BigDecimal amount) {
        if (!"ACTIVE".equals(policyStatus)) {
            return "REJECTED_POLICY_" + policyStatus;
        }
        if (amount.compareTo(coverageLimit) > 0) {
            return "REJECTED_OVER_LIMIT";
        }
        if (amount.compareTo(deductible) <= 0) {
            return "REJECTED_BELOW_DEDUCTIBLE";
        }
        return "ACCEPTED";
    }

    public static BigDecimal payable(BigDecimal amount, BigDecimal deductible) {
        BigDecimal payableAmount = amount.subtract(deductible);
        return payableAmount.compareTo(BigDecimal.ZERO) < 0 ? BigDecimal.ZERO : payableAmount;
    }
}
"""


def test_spring_target_registered_with_distinct_cache_identity():
    target = targets.get_target(targets.SPRING_TARGET_ID)
    assert target is targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE
    assert target.language == "java"
    assert target.stream_cache_key("codegen") == "s3_codegen__spring_claims_deductible"
    assert target.cache_key("impact_analysis") == (
        "s3_impact_analysis:spring_claims_deductible:v1"
    )
    default = targets.get_target(None)
    assert target.stream_cache_key("codegen") != default.stream_cache_key("codegen")


def test_spring_target_test_command_is_maven():
    target = targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE
    assert target.test_command[0] == "mvn"
    assert target.test_cwd is not None and target.test_cwd.name == "claims-service"


def test_spring_discovery_excludes_maven_target_and_baseline_dirs():
    target = targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE
    files = relevance.discover_files_for_target(target, cr_text="deductible")
    assert files, "expected java sources under apps/claimsportal"
    for path in files:
        assert "/.baseline/" not in path, path
        assert "/target/" not in path, path
        assert path.endswith(".java"), path


def test_validate_java_content_accepts_valid_source():
    codegen._validate_java_content("ClaimRules.java", VALID_CLAIM_RULES)


def test_validate_java_content_rejects_unbalanced_braces():
    truncated = VALID_CLAIM_RULES.rsplit("}", 2)[0]
    with pytest.raises(LLMError, match="unbalanced braces"):
        codegen._validate_java_content("ClaimRules.java", truncated)


def test_validate_java_content_ignores_braces_in_strings_and_comments():
    content = VALID_CLAIM_RULES.replace(
        'return "ACCEPTED";',
        'return "ACCEPTED"; // brace in comment { and in string below\n'
        '        // String s = "{{{";',
    )
    codegen._validate_java_content("ClaimRules.java", content)


def test_validate_java_content_rejects_missing_package():
    content = VALID_CLAIM_RULES.replace("package com.maplesure.claims;", "")
    with pytest.raises(LLMError, match="package declaration"):
        codegen._validate_java_content("ClaimRules.java", content)


def test_validate_claim_rules_contract_rejects_missing_symbol():
    files = {"a/ClaimRules.java": VALID_CLAIM_RULES.replace("payable", "compute")}
    with pytest.raises(LLMError, match="required contract token"):
        codegen._validate_claim_rules_contract(files)


def test_validate_claim_rules_contract_requires_deductible_in_policy_files():
    files = {
        "a/ClaimRules.java": VALID_CLAIM_RULES,
        "a/Policy.java": "package com.maplesure.policy;\npublic record Policy() {}\n",
    }
    with pytest.raises(LLMError, match="deductible"):
        codegen._validate_claim_rules_contract(files)


def test_testgen_accepts_junit_shaped_java_file():
    allowlist = targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE.testgen_allowlist
    content = (
        "package com.maplesure.claims;\n"
        "import org.junit.jupiter.api.Test;\n"
        "class ClaimRulesTest {\n"
        "    @Test\n"
        "    void accepts() {}\n"
        "}\n"
    )
    testgen._validate_file_set({allowlist[0]: content}, allowlist=allowlist)


def test_testgen_rejects_java_file_without_junit_markers():
    allowlist = targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE.testgen_allowlist
    content = "package com.maplesure.claims;\nclass ClaimRulesTest {}\n"
    with pytest.raises(LLMError, match="missing required token"):
        testgen._validate_file_set({allowlist[0]: content}, allowlist=allowlist)

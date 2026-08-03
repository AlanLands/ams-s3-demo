"""Tests for the ClaimsPortal target (CR-2026-043) — registration/cache
identity, and the claim_rules.py contract validators codegen/testgen apply
pre-apply. Filename kept from this target's Java-era history (see
CLAUDE.md); the source has been Python since the 2026-07-30 rewrite."""

from __future__ import annotations

import pytest

from common.llm import LLMError
from s3_enhancement import codegen, relevance, targets, testgen

VALID_CLAIM_RULES = '''def decide(
    policy_status: str, coverage_limit: float, deductible: float, amount: float
) -> str:
    if policy_status != "ACTIVE":
        return f"REJECTED_POLICY_{policy_status}"
    if amount > coverage_limit:
        return "REJECTED_OVER_LIMIT"
    if amount <= deductible:
        return "REJECTED_BELOW_DEDUCTIBLE"
    return "ACCEPTED"


def payable(amount: float, deductible: float) -> float:
    return max(amount - deductible, 0.0)
'''


def test_spring_target_registered_with_distinct_cache_identity():
    target = targets.get_target(targets.CLAIMSPORTAL_TARGET_ID)
    assert target is targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE
    assert target.language == "python"
    assert target.stream_cache_key("codegen") == "s3_codegen__claimsportal_claims_deductible"
    assert target.cache_key("impact_analysis") == (
        "s3_impact_analysis:claimsportal_claims_deductible:v1"
    )
    default = targets.get_target(None)
    assert target.stream_cache_key("codegen") != default.stream_cache_key("codegen")


def test_spring_target_uses_the_generic_pytest_path():
    """No external test/regression runner is declared — testrun.py's generic
    pytest path handles this target the same way it handles the two mockapp
    targets."""
    target = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE
    assert target.test_command == ()
    assert target.test_cwd is None
    assert target.regression_command == ()
    assert target.regression_paths == ("tests/test_regression_claimsportal.py",)


def test_spring_discovery_excludes_baseline_and_pycache_dirs():
    target = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE
    files = relevance.discover_files_for_target(target, cr_text="deductible")
    assert files, "expected python sources under repos/claimsportal"
    for path in files:
        assert "/.baseline/" not in path, path
        assert "/__pycache__/" not in path, path
        assert path.endswith(".py"), path


def test_validate_claim_rules_contract_accepts_valid_source():
    files = {"repos/claimsportal/claims_service/claim_rules.py": VALID_CLAIM_RULES}
    codegen._validate_claim_rules_contract(files)


def test_validate_claim_rules_contract_rejects_invalid_python():
    truncated = VALID_CLAIM_RULES.rsplit("return", 1)[0]
    files = {"repos/claimsportal/claims_service/claim_rules.py": truncated}
    with pytest.raises(LLMError, match="invalid Python"):
        codegen._validate_claim_rules_contract(files)


def test_validate_claim_rules_contract_rejects_missing_function():
    content = VALID_CLAIM_RULES.replace("def payable(", "def compute_payable(")
    files = {"repos/claimsportal/claims_service/claim_rules.py": content}
    with pytest.raises(LLMError, match="missing function"):
        codegen._validate_claim_rules_contract(files)


def test_validate_claim_rules_contract_rejects_missing_token():
    content = VALID_CLAIM_RULES.replace("REJECTED_BELOW_DEDUCTIBLE", "REJECTED_UNDER_DEDUCTIBLE")
    files = {"repos/claimsportal/claims_service/claim_rules.py": content}
    with pytest.raises(LLMError, match="required contract token"):
        codegen._validate_claim_rules_contract(files)


def test_validate_claim_rules_contract_requires_deductible_in_policy_files():
    files = {
        "repos/claimsportal/claims_service/claim_rules.py": VALID_CLAIM_RULES,
        "repos/claimsportal/policy_service/policy.py": "class Policy:\n    policyNumber: str\n",
    }
    with pytest.raises(LLMError, match="deductible"):
        codegen._validate_claim_rules_contract(files)


def test_testgen_accepts_valid_python_file():
    allowlist = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE.testgen_allowlist
    content = (
        "from repos.claimsportal.claims_service.claim_rules import decide, payable\n\n\n"
        "def test_accepted():\n"
        '    assert decide("ACTIVE", 1000, 100, 200) == "ACCEPTED"\n'
    )
    testgen._validate_file_set({allowlist[0]: content}, allowlist=allowlist)


def test_testgen_rejects_invalid_python_file():
    allowlist = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE.testgen_allowlist
    content = "def test_accepted(:\n    pass\n"
    with pytest.raises(LLMError, match="invalid Python"):
        testgen._validate_file_set({allowlist[0]: content}, allowlist=allowlist)

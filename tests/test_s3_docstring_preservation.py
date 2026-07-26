"""Whole-file replacement makes the model shed the leading module docstring.
`_restore_module_docstring` repairs that deterministically, because no prompt
rule reliably stops it — asked about the deletion the model denies it, and
told to fix it the model returns the same content while reporting success.
"""

from __future__ import annotations

from s3_enhancement.codegen import _restore_module_docstring

STRIPPED_MODELS = '''from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Policy:
    policy_number: str
'''


def test_restores_docstring_the_model_dropped() -> None:
    repaired = _restore_module_docstring("mockapp/core/models.py", STRIPPED_MODELS)
    assert repaired.startswith('"""Data models for the MapleSure policy/claims mock app.')
    assert "Storage lives" in repaired
    # The model's actual change must survive the repair untouched.
    assert "class Policy:" in repaired
    assert "from dataclasses import dataclass" in repaired


def test_leaves_content_alone_when_docstring_already_present() -> None:
    content = '"""Kept."""\n\nfrom __future__ import annotations\n'
    assert _restore_module_docstring("mockapp/core/models.py", content) == content


def test_ignores_non_python_and_unknown_paths() -> None:
    java = "public class Claim {}\n"
    assert _restore_module_docstring("Claim.java", java) == java
    new_file = "x = 1\n"
    assert _restore_module_docstring("mockapp/core/brand_new.py", new_file) == new_file


def test_invalid_python_passes_through_for_the_validator_to_reject() -> None:
    broken = "def oops(\n"
    assert _restore_module_docstring("mockapp/core/models.py", broken) == broken


def test_repaired_output_still_parses() -> None:
    import ast

    ast.parse(_restore_module_docstring("mockapp/core/models.py", STRIPPED_MODELS))

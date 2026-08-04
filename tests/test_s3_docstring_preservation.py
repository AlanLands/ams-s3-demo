"""Whole-file replacement makes the model shed the leading module docstring
— and, per the US-2026-042 replay recording that motivated
`_restore_body_docstrings` and `_format_generated_python`, every function
docstring and the blank-line spacing between top-level defs too.
`_restore_module_docstring` repairs the module case deterministically,
because no prompt rule reliably stops it — asked about the deletion the
model denies it, and told to fix it the model returns the same content while
reporting success.
"""

from __future__ import annotations

import ast

import pytest

from s3_enhancement import codegen
from s3_enhancement.codegen import (
    _repair_generated_content,
    _restore_body_docstrings,
    _restore_dropped_comment_lines,
    _restore_module_docstring,
    _restore_top_level_blank_lines,
)

STRIPPED_MODELS = '''from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Policy:
    policy_number: str
'''


def test_restores_docstring_the_model_dropped() -> None:
    repaired = _restore_module_docstring("repos/policycore/core/models.py", STRIPPED_MODELS)
    assert repaired.startswith('"""Data models for the MapleSure group benefits mock app.')
    assert "Storage lives" in repaired
    # The model's actual change must survive the repair untouched.
    assert "class Policy:" in repaired
    assert "from dataclasses import dataclass" in repaired


def test_leaves_content_alone_when_docstring_already_present() -> None:
    content = '"""Kept."""\n\nfrom __future__ import annotations\n'
    assert _restore_module_docstring("repos/policycore/core/models.py", content) == content


def test_ignores_non_python_and_unknown_paths() -> None:
    java = "public class Claim {}\n"
    assert _restore_module_docstring("Claim.java", java) == java
    new_file = "x = 1\n"
    assert _restore_module_docstring("repos/policycore/core/brand_new.py", new_file) == new_file


def test_invalid_python_passes_through_for_the_validator_to_reject() -> None:
    broken = "def oops(\n"
    assert _restore_module_docstring("repos/policycore/core/models.py", broken) == broken


def test_repaired_output_still_parses() -> None:
    ast.parse(_restore_module_docstring("repos/policycore/core/models.py", STRIPPED_MODELS))


# ---------------------------------------------------------------------------
# _restore_body_docstrings — the function/class-level counterpart. These use
# a synthetic REPO_ROOT (rather than real repo files) so the fixture content
# can't drift out from under the test the way the live repo files did.
# ---------------------------------------------------------------------------

ORIGINAL_AMENDMENTS = '''"""Amendment-request business logic for the MapleSure mock app."""

from __future__ import annotations


def _next_amendment_number(policy_number: str) -> str:
    """Generate a new amendment number, unique across all policies."""
    return f"END-{policy_number}"


def submit_amendment(policy_number: str) -> str:
    """Create and persist a new amendment request, returning the record."""
    return _next_amendment_number(policy_number)
'''

STRIPPED_AMENDMENTS = '''"""Amendment-request business logic for the MapleSure mock app."""

from __future__ import annotations


def _next_amendment_number(policy_number: str) -> str:
    return f"END-{policy_number}"


def submit_amendment(policy_number: str, priority: str = "Standard") -> str:
    return _next_amendment_number(policy_number)
'''


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(codegen, "REPO_ROOT", tmp_path)
    return tmp_path


def _write_original(repo_root, rel_path: str, content: str) -> None:
    path = repo_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_restores_function_docstrings_the_model_dropped(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_AMENDMENTS)
    repaired = _restore_body_docstrings("amendments.py", STRIPPED_AMENDMENTS)
    assert '"""Generate a new amendment number, unique across all policies."""' in repaired
    assert (
        '"""Create and persist a new amendment request, returning the record."""'
        in repaired
    )
    # The model's actual change (the new `priority` parameter) must survive.
    assert 'priority: str = "Standard"' in repaired
    ast.parse(repaired)


def test_leaves_function_docstring_alone_when_already_present(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_AMENDMENTS)
    assert _restore_body_docstrings("amendments.py", ORIGINAL_AMENDMENTS) == (
        ORIGINAL_AMENDMENTS
    )


def test_does_not_restore_a_renamed_function(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_AMENDMENTS)
    renamed = STRIPPED_AMENDMENTS.replace(
        "def submit_amendment(", "def submit_amendment_request("
    )
    repaired = _restore_body_docstrings("amendments.py", renamed)
    # No node named "submit_amendment" exists in the model's output to
    # attach the original docstring to — nothing to match, nothing invented.
    assert "Create and persist a new amendment" not in repaired
    assert "def submit_amendment_request(" in repaired


def test_body_docstrings_ignores_non_python_and_missing_original(repo_root) -> None:
    java = "public class Claim {}\n"
    assert _restore_body_docstrings("Claim.java", java) == java
    assert _restore_body_docstrings("brand_new.py", "x = 1\n") == "x = 1\n"


def test_body_docstrings_invalid_python_passes_through(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_AMENDMENTS)
    broken = "def oops(\n"
    assert _restore_body_docstrings("amendments.py", broken) == broken


# ---------------------------------------------------------------------------
# _restore_dropped_comment_lines — the general, non-docstring case: a plain
# `#` comment deleted from the middle of a function body, with no docstring
# involved at all. Found against the real US-2026-042 recording, in
# repos/policycore/app.py's render(): a design-rationale comment between two
# statements vanished with nothing marking its former position.
# ---------------------------------------------------------------------------

ORIGINAL_WITH_BODY_COMMENT = '''from __future__ import annotations


def render() -> None:
    init_db()

    # Deliberately plain, not page_header(): this is the client's own app.
    inject_theme()
    st.title("Policy Portal")
'''

STRIPPED_BODY_COMMENT = '''from __future__ import annotations


def render() -> None:
    init_db()

    inject_theme()
    st.title("Policy Portal")
'''


def test_restores_a_comment_dropped_from_the_middle_of_a_function(repo_root) -> None:
    _write_original(repo_root, "app.py", ORIGINAL_WITH_BODY_COMMENT)
    repaired = _restore_dropped_comment_lines("app.py", STRIPPED_BODY_COMMENT)
    assert "# Deliberately plain, not page_header()" in repaired
    # Restored between the same two statements it originally sat between.
    assert "init_db()\n\n    # Deliberately plain" in repaired
    assert 'inject_theme()\n    st.title("Policy Portal")' in repaired


def test_leaves_content_alone_when_no_comment_was_dropped(repo_root) -> None:
    _write_original(repo_root, "app.py", ORIGINAL_WITH_BODY_COMMENT)
    assert _restore_dropped_comment_lines("app.py", ORIGINAL_WITH_BODY_COMMENT) == (
        ORIGINAL_WITH_BODY_COMMENT
    )


def test_does_not_restore_a_comment_the_model_reworded(repo_root) -> None:
    _write_original(repo_root, "app.py", ORIGINAL_WITH_BODY_COMMENT)
    reworded = ORIGINAL_WITH_BODY_COMMENT.replace(
        "# Deliberately plain, not page_header(): this is the client's own app.",
        "# Plain title, no AMS branding — this is the client's own app.",
    )
    repaired = _restore_dropped_comment_lines("app.py", reworded)
    # A "replace" diff opcode, not "delete" — the model's rewording survives
    # untouched rather than being overwritten by the stale original wording.
    assert repaired == reworded
    assert "Deliberately plain, not page_header()" not in repaired


def test_does_not_restore_a_comment_deleted_alongside_real_code(repo_root) -> None:
    # The comment's neighboring statement was legitimately removed too, with
    # no unchanged anchor between them — the deleted block mixes a comment
    # with real code, so this must not treat any of it as a silent drop.
    original = ORIGINAL_WITH_BODY_COMMENT.replace(
        "    # Deliberately plain, not page_header(): this is the client's own app.\n"
        "    inject_theme()\n",
        "    # Deliberately plain, not page_header(): this is the client's own app.\n"
        "    legacy_call()\n"
        "    inject_theme()\n",
    )
    _write_original(repo_root, "app.py", original)
    repaired = _restore_dropped_comment_lines("app.py", STRIPPED_BODY_COMMENT)
    assert "Deliberately plain, not page_header()" not in repaired
    assert repaired == STRIPPED_BODY_COMMENT


def test_comment_lines_ignores_non_python_and_missing_original(repo_root) -> None:
    java = "public class Claim {\n    // gone\n}\n"
    assert _restore_dropped_comment_lines("Claim.java", java) == java
    assert _restore_dropped_comment_lines("brand_new.py", "x = 1\n") == "x = 1\n"


def test_comment_lines_bails_out_if_restoring_breaks_syntax(repo_root) -> None:
    # A pathological case: the "comment" run also contains something that
    # would make the result unparsable once reinserted. The safety net
    # (re-parse after inserting) must hand back the input unchanged rather
    # than a worse result.
    original = "x = 1\n# comment\ny = (\n    1\n)\n"
    _write_original(repo_root, "weird.py", original)
    stripped = "x = 1\ny = 1\n"
    # Nothing here is a pure comment/blank deletion (the deleted run mixes
    # code), so this is really exercising the "no matching deletion" path —
    # included for completeness alongside the AST-repair functions' own
    # invalid-input tests.
    assert _restore_dropped_comment_lines("weird.py", stripped) == stripped


# ---------------------------------------------------------------------------
# _restore_top_level_blank_lines — narrow, name-matched fix for the blank-
# line collapse (2 blank lines between top-level defs -> 1) whole-file
# replacement introduces. Deliberately not a general formatter pass: it must
# never touch a line the user story didn't ask about, only the blank-line run right
# above a def/class it recognizes from the original file.
# ---------------------------------------------------------------------------

ORIGINAL_TWO_DEFS = (
    "from __future__ import annotations\n\n\ndef a() -> None:\n    pass\n\n\ndef b() -> None:\n"
    "    pass\n"
)

COLLAPSED_TWO_DEFS = (
    "from __future__ import annotations\n\n\ndef a() -> None:\n    pass\n\ndef b() -> None:\n"
    "    pass\n"
)


def test_restores_pep8_blank_line_spacing(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_TWO_DEFS)
    repaired = _restore_top_level_blank_lines("amendments.py", COLLAPSED_TWO_DEFS)
    assert "\n\n\ndef b() -> None:" in repaired
    ast.parse(repaired)


def test_blank_lines_only_touches_the_run_above_the_matched_def(repo_root) -> None:
    # A real reformatting side effect this fix must never reproduce: an
    # unrelated one-liner inside `a()` that a general formatter (ruff
    # format) would happily rewrap — this function never even parses that
    # line, so it can't touch it.
    reformatted_body = 'def a() -> None:\n    x = {\n        i for i in range(3)\n    }'
    original = ORIGINAL_TWO_DEFS.replace(
        "def a() -> None:\n    pass", 'def a() -> None:\n    x = {i for i in range(3)}'
    )
    collapsed = COLLAPSED_TWO_DEFS.replace("def a() -> None:\n    pass", reformatted_body)
    _write_original(repo_root, "amendments.py", original)
    repaired = _restore_top_level_blank_lines("amendments.py", collapsed)
    assert "\n\n\ndef b() -> None:" in repaired
    # The model's own (unrelated) multi-line formatting choice survives untouched.
    assert "x = {\n        i for i in range(3)\n    }" in repaired


def test_blank_lines_leaves_content_alone_when_spacing_already_matches(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_TWO_DEFS)
    assert _restore_top_level_blank_lines("amendments.py", ORIGINAL_TWO_DEFS) == (
        ORIGINAL_TWO_DEFS
    )


def test_blank_lines_does_not_restore_a_renamed_def(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_TWO_DEFS)
    renamed = COLLAPSED_TWO_DEFS.replace("def b() -> None:", "def c() -> None:")
    assert _restore_top_level_blank_lines("amendments.py", renamed) == renamed


def test_blank_lines_ignores_non_python_and_missing_original(repo_root) -> None:
    java = "public class Claim {\n\n}\n"
    assert _restore_top_level_blank_lines("Claim.java", java) == java
    assert _restore_top_level_blank_lines("brand_new.py", "x = 1\n") == "x = 1\n"


def test_blank_lines_invalid_python_passes_through(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_TWO_DEFS)
    broken = "def oops(\n"
    assert _restore_top_level_blank_lines("amendments.py", broken) == broken


# ---------------------------------------------------------------------------
# _repair_generated_content — the full chain, end to end against a synthetic
# reproduction of the US-2026-042 replay bug (module docstring, function
# docstrings, and blank-line spacing all lost in the same file).
# ---------------------------------------------------------------------------

ORIGINAL_FULL_FILE = '''"""Amendment-request business logic for the MapleSure mock app."""

from __future__ import annotations


def _next_amendment_number(policy_number: str) -> str:
    """Generate a new amendment number, unique across all policies."""
    return f"END-{policy_number}"


def submit_amendment(policy_number: str) -> str:
    """Create and persist a new amendment request, returning the record."""
    return _next_amendment_number(policy_number)
'''

STRIPPED_FULL_FILE = (
    "from __future__ import annotations\n"
    "\n"
    "def _next_amendment_number(policy_number: str) -> str:\n"
    '    return f"END-{policy_number}"\n'
    "\n"
    "def submit_amendment(policy_number: str, priority: str = \"Standard\") -> str:\n"
    "    return _next_amendment_number(policy_number)\n"
)


def test_repair_chain_restores_module_and_function_docstrings_and_spacing(repo_root) -> None:
    _write_original(repo_root, "amendments.py", ORIGINAL_FULL_FILE)
    repaired = _repair_generated_content("amendments.py", STRIPPED_FULL_FILE)
    assert repaired.startswith(
        '"""Amendment-request business logic for the MapleSure mock app."""'
    )
    assert '"""Generate a new amendment number, unique across all policies."""' in repaired
    assert (
        '"""Create and persist a new amendment request, returning the record."""'
        in repaired
    )
    assert "\n\n\ndef submit_amendment" in repaired
    assert 'priority: str = "Standard"' in repaired
    ast.parse(repaired)

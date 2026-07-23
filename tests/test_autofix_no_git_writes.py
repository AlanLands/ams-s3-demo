"""Structural guardrail: tools/autofix/ runs fully unattended (no mid-loop human
approval, by explicit design — see tools/autofix/loop.py's module docstring), so the
one thing that must be structurally impossible is it ever committing or pushing on
its own. This asserts the guarantee at the source level rather than by convention
alone, the same way tests/test_s1_demo_rows.py catches drift in the scripted demo
rows.
"""

from __future__ import annotations

from pathlib import Path

AUTOFIX_DIR = Path(__file__).resolve().parents[1] / "tools" / "autofix"

# Quoted-token form, matching how a subprocess argv list actually spells a git
# subcommand (e.g. `["git", "commit", "-m", ...]` contains the token `"commit"`).
# Deliberately not prose phrases like "git commit" — this package's own docstrings
# describe the guarantee in prose using exactly those words, which would otherwise
# be a false positive.
_FORBIDDEN_SUBSTRINGS = (
    '"commit"',
    "'commit'",
    '"push"',
    "'push'",
    '"add"',
    "'add'",
)


def _autofix_source_files() -> list[Path]:
    return sorted(AUTOFIX_DIR.rglob("*.py"))


def test_autofix_package_exists_and_has_source_files():
    files = _autofix_source_files()
    assert files, f"expected .py files under {AUTOFIX_DIR}, found none"


def test_no_autofix_source_file_writes_to_git():
    offenders = []
    for path in _autofix_source_files():
        text = path.read_text(encoding="utf-8")
        for marker in _FORBIDDEN_SUBSTRINGS:
            if marker in text:
                offenders.append(f"{path.relative_to(AUTOFIX_DIR.parents[1])}: contains {marker!r}")

    assert not offenders, (
        "tools/autofix/ must never commit or push — found forbidden substrings:\n"
        + "\n".join(offenders)
    )

#!/usr/bin/env bash
# CR-2026-042's demo beat mutates mockapp source files. Restore the
# pre-codegen mockapp files from the baseline tag, remove the generated test
# file, then reseed to restore pristine policy/claim/endorsement state.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

# Guard first, redirect second: `git show <missing-tag>:file > file` truncates
# `file` to empty via the shell redirect *before* git show runs and fails —
# `set -e` then stops the script, but too late to save the file it just
# emptied. Fail loudly here instead of silently destroying mockapp/ source.
if ! git rev-parse --verify --quiet "s3-endorsement-baseline" >/dev/null; then
  echo "FAIL: git tag 's3-endorsement-baseline' does not exist in this repo." >&2
  echo "Create it once (pinned to the commit with the pre-CR-042 mockapp/" >&2
  echo "state) before running this script — do not remove this guard." >&2
  exit 1
fi

git show s3-endorsement-baseline:mockapp/app.py > mockapp/app.py
git show s3-endorsement-baseline:mockapp/core/models.py > mockapp/core/models.py
git show s3-endorsement-baseline:mockapp/core/db.py > mockapp/core/db.py
git show s3-endorsement-baseline:mockapp/core/endorsements.py > mockapp/core/endorsements.py
rm -f tests/test_s3_endorsement_priority.py
python -m mockapp.core.seed
rm -rf .cache/llm
echo "CR-2026-042 source baseline restored, mockapp reseeded, and LLM cache cleared."

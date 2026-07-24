#!/usr/bin/env bash
# CR-2026-042's demo beat mutates mockapp source files. Restore the
# pre-codegen mockapp files from the baseline tag, remove the generated test
# file, then reseed to restore pristine policy/claim/endorsement state.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
git show s3-endorsement-baseline:mockapp/app.py > mockapp/app.py
git show s3-endorsement-baseline:mockapp/core/models.py > mockapp/core/models.py
git show s3-endorsement-baseline:mockapp/core/db.py > mockapp/core/db.py
git show s3-endorsement-baseline:mockapp/core/endorsements.py > mockapp/core/endorsements.py
rm -f tests/test_s3_endorsement_priority.py
python -m mockapp.core.seed
rm -rf .cache/llm
echo "CR-2026-042 source baseline restored, mockapp reseeded, and LLM cache cleared."

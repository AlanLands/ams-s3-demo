#!/usr/bin/env bash
# S3's demo beat mutates mockapp source files and SQLite state. Restore the
# pre-codegen mockapp files from the baseline tag, remove generated runtime
# artifacts, then reseed to restore pristine policy/claim state between rehearsals.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
git show s3-baseline:mockapp/app.py > mockapp/app.py
git show s3-baseline:mockapp/core/models.py > mockapp/core/models.py
git show s3-baseline:mockapp/core/db.py > mockapp/core/db.py
rm -f mockapp/core/coverage.py tests/test_s3_coverage_upgrade.py
python -m mockapp.core.seed
rm -rf .cache/llm
rm -rf s3_enhancement/out/*/harness
echo "S3 source baseline restored, mockapp reseeded, and LLM cache cleared."

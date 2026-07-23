#!/usr/bin/env bash
# Pre-warms .cache/llm for S3's short narrative drafts. Set RECORD_S3_REPLAY=1
# to also call the streamed record path for codegen/testgen replay caches.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${RECORD_S3_REPLAY:-0}" == "1" ]]; then
  python - <<'PY'
from s3_enhancement.warm_cache import record

for line in record():
    print(line)
PY
else
  python -m s3_enhancement.warm_cache
fi

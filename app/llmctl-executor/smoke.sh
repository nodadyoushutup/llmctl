#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
RESULT_FILE="${RESULT_FILE:-/tmp/llmctl-executor-smoke-result.json}"
LOG_FILE="${LOG_FILE:-/tmp/llmctl-executor-smoke.log}"

PAYLOAD='{"contract_version":"v1","request_id":"smoke","provider":"workspace","command":["/bin/bash","-lc","echo llmctl-executor-smoke-ok"]}'

cd "${REPO_ROOT}"
python3 app/llmctl-executor/run.py --payload-json "${PAYLOAD}" --output-file "${RESULT_FILE}" | tee "${LOG_FILE}"

python3 - <<'PY' "${RESULT_FILE}"
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
assert payload["contract_version"] == "v1", payload
assert payload["status"] == "success", payload
assert "llmctl-executor-smoke-ok" in payload["stdout"], payload
print("llmctl-executor smoke test passed")
PY

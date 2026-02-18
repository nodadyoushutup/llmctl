# llmctl-executor

`llmctl-executor` runs a single execution payload and emits a structured `ExecutionResult` contract (`v1`).

## Payload Input Contract (`v1`)

Input sources (highest priority first):
1. `--payload-file /path/to/payload.json`
2. `--payload-json '{"..."}'`
3. `LLMCTL_EXECUTOR_PAYLOAD_FILE`
4. `LLMCTL_EXECUTOR_PAYLOAD_JSON`
5. JSON piped on stdin

Required fields:
- `contract_version`: must be `"v1"`
- `provider`: `workspace|docker|kubernetes`
- one of:
  - `command`: non-empty string array
  - `shell_command`: non-empty string

Optional fields:
- `request_id`: string
- `cwd`: working directory (default `/tmp/llmctl-workspace`; override with `LLMCTL_EXECUTOR_DEFAULT_CWD`)
- `env`: object map of environment variables
- `stdin`: stdin text passed to subprocess
- `timeout_seconds`: integer (default `1800`)
- `capture_limit_bytes`: integer per stream (default `1000000`)
- `emit_start_markers`: boolean (default `true`)
- `result_contract_version`: when set, must also be `"v1"`
- `metadata`: object for caller metadata

## Startup Marker Contract

When `emit_start_markers=true`, executor emits both:
- literal line: `LLMCTL_EXECUTOR_STARTED`
- JSON line: `{"event":"executor_started","contract_version":"v1","ts":"<iso8601>"}`

## Structured Result Output (`v1`)

Executor prints one final line to stdout:
- `LLMCTL_EXECUTOR_RESULT_JSON=<json>`

Optional file output:
- `--output-file /path/to/result.json`
- or `LLMCTL_EXECUTOR_OUTPUT_FILE=/path/to/result.json`

Required result fields:
- `contract_version`
- `status`
- `exit_code`
- `started_at`
- `finished_at`
- `stdout`
- `stderr`
- `error`
- `provider_metadata`

Optional result fields (included when available): `usage`, `artifacts`, `warnings`, `metrics`.

## Build Image

```bash
# Build/refresh base image first (manual policy)
app/llmctl-executor/build-executor-base.sh

# Then build executor app image from the base
app/llmctl-executor/build-executor.sh

# Or pass a version tag positionally
app/llmctl-executor/build-executor-base.sh 0.0.3
app/llmctl-executor/build-executor.sh 0.0.4
```

Build args:
- `IMAGE_NAME=llmctl-executor:latest`
- `INSTALL_VLLM=true|false` (default `false`; normally `false` because base includes pinned vLLM)
- `VLLM_VERSION=<version>` (default `0.9.0`; used when `INSTALL_VLLM=true`)
- `TRANSFORMERS_VERSION=<version>` (default `4.53.3`; pinned for `vllm==0.9.0` compatibility)

Compatibility note:
- `vllm==0.9.0` must be paired with `transformers` 4.x (`4.53.3` default). Using `transformers` 5.x causes an `aimv2` registration conflict at import time.

Examples:

```bash
# Default: consume local llmctl-executor-base:latest
app/llmctl-executor/build-executor.sh

# If you need a different base source, retag it locally as llmctl-executor-base:latest first
# docker tag 127.0.0.1:30082/llmctl/llmctl-executor-base:sha-<tag> llmctl-executor-base:latest
```

## Smoke Test

```bash
app/llmctl-executor/smoke.sh
```

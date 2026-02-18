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
app/llmctl-executor/build-executor.sh
```

Build args:
- `INSTALL_VLLM=true|false` (default `true`)
- `INSTALL_CLAUDE=true|false` (default `true`)
- `IMAGE_NAME=llmctl-executor:latest`
- `EXECUTOR_BASE_IMAGE=nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04|ubuntu:24.04|vllm/vllm-openai:<tag>`
- `VENV_SYSTEM_SITE_PACKAGES=true|false` (default `false`)

Examples:

```bash
# CUDA base + pip install vLLM (default)
app/llmctl-executor/build-executor.sh

# CPU-only base image (no CUDA libs in image)
EXECUTOR_BASE_IMAGE=ubuntu:24.04 app/llmctl-executor/build-executor.sh

# Reuse preinstalled vLLM from vllm/vllm-openai image and skip pip install
EXECUTOR_BASE_IMAGE=vllm/vllm-openai:v0.10.1.1 \
INSTALL_VLLM=false \
VENV_SYSTEM_SITE_PACKAGES=true \
app/llmctl-executor/build-executor.sh
```

## Smoke Test

```bash
app/llmctl-executor/smoke.sh
```

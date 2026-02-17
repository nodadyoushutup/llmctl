---
name: chromium-screenshot
display_name: Chromium Screenshot
description: Capture Studio UI verification screenshots with headless Chromium from inside the llmctl-studio container and store artifacts in the Studio data directory.
version: 1.1.0
status: active
---

# Chromium Screenshot

## Overview

Capture frontend screenshots with deterministic naming so verification is repeatable and easy to audit.

This Studio-seeded variant is intended for runtime use inside the `llmctl-studio` container.

## Standard Workflow

1. Capture screenshots with `scripts/capture_screenshot.sh`.
2. Store artifacts under `${LLMCTL_STUDIO_DATA_DIR:-/app/data}/screenshots/`.
3. Use the filename format:
   - `<YYYY-MM-DD-HH-MM-SS>--<route-or-page>--<state>--<viewport>--<gitsha7>--<hash6>.png`
4. Review the generated image and report the artifact path in updates/summaries.
5. Remove obsolete or duplicate screenshots related to the current task.

## Command Pattern

```bash
bash scripts/capture_screenshot.sh \
  --url http://localhost:5055/settings \
  --route settings-runtime \
  --state validation-error
```

## Frontend Verification Rules

- Capture at least one headless screenshot for frontend-impacting work.
- If screenshots do not reflect frontend edits, restart relevant Docker container(s) and capture again.
- Explicitly confirm in final updates that screenshots were captured and reviewed.

## Resources

- `scripts/capture_screenshot.sh`: Generates correctly named screenshots using Chromium-compatible browsers available in the Studio container.

---
name: chromium-screenshot
description: Capture and manage frontend verification screenshots with headless Chromium for Codex workflows. Use when handling frontend-impacting changes, frontend audits, UI bug triage, visual regression checks, or any task that requires traceable screenshot artifacts under docs/screenshots with collision-resistant naming.
---

# Chromium Screenshot

## Overview

Capture frontend screenshots with deterministic naming and artifact placement so verification is repeatable and easy to audit.

## Standard Workflow

1. Capture screenshots with `scripts/capture_screenshot.sh`.
2. Store artifacts under `docs/screenshots/`.
3. Use the filename format:
   - `<route-or-page>--<state>--<viewport>--<YYYYMMDD-HHMMSS>--<gitsha7>--<hash6>.png`
4. Review the generated image and report the artifact path in updates/summaries.
5. Remove obsolete or duplicate screenshots related to the current task.

## Command Pattern

```bash
scripts/capture_screenshot.sh \
  --url http://localhost:5000/settings \
  --route settings-runtime \
  --state validation-error \
  --viewport 1920x1080 \
  --out-dir docs/screenshots
```

## Frontend Verification Rules

- Capture at least one headless screenshot for frontend-impacting work.
- If screenshots do not reflect frontend edits, restart relevant Docker container(s) and capture again.
- Explicitly confirm in final updates that screenshots were captured and reviewed.

## Resources

- `scripts/capture_screenshot.sh`: Generates correctly named screenshots using `chromium-browser` headless mode.

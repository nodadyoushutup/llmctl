# llmctl-studio-frontend

React/Vite frontend for Studio migration. This app is the Stage 4 bootstrap for the backend/frontend split.

## Commands

```bash
npm install
npm run dev
npm run build
npm run preview
```

## Runtime env model

Copy `.env.example` to `.env` (optional) and adjust as needed:

- `VITE_API_BASE_URL`: explicit backend origin. Leave empty for same-origin ingress routing.
- `VITE_API_BASE_PATH`: backend API prefix, default `/api`.
- `VITE_WEB_BASE_PATH`: frontend mount path for router basename.
- `VITE_SOCKET_PATH`: Socket.IO transport path.
- `VITE_SOCKET_NAMESPACE`: Socket namespace, default `/rt`.
- `VITE_DEV_API_PROXY_TARGET`: optional Vite dev proxy target for `/api` requests.

## What Stage 4 includes

- App shell and router skeleton for migration waves.
- Shared HTTP utilities with consistent auth/error handling.
- API diagnostics view that probes `/api/health` and `/api/chat/activity`.

## Stage 5 progress (Wave 1)

- Parity tracker route at `/parity-checklist` with wave-by-wave legacy-to-react mapping.
- Migrated chat activity route at `/chat/activity` (read from `/api/chat/activity`).
- Migrated chat thread detail route at `/chat/threads/:threadId` (read from `/api/chat/threads/:threadId`).
- Each migrated view keeps a legacy fallback link while backend templates remain online.

## Stage 5 progress (Wave 2 partial)

- Execution monitor route at `/execution-monitor`.
- Run detail read probe wired to `/api/runs/:id`.
- Node status read probe wired to `/api/nodes/:id/status`.

## Stage 5 completion mode

- Native React routes currently cover shell, parity tracker, diagnostics, chat activity/thread, and execution monitor.
- All remaining legacy GUI paths are covered by React bridge mode via mirrored `/api/...` pages rendered in-app.
- This keeps full behavior parity while native replacements continue in later stages.

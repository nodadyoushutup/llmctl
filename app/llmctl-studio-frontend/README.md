# llmctl-studio-frontend

React/Vite frontend for Studio. This is the only user-facing Studio UI runtime.

## Commands

```bash
npm install
npm run dev
npm run lint
npm run check:flash-notifications
npm test
npm run build
npm run preview
```

`npm run check:flash-notifications` verifies that Studio page components using local notification-like setters (`set*Error`, `set*Message`, etc.) are wired to the shared flash message hooks (`useFlash`/`useFlashState`).

## Runtime Environment

Copy `.env.example` to `.env` (optional) and adjust as needed:

- `VITE_API_BASE_URL`: explicit backend origin. Leave empty for same-origin ingress routing.
- `VITE_API_BASE_PATH`: backend API prefix, default `/api`.
- `VITE_WEB_BASE_PATH`: frontend mount path for router basename (typically `/web` in Kubernetes ingress).
- `VITE_SOCKET_PATH`: Socket.IO transport path (default `/api/socket.io`).
- `VITE_SOCKET_NAMESPACE`: Socket namespace, default `/rt`.
- `VITE_DEV_API_PROXY_TARGET`: optional Vite dev proxy target for `/api` requests.

## Split Runtime Contract

- Frontend routes are served from `/web/*`.
- Backend API/realtime routes are served from `/api/*`.
- Frontend nginx proxies only `/api/*` to `llmctl-studio-backend`.
- No legacy Flask GUI bridge/fallback is used in this runtime.

## Local Development

1. Start backend from repo root:

   ```bash
   python3 app/llmctl-studio-backend/run.py
   ```

2. Start frontend:

   ```bash
   cd app/llmctl-studio-frontend
   npm run dev
   ```

3. If needed, set `VITE_DEV_API_PROXY_TARGET` (for example `http://127.0.0.1:5155`) so frontend `/api` requests reach the backend.

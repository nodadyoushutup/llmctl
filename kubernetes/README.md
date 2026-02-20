# Kubernetes manifests

This folder deploys the full `llmctl` stack into a single `llmctl` namespace:

- `llmctl-studio-backend`
- `llmctl-studio-frontend`
- `llmctl-celery-worker`
- `llmctl-celery-beat`
- `llmctl-redis`
- `llmctl-postgres`
- `llmctl-chromadb`
- integrated MCP services (`llmctl-mcp`, `llmctl-mcp-github`, `llmctl-mcp-atlassian`, `llmctl-mcp-chroma`, `llmctl-mcp-google-cloud`, `llmctl-mcp-google-workspace`)

ArgoCD tracks this as one application (`llmctl-studio`) for core services. pgAdmin and Harbor are tracked as separate ArgoCD applications (`llmctl-pgadmin`, `llmctl-harbor`).

## Layout

- `kubernetes/llmctl-studio/base/`: core llmctl manifests (namespace, redis, postgres, chromadb, integrated MCP services, Studio backend/frontend, celery worker/beat, ingress, and example secrets).
- `kubernetes/llmctl-studio/overlays/dev/`: single deployable overlay for llmctl-studio resources (Harbor image overrides + live-code mounts + executor live-code config).
- `kubernetes/llmctl-studio/argocd-application.yaml`: ArgoCD Application for the core stack at `kubernetes/llmctl-studio/overlays/dev`.
- `kubernetes/pgadmin/`: pgAdmin secret example and ArgoCD application (Helm chart source).
- `kubernetes/argocd-harbor-application.yaml`: ArgoCD Application that installs Harbor from the upstream Helm chart into `llmctl-harbor`.

## Quick start

One-command local Minikube restore (profile start/resume + live-code mount + dev overlay apply + rollout wait):

```bash
scripts/minikube-up.sh
```

Create secrets before applying manifests:

```bash
cp kubernetes/llmctl-studio/base/studio-secret.example.yaml /tmp/llmctl-studio-secret.yaml
cp kubernetes/llmctl-studio/base/mcp-secret.example.yaml /tmp/llmctl-mcp-secret.yaml
# edit /tmp/llmctl-studio-secret.yaml
# edit /tmp/llmctl-mcp-secret.yaml (optional but recommended)
kubectl apply -f /tmp/llmctl-studio-secret.yaml
kubectl apply -f /tmp/llmctl-mcp-secret.yaml
```

Guard before ArgoCD sync or `kubectl apply -k`:

```bash
kubectl -n llmctl get secret llmctl-studio-secrets llmctl-mcp-secrets
```

`llmctl-studio-secrets` is required. `llmctl-mcp-secrets` is optional for boot. It is required for provider-authenticated GitHub/Atlassian MCP behavior, and can optionally provide fallback credentials for Google Cloud/Workspace MCP.

If your Harbor registry is private, also create image pull secret `llmctl-harbor-regcred` from `kubernetes/llmctl-studio/base/harbor-pull-secret.example.yaml`, then uncomment `imagePullSecrets` in `kubernetes/llmctl-studio/base/mcp-llmctl.yaml`.

Apply the full stack:

```bash
kubectl apply -k kubernetes/llmctl-studio/overlays/dev
```

Port-forward Studio backend API:

```bash
kubectl -n llmctl port-forward svc/llmctl-studio-backend 5155:5155
```

Port-forward Studio frontend:

```bash
kubectl -n llmctl port-forward svc/llmctl-studio-frontend 8080:8080
```

Direct NodePort access (Minikube):

```bash
minikube -p llmctl ip
# open http://<minikube-ip>:30157/ (frontend)
# backend/API is available on http://<minikube-ip>:30155/
```

Optional GPU (Minikube + NVIDIA):

```bash
scripts/install/install-minikube-single-node.sh --gpu
kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'
```

## Integrated MCP services

Integrated MCP runtimes are deployed as first-class Kubernetes services in the same namespace as Studio. Studio stores these endpoints in `mcp_servers.config_json` as `url + transport=streamable-http` values and no longer needs bundled MCP executables in the Studio image.

Service endpoint contract:

- `http://llmctl-mcp.llmctl.svc.cluster.local:9020/mcp`
- `http://llmctl-mcp-github.llmctl.svc.cluster.local:8000/mcp/`
- `http://llmctl-mcp-atlassian.llmctl.svc.cluster.local:8000/mcp/`
- `http://llmctl-mcp-chroma.llmctl.svc.cluster.local:8000/mcp/`
- `http://llmctl-mcp-google-cloud.llmctl.svc.cluster.local:8000/mcp/`
- `http://llmctl-mcp-google-workspace.llmctl.svc.cluster.local:8000/mcp/`

Public ingress endpoints (for OpenAI/Codex remote MCP reachability):

- `<PUBLIC_BASE_URL>/mcp/llmctl` -> `llmctl-mcp`
- `<PUBLIC_BASE_URL>/mcp/github` -> `llmctl-mcp-github`
- `<PUBLIC_BASE_URL>/mcp/atlassian` -> `llmctl-mcp-atlassian`
- `<PUBLIC_BASE_URL>/mcp/chroma` -> `llmctl-mcp-chroma`
- `<PUBLIC_BASE_URL>/mcp/google-cloud` -> `llmctl-mcp-google-cloud`
- `<PUBLIC_BASE_URL>/mcp/google-workspace` -> `llmctl-mcp-google-workspace`

Set `LLMCTL_MCP_PUBLIC_BASE_URL` in a Kubernetes Secret (for example `llmctl-studio-secrets`) to switch integrated MCP rows from internal `*.svc.cluster.local` URLs to these public ingress URLs.

Google Cloud and Google Workspace MCP deployments read service-account credentials from Studio integration-managed files under `/app/data/credentials` (shared PVC). `llmctl-mcp-secrets` remains supported as a fallback source.

Cutover sequencing is handled in one release by `studio-deployment.yaml` init-container `wait-for-integrated-mcp`. It blocks backend startup until required MCP endpoints respond (or timeout), so DB migration/seed sync runs only after MCP services are reachable.

Quick validation:

```bash
kubectl -n llmctl get deploy \
  llmctl-mcp \
  llmctl-mcp-github \
  llmctl-mcp-atlassian \
  llmctl-mcp-chroma \
  llmctl-mcp-google-cloud \
  llmctl-mcp-google-workspace \
  llmctl-studio-backend
```

## Celery runtime topology

Celery execution is decoupled from the Studio backend runtime:

- `llmctl-studio-backend` is producer/control-plane only (enqueue + revoke + status reads).
- `llmctl-celery-worker` consumes all task queues.
- `llmctl-celery-beat` is the only scheduler for periodic dispatch (for example `workspace_cleanup`).
- LLM execution is runtime-plane only: LLM calls dispatch to Kubernetes executor Jobs/Pods using split executor images (`llmctl-executor-frontier` and `llmctl-executor-vllm`) instead of executing in backend or Celery worker containers.

This avoids duplicate beat scheduling and keeps worker scale independent of API scale.
Do not run multiple beat deployments unless you intentionally coordinate distributed scheduling.

Dev rollback note for executor-only LLM runtime:
- If post-cutover regressions appear, roll back the Studio backend deployment to the previous known-good image tag while investigating executor dispatch logs/metadata.

Current queue contract (from `services.celery_app`):

- `llmctl_studio`
- `llmctl_studio.downloads.huggingface`
- `llmctl_studio.rag.index`
- `llmctl_studio.rag.drive`
- `llmctl_studio.rag.git`

Throughput model:

- worker slots = `worker replicas x --concurrency`
- current manifest baseline: `4 replicas x concurrency 1 = 4` worker slots

## Live code mount (Minikube dev only)

Use this when you want to keep stable base images in Minikube and mount your local repo code into running llmctl workloads.

1) Keep a Minikube mount session running in a separate terminal:

```bash
scripts/minikube/live-code.sh
```

2) Apply the dev overlay:

```bash
kubectl apply -k kubernetes/llmctl-studio/overlays/dev
```

3) Restart impacted Python workloads after code changes:

```bash
kubectl -n llmctl rollout restart deploy/llmctl-studio-backend
kubectl -n llmctl rollout status deploy/llmctl-studio-backend
kubectl -n llmctl rollout restart deploy/llmctl-mcp
kubectl -n llmctl rollout status deploy/llmctl-mcp
kubectl -n llmctl rollout restart deploy/llmctl-celery-worker
kubectl -n llmctl rollout status deploy/llmctl-celery-worker
kubectl -n llmctl rollout restart deploy/llmctl-celery-beat
kubectl -n llmctl rollout status deploy/llmctl-celery-beat
```

4) Frontend live edits hot-reload automatically in the `dev` overlay:

- `llmctl-studio-frontend` runs `npm run dev` (Vite) with polling file watching.
- Source edits under `app/llmctl-studio-frontend/src` should apply without a pod restart.
- Restart the frontend deployment only when dependencies or startup env/config change:

```bash
kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend
kubectl -n llmctl rollout status deploy/llmctl-studio-frontend
```

Notes:

- The `dev` overlay mounts `/workspace/llmctl` from the Minikube node into `/app` for Studio backend, frontend, `llmctl-mcp`, celery worker, and celery beat.
- Frontend `node_modules` is mounted as an in-pod `emptyDir`, so dependencies are isolated from the host checkout.
- Executor Jobs spawned by Studio also mount `/workspace/llmctl` into `/app` when `LLMCTL_NODE_EXECUTOR_K8S_LIVE_CODE_ENABLED=true`.
- Keep the `minikube mount` process running; if it stops, the pod cannot read mounted code paths.
- This is intended for local Minikube development, not shared/remote clusters.

## ArgoCD application

Create the single ArgoCD application resource:

```bash
kubectl apply -f kubernetes/llmctl-studio/argocd-application.yaml
```

This tracks repo path `kubernetes/llmctl-studio/overlays/dev` on `main`, which includes namespace, redis, postgres, chromadb, integrated MCP services, and Studio backend/frontend resources together.

## pgAdmin ArgoCD application

Create the pgAdmin ArgoCD application resource:

```bash
kubectl apply -f kubernetes/pgadmin/argocd-application.yaml
```

This installs `runix/pgadmin4` chart `1.59.0` from `https://helm.runix.net` into namespace `llmctl-pgadmin`, with NodePort HTTP exposed on `30156` and PostgreSQL bootstrap wired for `llmctl-postgres.llmctl.svc.cluster.local`.

If you are migrating from older bundled pgAdmin resources in namespace `llmctl`, remove them before syncing `llmctl-pgadmin` to avoid NodePort `30156` conflicts:

```bash
kubectl -n llmctl delete svc/llmctl-pgadmin deploy/llmctl-pgadmin pvc/llmctl-pgadmin-data --ignore-not-found
```

If you already deployed the previous manifest-based pgAdmin in namespace `llmctl-pgadmin`, run this one-time cleanup before first sync (Deployment selector changed and is immutable):

```bash
kubectl -n llmctl-pgadmin delete deploy/llmctl-pgadmin svc/llmctl-pgadmin configmap/llmctl-pgadmin-config --ignore-not-found
```

## Harbor ArgoCD application

Create the Harbor ArgoCD application resource:

```bash
kubectl apply -f kubernetes/argocd-harbor-application.yaml
```

This installs Harbor chart `1.18.2` (Harbor `2.14.2`) from `https://helm.goharbor.io` into namespace `llmctl-harbor`, with NodePort HTTP exposed on `30082`.

First login defaults:

- Username: `admin`
- Password: `Harbor12345`

For local Minikube access:

```bash
minikube -p llmctl ip
# open http://<minikube-ip>:30082/
```

For Kubernetes image pulls from Harbor, render the `dev` overlay with the in-cluster Harbor Service endpoint (ClusterIP:80):

```bash
scripts/configure-harbor-image-overlays.sh
kubectl apply -k kubernetes/llmctl-studio/overlays/dev
```

This avoids Docker/CRI HTTPS-vs-HTTP pull mismatches that can occur when using Harbor NodePort endpoints directly in image names.

If ArgoCD tracks `path: kubernetes/llmctl-studio/overlays/dev`, set Harbor image overrides on the app:

```bash
scripts/configure-harbor-image-overlays.sh --argocd-app llmctl-studio
argocd app sync llmctl-studio
```

That command updates Harbor image names for all llmctl-managed images so ArgoCD does not fall back to unqualified local names.
`llmctl-celery-worker` is intentionally fixed to `:latest` in this workflow; the `--tag` value applies to `llmctl-studio-backend`, `llmctl-studio-frontend`, `llmctl-mcp`, `llmctl-executor-frontier`, and `llmctl-executor-vllm`.

## Runtime knobs to edit

Edit `kubernetes/llmctl-studio/base/studio-configmap.yaml` for these keys:

- `LLMCTL_POSTGRES_HOST`, `LLMCTL_POSTGRES_PORT`, `LLMCTL_POSTGRES_DB`, `LLMCTL_POSTGRES_USER`
- `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_SSL`
- `LLMCTL_STUDIO_MCP_WAIT_ENABLED` (toggle integrated MCP readiness gate at startup)
- `LLMCTL_STUDIO_MCP_WAIT_TIMEOUT_SECONDS` (startup wait timeout)
- `LLMCTL_STUDIO_MCP_REQUIRED_ENDPOINTS` (comma-separated list of MCP endpoint URLs Studio must see before startup)
- `LLMCTL_NODE_EXECUTOR_PROVIDER` (`kubernetes` only)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE` (legacy fallback executor image; defaults to frontier image behavior)
- `LLMCTL_NODE_EXECUTOR_K8S_FRONTIER_IMAGE` (frontier executor image for non-vLLM providers)
- `LLMCTL_NODE_EXECUTOR_K8S_VLLM_IMAGE` (vLLM executor image for `vllm_local` and `vllm_remote` providers)
- `LLMCTL_NODE_EXECUTOR_K8S_SERVICE_ACCOUNT` (job pod service account)
- `LLMCTL_NODE_EXECUTOR_K8S_GPU_LIMIT` (set `>0` to request NVIDIA GPU per executor Job)
- `LLMCTL_NODE_EXECUTOR_K8S_JOB_TTL_SECONDS` (terminal pod/job retention before auto-cleanup)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON` (JSON list, for private registries)
- `LLMCTL_NODE_EXECUTOR_K8S_LIVE_CODE_ENABLED` (`true` mounts local repo into executor Jobs)
- `LLMCTL_NODE_EXECUTOR_K8S_LIVE_CODE_HOST_PATH` (host path mounted into executor Jobs, default `/workspace/llmctl`)

Celery worker sizing is configured in `kubernetes/llmctl-studio/base/celery-worker-deployment.yaml`:

- `spec.replicas` controls worker pod count.
- container `command` args control `--concurrency` and queue selection.
- total worker slots follow `replicas x concurrency`.

Beat scheduling is configured in `kubernetes/llmctl-studio/base/celery-beat-deployment.yaml`:

- keep `spec.replicas: 1` unless you have explicit leader-election/scheduler coordination.

Edit `kubernetes/llmctl-studio/base/studio-secret.example.yaml` for:

- `LLMCTL_POSTGRES_PASSWORD` (required)
- optional `LLMCTL_STUDIO_DATABASE_URI` override
- optional `LLMCTL_MCP_PUBLIC_BASE_URL` (public origin used for integrated MCP URL rows, for example `https://203-0-113-10.sslip.io`)

Edit `kubernetes/llmctl-studio/base/mcp-secret.example.yaml` for:

- `GITHUB_PERSONAL_ACCESS_TOKEN`
- `JIRA_*` and `CONFLUENCE_*` credentials
- optional fallback `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON` and project selectors
- optional fallback `GOOGLE_WORKSPACE_SERVICE_ACCOUNT_JSON` and `GOOGLE_WORKSPACE_IMPERSONATE_USER`

If Harbor pull auth is needed, edit `kubernetes/llmctl-studio/base/harbor-pull-secret.example.yaml` for:

- `.dockerconfigjson` for your Harbor endpoint and project credentials

Edit `kubernetes/pgadmin/pgadmin-secret.example.yaml` for:

- `PGADMIN_DEFAULT_PASSWORD` (required)
- `LLMCTL_POSTGRES_PASSWORD` (required, must match `llmctl` PostgreSQL password)

## Optional executor smoke test

```bash
kubectl apply -f kubernetes/llmctl-studio/base/executor-smoke-job.example.yaml
kubectl -n llmctl logs job/llmctl-executor-smoke
```

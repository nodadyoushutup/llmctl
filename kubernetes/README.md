# Kubernetes manifests

This folder deploys the full `llmctl` stack into a single `llmctl` namespace:

- `llmctl-studio-backend`
- `llmctl-studio-frontend`
- `llmctl-redis`
- `llmctl-postgres`
- `llmctl-pgadmin`
- `llmctl-chromadb`
- integrated MCP services (`llmctl-mcp`, `llmctl-mcp-github`, `llmctl-mcp-atlassian`, `llmctl-mcp-chroma`, `llmctl-mcp-google-cloud`)

ArgoCD tracks this as one application (`llmctl-kubernetes`) for core services. Harbor can be tracked as a separate ArgoCD application (`llmctl-harbor`).

## Files

- `namespace.yaml`: `llmctl` namespace.
- `redis.yaml`: in-cluster Redis for Celery and Socket.IO queueing.
- `postgres.yaml`: in-cluster PostgreSQL for mandatory Studio persistence.
- `pgadmin.yaml`: in-cluster pgAdmin UI preconfigured for `llmctl-postgres`.
- `chromadb.yaml`: in-cluster ChromaDB for RAG vector storage.
- `mcp-configmap.yaml`: shared transport/runtime config for integrated MCP Deployments.
- `mcp-llmctl.yaml`: Deployment + Service for `llmctl-mcp` (Harbor/your built image).
- `mcp-github.yaml`: Deployment + Service for upstream `mcp/github` with HTTP wrapper.
- `mcp-atlassian.yaml`: Deployment + Service for upstream `mcp/atlassian` in native streamable HTTP mode.
- `mcp-chroma.yaml`: Deployment + Service for upstream `mcp/chroma` with HTTP wrapper.
- `mcp-google-cloud.yaml`: Deployment + Service for Google Cloud MCP runtime with HTTP wrapper.
- `studio-configmap.yaml`: non-secret Studio runtime settings.
- `studio-rbac.yaml`: service accounts and RBAC for Studio to create/read/delete executor Jobs.
- `studio-pvc.yaml`: persistent storage for `/app/data`.
- `studio-deployment.yaml`: Studio backend Deployment (`llmctl-studio-backend`) with integrated MCP readiness init-container.
- `studio-service.yaml`: backend NodePort Service (`30155`) targeting Studio API/backend port `5155`.
- `studio-frontend-deployment.yaml`: Studio frontend Deployment (`llmctl-studio-frontend`).
- `studio-frontend-service.yaml`: frontend NodePort Service (`30157`) targeting frontend port `8080`.
- `studio-secret.example.yaml`: required secret template for PostgreSQL password, `FLASK_SECRET_KEY`, and optional API keys.
- `mcp-secret.example.yaml`: optional secret template for integrated MCP provider credentials.
- `pgadmin-secret.example.yaml`: required secret template for pgAdmin web login credentials.
- `harbor-pull-secret.example.yaml`: optional image pull secret for private Harbor projects.
- `argocd-application.yaml`: single ArgoCD Application pointing at `kubernetes/`.
- `argocd-harbor-application.yaml`: ArgoCD Application that installs Harbor from the upstream Helm chart into `llmctl-harbor`.
- `kubernetes-overlays/minikube-live-code/`: local-only overlay that mounts host project code into `llmctl-studio-backend` for rapid iteration without rebuilding images.

## Quick start

Create secrets before applying manifests:

```bash
cp kubernetes/studio-secret.example.yaml /tmp/llmctl-studio-secret.yaml
cp kubernetes/pgadmin-secret.example.yaml /tmp/llmctl-pgadmin-secret.yaml
cp kubernetes/mcp-secret.example.yaml /tmp/llmctl-mcp-secret.yaml
# edit /tmp/llmctl-studio-secret.yaml
# edit /tmp/llmctl-pgadmin-secret.yaml
# edit /tmp/llmctl-mcp-secret.yaml (optional but recommended)
kubectl apply -f /tmp/llmctl-studio-secret.yaml
kubectl apply -f /tmp/llmctl-pgadmin-secret.yaml
kubectl apply -f /tmp/llmctl-mcp-secret.yaml
```

Guard before ArgoCD sync or `kubectl apply -k`:

```bash
kubectl -n llmctl get secret llmctl-studio-secrets llmctl-pgadmin-secrets llmctl-mcp-secrets
```

`llmctl-studio-secrets` and `llmctl-pgadmin-secrets` are required. `llmctl-mcp-secrets` is optional for boot, but required if you want provider-authenticated GitHub/Atlassian/Google Cloud MCP behavior.

If your Harbor registry is private, also create image pull secret `llmctl-harbor-regcred` from `kubernetes/harbor-pull-secret.example.yaml`, then uncomment `imagePullSecrets` in `kubernetes/mcp-llmctl.yaml`.

Apply the full stack:

```bash
kubectl apply -k kubernetes
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
# open http://<minikube-ip>:30156/ (pgAdmin)
```

Port-forward pgAdmin:

```bash
kubectl -n llmctl port-forward svc/llmctl-pgadmin 5050:5050
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
- `http://llmctl-mcp-github.llmctl.svc.cluster.local:8000/mcp`
- `http://llmctl-mcp-atlassian.llmctl.svc.cluster.local:8000/mcp`
- `http://llmctl-mcp-chroma.llmctl.svc.cluster.local:8000/mcp`
- `http://llmctl-mcp-google-cloud.llmctl.svc.cluster.local:8000/mcp`

`google-workspace` remains intentionally deferred/feature-gated and is not deployed in this manifest set.

Cutover sequencing is handled in one release by `studio-deployment.yaml` init-container `wait-for-integrated-mcp`. It blocks backend startup until required MCP endpoints respond (or timeout), so DB migration/seed sync runs only after MCP services are reachable.

Quick validation:

```bash
kubectl -n llmctl get deploy \
  llmctl-mcp \
  llmctl-mcp-github \
  llmctl-mcp-atlassian \
  llmctl-mcp-chroma \
  llmctl-mcp-google-cloud \
  llmctl-studio-backend
```

## Live code mount (Minikube dev only)

Use this when you want to keep a stable base image in Minikube and mount your local repo code into the running Studio pod.

1) Keep a Minikube mount session running in a separate terminal:

```bash
scripts/minikube-live-code-mount.sh
```

2) Apply the local code-mount overlay:

```bash
kubectl apply -k kubernetes-overlays/minikube-live-code
```

3) Restart Studio after code changes:

```bash
kubectl -n llmctl rollout restart deploy/llmctl-studio-backend
kubectl -n llmctl rollout status deploy/llmctl-studio-backend
```

Notes:

- This overlay mounts `/workspace/llmctl` from the Minikube node into `/app/app/llmctl-studio-backend/run.py`, `/app/app/llmctl-studio-backend/src`, and `/app/app/llmctl-studio-backend/seed-skills`.
- Keep the `minikube mount` process running; if it stops, the pod cannot read mounted code paths.
- This is intended for local Minikube development, not shared/remote clusters.

## ArgoCD application

Create the single ArgoCD application resource:

```bash
kubectl apply -f kubernetes/argocd-application.yaml
```

This tracks repo path `kubernetes` on `main`, which includes namespace, redis, postgres, pgAdmin, chromadb, integrated MCP services, and Studio backend/frontend resources together.

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

For Kubernetes image pulls from Harbor, render overlays with the in-cluster Harbor Service endpoint (ClusterIP:80):

```bash
scripts/configure-harbor-image-overlays.sh
kubectl apply -k kubernetes-overlays/harbor-images
```

This avoids Docker/CRI HTTPS-vs-HTTP pull mismatches that can occur when using Harbor NodePort endpoints directly in image names.

## Runtime knobs to edit

Edit `kubernetes/studio-configmap.yaml` for these keys:

- `LLMCTL_POSTGRES_HOST`, `LLMCTL_POSTGRES_PORT`, `LLMCTL_POSTGRES_DB`, `LLMCTL_POSTGRES_USER`
- `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_SSL`
- `LLMCTL_STUDIO_MCP_WAIT_ENABLED` (toggle integrated MCP readiness gate at startup)
- `LLMCTL_STUDIO_MCP_WAIT_TIMEOUT_SECONDS` (startup wait timeout)
- `LLMCTL_STUDIO_MCP_REQUIRED_ENDPOINTS` (comma-separated list of MCP endpoint URLs Studio must see before startup)
- `LLMCTL_NODE_EXECUTOR_PROVIDER` (`kubernetes` only)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE` (executor image)
- `LLMCTL_NODE_EXECUTOR_K8S_SERVICE_ACCOUNT` (job pod service account)
- `LLMCTL_NODE_EXECUTOR_K8S_GPU_LIMIT` (set `>0` to request NVIDIA GPU per executor Job)
- `LLMCTL_NODE_EXECUTOR_K8S_JOB_TTL_SECONDS` (terminal pod/job retention before auto-cleanup)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON` (JSON list, for private registries)

Edit `kubernetes/studio-secret.example.yaml` for:

- `LLMCTL_POSTGRES_PASSWORD` (required)
- optional `LLMCTL_STUDIO_DATABASE_URI` override

Edit `kubernetes/mcp-secret.example.yaml` for:

- `GITHUB_PERSONAL_ACCESS_TOKEN`
- `JIRA_*` and `CONFLUENCE_*` credentials
- `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON` and optional project selectors

If Harbor pull auth is needed, edit `kubernetes/harbor-pull-secret.example.yaml` for:

- `.dockerconfigjson` for your Harbor endpoint and project credentials

Edit `kubernetes/pgadmin-secret.example.yaml` for:

- `PGADMIN_DEFAULT_EMAIL` (required)
- `PGADMIN_DEFAULT_PASSWORD` (required)

## Optional executor smoke test

```bash
kubectl apply -f kubernetes/executor-smoke-job.example.yaml
kubectl -n llmctl logs job/llmctl-executor-smoke
```

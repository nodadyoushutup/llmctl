# Kubernetes manifests

This folder deploys the full `llmctl` stack into a single `llmctl` namespace:

- `llmctl-studio`
- `llmctl-redis`
- `llmctl-postgres`
- `llmctl-pgadmin`
- `llmctl-chromadb`

ArgoCD tracks this as one application (`llmctl-kubernetes`) for core services. Harbor can be tracked as a separate ArgoCD application (`llmctl-harbor`).

## Files

- `namespace.yaml`: `llmctl` namespace.
- `redis.yaml`: in-cluster Redis for Celery and Socket.IO queueing.
- `postgres.yaml`: in-cluster PostgreSQL for mandatory Studio persistence.
- `pgadmin.yaml`: in-cluster pgAdmin UI preconfigured for `llmctl-postgres`.
- `chromadb.yaml`: in-cluster ChromaDB for RAG vector storage.
- `studio-configmap.yaml`: non-secret Studio runtime settings.
- `studio-rbac.yaml`: service accounts and RBAC for Studio to create/read/delete executor Jobs.
- `studio-pvc.yaml`: persistent storage for `/app/data`.
- `studio-deployment.yaml`: Studio Deployment.
- `studio-service.yaml`: NodePort Service (`30155`) targeting Studio port `5155`.
- `studio-secret.example.yaml`: required secret template for PostgreSQL password, `FLASK_SECRET_KEY`, and optional API keys.
- `pgadmin-secret.example.yaml`: required secret template for pgAdmin web login credentials.
- `argocd-application.yaml`: single ArgoCD Application pointing at `kubernetes/`.
- `argocd-harbor-application.yaml`: ArgoCD Application that installs Harbor from the upstream Helm chart into `llmctl-harbor`.
- `kubernetes-overlays/minikube-live-code/`: local-only overlay that mounts host project code into `llmctl-studio` for rapid iteration without rebuilding images.

## Quick start

Create secrets before applying manifests:

```bash
cp kubernetes/studio-secret.example.yaml /tmp/llmctl-studio-secret.yaml
cp kubernetes/pgadmin-secret.example.yaml /tmp/llmctl-pgadmin-secret.yaml
# edit /tmp/llmctl-studio-secret.yaml
# edit /tmp/llmctl-pgadmin-secret.yaml
kubectl apply -f /tmp/llmctl-studio-secret.yaml
kubectl apply -f /tmp/llmctl-pgadmin-secret.yaml
```

Guard before ArgoCD sync or `kubectl apply -k`:

```bash
kubectl -n llmctl get secret llmctl-studio-secrets llmctl-pgadmin-secrets
```

If either secret is missing, create it first; pgAdmin stays unhealthy until `llmctl-pgadmin-secrets` exists.

Apply the full stack:

```bash
kubectl apply -k kubernetes
```

Port-forward Studio:

```bash
kubectl -n llmctl port-forward svc/llmctl-studio 5155:5155
```

Direct NodePort access (Minikube):

```bash
minikube -p llmctl ip
# open http://<minikube-ip>:30155/
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
kubectl -n llmctl rollout restart deploy/llmctl-studio
kubectl -n llmctl rollout status deploy/llmctl-studio
```

Notes:

- This overlay mounts `/workspace/llmctl` from the Minikube node into `/app/app/llmctl-studio/run.py`, `/app/app/llmctl-studio/src`, and `/app/app/llmctl-mcp`.
- Keep the `minikube mount` process running; if it stops, the pod cannot read mounted code paths.
- This is intended for local Minikube development, not shared/remote clusters.

## ArgoCD application

Create the single ArgoCD application resource:

```bash
kubectl apply -f kubernetes/argocd-application.yaml
```

This tracks repo path `kubernetes` on `main`, which includes namespace, redis, postgres, pgAdmin, chromadb, and studio resources together.

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

## Runtime knobs to edit

Edit `kubernetes/studio-configmap.yaml` for these keys:

- `LLMCTL_POSTGRES_HOST`, `LLMCTL_POSTGRES_PORT`, `LLMCTL_POSTGRES_DB`, `LLMCTL_POSTGRES_USER`
- `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_SSL`
- `LLMCTL_NODE_EXECUTOR_PROVIDER` (`kubernetes` or `workspace`)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE` (executor image)
- `LLMCTL_NODE_EXECUTOR_K8S_SERVICE_ACCOUNT` (job pod service account)
- `LLMCTL_NODE_EXECUTOR_K8S_GPU_LIMIT` (set `>0` to request NVIDIA GPU per executor Job)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON` (JSON list, for private registries)

Edit `kubernetes/studio-secret.example.yaml` for:

- `LLMCTL_POSTGRES_PASSWORD` (required)
- optional `LLMCTL_STUDIO_DATABASE_URI` override

Edit `kubernetes/pgadmin-secret.example.yaml` for:

- `PGADMIN_DEFAULT_EMAIL` (required)
- `PGADMIN_DEFAULT_PASSWORD` (required)

## Optional executor smoke test

```bash
kubectl apply -f kubernetes/executor-smoke-job.example.yaml
kubectl -n llmctl logs job/llmctl-executor-smoke
```

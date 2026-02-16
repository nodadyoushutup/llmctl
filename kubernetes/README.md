# Kubernetes manifests

This folder deploys the full `llmctl` stack into a single `llmctl` namespace:

- `llmctl-studio`
- `llmctl-redis`
- `llmctl-postgres`
- `llmctl-chromadb`

ArgoCD tracks this as one application (`llmctl-kubernetes`) so everything is visible on one screen.

## Files

- `namespace.yaml`: `llmctl` namespace.
- `redis.yaml`: in-cluster Redis for Celery and Socket.IO queueing.
- `postgres.yaml`: in-cluster PostgreSQL for mandatory Studio persistence.
- `chromadb.yaml`: in-cluster ChromaDB for RAG vector storage.
- `studio-configmap.yaml`: non-secret Studio runtime settings.
- `studio-rbac.yaml`: service accounts and RBAC for Studio to create/read/delete executor Jobs.
- `studio-pvc.yaml`: persistent storage for `/app/data`.
- `studio-deployment.yaml`: Studio Deployment.
- `studio-service.yaml`: NodePort Service (`30155`) targeting Studio port `5155`.
- `studio-secret.example.yaml`: required secret template for PostgreSQL password, `FLASK_SECRET_KEY`, and optional API keys.
- `argocd-application.yaml`: single ArgoCD Application pointing at `kubernetes/`.

## Quick start

Create secrets before applying manifests:

```bash
cp kubernetes/studio-secret.example.yaml /tmp/llmctl-studio-secret.yaml
# edit /tmp/llmctl-studio-secret.yaml
kubectl apply -f /tmp/llmctl-studio-secret.yaml
```

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
```

## ArgoCD application

Create the single ArgoCD application resource:

```bash
kubectl apply -f kubernetes/argocd-application.yaml
```

This tracks repo path `kubernetes` on `main`, which includes namespace, redis, postgres, chromadb, and studio resources together.

## Runtime knobs to edit

Edit `kubernetes/studio-configmap.yaml` for these keys:

- `LLMCTL_POSTGRES_HOST`, `LLMCTL_POSTGRES_PORT`, `LLMCTL_POSTGRES_DB`, `LLMCTL_POSTGRES_USER`
- `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_SSL`
- `LLMCTL_NODE_EXECUTOR_PROVIDER` (`kubernetes` or `workspace`)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE` (executor image)
- `LLMCTL_NODE_EXECUTOR_K8S_SERVICE_ACCOUNT` (job pod service account)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON` (JSON list, for private registries)

Edit `kubernetes/studio-secret.example.yaml` for:

- `LLMCTL_POSTGRES_PASSWORD` (required)
- optional `LLMCTL_STUDIO_DATABASE_URI` override

## Optional executor smoke test

```bash
kubectl apply -f kubernetes/executor-smoke-job.example.yaml
kubectl -n llmctl logs job/llmctl-executor-smoke
```

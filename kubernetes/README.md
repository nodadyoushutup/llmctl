# Kubernetes manifests

This folder deploys `llmctl-studio` with Redis and enables Kubernetes-based ephemeral node executor Jobs.

## Files

- `namespace.yaml`: `llmctl` namespace.
- `redis.yaml`: in-cluster Redis for Celery and Socket.IO queueing.
- `studio-configmap.yaml`: non-secret Studio runtime settings.
- `studio-rbac.yaml`: service accounts and RBAC for Studio to create/read/delete executor Jobs.
- `studio-pvc.yaml`: persistent storage for `/app/data`.
- `studio-deployment.yaml`: Studio Deployment.
- `studio-service.yaml`: ClusterIP Service on port `5155` (test port, separate from local Docker defaults).
- `studio-secret.example.yaml`: optional secret template for API keys and `FLASK_SECRET_KEY`.
- `executor-smoke-job.example.yaml`: optional one-off Job to validate `llmctl-executor` image.

## Quick start

```bash
kubectl apply -k kubernetes
```

Create secrets if needed:

```bash
cp kubernetes/studio-secret.example.yaml /tmp/llmctl-studio-secret.yaml
# edit /tmp/llmctl-studio-secret.yaml
kubectl apply -f /tmp/llmctl-studio-secret.yaml
```

Port-forward Studio:

```bash
kubectl -n llmctl port-forward svc/llmctl-studio 5155:5155
```

## ArgoCD application

Create the ArgoCD application resource:

```bash
kubectl apply -f kubernetes/argocd-application.yaml
```

Note: ArgoCD reads from `https://github.com/nodadyoushutup/llmctl.git` at `main`, path `kubernetes`.
If this folder is not pushed to `main` yet, the app will exist but show `ComparisonError` until pushed.

## Runtime knobs to edit

Edit `kubernetes/studio-configmap.yaml` for these keys:

- `LLMCTL_NODE_EXECUTOR_PROVIDER` (`kubernetes` or `workspace`)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE` (executor image)
- `LLMCTL_NODE_EXECUTOR_K8S_SERVICE_ACCOUNT` (job pod service account)
- `LLMCTL_NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON` (JSON list, for private registries)

If `llmctl-executor:latest` is not available yet, keep provider as `kubernetes` with fallback enabled (already defaulted), or switch `LLMCTL_NODE_EXECUTOR_PROVIDER` to `workspace` temporarily.

## Optional executor smoke test

```bash
kubectl apply -f kubernetes/executor-smoke-job.example.yaml
kubectl -n llmctl logs job/llmctl-executor-smoke
```

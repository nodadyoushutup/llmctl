# Kubernetes pgAdmin ArgoCD app

This folder defines `llmctl-pgadmin` as an ArgoCD Application sourced from the upstream `runix/pgadmin4` Helm chart. It deploys into `llmctl-pgadmin` and connects to the core PostgreSQL service in `llmctl`.

## Files

- `argocd-application.yaml`: ArgoCD Application that installs Helm chart `pgadmin4` version `1.59.0` from `https://helm.runix.net`.
- `pgadmin-secret.example.yaml`: required secret template for pgAdmin password and PostgreSQL password.

## Quick start

```bash
cp kubernetes/pgadmin/pgadmin-secret.example.yaml /tmp/llmctl-pgadmin-secret.yaml
# edit /tmp/llmctl-pgadmin-secret.yaml
kubectl apply -f /tmp/llmctl-pgadmin-secret.yaml
kubectl apply -f kubernetes/pgadmin/argocd-application.yaml
```

If migrating from the legacy bundled pgAdmin in namespace `llmctl`, remove old resources first to avoid NodePort conflict on `30156`:

```bash
kubectl -n llmctl delete svc/llmctl-pgadmin deploy/llmctl-pgadmin pvc/llmctl-pgadmin-data --ignore-not-found
```

If migrating from the previous manifest-based pgAdmin in namespace `llmctl-pgadmin`, delete the old Deployment/Service/ConfigMap once before the first Helm-backed sync (the Deployment selector changed and is immutable):

```bash
kubectl -n llmctl-pgadmin delete deploy/llmctl-pgadmin svc/llmctl-pgadmin configmap/llmctl-pgadmin-config --ignore-not-found
```

Guard before ArgoCD sync:

```bash
kubectl -n llmctl-pgadmin get secret llmctl-pgadmin-secrets
```

Important:

- Set `LLMCTL_POSTGRES_PASSWORD` in `kubernetes/pgadmin/pgadmin-secret.example.yaml` to match the `llmctl` PostgreSQL password (`llmctl-studio-secrets` in namespace `llmctl`), otherwise pgAdmin cannot connect.
- Default pgAdmin login email is `admin@example.com` (configured in `kubernetes/pgadmin/argocd-application.yaml` Helm values).

Port-forward pgAdmin:

```bash
kubectl -n llmctl-pgadmin port-forward svc/llmctl-pgadmin 5050:5050
```

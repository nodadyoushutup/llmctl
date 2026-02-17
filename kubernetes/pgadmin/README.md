# Kubernetes pgAdmin manifests

This folder deploys `llmctl-pgadmin` into its own namespace (`llmctl-pgadmin`) and keeps it connected to the core PostgreSQL service in `llmctl`.

## Files

- `namespace.yaml`: `llmctl-pgadmin` namespace.
- `pgadmin-configmap.yaml`: PostgreSQL connection settings used by pgAdmin bootstrap.
- `pgadmin.yaml`: pgAdmin PVC, Deployment, and NodePort Service (`30156`).
- `pgadmin-secret.example.yaml`: required secret template for pgAdmin login and PostgreSQL password.

## Quick start

```bash
cp kubernetes/pgadmin/pgadmin-secret.example.yaml /tmp/llmctl-pgadmin-secret.yaml
# edit /tmp/llmctl-pgadmin-secret.yaml
kubectl apply -f /tmp/llmctl-pgadmin-secret.yaml
kubectl apply -k kubernetes/pgadmin
```

If migrating from the legacy bundled pgAdmin in namespace `llmctl`, remove the old resources first to avoid NodePort conflict on `30156`:

```bash
kubectl -n llmctl delete svc/llmctl-pgadmin deploy/llmctl-pgadmin pvc/llmctl-pgadmin-data --ignore-not-found
```

Guard before ArgoCD sync or `kubectl apply -k`:

```bash
kubectl -n llmctl-pgadmin get secret llmctl-pgadmin-secrets
```

Important:

- Set `LLMCTL_POSTGRES_PASSWORD` in `kubernetes/pgadmin/pgadmin-secret.example.yaml` to the same value used by `llmctl` PostgreSQL (`llmctl-studio-secrets` in namespace `llmctl`), otherwise pgAdmin cannot connect.

Port-forward pgAdmin:

```bash
kubectl -n llmctl-pgadmin port-forward svc/llmctl-pgadmin 5050:5050
```

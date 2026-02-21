# Install Scripts

Centralized install/setup scripts live in this directory.

## Existing installers moved here

- `install-claude-cli.sh`
- `install-codex-cli.sh`
- `install-gemini-cli.sh`
- `install-docker-cli.sh`
- `install-kubectl.sh`
- `install-nvidia-container-toolkit.sh`

## New local Kubernetes scripts

- `scripts/minikube/minikube-up.sh` (convenience wrapper)
  - One-command Minikube start/resume flow only.
  - Live-code mount and overlay apply are handled separately.
  - Example:
    - `scripts/minikube/minikube-up.sh`

- `install-minikube-single-node.sh`
  - Installs `kubectl` + `minikube` and starts a single-node local cluster.
  - Default profile: `llmctl`
  - GPU flags: `--gpu`, `--no-gpu`, `--gpu-mode auto|on|off`
  - Example:
    - `scripts/install/install-minikube-single-node.sh`

- `install-argocd-on-minikube.sh`
  - Installs Argo CD into a minikube profile and writes admin credentials.
  - Default credentials file:
    - `data/argocd/argocd-admin-credentials.env`
  - Example:
    - `scripts/install/install-argocd-on-minikube.sh`

## Common environment variables

- `BIN_DIR` (default `/usr/local/bin`)
- `FORCE_INSTALL=1` to reinstall binaries

### Minikube script variables

- `MINIKUBE_PROFILE` (default `llmctl`)
- `MINIKUBE_DRIVER` (default `docker`)
- `MINIKUBE_K8S_VERSION` (optional)
- `MINIKUBE_CPUS` (default `4`)
- `MINIKUBE_MEMORY_MB` (default `8192`)
- `MINIKUBE_DISK_SIZE` (default `30g`)
- `MINIKUBE_GPU` (default `auto`; values: `auto`, `on`, `off`)

### Argo CD script variables

- `MINIKUBE_PROFILE` (default `llmctl`)
- `ARGOCD_NAMESPACE` (default `argocd`)
- `ARGOCD_ADMIN_PASSWORD` (optional; sets admin password during install)
- `ARGOCD_CREDENTIALS_FILE` (default `data/argocd/argocd-admin-credentials.env`)
- `ARGOCD_SERVER_SERVICE_TYPE` (default `NodePort`)

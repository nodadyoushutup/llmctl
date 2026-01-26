#!/usr/bin/env bash
set -euo pipefail

KUBECTL_VERSION="${KUBECTL_VERSION:-}"
ARCH="$(dpkg --print-architecture)"

if [ -z "$KUBECTL_VERSION" ]; then
  KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
fi

curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl" -o /usr/local/bin/kubectl
curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl.sha256" -o /tmp/kubectl.sha256

echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum -c -

chmod +x /usr/local/bin/kubectl
rm -f /tmp/kubectl.sha256

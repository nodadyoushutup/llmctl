# vLLM Local GPU (NVIDIA)

`llmctl-studio` is configured to request all host NVIDIA GPUs in the main compose file.

## Prerequisites

- NVIDIA driver installed on the host
- NVIDIA Container Toolkit installed and configured for Docker

## Start with GPU passthrough

Download the local Qwen model first (stores files in `<repo>/models`):

```bash
./download-qwen.sh
```

Then start Studio with GPU passthrough:

```bash
cd docker
docker compose -f docker-compose.yml up -d --build llmctl-studio
```

## Verify GPU is visible in the container

```bash
cd docker
docker compose -f docker-compose.yml exec llmctl-studio nvidia-smi
```

If `nvidia-smi` is not found or no GPU appears, verify host NVIDIA runtime setup first.

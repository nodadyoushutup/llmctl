ARG EXECUTOR_BASE_IMAGE=nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04
FROM ${EXECUTOR_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

ARG INSTALL_VLLM=true
ARG INSTALL_CLAUDE=true
ARG VENV_SYSTEM_SITE_PACKAGES=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gnupg \
        openssh-client \
        python3 \
        python3-pip \
        python3-venv \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @openai/codex@latest @google/gemini-cli@latest \
    && if [ "${INSTALL_CLAUDE}" = "true" ]; then npm install -g @anthropic-ai/claude-code@latest; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/llmctl-executor/requirements.txt /app/app/llmctl-executor/requirements.txt
COPY app/llmctl-studio-backend/requirements.txt /app/app/llmctl-studio-backend/requirements.txt
RUN if [ "${VENV_SYSTEM_SITE_PACKAGES}" = "true" ]; then \
        python3 -m venv --system-site-packages /opt/venv; \
    else \
        python3 -m venv /opt/venv; \
    fi
ENV PATH="/opt/venv/bin:${PATH}"
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && if [ -s /app/app/llmctl-executor/requirements.txt ]; then /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-executor/requirements.txt; fi \
    && if [ -s /app/app/llmctl-studio-backend/requirements.txt ]; then /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio-backend/requirements.txt; fi \
    && if [ "${INSTALL_VLLM}" = "true" ]; then /opt/venv/bin/pip install --no-cache-dir "vllm>=0.8.5"; fi

COPY app/llmctl-executor /app/app/llmctl-executor

CMD ["python3", "app/llmctl-executor/run.py"]

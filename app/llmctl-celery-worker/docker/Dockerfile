FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

ARG APP_UID=1000
ARG APP_GID=1000
ARG DOCKER_GID=999
ARG INSTALL_VLLM=true
ARG INSTALL_CLAUDE=true
ENV APP_UID=$APP_UID \
    APP_GID=$APP_GID \
    DOCKER_GID=$DOCKER_GID \
    APP_USER=llmctl-celery-worker \
    APP_GROUP=llmctl-celery-worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
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
    && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/google-cloud.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/google-cloud.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        google-cloud-cli \
        nodejs \
    && npm install -g @openai/codex@latest @google/gemini-cli@latest \
    && if [ "${INSTALL_CLAUDE}" = "true" ]; then npm install -g @anthropic-ai/claude-code@latest; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/install /app/scripts/install
COPY app/llmctl-studio-backend/docker/scripts /app/app/llmctl-studio-backend/docker/scripts
RUN /app/scripts/install/install-docker-cli.sh \
    && /app/scripts/install/install-kubectl.sh \
    && /app/app/llmctl-studio-backend/docker/scripts/setup-user-groups.sh

COPY app/llmctl-studio-backend/requirements.txt /app/app/llmctl-studio-backend/requirements.txt
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    LLMCTL_CELERY_WORKER_MODE=worker
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio-backend/requirements.txt \
    && if [ "${INSTALL_VLLM}" = "true" ]; then /opt/venv/bin/pip install --no-cache-dir "vllm>=0.8.5"; fi

COPY . /app
RUN mkdir -p /app/data \
    && chown -R "${APP_UID}:${APP_GID}" /app/data

USER llmctl-celery-worker

CMD ["python3", "app/llmctl-celery-worker/run.py", "worker"]

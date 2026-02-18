FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

ARG APP_UID=1000
ARG APP_GID=1000
ARG DOCKER_GID=999
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/install /app/scripts/install
COPY app/llmctl-studio-backend/docker/scripts /app/app/llmctl-studio-backend/docker/scripts
RUN /app/scripts/install/install-docker-cli.sh \
    && /app/scripts/install/install-kubectl.sh \
    && /app/app/llmctl-studio-backend/docker/scripts/setup-user-groups.sh

COPY app/llmctl-studio-backend/requirements.txt /app/app/llmctl-studio-backend/requirements.txt
COPY app/llmctl-rag/requirements.txt /app/app/llmctl-rag/requirements.txt
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    LLMCTL_CELERY_WORKER_MODE=worker
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio-backend/requirements.txt \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-rag/requirements.txt

COPY . /app
RUN mkdir -p /app/data \
    && chown -R "${APP_UID}:${APP_GID}" /app/data

USER llmctl-celery-worker

CMD ["python3", "app/llmctl-celery-worker/run.py", "worker"]

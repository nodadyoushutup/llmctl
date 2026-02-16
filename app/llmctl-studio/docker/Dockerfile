FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

ARG APP_UID=1000
ARG APP_GID=1000
ARG DOCKER_GID=999
ARG INSTALL_VLLM=true
ENV APP_UID=$APP_UID \
    APP_GID=$APP_GID \
    DOCKER_GID=$DOCKER_GID \
    APP_USER=llmctl-studio \
    APP_GROUP=llmctl-studio

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
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        nodejs \
    && npm install -g @openai/codex@latest @google/gemini-cli@latest @modelcontextprotocol/server-github@2025.4.8 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/llmctl-studio/docker/scripts /app/app/llmctl-studio/docker/scripts
RUN /app/app/llmctl-studio/docker/scripts/install-docker-cli.sh \
    && /app/app/llmctl-studio/docker/scripts/install-kubectl.sh \
    && /app/app/llmctl-studio/docker/scripts/setup-user-groups.sh

COPY app/llmctl-studio/requirements.txt /app/app/llmctl-studio/requirements.txt
COPY app/llmctl-mcp/requirements.txt /app/app/llmctl-mcp/requirements.txt
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio/requirements.txt \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-mcp/requirements.txt \
    && if [ "${INSTALL_VLLM}" = "true" ]; then /opt/venv/bin/pip install --no-cache-dir "vllm>=0.8.5"; fi

COPY . /app
RUN mkdir -p /app/data

EXPOSE 5055

USER llmctl-studio

CMD ["python3", "app/llmctl-studio/run.py"]

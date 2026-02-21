FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

ARG APP_UID=1000
ARG APP_GID=1000
ARG DOCKER_GID=999
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
    && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/google-cloud.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/google-cloud.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-linux.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        google-chrome-stable \
        google-cloud-cli \
    && ln -sf /usr/bin/google-chrome-stable /usr/local/bin/chromium-browser \
    && ln -sf /usr/bin/google-chrome-stable /usr/local/bin/chromium \
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
    LLMCTL_STUDIO_USE_GUNICORN=true
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio-backend/requirements.txt

COPY . /app
RUN mkdir -p /app/data

EXPOSE 5055

USER llmctl-studio

CMD ["python3", "app/llmctl-studio-backend/run.py"]

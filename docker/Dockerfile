FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        openssh-client \
        nodejs \
        npm \
        python3 \
        python3-pip \
        python3-venv \
    && npm install -g @openai/codex \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/llmctl-studio/requirements.txt /app/app/llmctl-studio/requirements.txt
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio/requirements.txt

COPY . /app
RUN mkdir -p /app/data

EXPOSE 5055

CMD ["python3", "app/llmctl-studio/run.py"]

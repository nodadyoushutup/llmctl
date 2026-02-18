FROM llmctl-executor-base:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

ARG INSTALL_VLLM=false

WORKDIR /app

COPY app/llmctl-executor/requirements.txt /app/app/llmctl-executor/requirements.txt
COPY app/llmctl-studio-backend/requirements.txt /app/app/llmctl-studio-backend/requirements.txt
RUN if [ ! -x /opt/venv/bin/python3 ]; then \
        echo "Missing /opt/venv in base image. Build/use llmctl-executor-base:latest (or retag a compatible base to that local tag)." >&2; \
        exit 1; \
    fi \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && if [ -s /app/app/llmctl-executor/requirements.txt ]; then /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-executor/requirements.txt; fi \
    && if [ -s /app/app/llmctl-studio-backend/requirements.txt ]; then /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-studio-backend/requirements.txt; fi \
    && if [ "${INSTALL_VLLM}" = "true" ]; then /opt/venv/bin/pip install --no-cache-dir "vllm==0.8.5"; fi

COPY app/llmctl-executor /app/app/llmctl-executor

CMD ["python3", "app/llmctl-executor/run.py"]

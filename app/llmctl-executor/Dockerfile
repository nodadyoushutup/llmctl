FROM llmctl-executor-base:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

ARG INSTALL_VLLM=false
ARG VLLM_VERSION=0.9.0
ARG TRANSFORMERS_VERSION=4.53.3
ARG INSTALL_STUDIO_BACKEND_DEPS=true

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY app/llmctl-executor/requirements.txt /app/app/llmctl-executor/requirements.txt
COPY app/llmctl-executor/requirements.studio-runtime.txt /app/app/llmctl-executor/requirements.studio-runtime.txt
RUN if [ ! -x /opt/venv/bin/python3 ]; then \
        echo "Missing /opt/venv in base image. Build/use llmctl-executor-base:latest (or retag a compatible base to that local tag)." >&2; \
        exit 1; \
    fi \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && if [ "${INSTALL_STUDIO_BACKEND_DEPS}" = "true" ] && [ -s /app/app/llmctl-executor/requirements.studio-runtime.txt ]; then /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-executor/requirements.studio-runtime.txt; fi \
    && if [ -s /app/app/llmctl-executor/requirements.txt ]; then /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-executor/requirements.txt; fi \
    && if [ "${INSTALL_VLLM}" = "true" ] && [ "${VLLM_VERSION}" = "0.9.0" ] && ! printf '%s' "${TRANSFORMERS_VERSION}" | grep -Eq '^4\.'; then \
        echo "Unsupported dependency combination: vllm ${VLLM_VERSION} requires transformers 4.x (got ${TRANSFORMERS_VERSION})." >&2; \
        exit 1; \
    fi \
    && if [ "${INSTALL_VLLM}" = "true" ]; then /opt/venv/bin/pip install --no-cache-dir "vllm==${VLLM_VERSION}" "transformers==${TRANSFORMERS_VERSION}"; fi \
    && /opt/venv/bin/pip check

COPY app/llmctl-executor /app/app/llmctl-executor

CMD ["python3", "app/llmctl-executor/run.py"]

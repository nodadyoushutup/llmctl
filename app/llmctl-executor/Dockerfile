FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    LLMCTL_EXECUTOR_FLAVOR="frontier"

LABEL org.opencontainers.image.title="llmctl-executor-frontier" \
      org.opencontainers.image.description="CPU-only executor for non-vLLM providers with SDK-only dependency policy" \
      io.llmctl.executor.flavor="frontier" \
      io.llmctl.executor.cpu_only="true"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        ghostscript \
        openssh-client \
        ocrmypdf \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/llmctl-executor/requirements.frontier.lock.txt /app/app/llmctl-executor/requirements.frontier.lock.txt
COPY app/llmctl-executor/requirements.studio-runtime.txt /app/app/llmctl-executor/requirements.studio-runtime.txt
COPY app/llmctl-executor/requirements.txt /app/app/llmctl-executor/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-executor/requirements.frontier.lock.txt \
    && /opt/venv/bin/pip check \
    && /opt/venv/bin/python3 -c "import fitz, pytesseract, PIL; print('frontier-ocr-python-deps-ok')" \
    && for required in tesseract pdfinfo pdftotext pdftoppm gs ocrmypdf; do \
        command -v "${required}" >/dev/null 2>&1 || { \
            echo "Missing required OCR/PDF tool in frontier image: ${required}" >&2; \
            exit 1; \
        }; \
    done \
    && /opt/venv/bin/python3 -c "import importlib.util,sys; sys.exit(1 if importlib.util.find_spec('vllm') else 0)" \
    && for blocked in codex gemini claude; do \
        if command -v "${blocked}" >/dev/null 2>&1; then \
            echo "Denied CLI binary found in frontier image: ${blocked}" >&2; \
            exit 1; \
        fi; \
    done

COPY app/llmctl-executor /app/app/llmctl-executor

CMD ["python3", "app/llmctl-executor/run.py"]

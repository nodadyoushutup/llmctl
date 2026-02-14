FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    python3 \
    python3-venv \
    tesseract-ocr \
    tesseract-ocr-eng \
  && python3 -m venv /opt/venv \
  && pip install --no-cache-dir --upgrade pip \
  && rm -rf /var/lib/apt/lists/*

COPY app/llmctl-rag/requirements.txt /app/app/llmctl-rag/requirements.txt
RUN pip install --no-cache-dir -r /app/app/llmctl-rag/requirements.txt

COPY app/llmctl-rag /app/app/llmctl-rag

CMD ["python3", "app/llmctl-rag/run.py"]

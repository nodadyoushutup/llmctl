FROM ubuntu:22.04

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    python3 \
    python3-pip \
  && rm -rf /var/lib/apt/lists/*

COPY app/llmctl-rag/requirements.txt /app/app/llmctl-rag/requirements.txt
RUN pip3 install --no-cache-dir -r /app/app/llmctl-rag/requirements.txt

COPY app/llmctl-rag /app/app/llmctl-rag

CMD ["python3", "app/llmctl-rag/watch.py"]

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app/app/llmctl-mcp/src"

WORKDIR /app

COPY app/llmctl-studio-backend/requirements.txt /app/app/llmctl-studio-backend/requirements.txt
COPY app/llmctl-mcp/requirements.txt /app/app/llmctl-mcp/requirements.txt

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/app/llmctl-mcp/requirements.txt

COPY . /app
RUN mkdir -p /app/data

EXPOSE 9020

CMD ["python", "app/llmctl-mcp/run.py"]

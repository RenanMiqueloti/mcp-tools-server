# syntax=docker/dockerfile:1.7
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --user -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

# Stdio transport — no port exposed. The MCP client connects via stdin/stdout.
CMD ["python", "server.py"]

# Service image: ping — a lightweight FastMCP streamable-http tracer (plan 04-01).
#
# Built by `harnessed svc up ping` on first use (or `podman build -t harnessed-ping:latest`).
# Scanned by the BLD-02 image-scan gate (T-04-02) when built via the launcher.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "mcp[cli]"

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

CMD ["python", "/app/server.py"]

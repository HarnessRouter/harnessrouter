# session-router — one gateway, many runners (Linux containers only).
#
#   1. build:                 docker build -t harnessrouter/session-router .
#   2. run beside the split images (docker-compose.split.yml):
#        HR_RUNNERS=r1=http://runner-1:8081,r2=http://runner-2:8081
#        POOL_MGMT_ENDPOINT=http://session-router:8090   (on the gateway)
#        HARNESS_GATEWAY_URL=http://gateway:8080         (unchanged; the runner still dials the gateway)
#   3. or let runners self-register: POST /register {"name": "r3", "url": "http://r3:8081"}
#      with X-Harness-Internal: <HR_ROUTER_KEY>
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HR_ROUTER_DB=/data/session-router.db

RUN apt-get update -y && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .

# The registry and the affinity table live on a volume, so a router restart puts every
# session back on the runner that owns its workspace directory.
VOLUME ["/data"]
EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s \
  CMD curl -fsS http://127.0.0.1:8090/healthz >/dev/null || exit 1

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--log-level", "warning"]

# HarnessRouter — self-hosted, all-in-one.
#
# One container runs the whole product: the UI, the gateway, and the agent runner. There is
# no cloud dependency, no control plane to reach, and nothing to provision. State is SQLite
# and files on one mounted volume.
#
# Why one container rather than compose-by-default: self-hosting should be `docker run`. The
# three processes are supervised by a tiny entrypoint, and because the gateway talks to the
# runner over loopback it needs no pool, no service discovery and no cloud identity.
#
# AGENT CLIs ARE INSTALLED ON FIRST RUN, NOT BAKED IN. This is a licensing requirement, not a
# size optimisation: Claude Code ships under Anthropic's own terms ("SEE LICENSE IN README.md")
# and hermes-agent declares no license at all, so neither may be redistributed inside a public
# image. Installing them at first start means YOU install them, under their terms, exactly as
# if you had run npm/pip yourself — and it keeps this image redistributable.
#
# They land in the data volume, so the cost is paid once per volume rather than once per start.
# Choose backends at RUN time:
#
#   docker run -e HR_BACKENDS=claude,codex,hermes   ...   # default: all three
#   docker run -e HR_BACKENDS=claude                ...   # lean
#
# WITH_BROWSER is still a build arg because Chromium and its system libraries genuinely belong
# in the image layer.

# ── UI build ──────────────────────────────────────────────────────────────────
FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY ui/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ARG WITH_BROWSER=0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    HOME=/home/agent \
    HARNESS_WORKSPACE=/workspace \
    HR_DATA_DIR=/data

RUN apt-get update -y && apt-get install -y --no-install-recommends \
        curl ca-certificates git bash tini \
    && rm -rf /var/lib/apt/lists/*

# Node is needed for the UI server and for the npm-based agent CLIs.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# Optional: browser automation for harnesses that verify their own output.
RUN set -eux; \
    if [ "$WITH_BROWSER" = "1" ]; then \
      pip install --no-cache-dir playwright && playwright install --with-deps chromium; \
    fi

WORKDIR /app

COPY gateway/requirements.txt /app/gateway/requirements.txt
COPY runner/requirements.txt  /app/runner/requirements.txt
# The gateway's requirements include hosted-only clients (cloud identity, the hosted document
# store). They are imported lazily and never touched self-hosted, so they are stripped here to
# keep the image small and the dependency surface honest about what this build actually uses.
RUN grep -viE "^(azure-|azure_)" /app/gateway/requirements.txt > /app/gateway/req.local.txt \
    && pip install --no-cache-dir -r /app/gateway/req.local.txt \
    && pip install --no-cache-dir -r /app/runner/requirements.txt

COPY gateway/ /app/gateway/
COPY runner/  /app/runner/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Next.js standalone output: server + only the modules it actually needs.
COPY --from=ui /ui/.next/standalone /app/ui/
COPY --from=ui /ui/.next/static     /app/ui/.next/static
COPY --from=ui /ui/public           /app/ui/public

# The agent CLIs refuse to run as root (they gate their own permission bypass on it), so the
# runtime user is unprivileged and owns the workspace and data volume.
RUN useradd -m -u 10001 agent \
    && mkdir -p /workspace /data \
    && chown -R agent:agent /workspace /data /app
USER agent

EXPOSE 3000
VOLUME ["/data"]

# The UI is the only published port. The gateway and runner stay on loopback — nothing else
# needs to be reachable from outside the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD curl -fsS http://127.0.0.1:8080/healthz >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]

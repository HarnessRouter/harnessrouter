# Audit image only. The scanner builds with network access, then audits offline.
# Build with the repository root as context; do not use the product entrypoint.
FROM node:22-bookworm-slim AS node
FROM python:3.12-bookworm

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_HR_EDITION=selfhost \
    PYTHONUNBUFFERED=1

# /src is the scanner's source-tree contract. Keep source and tests available.
COPY . /src
WORKDIR /src

RUN python -m pip install --no-cache-dir \
      -r gateway/requirements.txt -r runner/requirements.txt \
      pytest pytest-asyncio httpx jsonschema build wheel 'setuptools>=68' \
    && python -m pip install --no-cache-dir -e protocol/conformance \
    && python -m pip check

RUN cd ui \
    && npm ci --no-audit --no-fund \
    && npm run build \
    && npm run type-check

CMD ["bash"]

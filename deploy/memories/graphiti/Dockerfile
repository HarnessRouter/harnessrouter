FROM python:3.12-slim
RUN pip install --no-cache-dir graphiti-core==0.31.2 ladybug==0.22.1 httpx fastapi "uvicorn[standard]"
COPY server.py /app/server.py
WORKDIR /app
RUN mkdir -p /data /app/home && chown -R 1000 /data /app/home
ENV HOME=/app/home GRAPHITI_TELEMETRY_ENABLED=false
USER 1000
# The store's search by words is an extension it fetches once, here, so the server doesn't need that network later.
RUN python -c "import ladybug; ladybug.Connection(ladybug.Database(':memory:')).execute('INSTALL FTS')"
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

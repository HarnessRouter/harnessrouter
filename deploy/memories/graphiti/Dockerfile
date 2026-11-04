FROM python:3.12-slim
RUN pip install --no-cache-dir "graphiti-core[falkordb]==0.31.2" httpx fastapi "uvicorn[standard]"
COPY server.py /app/server.py
WORKDIR /app
USER 1000
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

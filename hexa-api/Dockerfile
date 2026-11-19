FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
COPY migrations /app/migrations
COPY migrate.py /app/migrate.py

ENV PYTHONUNBUFFERED=1
EXPOSE 4010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4010"]

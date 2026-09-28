# The public copy of uhp-conformance-fixture: the suite's own package with its `fixture` extra.
# Build from protocol/conformance as the context: docker build -f fixture/Dockerfile .
FROM python:3.12-slim
WORKDIR /src
COPY . /src
RUN pip install --no-cache-dir "/src[fixture]"
EXPOSE 8080
CMD ["uhp-conformance-fixture", "--host", "0.0.0.0", "--port", "8080"]

# Mem0's server, built as its repository builds it (server/Dockerfile at the pinned commit, given to this build as the
# `mem0` context), with what its entity linking needs and one read-only route.
#  - spaCy and its English model: without them Mem0 extracts no entities, links no facts, and its search gets no
#    boost from them (the server image as shipped has neither).
#  - hr_entities.py: GET /hr/entities, the entities and the facts each is linked to, so a memory's graph can be drawn.
FROM python:3.12-slim
WORKDIR /app
COPY --from=mem0 requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=mem0 . .
RUN pip install --no-cache-dir "spacy>=3.7,<4" && python -m spacy download en_core_web_sm
COPY hr_entities.py routers/hr_entities.py
RUN printf '\n# HarnessRouter: what Mem0 links inside itself, read only (deploy/memories/mem0)\nfrom routers import hr_entities as _hr_entities  # noqa: E402\napp.include_router(_hr_entities.router)\n' >> main.py \
 && python -c "import ast; ast.parse(open('main.py').read())"
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

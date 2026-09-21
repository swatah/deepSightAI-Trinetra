# deepSightAI Trinetra - AuditService Dockerfile (DEP-66)
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY setup.py pyproject.toml ./
COPY deepSightAI/ ./deepSightAI/
COPY config/ ./config/

RUN pip install --no-cache-dir psycopg2-binary kafka-python jsonschema \
    && pip install --no-cache-dir --no-deps -e .

EXPOSE 8080

CMD ["uvicorn", "deepSightAI.Trinetra.AuditService.audit_service:app", "--host", "0.0.0.0", "--port", "8080"]

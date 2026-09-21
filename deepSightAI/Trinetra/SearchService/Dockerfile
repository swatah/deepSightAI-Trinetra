# deepSightAI Trinetra - SearchService Dockerfile (DEP-66)
FROM python:3.10-slim

WORKDIR /app

# Install system runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy package metadata and application packages
COPY setup.py pyproject.toml ./
COPY deepSightAI/ ./deepSightAI/
COPY config/ ./config/

# Native package installation without PYTHONPATH hacks
RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8081

# Liveness probe on /health, readiness probe on /ready
CMD ["uvicorn", "deepSightAI.Trinetra.SearchService.main:app", "--host", "0.0.0.0", "--port", "8081"]

# deepSightAI Trinetra - AuthService Dockerfile (DEP-66)
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY deepSightAI/Trinetra/AuthService/requirements.txt ./requirements_auth.txt
RUN pip install --no-cache-dir -r requirements_auth.txt

COPY setup.py pyproject.toml ./
COPY deepSightAI/ ./deepSightAI/
COPY config/ ./config/

RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8002

CMD ["uvicorn", "deepSightAI.Trinetra.AuthService.auth_service:app", "--host", "0.0.0.0", "--port", "8002"]

# deepSightAI Trinetra - UI Dashboard Dockerfile (DEP-66)
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY deepSightAI/Trinetra/UI/requirements_ui.txt ./requirements_ui.txt
RUN pip install --no-cache-dir -r requirements_ui.txt

COPY setup.py pyproject.toml ./
COPY deepSightAI/ ./deepSightAI/
COPY config/ ./config/

RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8501

CMD ["streamlit", "run", "deepSightAI/Trinetra/UI/ui.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]

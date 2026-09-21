# Standard Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy package configuration, canonical deepSightAI package, and global config
COPY setup.py pyproject.toml ./
COPY deepSightAI/ ./deepSightAI/
COPY config/ ./config/

# Install deepSightAI package natively
RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8002

# Run Vision Processing Service FastAPI app
CMD ["uvicorn", "deepSightAI.Trinetra.VisionProcessingService.dsai_vps:app", "--host", "0.0.0.0", "--port", "8002"]

# Use a standard Python base image.
FROM python:3.9-bullseye

# Set the working directory inside the container.
WORKDIR /app

# Copy only the requirements file first to leverage Docker's build cache.
COPY deepSightAI/Trinetra/Embedder/requirements_embedder.txt ./

# Install the Python packages.
RUN pip install --no-cache-dir -r requirements_embedder.txt

# Copy the models directory (including ONNX model)
COPY deepSightAI/Trinetra/Embedder/models/ ./models/

# Copy the embedder scripts and startup script into the container.
COPY deepSightAI/Trinetra/Embedder/embedder.py .
COPY deepSightAI/Trinetra/Embedder/export_to_onnx.py .
COPY deepSightAI/Trinetra/Embedder/start.sh .

# Copy package configuration, canonical deepSightAI package, and global config
COPY setup.py pyproject.toml ./
COPY deepSightAI/ ./deepSightAI/
COPY config/ ./config/

# Install deepSightAI package natively
RUN pip install --no-deps -e .

# Make the startup script executable
RUN chmod +x start.sh

# The command to run when the container starts.
CMD ["./start.sh"]
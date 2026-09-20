# Use a standard Python base image.
FROM python:3.9-bullseye

# Set the working directory inside the container.
WORKDIR /app

# Copy only the requirements file first to leverage Docker's build cache.
# This step will only re-run if requirements_embedder.txt changes.
COPY Embedder/requirements_embedder.txt ./

# Install the Python packages.
RUN pip install --no-cache-dir -r requirements_embedder.txt

# Copy the models directory (including ONNX model)
COPY Embedder/models/ ./models/

# Copy the embedder script and startup script into the container.
COPY Embedder/embedder.py .
COPY Embedder/export_to_onnx.py .
COPY Embedder/start.sh .

# shared/ and config/ live at the repo root, not inside Embedder/ -- the
# build context is the repo root (see docker-compose.embedder.yaml) so
# they're available to COPY here.
COPY shared/ ./shared/
COPY config/ ./config/
ENV PYTHONPATH=/app

# Make the startup script executable
RUN chmod +x start.sh

# The command to run when the container starts.
CMD ["./start.sh"]
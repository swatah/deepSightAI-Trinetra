# Use a standard Python base image.
FROM python:3.9-bullseye

# Set the working directory inside the container.
WORKDIR /app

# Copy only the requirements file first to leverage Docker's build cache.
# This step will only re-run if requirements.txt changes.
COPY requirements_embedder.txt .

# Install the Python packages.
RUN pip install --no-cache-dir -r requirements_embedder.txt

# Copy the embedder script into the container.
COPY embedder.py .

# The command to run when the container starts.
CMD ["python", "embedder.py"]
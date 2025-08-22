# Use the full, non-slim version of the Debian Bullseye image for better compatibility
FROM python:3.9-bullseye

# Install ALL system dependencies in a single layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Add ffmpeg for segmentation
    ffmpeg \
    # GStreamer runtime libraries
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-tools \
    python3-gi \
    python3-gst-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
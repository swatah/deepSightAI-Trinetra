# Video Frame Embedding Service

This service automatically scans for video frames in a MinIO bucket, generates vector embeddings for each frame using the OpenCLIP model, and stores them in a Milvus vector database. This enables efficient similarity searching on video content.

The system runs as a set of containerized services managed by Docker Compose.

## How It Works

1. **Scan**: The service continuously scans MinIO buckets (`frames` and `frames-rtsp-*`) for new, unprocessed video segments or RTSP frame buckets.

2. **Embed**: It downloads batches of frames and uses the OpenCLIP `ViT-B-32` model to generate 512-dimensional vector embeddings, using a GPU if available.

3. **Store**: The embeddings and their metadata (video ID, frame path) are inserted into a Milvus collection.

4. **Mark**: Once a segment or bucket is fully processed, it's marked with a `.processed` file to prevent re-processing. If no new frames are found, the service waits briefly before scanning again.

## Services

The system consists of three main services:

* **`embedder`**: The main Python service that performs the scanning, embedding, and storing.

* **`milvus-standalone`**: The Milvus vector database for storing the embeddings.

* **`etcd`**: A key-value store required by Milvus.

## Configuration

The service is configured using environment variables in the `docker-compose.embedder.yaml` file.

| Variable | Description | Default | 
 | ----- | ----- | ----- | 
| `MILVUS_HOST` | Hostname of the Milvus service. | `milvus-standalone` | 
| `MILVUS_PORT` | Port for the Milvus service. | `19530` | 
| `MINIO_URL` | URL for the MinIO server. | `host.docker.internal:9000` | 
| `FRAME_BUCKET` | The MinIO bucket to scan for video frames. | `frames` | 
| `FILES_PER_EMBED_BATCH` | Number of frames to process at once. | `32` | 
| `INSERT_BATCH_SIZE` | Number of embeddings to batch before inserting into Milvus. | `500` | 

## Usage

With Docker and Docker Compose installed, run the following command from the project directory to build and start the services:

```
docker-compose -f docker-compose.embedder.yaml up --build

```

The `embedder` will then automatically start processing frames from the configured MinIO instance.

## Dependencies

Key Python dependencies include `torch`, `open_clip_torch`, `pymilvus`, and `minio`. All packages are listed in `requirements_embedder.txt` and installed via the `Dockerfile`.

# Video Frame Embedding Service

This service automatically scans for video frames in a MinIO bucket, generates vector embeddings for each frame using a bundled OpenCLIP model, and stores them in a Milvus vector database. This enables efficient similarity searching on video content.

The system runs as a set of containerized services managed by Docker Compose.

## How It Works

1.  **Scan**: The service continuously scans MinIO buckets (`frames` and `frames-rtsp-*`) for new, unprocessed video segments or RTSP frame buckets.
2.  **Embed**: It downloads batches of frames and uses the bundled OpenCLIP model to generate vector embeddings, using a GPU if available.
3.  **Store**: The embeddings and their metadata (video ID, frame path) are inserted into a Milvus collection.
4.  **Mark**: Once a segment or bucket is fully processed, it's marked with a `.processed` file to prevent re-processing. If no new frames are found, the service waits briefly before scanning again.

## Model Setup

This service requires you to download the model and include it in the repository to ensure it is self-contained and works in any environment.

**1. Create the `models` Folder**
In the root of your project, create a new folder named `models`.

**2. Download the Model**
Download the model weights file (`open_clip_pytorch_model.bin`) from the link below and place it inside the `models` folder you just created.

* **Model**: `ViT-B-32`

Your project structure should look like this:

```
Embedder/
├── models/
│   └── open_clip_pytorch_model.bin
├── docker-compose.embedder.yaml
├── Dockerfile
├── embedder.py
└── requirements_embedder.txt
```

**3. Modify `embedder.py`**
In `embedder.py`, find the line where the model is created and change it to point to the local file path:

```python
# Find this line:
model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32", pretrained="laion2b_s34b_b79k"
)

# And change it to this:
model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32", pretrained="models/open_clip_pytorch_model.bin"
)
```

**4. Update the `Dockerfile`**
Add a line to your `Dockerfile` to copy the `models` folder into the Docker image. This line should be added before the line that copies `embedder.py`.

```dockerfile
# Add this line before "COPY embedder.py ."
COPY models/ ./models/
```

After making these changes, the service is ready to be built and will use the local model file.

### Alternative Models

While `ViT-B-32` is a good default, you can use other OpenCLIP models depending on your needs for speed vs. accuracy.

* **`ViT-L-14`**: A larger, more accurate model. (Embedding Dimension: 768)
* **`ViT-H-14`**: One of the largest and most accurate models available. (Embedding Dimension: 1024)
* **`ViT-B-16`**: A model of similar size to the default but with a different patch size, which may offer different performance. (Embedding Dimension: 512)

To use an alternative, you must download the correct model weights, update the model name in `embedder.py`, and crucially, change the `EMBEDDING_DIM` in `docker-compose.embedder.yaml` to match the new model.

## Services

The system consists of three main services:

* **`embedder`**: The main Python service that performs the scanning, embedding, and storing.
* **`milvus-standalone`**: The Milvus vector database for storing the embeddings.
* **`etcd`**: A key-value store required by Milvus.

## Configuration

The service is configured using environment variables in the `docker-compose.embedder.yaml` file.

| Variable                | Description                                                 | Default                     |
| ----------------------- | ----------------------------------------------------------- | --------------------------- |
| `EMBEDDING_DIM`         | The output dimension of the model's vector.                 | `"512"`                     |
| `MILVUS_HOST`           | Hostname of the Milvus service.                             | `milvus-standalone`         |
| `MILVUS_PORT`           | Port for the Milvus service.                                | `19530`                     |
| `MINIO_URL`             | URL for the MinIO server.                                   | `host.docker.internal:9000` |
| `FRAME_BUCKET`          | The MinIO bucket to scan for video frames.                  | `frames`                    |
| `FILES_PER_EMBED_BATCH` | Number of frames to process at once.                        | `32`                        |
| `INSERT_BATCH_SIZE`     | Number of embeddings to batch before inserting into Milvus. | `500`                       |

## Usage

With Docker and Docker Compose installed, run the following command from the project directory to build and start the services:

```bash
docker-compose -f docker-compose.embedder.yaml up --build
```

## Dependencies

Key Python dependencies include `torch`, `open_clip_torch`, `pymilvus`, and `minio`. All packages are listed in `requirements_embedder.txt` and installed via the `Dockerfile`.

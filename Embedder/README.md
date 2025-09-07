# Video Frame Embedding Service

This service automatically scans for video frames in a MinIO bucket, generates vector embeddings for each frame using a bundled OpenCLIP model, and stores them in a Milvus vector database. This enables efficient similarity searching on video content.

The system runs as a set of containerized services managed by Docker Compose. The vision encoder can be exported to ONNX format for optimized inference or integration.
## How It Works

1.  **Scan**: The service continuously scans MinIO buckets (`frames` and `frames-rtsp-*`) for new, unprocessed video segments or RTSP frame buckets.
2.  **Embed**: It downloads batches of frames and uses the bundled OpenCLIP model to generate vector embeddings, using a GPU if available.
3.  **Store**: The embeddings and their metadata (video ID, frame path) are inserted into a Milvus collection.
4.  **Mark**: Once a segment or bucket is fully processed, it's marked with a `.processed` file to prevent re-processing. If no new frames are found, the service waits briefly before scanning again.
5.  **Delete**: After embedding and storing, frames are automatically deleted from the bucket to save storage and keep the system efficient.

## Model Setup

This service requires you to download the model and include it in the repository to ensure it is self-contained and works in any environment. You can also export the vision encoder to ONNX format for faster inference or deployment in other environments.

**1. Create the `models` Folder**
In the root of your project, create a new folder named `models`.

**2. Download the Model**

Download the model weights file (`open_clip_pytorch_model.bin`) from the link below and place it inside the `models` folder you just created. When you start the container, it will automatically check for and export the vision encoder to ONNX format if the ONNX model doesn't already exist.

* **Model**: `ViT-B-32`

The container startup process will:
- Check if `models/open_clip_vit_b32.onnx` exists
- If not, look for `models/open_clip_pytorch_model.bin` and export it to ONNX
- Use the available model format (ONNX preferred for performance, PyTorch as fallback)
- Start the embedder service

Your project structure should look like this:


```
Embedder/
├── models/
│   ├── open_clip_pytorch_model.bin
│   └── open_clip_vit_b32.onnx (auto-generated)
├── docker-compose.embedder.yaml
├── Dockerfile
├── embedder.py
├── export_to_onnx.py
├── start.sh
└── requirements_embedder.txt
```

**3. Model Loading (Automatic)**

The `embedder.py` automatically detects and uses local model files:

- If `models/open_clip_pytorch_model.bin` exists, it will use the local PyTorch model
- If `models/open_clip_vit_b32.onnx` exists, it will preferentially use the ONNX model for faster inference  
- If no local models exist, it will download the pretrained model (`laion2b_s34b_b79k`) on first run

No manual code modification is required - the system automatically chooses the best available model format.

**4. Update the `Dockerfile`**

The `Dockerfile` has been updated to include a startup script (`start.sh`) that automatically:
1. Checks if an ONNX model exists
2. If not, exports the PyTorch model to ONNX format (if available)
3. Starts the embedder service

```dockerfile
# The startup script and export script are copied automatically
COPY start.sh .
COPY export_to_onnx.py .
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
| `USE_ONNX`              | Whether to use ONNX model for inference if available.       | `"1"` (enabled)             |

## Usage

With Docker and Docker Compose installed, run the following command from the project directory to build and start the services:

```bash
docker-compose -f docker-compose.embedder.yaml up --build
```

The container will automatically:
1. Check for existing ONNX model (`models/open_clip_vit_b32.onnx`)
2. If not found, attempt to export from PyTorch model (`models/open_clip_pytorch_model.bin`)
3. Start the embedder service with the best available model format

**Manual ONNX Export** (Optional):
To manually export the ONNX model before running the container:

```bash
python export_to_onnx.py
```

The startup script will skip the export step if the ONNX model already exists.

## Dependencies


Key Python dependencies include:
- `torch`
- `open_clip_torch`
- `pymilvus`
- `minio`
- `onnx` (for exporting models)
- `onnxruntime-gpu` (for ONNX inference)

All packages are listed in `requirements_embedder.txt` and installed via the `Dockerfile`.
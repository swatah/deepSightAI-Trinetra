# Searching Video Content

This page explains how to perform semantic search on your videos, understand results, and optimize queries for better accuracy.

---

## What is Semantic Search?

Unlike traditional keyword search that matches exact words in metadata, **semantic search** understands the *meaning* of your query.

Example:
- ✅ Query: `"red truck"` → finds frames with red trucks (even if "red" or "truck" never appears in metadata)
- ❌ Traditional metadata search: would only match if someone manually tagged "red truck"

deepSightAI Trinetra uses **OpenCLIP**, a vision-language model trained on 400M image-text pairs. It converts both images and text into 512-dimensional vectors; similar concepts cluster together in vector space.

---

## Performing a Search

### Via Web UI

1. Navigate to **Search** tab
2. Enter query in search box: e.g., `"person wearing hard hat"`
3. Adjust sliders:
   - **Results to show**: 10-100
   - **Minimum similarity**: 70-99% (higher = more precise)
4. Click **Search**

Results appear as image thumbnails with:
- Similarity score (e.g., 94%)
- Timestamp (video position)
- Video name
- Action buttons: **View**, **Jump to video**, **Feedback** (thumbs up/down)

---

### Via API

```bash
curl -X POST https://api.trinetra.com/v1/search \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "person wearing hard hat",
    "tenant_id": "your-tenant",
    "top_k": 20,
    "min_similarity": 0.75,
    "video_filter": "vid_abc123"  # optional: limit to specific video
  }'
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Natural language search query |
| `tenant_id` | string | Yes | Your tenant identifier |
| `top_k` | integer | No | Max results to return (default: 10, max: 100) |
| `min_similarity` | float | No | Minimum cosine similarity 0.0-1.0 (default: 0.5) |
| `video_filter` | string | No | Only search within specific video ID |
| `timestamp_range` | object | No | `{"start": "00:01:00", "end": "00:05:00"}` |
| `include_thumbnails` | boolean | No | Generate thumbnail URLs (default: true) |

---

### Response Format

```json
{
  "query": "person wearing hard hat",
  "video_filter": null,
  "results": [
    {
      "frame_id": "frame_00423",
      "video_id": "vid_abc123",
      "video_name": "construction_site_day1.mp4",
      "timestamp_seconds": 45.2,
      "timestamp_formatted": "00:00:45",
      "similarity": 0.94,
      "thumbnail_url": "https://minio.deepSightAI-Trinetra.com/frames/vid_abc/frame_00423.jpg",
      "video_url": "https://minio.deepSightAI-Trinetra.com/videos/vid_abc.mp4",
      "segment_id": "seg_0002"
    },
    ...
  ],
  "total_results": 156,
  "returned": 20,
  "query_time_ms": 145,
  "searched_frames": 12450
}
```

---

## Understanding Similarity Scores

The `similarity` field is the **cosine similarity** between the query text embedding and the frame image embedding.

- **1.0 (100%)**: Perfect match
- **0.90-0.99 (90-99%)**: Very strong match
- **0.70-0.89 (70-89%)**: Good match (what you want)
- **0.50-0.69 (50-69%)**: Weak match (may be false positive)
- **< 0.50 (<50%)**: Likely irrelevant

**Recommended thresholds**:
- General search: `min_similarity = 0.6` (60%)
- Precision required: `min_similarity = 0.8` (80%)
- Broad discovery: `min_similarity = 0.4` (40%)

---

## Search Best Practices

### Use Specific Language

| Better | Worse | Why |
|--------|-------|-----|
| `"red pickup truck"` | `"vehicle"` | Specificity improves precision |
| `"person wearing hard hat"` | `"person"` | Adds attribute filter |
| `"office meeting room"` | `"meeting"` | Context matters |
| `"nighttime street"` | `"dark"` | Concrete concepts work better |

### Avoid Ambiguous Queries

- ❌ `"object"` (too vague)
- ❌ `"something moving"` (CLIP is frame-based, not motion-based)
- ❌ `"person with smile"` (works OK but "smiling person" better)

### Combine Concepts

CLIP handles multiple concepts well:

```bash
"person AND hard hat AND yellow"
"indoor OR hallway"
"car NOT truck"
```

However, boolean operators are not formally supported yet. Use phrasing:

- `"person wearing yellow hard hat"` (AND)
- `"living room or bedroom"` (OR via phrasing)

---

## Filtering Results

### By Video

Search within a specific video:

```bash
curl -d '{"query": "car", "video_filter": "vid_123"}' ...
```

UI: After uploading, click **Search** from the video details page to pre-filter.

### By Timestamp Range

Search only within a time window:

```bash
curl -d '{
  "query": "meeting",
  "timestamp_range": {"start": "00:10:00", "end": "00:20:00"}
}' ...
```

Useful for long videos where you know approximate timing.

### By Custom Metadata

If you've attached metadata to videos (camera location, operator, etc.), you can filter:

```bash
curl -d '{
  "query": "person",
  "metadata_filters": {
    "camera_location": "north-entrance",
    "weather": "clear"
  }
}' ...
```

---

## Common Use Cases

### Law Enforcement: Find Suspects

```
Query: "male wearing black hoodie"
Query: "red sedan"
Query: "person carrying backpack"
```

### Commercial: Analyze Customer Behavior

```
Query: "customer looking at shelf"
Query: "person at checkout counter"
Query: "queue of people"
```

### Logistics: Verify PPE Compliance

```
Query: "person wearing hard hat"
Query: "person wearing safety vest"
Query: "forklift truck"
```

---

## Evaluating Search Quality

### Precision vs Recall

- **Precision**: Of the results shown, how many are relevant? (minimize false positives)
- **Recall**: Of all relevant frames, how many did we find? (minimize false negatives)

Adjust `min_similarity` to balance:
- Higher threshold → higher precision, lower recall (fewer results but better quality)
- Lower threshold → higher recall, lower precision (more results but more false positives)

### Manual Evaluation

Spot-check results:
1. Are top 10 results all relevant?
2. Is the similarity score a good proxy for relevance?
3. Are there obvious misses (frames that should match but didn't)?

If poor quality:
- Check video quality (clarity, lighting)
- Consider re-embedding with different model (future: fine-tune CLIP on your domain)
- Adjust query phrasing

---

## Advanced Features

### Search with Image (reverse image search)

Instead of text, provide an image to find visually similar frames:

```bash
curl -X POST https://api.trinetra.com/v1/search/image \
  -H "Authorization: Bearer TOKEN" \
  -F "image=@query_image.jpg" \
  -F "top_k=20"
```

Useful for:
- Finding similar scenes
- "Show me all frames that look like this"

---

### Hybrid Search (text + image)

Combine text query with image reference:

```bash
curl -d '{
  "query": "similar vehicle but blue",
  "reference_image_url": "https://minio.deepSightAI-Trinetra.com/frames/frame_123.jpg",
  "lambda": 0.7  # weight: 0.7 text, 0.3 image
}'
```

---

### Batch Queries

Search multiple queries at once:

```bash
curl -X POST https://api.trinetra.com/v1/search/batch \
  -H "Authorization: Bearer TOKEN" \
  -d '{
    "queries": [
      {"query": "person", "top_k": 5},
      {"query": "vehicle", "top_k": 5},
      {"query": "building", "top_k": 5}
    ]
  }'
```

Saves API calls when you need multiple searches.

---

## Feedback Loop

Help improve search quality by providing feedback:

### Web UI

On each result, click 👍 or 👎. This data is used (future) to:
- Fine-tune CLIP on your domain
- Adjust ranking algorithm
- Detect systematic failures

### API Feedback Endpoint

```bash
curl -X POST https://api.trinetra.com/v1/feedback \
  -H "Authorization: Bearer TOKEN" \
  -d '{
    "query": "person wearing helmet",
    "frame_id": "frame_00423",
    "relevant": true
  }'
```

---

## Troubleshooting

### No Results Found

**Possible causes**:
- Query too specific: `"person wearing blue striped shirt with logo"` → try `"person wearing blue shirt"`
- Video content doesn't match query (verify by manually watching)
- Video not fully processed yet (status not `ready`)
- `min_similarity` set too high → lower to 0.4

**Debug steps**:
1. Check video status = `ready`
2. Try simple query: `"person"`
3. Lower `min_similarity` to 0.3
4. If still no results, video may not contain matching content

---

### Low Quality Results (many false positives)

- Increase `min_similarity` (e.g., 0.8)
- Use more specific query terms
- Check if training data for CLIP includes your domain (general model may struggle with specialized equipment like specific PPE brands)
- Consider fine-tuning (future feature)

---

### Slow Search

Search time depends on:
- Number of frames in Milvus (larger → slightly slower)
- `top_k` parameter (higher → more distance calculations)
- Milvus index type (HNSW is fast, brute force slower)

Typical latency: 50-200ms for 100K frames. If >2s:
- Check Milvus resource usage (CPU, memory)
- Verify HNSW index parameters (ef parameter affects speed/accuracy trade-off)
- Consider sharding Milvus or increasing resources

---

## Performance Tips

1. **Use specific queries** - fewer candidate matches means faster search
2. **Cache frequent queries** - add Redis in front of API
3. **Pre-filter by video** if you know which video to search (reduces search space)
4. **Increase Milvus resources** if latency too high
5. **Reduce `top_k`** if you only need top few matches

---

## Next Steps

After mastering search:
- Learn to [upload videos effectively](uploading.md)
- Explore the [complete API reference](api.md)
- Set up [monitoring](operations/monitoring.md) to track search performance
- Configure [authentication](auth.md) for secure multi-tenant operation

Happy searching! 🔍

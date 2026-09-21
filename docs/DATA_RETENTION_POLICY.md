# deepSightAI Trinetra: Data Retention & Legal-Hold Policy (GOV-1, GOV-2)

## 1. Objective & Scope
This policy defines retention intervals, automated lifecycle policies, and legal-hold override mechanisms across all data tiers in the deepSightAI Trinetra platform, encompassing:
- Raw video frames and clips in MinIO object storage.
- Extracted object detection crops (people and vehicles).
- Vector embeddings and metadata records in Milvus collections (`video_frames_{tenant_id}`, `video_objects_person_{tenant_id}`, `video_objects_vehicle_{tenant_id}`).
- Relational metadata in PostgreSQL (cameras, plate reads, watchlists, security alerts, and audit logs).

---

## 2. Retention Schedules

| Data Category | Default Retention Period | Storage Engine | Enforcement Mechanism |
|---|---|---|---|
| **Raw Video Frames** | 7 Days | MinIO (`frames`) | S3 Bucket Lifecycle Expiration Rule |
| **Object Detections Crops** | 7 Days | MinIO (`frames` / `crops/`) | `CropRetentionPolicy` + S3 Lifecycle |
| **Vector Embeddings (Frames)** | 30 Days | Milvus (`video_frames_{tenant_id}`) | Milvus TTL / Periodic Purge Worker |
| **Vector Embeddings (Person/Vehicle)** | 30 Days | Milvus (`video_objects_*_{tenant_id}`) | Milvus Partition / Periodic Purge Worker |
| **License Plate Reads** | 90 Days | PostgreSQL (`plate_reads`) | Database Partitioning / Archival Worker |
| **Security Alerts** | 365 Days (1 Year) | PostgreSQL (`alerts`) | Compliance Archival Policy |
| **Audit Log Trail** | 7 Years | AuditService / SIEM | WORM (Write-Once-Read-Many) Storage |

---

## 3. Crop Storage Retention Policy (GOV-2, DM-8)
To optimize storage efficiency while maintaining investigative utility:
1. **Confidence Gating**: By default, cropped images are only persisted to MinIO if detection confidence $\ge 0.50$.
2. **Embedding-Only Fallback**: Detections below the confidence threshold or with `store_crops=False` maintain their vector embeddings and bounding box coordinates in Milvus, but no separate JPEG crop is persisted to object storage.
3. **Sector Customization**: Sectors (such as commercial vs law enforcement) may configure customized confidence thresholds (`min_confidence`) and class filters (`persist_classes`).

---

## 4. Legal-Hold Override (GOV-1, DM-9)

> **CRITICAL LEGAL DIRECTIVE**:
> Any camera, tenant, incident, or case placed under an active **Legal Hold** immediately suspends all automated expiration and deletion procedures for all associated frames, crops, plate reads, detections, and alerts.

### 4.1 Activation & Scoping
- **Tenant-Level Hold**: Halts all scheduled purges for all data belonging to the designated `tenant_id`.
- **Camera-Level Hold**: Halts scheduled purges for all data ingested from the specified `camera_id`.
- **Record-Level Hold**: Pins specific `video_object_pk` or incident video IDs indefinitely until formal legal release.

### 4.2 Technical Enforcement
- The `DataRetentionManager.evaluate_expiration()` API performs a fail-closed legal-hold verification before permitting any record removal. If an active hold is detected, `evaluate_expiration` unconditionally evaluates to `False`.
- Any automated purge script attempting to delete records under active hold raises `LegalHoldError`.

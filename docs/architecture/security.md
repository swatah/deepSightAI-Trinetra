# Security Architecture

This page describes the security model of deepSightAI Trinetra: multi-tenancy, authentication, encryption, network policies, and audit logging.

---

## Multi-Tenancy

### Data Isolation Guarantees

Every tenant's data is completely isolated:

- **Database**: Queries always filter by `tenant_id`. Using PostgreSQL Row-Level Security (RLS) or schema-per-tenant.
- **Object Storage**: MinIO paths include tenant ID (`{tenant_id}/videos/...`). Bucket policies prevent cross-tenant access.
- **Vector DB**: Milvus collections partitioned by tenant ID. All searches include tenant filter.
- **Cache**: Redis keys prefixed with `{tenant_id}:`.
- **Kafka**: Topics include tenant ID for stream processing.

**Result**: No tenant can ever access another tenant's data, even if they compromise the API.

---

### Implementation Details

**Database Tenant Filter** (FastAPI middleware):

```python
@app.middleware("http")
async def inject_tenant(request: Request, call_next):
    # JWT already validated, tenant_id extracted
    tenant_id = request.state.tenant_id
    
    # Create tenant-scoped DB session
    # For schema-per-tenant:
    #   conn.execute(f"SET search_path TO tenant_{tenant_id}, public")
    # For row-level security (RLS):
    #   conn.execute(f"SET app.tenant_id = '{tenant_id}'")
    
    response = await call_next(request)
    return response
```

**RLS Policy** (PostgreSQL):

```sql
-- Enable RLS on all tenant-data tables
ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments ENABLE ROW LEVEL SECURITY;

-- Policy: only allow access to rows where tenant_id matches app.tenant_id
CREATE POLICY tenant_isolation ON videos
    USING (tenant_id = current_setting('app.tenant_id'));

-- Set tenant context per request (from JWT):
SET app.tenant_id = 'acme-corp';
```

**MinIO Tenant Prefix**:

```python
# All operations under tenant-specific prefix
bucket = f"{tenant_id}-videos"  # OR use common bucket with prefix
key = f"{tenant_id}/videos/{video_id}.mp4"
```

**Milvus Partition Key**:

```python
# Insert with partition tag
milvus.insert(
    collection_name="video_frames",
    partition_tags=[tenant_id],  # Partition by tenant
    data=[...]
)

# Search with partition filter
milvus.search(
    collection_name="video_frames",
    partition_names=[tenant_id],
    ...
)
```

---

## Authentication & Authorization

### JWT-Based Auth

All API requests (except `/health`) require JWT in `Authorization: Bearer <token>` header.

**Token validation** (in middleware):

```python
from jose import jwt

public_key = load_public_key_from_jwks()
payload = jwt.decode(
    token,
    public_key,
    algorithms=["RS256"],
    audience="api.deepSightAI-Trinetra.com",
    issuer="https://auth.trinetra.com"
)

# Extract claims
tenant_id = payload["tenant_id"]
roles = payload["roles"]  # ["admin", "operator"]
user_id = payload["sub"]
```

**Required claims**:
- `exp` - expiration (required)
- `iss` - issuer (must match AuthService)
- `aud` - audience (must be our API URL)
- `tenant_id` - tenant identifier
- `sub` - user ID

---

### API Keys (Alternative)

For service-to-service communication, long-lived API keys:

```python
# Look up hashed API key in DB
api_key_hash = hash(request.headers["X-API-Key"])
client = db.query(ApiClient).filter_by(key_hash=api_key_hash).first()
if not client:
    raise HTTPException(401, "Invalid API key")

# Client has tenant_id and roles attached
request.state.tenant_id = client.tenant_id
request.state.roles = client.roles
```

API keys stored hashed with bcrypt/scrypt/argon2.

---

### Role-Based Access Control (RBAC)

API endpoints check roles:

```python
@require_role("operator")  # Decorator
async def upload_video(request):
    # Only operators and admins can upload
    pass

@require_role("admin")  # Admin required
async def delete_video(request, video_id):
    pass

@require_any_role("viewer", "operator", "admin")
async def search_videos(request):
    # All authenticated roles can search
    pass
```

**Built-in roles**:
- `admin` - full access
- `operator` - can upload/delete videos, but not manage users
- `viewer` - search only
- `service_account` - for automation (no UI login)

**Custom roles**: Admins can define custom role with granular permissions (e.g., `can_upload`, `can_search`, `can_delete`).

---

## Encryption

### In Transit (TLS 1.3)

All external communication uses TLS 1.3:

- API endpoints: HTTPS (443)
- Database connections: TLS (postgresql://...?sslmode=require)
- Redis: REDIS-TLS (or stunnel for older versions)
- MinIO: HTTPS (S3 over TLS)
- Milvus: TLS (if enabled)

**Certificates**: Managed by cert-manager in Kubernetes, auto-renewing Let's Encrypt certificates. For internal service-to-service, use mTLS with Istio (optional).

**Verification**:

```bash
curl -I https://api.trinetra.com  # Should return 200, not 301 to http
openssl s_client -connect api.deepSightAI-Trinetra.com:443 -tls1_3
```

---

### At Rest

**PostgreSQL**: Transparent Data Encryption (TDE) using cloud provider KMS or LUKS on bare metal.

```ini
# postgresql.conf
ssl = on
ssl_cert_file = '/etc/ssl/server.crt'
ssl_key_file = '/etc/ssl/server.key'

# For TDE, use tablespace encryption
```

**MinIO**: Server-Side Encryption with KMS (SSE-KMS) or customer-provided keys (SSE-C).

```bash
# Upload with SSE-KMS
mc cp video.mp4 deepSightAI-Trinetra/videos/ --sse-kms aws:kms:KMS_KEY_ID
```

**Milvus**: Disk encryption at cloud provider level (EBS encryption, GCE PD encryption).

**Redis**: If persistence enabled (`appendonly yes`), encrypted disk.

---

## Network Security

### Zero-Trust Network

Kubernetes Network Policies restrict pod-to-pod communication:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow-outbound
spec:
  podSelector:
    matchLabels:
      app: deepSightAI-Trinetra-api
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - podSelector:
        matchLabels:
          app: minio
    ports:
    - protocol: TCP
      port: 9000
  - to:
    - namespace: kube-system
      matchLabels:
        k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

**Default deny-all**: All other egress blocked.

### Ingress

External traffic enters via Ingress Controller (nginx/traefik/alb) with:
- TLS termination
- Rate limiting (per IP)
- WAF rules (optional)
- IP whitelisting (for admin endpoints)

---

## Secrets Management

### HashiCorp Vault

All secrets stored in Vault, NOT in Git.

```hcl
# Vault policies for deepSightAI Trinetra
path "secret/data/deepSightAI-Trinetra/*" {
  capabilities = ["read"]
}

path "cubbyhole/creds/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
```

Kubernetes External Secrets Operator fetches secrets at pod startup:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: deepSightAI-Trinetra-db-secret
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: deepSightAI-Trinetra-db-secret
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: secret/data/deepSightAI-Trinetra/database
      property: postgres-password
```

### Secret Rotation

**PostgreSQL password**: Rotated automatically by script; API rolls over connections smoothly.

**JWT key pairs**: Rotated by keeping both old and new public keys in JWKS endpoint; tokens signed with either accepted until old key retired.

---

## Audit Logging

All user actions logged to `audit_logs` table with WORM (Write Once Read Many) storage.

### Logged Events

| Action | Fields logged |
|--------|---------------|
| `video.upload` | user_id, tenant_id, video_id, IP, user_agent, file size |
| `video.delete` | user_id, tenant_id, video_id |
| `search.perform` | user_id, tenant_id, query, result_count, latency_ms |
| `login.success` | user_id, tenant_id, IP |
| `login.failure` | user_id (if provided), IP, reason |
| `api_key.create` | admin_user_id, target_user, key_name |
| `permission.denied` | user_id, resource, required_role |

### Immutability

PostgreSQL policies prevent UPDATE/DELETE on `audit_logs`:

```sql
CREATE POLICY audit_deny_update ON audit_logs
  FOR UPDATE USING (false);
CREATE POLICY audit_deny_delete ON audit_logs
  FOR DELETE USING (false);

-- Also trigger with explicit error
CREATE TRIGGER audit_prevent_update BEFORE UPDATE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_prevent_modification();
```

**Even database administrators cannot modify audit logs**. Only `COPY` export allowed.

### Retention

- Hot storage (PostgreSQL): 90 days
- Cold storage (S3 Glacier): Archive after 90 days
- Retention period: 7 years (compliance requirement)
- Deletion mechanism: Compliance must approve manual removal after 7 years (legal hold)

[Retention script](../scripts/retention/archive_audit_logs.py)

---

## Compliance

### GDPR

- **Data deletion**: `DELETE /tenants/{id}` cascades to all data stores (PostgreSQL, MinIO, Milvus)
- **Right to be forgotten**: 30-day purge window
- **Data export**: `GET /users/{id}/export` returns all personal data in JSON
- **Consent**: Tracks user consent in audit logs

### CJIS (Criminal Justice)

- Immutable audit logs (7 years)
- Encryption at rest and in transit
- Access controls (RBAC, MFA required)
- Regular security audits (annual)

### HIPAA (Healthcare)

- Encrypted storage (AES-256)
- Access logging (who viewed what)
- Backup encryption
- BAA available (contact sales)

### SOC 2 Type II

- Change management (all Git-tracked)
- Incident response procedures
- Regular penetration testing (annual)
- Monitoring and alerting

---

## Penetration Testing

Internal security tests:
- [x] SQL injection (blocked by ORM + RLS)
- [x] XSS (no user-generated HTML)
- [x] CSRF (JWT in Authorization header, not cookies)
- [x] SSRF (MinIO URLs restricted to internal endpoints)
- [x] Path traversal (MinIO bucket isolation)
- [x] Privilege escalation (RBAC enforcement tested)
- [ ] DDoS protection (use cloud WAF)
- [ ] Rate limit bypass (implement per-tenant)

External pentest scheduled Q2 2025.

---

## Incident Response

If security incident suspected:

1. **Contain**: Rotate all secrets (Vault), revoke all JWT tokens (`jwt_blacklist` table)
2. **Investigate**: Check audit logs, search for anomalous activity
3. **Notify**: Customers per SLA (72h for breaches)
4. **Remediate**: Patch vulnerabilities, rotate keys
5. **Post-mortem**: Document lessons learned

Contact: security@deepSightAI-Trinetra.com (24/7 on-call)

---

## Further Reading

- [Multi-tenancy implementation](../development/tenancy.md)
- [API authentication](../user-guide/auth.md)
- [Operations security](../operations/security-hardening.md)
- [Compliance documentation](../reference/compliance.md)

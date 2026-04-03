# Authentication & Authorization

This guide covers authentication setup for ClipSight, including JWT tokens, API keys, and role-based access control (RBAC).

---

## Overview

In production deployments, **authentication is required** to:
- Verify user identity
- Enforce tenant isolation (multi-tenancy)
- Audit user actions
- Control permissions via roles

ClipSight supports:
- **JWT Bearer tokens** (OAuth2/OIDC compatible)
- **API Keys** (for programmatic access)
- **OAuth2 social login** (Google, GitHub, Azure AD, Okta)

All methods ultimately yield a JWT token with claims identifying the user and tenant.

---

## Getting a Token

### For Interactive Users (Web UI)

1. Navigate to deployment URL
2. Click **Login** (top-right)
3. Enter credentials (or choose SSO provider)
4. Redirect back to UI with session cookie

### For API Clients (Scripts, Services)

```bash
# Obtain JWT via OAuth2 client credentials flow
curl -X POST https://auth.clipsight.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "grant_type=client_credentials" \
  -d "tenant_id=YOUR_TENANT_ID"

# Response:
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "read write"
}

# Use token:
curl -H "Authorization: Bearer eyJhbGci..." https://api.clipsight.com/v1/videos
```

---

## Token Format

ClipSight uses **RS256** (RSA with SHA-256) signed JWTs.

### Claims

| Claim | Type | Description |
|-------|------|-------------|
| `iss` | string | Issuer (e.g., `https://auth.clipsight.com`) |
| `sub` | string | Subject (user ID or client ID) |
| `aud` | string | Audience (expected API URL) |
| `exp` | integer | Expiration timestamp (seconds since epoch) |
| `iat` | integer | Issued at timestamp |
| `tenant_id` | string | Tenant identifier |
| `roles` | array | List of roles: `["admin", "viewer"]` |
| `scope` | string | Space-separated scopes: `"read write"` |

Example decoded JWT:

```json
{
  "iss": "https://auth.clipsight.com",
  "sub": "user_abc123",
  "aud": "api.clipsight.com",
  "exp": 1743751200,
  "iat": 1743664800,
  "tenant_id": "acme-corp",
  "roles": ["viewer"],
  "scope": "read"
}
```

---

## API Keys (Alternative)

For long-lived service accounts, create API keys:

1. Go to **Admin → API Keys** (in UI)
2. Click **Create New Key**
3. Enter name: `"deployment-script"`
4. Select role: `service_account` or `admin`
5. Copy the key (shown once!)

Use API key as `X-API-Key` header:

```bash
curl -H "X-API-Key: clipsight_live_xxxxx" https://api.clipsight.com/v1/videos
```

API keys never expire (unless revoked). Store securely (vault, env vars).

---

## Role-Based Access Control (RBAC)

### Built-in Roles

| Role | Permissions |
|------|-------------|
| `admin` | Full access: read/write all data, manage users, delete videos |
| `operator` | Upload videos, view all videos, search (read-only operations) |
| `viewer` | Search only, cannot upload |
| `service_account` | Machine-to-machine; same as operator but no UI login |

### Custom Roles

Admins can create custom roles via Admin UI or API:

```yaml
name: "quality_inspector"
permissions:
  - "video:read"
  - "video:search"
  - "video:review"  # can add feedback, but not delete
```

---

## Multi-Tenant Isolation

Each JWT token contains `tenant_id`. All API requests are scoped to that tenant:
- Database queries filter by `tenant_id`
- MinIO paths include `{tenant_id}/`
- Milvus searches include tenant partition key

**You can only see your own tenant's data**. Tenant isolation is enforced at every layer (SQL, storage, vectors). See [Architecture → Security](architecture/security.md) for implementation details.

---

## Common Scenarios

### Granting Access to New User

```bash
# 1. Create user in AuthService (or IdP)
curl -X POST https://auth.clipsight.com/admin/users \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{
    "email": "jane@acme.com",
    "tenant_id": "acme-corp",
    "roles": ["viewer"],
    "send_invite": true
  }'

# 2. User receives email with login link
# 3. User sets password and logs in
```

---

### Service-to-Service Communication

For microservices calling ClipSight API (e.g., your monitoring system), use service account:

```bash
# Create service account key
curl -X POST https://auth.clipsight.com/admin/api-keys \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{
    "name": "monitoring-bot",
    "tenant_id": "acme-corp",
    "roles": ["viewer"]
  }'

# Response: {"api_key": "clipsight_live_xxxxx"}
```

Store key in Kubernetes Secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: monitoring-credentials
type: Opaque
stringData:
  clipsight-api-key: "clipsight_live_xxxxx"
```

Your monitoring script:

```python
import os
import requests

API_KEY = os.getenv("CLIPSIGHT_API_KEY")
response = requests.get(
    "https://api.clipsight.com/v1/videos",
    headers={"X-API-Key": API_KEY}
)
```

---

### OAuth2 Integration with External IdP

For enterprise SSO (Okta, Azure AD, Keycloak), configure AuthService to trust external provider:

```yaml
# config.yaml for AuthService
oauth2:
  providers:
    okta:
      client_id: "0oa1abc2def3gh4ijk"
      client_secret: "SECRET"
      issuer: "https://dev-123456.okta.com/oauth2/default"
      scopes: ["openid", "profile", "email"]
```

Then in UI, users click **Login with Okta**. Redirect flow handles JWT issuance.

---

## Security Considerations

1. **Never hardcode tokens** in source code. Use environment variables or secret managers.
2. **Rotate API keys** periodically (every 90 days for production).
3. **Use least-privilege roles**: Give users only permissions they need.
4. **HTTPS only**: Tokens transmitted over TLS. Never send in clear text.
5. **Short-lived JWTs**: Default expiration 1 hour. Refresh with `refresh_token` flow.
6. **Revoke compromised tokens**: Admin can delete user sessions or revoke API keys via AuthService admin API.

---

## Troubleshooting

### "401 Unauthorized" or "Invalid token"

- Token expired (check `exp` claim)
- Wrong issuer or audience
- Token not signed with expected key (key rotation may be in progress)
- Missing `tenant_id` claim

### "403 Forbidden" - Insufficient Permissions

User authenticated but lacks required role for endpoint:
- `POST /process_video` requires `operator` or `admin`
- `DELETE /video/{id}` requires `admin`

Ask admin to assign correct role.

### "429 Too Many Requests" - Rate Limiting

Default: 60 requests/minute per user. Backoff and retry after `Retry-After` header.

---

## Testing Authentication Locally

For development, disable auth in `main_api.py`:

```python
# Set env var
export DISABLE_AUTH=true

# Then API skips JWT validation (DO NOT USE IN PRODUCTION)
```

Or use test credentials:

```bash
# Test JWT (signed with test private key)
TEST_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyX2FiYzEyMyIsInRlbmFudF9pZCI6ImFjbWUtY29ycCIsInJvbGVzIjpbInZpZXdlciIsImFkbWluIl0sImV4cCI6MTc0Mzc1MTIwMH0.signature"
```

---

## Next Steps

- Configure authentication for your deployment: [Installation → Kubernetes](installation/kubernetes.md#7-configure-ingress)
- Set up multi-tenancy: [Architecture → Tenancy](architecture/components.md#multi-tenancy)
- Integrate with your IdP: [AuthService docs](https://github.com/yourorg/clipsight/tree/main/AuthService)
- Learn about [security architecture](architecture/security.md)

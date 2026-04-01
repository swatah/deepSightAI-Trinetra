# Development Tracking & Progress Management

**Purpose**: Track all development work against the enterprise roadmap, enable recovery from failures without redoing work, and enforce test-driven development.

---

## How to Use This System

### Philosophy
- **Never redo work**: Every code change must be traceable to a tracked task
- **Test-first**: No code without failing test first
- **Atomic commits**: Each commit implements ONE task and makes tests pass
- **Clear rollback**: If something breaks, revert to last green commit

### Daily Workflow

```bash
# 1. Start work on a task
python scripts/tracking.py start T1.1.1
# Output: Task T1.1.1 started at 2025-04-01 10:00
# Creates: .current_task

# 2. Write failing test first (red phase)
# Edit: tests/phase1/auth/test_jwt_middleware.py
# Run: pytest tests/phase1/auth/test_jwt_middleware.py -v
# Should fail (test expects functionality not yet written)

# 3. Write minimal code to pass (green phase)
# Edit: AuthService/middleware.py
# Run: pytest tests/phase1/auth/test_jwt_middleware.py -v
# Should pass

# 4. Refactor (optional)
# Improve code quality, run all tests

# 5. Complete task
python scripts/tracking.py complete T1.1.1
# Output: Task T1.1.1 completed, 2 hours 15 minutes
# Creates: commits/T1.1-1.2.3_add_jwt_middleware/<commit-hash>
# Commits with message: "feat(auth): add JWT middleware with tenant extraction"

# 6. If something breaks later, can cherry-pick or revert task commit
```

---

## Task Structure

All tasks are hierarchical:
- **Phase**: Major project phase (P1-P5)
- **Area**: Functional area within phase (1.1, 1.2, etc.)
- **Task**: Atomic work unit (T1.1.1, T1.1.2, etc.)

Each task has:
- Unique ID
- Description
- Acceptance criteria (testable)
- Estimated hours
- Dependencies (other tasks that must complete first)
- Test file location(s)
- Implementation file(s)

---

## Master Task List

### Phase 1: Foundation (Months 1-2) - Secure Multi-Tenant Core

#### Area 1.1: Kubernetes-Native Architecture Migration (P0)
**Dependencies**: None
**Estimated**: 40 hours

| Task | Description | Acceptance Criteria | Tests | Files |
|------|-------------|-------------------|-------|-------|
| T1.1.1 | Convert Docker Compose services to K8s manifests | All services deploy with `kubectl apply -k k8s/overlays/development` | `tests/k8s/test_manifests.py` | `k8s/base/` |
| T1.1.2 | Create Kustomize overlays for dev/prod | `kubectl apply -k k8s/overlays/development` works on k3s | `tests/k8s/test_overlays.py` | `k8s/overlays/` |
| T1.1.3 | Package each service as Helm chart | `helm install clipsight-main-api ./helm/main-api` succeeds | `tests/helm/test_charts.py` | `helm/` |
| T1.1.4 | Set up ArgoCD for GitOps deployment | Pushing to Git auto-deploys to test cluster | `tests/gitops/test_argocd_sync.py` | `argocd-apps/` |
| T1.1.5 | Validate K8s manifests with kubeval/Score | CI fails on invalid YAML | CI pipeline | GitHub Actions |
| T1.1.6 | Test local k3d cluster deployment | `k3d cluster create clipsight-test` + ArgoCD deploys successfully | `tests/k8s/test_k3d.py` | N/A |

#### Area 1.2: Authentication & Authorization (P0)
**Dependencies**: T1.1.1-T1.1.4
**Estimated**: 80 hours

| Task | Description | Acceptance Criteria | Tests | Files |
|------|-------------|-------------------|-------|-------|
| T1.2.1 | Design authentication schema (DB tables) | ERD approved: users, roles, tenants, api_keys, user_tenants | Design doc | `docs/design/auth-schema.md` |
| T1.2.2 | Create AuthService FastAPI app | `POST /auth/register` creates user, returns JWT | `tests/auth/test_auth_service.py` | `AuthService/auth_service.py` |
| T1.2.3 | Implement JWT token issuance (RS256) | Tokens have proper claims: sub, tenant_id, roles, exp | `tests/auth/test_jwt.py` | `AuthService/jwt.py` |
| T1.2.4 | Create JWT validation middleware | All APIs reject unauthenticated requests (401) | `tests/middleware/test_auth.py` | `shared/middleware.py` |
| T1.2.5 | Implement tenant extraction from JWT | Middleware sets `request.state.tenant_id` | `tests/middleware/test_tenant_context.py` | `shared/tenant_context.py` |
| T1.2.6 | RBAC: role-based permission checks | User with role=viewer cannot POST /process_video | `tests/auth/test_rbac.py` | `AuthService/rbac.py` |
| T1.2.7 | API Key generation for programmatic access | `POST /auth/api-keys` generates key, stored hashed | `tests/auth/test_api_keys.py` | |
| T1.2.8 | Integration: All APIs require auth | Main API, Extractor, Embedder all validate JWT | `tests/integration/test_authenticated_flow.py` | patch existing services |
| T1.2.9 | Password reset flow (email) | `POST /auth/password-reset` sends email (mock in test) | `tests/auth/test_password_reset.py` | |
| T1.2.10 | OAuth2 social login (Google, GitHub) optional | `GET /auth/oauth/{provider}` redirects, callback sets JWT | `tests/auth/test_oauth.py` | |

#### Area 1.3: Multi-Tenancy & Data Isolation (P0)
**Dependencies**: T1.2.1-T1.2.4
**Estimated**: 60 hours

| Task | Description | Acceptance Criteria | Tests | Files |
|------|-------------|-------------------|-------|-------|
| T1.3.1 | Create PostgreSQL multi-tenancy schema strategy | Document: schemas per tenant vs. row-level security | Design doc | `docs/design/tenancy.md` |
| T1.3.2 | Implement tenant-aware database connection | `get_tenant_connection(tenant_id)` returns schema-bound conn | `tests/db/test_tenant_isolation.py` | `shared/db.py` |
| T1.3.3 | Update all repositories to filter by tenant_id | No query can leak data across tenants | `tests/repositories/test_isolation.py` | All repository classes |
| T1.3.4 | MinIO tenant-prefixed bucket paths | Frames stored at `{tenant_id}/frames/...` | `tests/storage/test_minio_tenant_prefix.py` | `shared/minio.py` |
| T1.3.5 | Milvus tenant isolation (partition or collection) | Search with tenant filter returns only tenant's videos | `tests/milvus/test_tenant_isolation.py` | `Embedder/milvus_utils.py` |
| T1.3.6 | Redis key namespace per tenant | All keys: `{tenant_id}:extractor:status` | `tests/redis/test_tenant_keys.py` | `shared/redis.py` |
| T1.3.7 | Tenant provisioning automation script | `./scripts/provision-tenant.sh acme` creates all resources | `tests/scripts/test_provisioning.py` | `scripts/provision-tenant.sh` |
| T1.3.8 | Tenant deletion (GDPR Article 17) | `DELETE /tenants/{id}` cascades to all data stores | `tests/tenancy/test_deletion.py` | |

#### Area 1.4: Encryption & Security (P0)
**Dependencies**: T1.3.1-T1.3.4
**Estimated**: 50 hours

| Task | Description | Acceptance Criteria | Tests | Files |
|------|-------------|-------------------|-------|-------|
| T1.4.1 | Set up HashiCorp Vault for secrets management | Vault running, app fetches secrets via K8s External Secrets | `tests/vault/test_integration.py` | `kubernetes/external-secrets/` |
| T1.4.2 | Implement TLS 1.3 everywhere (mTLS for services) | `kubectl get secrets` shows TLS certs, services use HTTPS | `tests/security/test_tls.py` | `kubernetes/ingress/`, cert-manager |
| T1.4.3 | Enable MinIO server-side encryption (SSE-KMS) | Objects stored with `x-amz-server-side-encryption` header | `tests/storage/test_minio_encryption.py` | MinIO Helm values |
| T1.4.4 | PostgreSQL transparent data encryption (TDE) | Database encrypted at rest, verified with pg_stat_file | Manual test | postgresql.conf |
| T1.4.5 | Secrets rotation automation | API can rotate DB password without downtime | `tests/security/test_secrets_rotation.py` | `scripts/rotate-secrets.sh` |
| T1.4.6 | Network Policies: deny-all, allow-by-role | Pods can only talk to required services | `tests/k8s/test_network_policies.py` | `kubernetes/network-policies/` |
| T1.4.7 | Pod Security Standards enforcement | No privileged pods, runAsNonRoot enforced | `tests/k8s/test_pod_security.py` | PSP / Kyverno policies |
| T1.4.8 | Service Mesh (Istio) mTLS installation | All service-to-service traffic encrypted | `tests/istio/test_mtls.py` | |

#### Area 1.5: Audit Logging (P0)
**Dependencies**: T1.2.4, T1.3.1
**Estimated**: 40 hours

| Task | Description | Acceptance Criteria | Tests | Files |
|------|-------------|-------------------|-------|-------|
| T1.5.1 | Design audit log schema | Schema includes: tenant_id, user_id, action, resource, timestamp, outcome | `docs/design/audit-schema.json` | |
| T1.5.2 | Create AuditService (FastAPI) | `POST /audit` accepts log entries, stores immutably | `tests/audit/test_audit_service.py` | `AuditService/` |
| T1.5.3 | Middleware to auto-log all API requests | Every request generates audit entry in DB + Kafka | `tests/middleware/test_audit_middleware.py` | `shared/middleware.py` |
| T1.5.4 | Implement Kafka audit stream | Logs published to `audit-logs` topic | `tests/kafka/test_audit_stream.py` | |
| T1.5.5 | SIEM integration (Splunk/Elastic) | Logstash forwards to SIEM, searchable within 5min | Manual test | logstash config |
| T1.5.6 | Immutable storage (WORM) for audit logs | Cannot delete or modify audit entries even with DB admin | `tests/audit/test_immutability.py` | PostgreSQL policies |
| T1.5.7 | Audit log retention policy (7+ years) | Automated archival to cold storage after 90 days | `tests/audit/test_retention.py` | |

---

### Phase 2: Multi-Sector Analytics (Months 3-4)

#### Area 2.1: Plugin Architecture for Detection Models
**Dependencies**: T1.3.1-T1.3.4
**Estimated**: 60 hours

| Task | Description | Acceptance Criteria | Tests | Files |
|------|-------------|-------------------|-------|-------|
| T2.1.1 | Design plugin interface and discovery | Base class `DetectionPlugin` with `detect(frame) -> list` | `tests/plugins/test_interface.py` | `Embedder/models/plugins/base.py` |
| T2.1.2 | Implement plugin loader (config-based) | Loads plugins based on `tenant.sector` config | `tests/plugins/test_loader.py` | `Embedder/models/plugin_loader.py` |
| T2.1.3 | License Plate Recognition plugin (law_enf) | LPR plugin detects plates with 90%+ accuracy on test set | `tests/plugins/law_enf/test_lpr.py` | `plugins/law_enforcement/lpr.py` |
| T2.1.4 | Weapon Detection plugin (YOLOv8) | Weapon detection with 85%+ accuracy, < 1 FPS overhead | `tests/plugins/law_enf/test_weapon.py` | |
| T2.1.5 | Face blur plugin (GDPR privacy) | All faces blurred with 95% coverage, preserves utility | `tests/plugins/law_enf/test_blur.py` | |
| T2.1.6 | Demographics plugin (commercial) | Age/gender estimation within 5 years / binary accuracy 88% | `tests/plugins/commercial/test_demographics.py` | `plugins/commercial/demographics.py` |
| T2.1.7 | Heatmap and queue detection (commercial) | Generates heatmap data from 1 hour of footage | `tests/plugins/commercial/test_heatmap.py` | |
| T2.1.8 | PPE detection plugin (logistics) | Hard hat/vest detection 92%+ accuracy | `tests/plugins/logistics/test_ppe.py` | `plugins/logistics/ppe.py` |
| T2.1.9 | Plugin configuration API (tenant admin) | `PUT /tenants/{id}/plugins` enables/disables plugins | `tests/api/test_plugin_config.py` | `API endpoints` |
| T2.1.10 | Performance benchmarking suite | Measure FPS overhead per plugin, stay < 10% | `tests/performance/test_plugin_overhead.py` | |

---

### Phase 3: Subscription & Billing (Months 5-6)

#### Area 3.1: Tenant Management Portal
...

---

## Total Estimated Hours: ~1,200 hours (60 weeks @ 20h/week)

---

## Tracking Commands

```bash
# List all tasks with status
python scripts/tracking.py list --phase 1

# Show task details
python scripts/tracking.py show T1.2.3

# Start work
python scripts/tracking.py start T1.2.3

# Complete task (commits with proper message)
python scripts/tracking.py complete T1.2.3

# Block task (dependency not met)
python scripts/tracking.py block T1.3.2 --waiting-on T1.2.5

# Generate progress report
python scripts/tracking.py report --output progress.md

# Generate burndown chart
python scripts/tracking.py burndown --weeks 24
```

---

## Git Workflow Integration

```bash
git checkout -b feat/T1.2.3-jwt-middleware
# Work on task
pytest tests/auth/test_jwt_middleware.py -v  # Red (fails)
# Write code
pytest tests/auth/test_jwt_middleware.py -v  # Green (passes)
git add .
git commit -m "$(scripts/tracking.py commit-msg T1.2.3)"
# Commit msg: "feat(auth): add JWT middleware with tenant extraction

# - Extract tenant_id from JWT claims
# - Set request state for downstream middleware
# - Add test coverage for missing/invalid tokens

# Task: T1.2.3
# Tests: tests/auth/test_jwt_middleware.py
# Time: 3h 15m"
```

---

## Recovery After Failure

**Scenario**: You're on T2.1.4, everything breaks, need to restart

```bash
# 1. Find last green commit
git log --oneline --grep="✅"
# Output: abc123 feat(plugins): weapon detection YOLOv8 integration (T2.1.4) [green]

# 2. Reset to that point
git reset --hard abc123

# 3. Check task status
python scripts/tracking.py status T2.1.4
# Status: "in_progress", tests: 8/10 passing

# 4. Rerun tests to see current state
pytest tests/plugins/law_enf/test_weapon.py::test_yolov8_loading -v
# Shows exactly which tests fail, no need to redo previous work

# 5. Fix only the failing tests, don't rewrite working code
```

**Never lose work**: Each task commit is atomic and recoverable.

---

## Test-Driven Development Rules

1. **RED → GREEN → REFACTOR**
   - Write failing test FIRST (red)
   - Write minimal code to pass (green)
   - Refactor (improve code, keep tests green)

2. **One test per commit**
   - Commit after each passing test
   - Small commits = easy rollback

3. **Tests must be deterministic**
   - No `time.sleep(10)` without mocking
   - Mock external services (MinIO, Milvus, Stripe)
   - Use fixtures for test data

4. **Coverage requirement**
   - Minimum 80% line coverage for new code
   - Enforced by CI (`pytest --cov --cov-fail-under=80`)

5. **Integration tests separate from unit tests**
   - `tests/unit/` - Fast, no external dependencies
   - `tests/integration/` - Uses test containers (Postgres, Redis)
   - `tests/e2e/` - Full stack, runs nightly only

6. **No code without test**
   - Code review checklist: "Are there tests?"
   - Merges blocked by CI if coverage drops

---

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
      milvus-standalone:
        image: milvusdb/milvus:v2.4.4
        ports: ['19530:19530']

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-cov pytest-xdist

    - name: Run unit tests
      run: |
        pytest tests/unit/ -v --cov=src --cov-report=xml --cov-fail-under=80

    - name: Run integration tests
      run: |
        pytest tests/integration/ -v --cov=src --cov-append
      env:
        DATABASE_URL: postgresql://postgres:test@localhost:5432/postgres
        REDIS_URL: redis://localhost:6379
        MILVUS_HOST: localhost

    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3

    - name: Check manifest validity
      run: |
        kubeval k8s/base/**/*.yaml
        kube-score score k8s/base/

  gitops-validate:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Validate ArgoCD apps
      run: |
        # Check that all ArgoCD apps point to valid clusters
        ./scripts/validate-argocd-apps.sh
```

---

## Burndown Tracking

```bash
# Generate weekly burndown report
python scripts/tracking.py burndown --weeks 12 --output burndown.png

# Shows:
# - Completed tasks per week (actual vs planned)
# - Remaining hours by phase
# - Velocity trend
# - Projected completion date
```

---

## Blockers & Dependencies

When a task is blocked:

```bash
python scripts/tracking.py block T1.3.2 --waiting-on T1.2.5 --reason "AuthService not ready"
```

This:
- Marks T1.3.2 as `blocked`
- Creates dependency edge in `DEPS.md`
- Notifies if T1.2.5 overdue
- Prevents starting blocked task

---

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `tracking.py` | Main task tracking (start, complete, block, list) |
| `commit-msg` | Generate conventional commit message |
| `provision-tenant.sh` | Automate tenant provisioning |
| `validate-argocd-apps.sh` | Check GitOps configuration |
| `backup.sh` | Database + Milvus backup |
| `restore.sh` | Restore from backup |
| `rotate-secrets.sh` | Secret rotation automation |
| `load-test.sh` | Run Locust load tests |

---

## File Structure

```
repo/
├── TASKS.md                      # This file (master task list)
├── DEPS.md                       # Dependency graph (auto-generated)
├── scripts/
│   ├── tracking.py              # Task lifecycle management
│   ├── commit-msg               # Git commit hook
│   └── ...
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── k8s/
│   ├── base/
│   ├── overlays/
│   └── apps/
├── helm/
├── docs/
│   ├── design/
│   └── compliance/
├── .task_state/                  # Auto-generated tracking state
│   ├── current_task
│   ├── tasks/
│   │   ├── T1.1.1.json
│   │   ├── T1.1.2.json
│   │   └── ...
│   └── history.log
└── .github/
    └── workflows/
        └── ci.yml
```

---

## Integration with Project Management

Jira/GitHub Issues can map to tasks:

- Epic → Phase (e.g., EPIC-123 "Multi-tenancy" → Phase 1)
- Story → Area (e.g., STORY-456 "As a tenant, I want data isolation" → Area 1.3)
- Task → Task ID (e.g., T1.3.2)

Commit messages reference task ID:
```
feat(tenancy): implement Milvus tenant isolation

- Create collection per tenant with partition key
- Add middleware to inject tenant_id into Milvus queries
- Add integration tests verifying cross-tenant isolation

Task: T1.3.2
Tests: tests/milvus/test_tenant_isolation.py
Refs: STORY-456, EPIC-123
```

---

## Success Metrics

- **No task without test**: 100% of tasks have associated test file(s)
- **Test before code**: Git hooks enforce tests added before code changes
- **Green master**: `main` branch always passing CI
- **Atomic rollback**: Any task can be reverted without affecting others
- **Zero rework**: Work never lost due to poor tracking

---

## Getting Started

1. Setup tracking system:
   ```bash
   python scripts/tracking.py init
   # Creates .task_state/ directory with empty database
   ```

2. Pick first task from Phase 1, Area 1.1:
   ```bash
   python scripts/tracking.py start T1.1.1
   ```

3. Work through RED → GREEN → COMMIT cycle

4. Mark complete, move to next

---

**Never redo work. Always recoverable. Always tested.**

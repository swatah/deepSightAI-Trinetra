# Quick Start: Enterprise Development with TDD

This guide gets you from zero to first commit in 10 minutes.

---

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Git
- Ubuntu 22.04 / macOS / WSL2

---

## 5-Minute Setup

```bash
# 1. Clone and setup (done)
cd /path/to/clipsight

# 2. Initialize task tracking
python scripts/tracking.py init
# ✓ Loaded 58 tasks from DEVELOPMENT_TRACKING.md

# 3. Install git hooks
./scripts/install-hooks.sh
# ✓ Git hooks installed

# 4. Verify installation
python scripts/tracking.py list
# Should show all tasks with status 'pending'
```

---

## Your First Task (T1.1.1)

### Step 1: Start task

```bash
python scripts/tracking.py start T1.1.1
```

Output:
```
✓ Started task T1.1.1: Convert Docker Compose services to K8s manifests
  Tests: `tests/k8s/test_manifests.py`
  Files: `k8s/base/`

  Run: pytest tests/k8s/test_manifests.py (should FAIL - red phase)
```

### Step 2: RED - Write failing test

Check if test exists (it should from templates):
```bash
cat tests/k8s/test_manifests.py
```

If not, create it:
```python
# tests/k8s/test_manifests.py
import pytest
import yaml
from pathlib import Path

def test_manifests_exist():
    """T1.1.1: Verify K8s base manifests are created."""
    base_dir = Path("k8s/base")
    required_files = ["deployments.yaml", "services.yaml", "configmap.yaml"]

    for f in required_files:
        assert (base_dir / f).exists(), f"Missing {f}"
```

Run it (should fail):
```bash
pytest tests/k8s/test_manifests.py -v
# FAILED because k8s/base/ doesn't exist yet
```

### Step 3: GREEN - Write minimal code

Create `k8s/base/` and minimal files:
```bash
mkdir -p k8s/base
cat > k8s/base/deployments.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: main-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: main-api
  template:
    metadata:
      labels:
        app: main-api
    spec:
      containers:
      - name: main-api
        image: clipsight/main-api:latest
        ports:
        - containerPort: 8080
EOF

cat > k8s/base/services.yaml << 'EOF'
apiVersion: v1
kind: Service
metadata:
  name: main-api
spec:
  selector:
    app: main-api
  ports:
  - port: 8080
    targetPort: 8080
EOF
```

Run test (should pass):
```bash
pytest tests/k8s/test_manifests.py -v
# PASSED ✅
```

### Step 4: Complete task

```bash
python scripts/tracking.py complete T1.1.1
```

Output:
```
✓ Task T1.1.1 completed (0h 45m)

Suggested commit message:
feat(k8s): convert main-api to K8s deployment and service

- Task: T1.1.1
- Tests: tests/k8s/test_manifests.py
- Time: 0.75h
```

Commit it:
```bash
git add k8s/base/ tests/k8s/test_manifests.py
git commit -m "$(python scripts/tracking.py commit-msg T1.1.1)"
git push  # if branch tracking
```

**Done**. You just completed your first enterprise task following TDD.

---

## Continue to Next Task

```bash
python scripts/tracking.py start T1.1.2
# Work on next task...
```

---

## Common Issues & Solutions

### "Task T1.1.3 depends on T1.1.1 which is not completed"

**Fix**: Complete tasks in order. Don't skip dependencies.

### "Git commit hook failed: missing Task reference"

**Fix**: Your commit message must include `Task: T1.1.1`. Use:
```bash
git commit -m "$(python scripts/tracking.py commit-msg T1.1.1)"
```

### "Tests failing in pre-commit hook"

**Fix**: Don't commit broken code. Run `pytest` first, fix failures, then commit.

### "No .task_state/tasks.json"

**Fix**: Run `python scripts/tracking.py init`

---

## Command Cheat Sheet

| Command | Purpose |
|---------|---------|
| `python scripts/tracking.py list` | Show all tasks |
| `python scripts/tracking.py start T1.1.1` | Start working |
| `pytest tests/path/to/test.py -v` | Run tests (red → green) |
| `python scripts/tracking.py complete T1.1.1` | Finish & commit |
| `git commit -m "$(python scripts/tracking.py commit-msg T1.1.1)"` | Proper commit |
| `python scripts/tracking.py show T1.1.1` | See task details |
| `python scripts/tracking.py report` | Progress report |

---

## What's Next?

1. **Read** `SUMMARY.md` for full context
2. **Read** `DEVELOPMENT_TRACKING.md` for detailed TDD methodology
3. **Read** `ENTERPRISE_ROADMAP.md` to understand the 12-month vision
4. **Read** `DEPLOYMENT.md` for infrastructure patterns
5. **Start task T1.1.1** and begin implementation

---

## Need Help?

```bash
# List all tasks
python scripts/tracking.py list

# Generate burndown chart
python scripts/tracking.py burndown

# Show current work
python scripts/tracking.py show $(cat .current_task 2>/dev/null || echo "No current task")
```

---

**Never redo work. Every task tracked. Every commit recoverable.**

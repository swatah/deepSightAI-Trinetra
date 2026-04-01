# ClipSight Enterprise - Complete Documentation Index

**Quick Navigation**: Start with `SUMMARY.md` for comprehensive overview, or `DEVELOPMENT_QUICKSTART.md` to begin coding.

---

## Core Documentation (Read First)

| Document | Purpose | When to Read |
|----------|---------|--------------|
| **`SUMMARY.md`** | ⭐ **MAIN HUB** - Links everything together, quick reference | **START HERE** - read first |
| `DEVELOPMENT_QUICKSTART.md` | Step-by-step first task walkthrough | When ready to code |
| `ARCHITECTURE.md` | Current Docker Compose architecture design | Understanding existing system |
| `ENTERPRISE_ROADMAP.md` | 12-month plan with phases, features, compliance | Planning, stakeholder updates |
| `DEPLOYMENT.md` | **USE THIS** - Vendor-neutral deployment guide | ✅ |
| `DEPLOYMENT.md` | ✅ **ACTUAL GUIDE** - Cloud-agnostic K8s deployment | **Read for deployment** |
| `DEVELOPMENT_TRACKING.md` | TDD methodology, task tracking, recovery | **Read before coding** |
| `README.md` | Original project README (outdated) | Historical context only |

---

## Documentation Map

```
ClipSight Documentation
├── Getting Started
│   ├── SUMMARY.md ⭐ (main hub)
│   ├── DEVELOPMENT_QUICKSTART.md (first steps)
│   └── README.md (outdated, ignore)
│
├── Architecture & Design
│   ├── ARCHITECTURE.md (current Docker Compose)
│   ├── ENTERPRISE_ROADMAP.md (12-month vision)
│   └── DEPLOYMENT.md (K8s patterns)
│
├── Development Process
│   ├── DEVELOPMENT_TRACKING.md (TDD methodology)
│   └── .github/workflows/ci.yml (CI/CD enforcing TDD)
│
├── Implementation
│   ├── scripts/
│   │   ├── tracking.py (task management)
│   │   ├── install-hooks.sh (git hooks installer)
│   │   └── ...
│   ├── tests/
│   │   ├── unit/example_test.py
│   │   ├── integration/test_video_processing_flow.py
│   │   └── e2e/, perf/, security/
│   └── pyproject.toml (pytest & coverage config)
│
└── Deployment
    └── DEPLOYMENT.md (complete)
        └── Covers:
            - Docker Compose (current)
            - k3s (edge/on-premise)
            - Full K8s (enterprise cloud)
            - GitOps with ArgoCD
            - Security hardening
            - Monitoring, backup, DR, scaling
```

---

## What to Read When...

### "I want to understand ClipSight"
**→ Read**: `ARCHITECTURE.md` (30 min)

### "I want to contribute code"
**→ Read**: `DEVELOPMENT_QUICKSTART.md` → `DEVELOPMENT_TRACKING.md` (1 hour)

### "I want to deploy to production"
**→ Read**: `DEPLOYMENT.md` (2 hours)
- Skip "Cloud-Native (AWS Example)" - that's deprecated
- Focus on "Vendor-Neutral Kubernetes" sections

### "I'm a project manager tracking progress"
**→ Read**: `SUMMARY.md` → ENTERPRISE_ROADMAP.md Executive Summary

### "I'm an architect evaluating technical approach"
**→ Read**: `ARCHITECTURE.md` → `DEPLOYMENT.md` → `ENTERPRISE_ROADMAP.md`

### "I'm an engineer ready to start coding"
**→ Read**: `DEVELOPMENT_QUICKSTART.md` → run through first task

---

## Key Files to Edit

| File | Purpose | When to Edit |
|------|---------|--------------|
| `k8s/base/*.yaml` | K8s manifests | Phase 1, T1.1.1-T1.1.6 |
| `helm/` | Helm charts (optional) | When packaging services |
| `argocd-apps/*.yaml` | GitOps config | Phase 1, T1.1.4 |
| `src/` | Application code | All implementation tasks |
| `tests/unit/` | Unit tests | Every task (TDD) |
| `tests/integration/` | Integration tests | Phase 1+, critical paths |
| `.env.example` | Environment template | Local development |
| `scripts/` | Automation scripts | Various utility tasks |
| `docs/design/` | Design documents | Architecture decisions |

---

## Deprecated / Outdated Documents

| Document | Why Deprecated | Use Instead |
|----------|----------------|-------------|
| `DEPLOYMENT.md` | Vendor-neutral deployment (cloud, on-prem, edge) | - |
| Original `README.md` | Only covers Docker Compose, no enterprise | SUMMARY.md |

**Use** `DEPLOYMENT.md` for all deployment scenarios.

---

## Progress Tracking

Check current development status:

```bash
# Overall progress
python scripts/tracking.py report

# Tasks by phase
python scripts/tracking.py list --phase=1  # Foundation tasks
python scripts/tracking.py list --status=in_progress
python scripts/tracking.py list --status=blocked

# Burndown
python scripts/tracking.py burndown --weeks 24

# Task detail
python scripts/tracking.py show T1.2.3
```

---

## Git Workflow

```bash
# 1. Pick task from DEVELOPMENT_TRACKING.md
python scripts/tracking.py start T1.2.3

# 2. Work RED → GREEN → REFACTOR
pytest tests/unit/auth/test_jwt.py -v  # Red (fails)
# Write code
pytest tests/unit/auth/test_jwt.py -v  # Green (passes)
# Refactor

# 3. Complete
python scripts/tracking.py complete T1.2.3
# Auto-generates proper commit message

# 4. Commit
git add .
git commit -m "$(python scripts/tracking.py commit-msg T1.2.3)"
git push
```

**Commit message format**:
```
feat(auth): add JWT middleware with tenant extraction

- Task: T1.2.3
- Tests: tests/unit/auth/test_jwt_middleware.py
- Time: 2.5h
```

---

## CI/CD Status Badges

Once CI is set up, add to README:

```
- **Tests**: [![CI](https://github.com/yourorg/clipsight/actions/workflows/ci.yml/badge.svg)](...)
- **Coverage**: [![codecov](https://codecov.io/gh/yourorg/clipsight/branch/main/graph/badge.svg)](...)
```

---

## Support & Questions

1. **Internal wiki**: [Confluence link to ClipSight space]
2. **Slack**: #clipsight-dev, #clipsight-ops
3. **Jira**: Project `CS` (ClipSight)
4. **Design docs**: `docs/design/` directory (create as needed)
5. **Architecture decisions**: One `adr-*.md` file per major decision

---

## Updating Documentation

Documentation is **code**. All docs in Git, reviewed in PRs.

When you:
- Change architecture → Update `ARCHITECTURE.md`
- Add new feature → Update `ENTERPRISE_ROADMAP.md` checklist
- Fix deployment process → Update `DEPLOYMENT.md`
- Learn something new → Add to `docs/lessons-learned.md`

**Documentation updates are part of Definition of Done.**

---

## File Size & Structure Stats

```
Total docs:     8 markdown files (~200 KB total)
Tracking DB:    ~20 KB JSON
Test dirs:      5 (unit, integration, e2e, perf, security)
Infrastructure: k8s/ (to be created), helm/ (to be created)
Scripts:        4 utilities (tracking, install-hooks, etc.)
CI/CD:          GitHub Actions workflow
```

---

## Quick Links

- [Summary](SUMMARY.md) - Main overview
- [Quick Start](DEVELOPMENT_QUICKSTART.md) - First 10 minutes
- [Tracking](DEVELOPMENT_TRACKING.md) - Work management
- [Vendor-Neutral Deploy](DEPLOYMENT.md) - Infrastructure
- [Enterprise Roadmap](ENTERPRISE_ROADMAP.md) - 12-month plan
- [Architecture](ARCHITECTURE.md) - System design

---

**Last Updated**: 2025-04-01
**Maintained By**: Platform Engineering Team
**Version**: 0.1.0 - Initial enterprise transformation

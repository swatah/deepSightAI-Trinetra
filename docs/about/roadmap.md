# Product Roadmap

ClipSight is under active development. This document outlines our planned features and releases.

**For the detailed enterprise roadmap with phases, milestones, and timelines, see the main project document:**

[ENTERPRISE_ROADMAP.md](../../ENTERPRISE_ROADMAP.md)

---

## Quick Overview

### Completed (Phase 1: Foundation)

- ✅ Kubernetes-native architecture (Helm charts, Kustomize overlays)
- ✅ Multi-tenancy with data isolation (PostgreSQL, MinIO, Milvus)
- ✅ Authentication & Authorization (JWT, RBAC, API keys)
- ✅ Encryption (TLS 1.3, mTLS, SSE-KMS, TDE)
- ✅ Audit logging with WORM storage (7+ year retention)
- ✅ SIEM integration (Kafka to Splunk/Elastic)

### In Progress (Phase 2: Multi-Sector Analytics)

- 🔄 Plugin architecture for sector-specific detection models
- 🔄 Law enforcement plugins (License Plate Recognition, Weapon Detection, Face Blur)
- 🔄 Commercial plugins (Demographics, Heatmap, Queue detection)
- 🔄 Logistics plugins (PPE detection)

### Upcoming (Phase 3: Operations & Developer Experience)

- 📋 Comprehensive monitoring stack (Prometheus, Grafana, Loki)
- 📋 Automated backup & disaster recovery
- 📋 Advanced search filters (date ranges, metadata, exclusions)
- 📋 Real-time streaming from RTSP cameras
- 📋 Performance optimization (GPU scheduling, load balancing)

### Future (Phase 4: Subscription & Billing)

- 📋 Tenant management portal
- 📋 Usage-based billing and invoicing
- 📋 Stripe/PayPal integration
- 📋 Quota management and alerts

---

## Release Cadence

We follow a **quarterly release cycle**:

- **Q2 2025**: Phase 1 complete (v1.0 GA) - Foundation features
- **Q3 2025**: Phase 2 features (v1.1-v1.3) - Plugin system + sector models
- **Q4 2025**: Phase 3 features (v1.4-v1.6) - Operations maturity
- **Q1 2026**: Phase 4 features (v2.0) - Billing and self-service

Each release includes:
- New features
- Bug fixes and security patches
- Performance improvements
- Documentation updates

---

## Community Requests

We prioritize development based on user feedback. To request a feature:

1. Check existing [GitHub Issues](https://github.com/yourorg/clipsight/issues) to avoid duplicates
2. Create a new issue with:
   - Clear description of the problem/use case
   - Proposed solution (optional)
   - Impact on other users
3. Upvote existing issues you'd like to see prioritized

**Popular requested features** (under consideration):
- [ ] Webhook notifications for video processing completion
- [ ] Batch search across multiple videos
- [ ] User interface themes (dark mode)
- [ ] Mobile app
- [ ] Advanced analytics dashboard (usage statistics)
- [ ] Export search results to CSV/PDF
- [ ] Integration with video management systems (VMS)

---

## Versioning Policy

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (v2.0, v3.0): Incompatible API changes
- **MINOR** (v1.1, v1.2): New features in backward-compatible manner
- **PATCH** (v1.1.1, v1.1.2): Backward-compatible bug fixes

Breaking changes will be announced with migration guides.

---

## Staying Updated

- **GitHub Releases**: Watch the repository for release announcements
- **Changelog**: Each release includes detailed [CHANGELOG.md](../operations/changelog.md)
- **Documentation**: This site is versioned; use the selector to view docs for specific releases
- **Beta Program**: Join our beta program for early access to new features (sign up at our website)

---

## Feedback

Have questions or suggestions about the roadmap? 

- Join our [Community Slack](https://clipsight-community.slack.com)
- Start a [GitHub Discussion](https://github.com/yourorg/clipsight/discussions)
- Email: **roadmap@clipsight.com**

We appreciate your input as we build the future of video content search!

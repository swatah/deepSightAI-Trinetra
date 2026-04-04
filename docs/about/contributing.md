# Contributing to deepSightAI Trinetra

Thank you for your interest in contributing! deepSightAI Trinetra is an open-source project (AGPL v3) and we welcome contributions from the community.

---

## Ways to Contribute

### 🐛 Report Bugs

If you find a bug, please create an issue on GitHub with:

- Clear description of the bug and steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Docker/K8s version, deepSightAI Trinetra version)
- Logs/screenshots if applicable

### 💡 Suggest Features

We love new ideas! Before submitting a feature request:

1. Check if it's already been requested (search existing issues)
2. Consider if it fits the project scope (video content search platform)
3. Describe the problem you're solving and who it helps
4. Propose a solution if you have one

### 🔧 Submit Code

Contributions via pull requests are greatly appreciated.

#### Development Workflow

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/deepSightAI-Trinetra.git
   cd deepSightAI-Trinetra
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feat/your-feature-name
   ```
4. **Set up development environment**:
   - Install Docker and Docker Compose (or minikube/k3d for K8s work)
   - Copy `.env.example` to `.env` and adjust as needed
   - Run `docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d`
   - Run `docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d`
5. **Make your changes** following our coding standards (see below)
6. **Write tests** for your changes (we use pytest)
7. **Run tests locally**:
   ```bash
   pytest tests/
   ```
8. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat(component): description of change

   - Task: T1.2.3  # if applicable, reference tracking task
   - Tests: tests/path/to/test_file.py"
   ```
   - Use [Conventional Commits](https://www.conventionalcommits.org/) format
   - Reference any relevant task IDs from DEVELOPMENT_TRACKING.md
9. **Push to your fork**:
   ```bash
   git push origin feat/your-feature-name
   ```
10. **Open a Pull Request** against our `main` branch

#### Pull Request Guidelines

- **One PR per feature** - don't mix unrelated changes
- **Keep it small** - < 500 lines of code is easier to review
- **Include tests** - new code should have test coverage ≥80%
- **Update documentation** if you change user-facing behavior
- **Squash commits** before merging (use `git rebase -i`)
- **Wait for CI** - all checks must pass
- **Address review feedback** - respond to code review comments

---

## Code Standards

### Python

- Follow [PEP 8](https://pep8.org/) style guide
- Use `black` for code formatting (line length 100)
- Use `isort` for import sorting
- Type hints required for all function signatures (use `mypy`)
- Docstrings required for public APIs (Google style):
  ```python
  def process_video(video_uri: str, tenant_id: str) -> dict:
      """Process a video file and generate embeddings.

      Args:
          video_uri: S3 URI of the video file
          tenant_id: Tenant identifier for multi-tenancy

      Returns:
          dict: Processing job metadata with video_id and status
      """
  ```

### Tests

- Use pytest fixtures for test data
- Unit tests in `tests/unit/` (fast, isolated)
- Integration tests in `tests/integration/` (with real services)
- E2E tests in `tests/e2e/` (full stack, run nightly)
- Mock external dependencies (don't hit real APIs in unit tests)
- Aim for ≥80% code coverage on new code

### Docker

- Use official base images (python:3.11-slim, etc.)
- Multi-stage builds to minimize image size
- Non-root user (`deepSightAI-Trinetra`) for security
- Explicit `USER` directive before running app
- Health checks for all containers

### Kubernetes

- Use Kustomize overlays for environment-specific changes
- Set resource limits/requests on all pods
- Configure liveness and readiness probes
- Use ConfigMaps and Secrets (not env vars in manifests)
- Follow 12-factor app principles

---

## Project Structure

```
deepSightAI-Trinetra/
├── AuthService/          # Authentication microservice
├── AuditService/         # Audit log service
├── Embedder/             # Vector embedding service
├── Server and Extractor/ # Main API + video extraction
├── shared/               # Shared libraries (middleware, db, etc.)
├── k8s/                  # Kubernetes manifests (base + overlays)
├── helm/                 # Helm charts
├── tests/                # Test suite
├── docs/                 # Documentation (MkDocs)
├── scripts/              # Utility scripts (tracking, etc.)
└── .github/              # GitHub Actions workflows
```

---

## Development Tools

We provide several scripts to assist development:

```bash
# Task tracking (start, complete, block tasks)
python scripts/tracking.py start T1.2.3
python scripts/tracking.py complete T1.2.3

# Run specific test categories
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/ -m "not slow" -v

# Build and run locally with Docker Compose
docker-compose -f "Server and Extractor/docker-compose.extractor.yml" up -d
docker-compose -f "Embedder/docker-compose.embedder.yaml" up -d

# Build documentation
mkdocs serve  # Live preview at http://localhost:8000
mkdocs build  # Generate static site in site/
```

---

## Getting Help

- **Documentation**: Read the [docs](../../) first!
- **Discussions**: [GitHub Discussions](https://github.com/yourorg/deepSightAI-Trinetra/discussions) for questions
- **Chat**: [Community Slack](https://deepSightAI-Trinetra-community.slack.com)
- **Issues**: [GitHub Issues](https://github.com/yourorg/deepSightAI-Trinetra/issues) for bugs
- **Real-time**: `#development` channel on Slack

---

## Code of Conduct

We are committed to fostering a welcoming and inclusive community. By participating, you agree to abide by our [Code of Conduct](code-of-conduct.md).

- Be respectful and kind
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Accept responsibility and apologize for mistakes

Harassment or abusive behavior will not be tolerated.

---

## License

By contributing, you agree that your contributions will be licensed under the **GNU Affero General Public License v3.0 (AGPL v3)**.

See [LICENSE](../LICENSE) for details.

---

## Recognition

Contributors are recognized in:
- [README.md](../README.md) contributors section
- Release notes for each version
- Annual contributor report (published on our blog)

We thank all our amazing contributors! ❤️

---

## Questions?

Can't find what you're looking for? Reach out on Slack or start a GitHub Discussion.

Happy contributing! 🚀

"""
T1.3.3: Update all repositories to filter by tenant_id

Tests that all repository classes use tenant-aware database connections
and enforce data isolation between tenants.
"""

import pytest
import os
from typing import List, Type
from sqlalchemy import create_engine, text


def discover_repository_classes() -> List[type]:
    """Discover all Repository classes in shared.repositories."""
    try:
        import shared.repositories
        import inspect
        members = inspect.getmembers(shared.repositories, inspect.isclass)
        repos = [cls for name, cls in members if name.endswith("Repository")]
        return repos
    except ImportError:
        return []


class TestRepositoryDesign:
    """Design checks for tenant-aware repositories."""

    def test_at_least_one_repository_exists(self):
        """Should have at least one repository class."""
        repos = discover_repository_classes()
        assert len(repos) > 0, "No repository classes found in shared.repositories"

    def test_repositories_require_tenant_id(self):
        """All repositories should accept tenant_id in __init__."""
        repos = discover_repository_classes()
        import inspect
        for repo_cls in repos:
            sig = inspect.signature(repo_cls.__init__)
            params = list(sig.parameters.keys())
            assert 'tenant_id' in params, \
                f"{repo_cls.__name__} must accept tenant_id parameter"

    def test_repositories_inherit_from_base_repository(self):
        """All repositories should inherit from BaseRepository."""
        from shared.repositories.base import BaseRepository
        repos = discover_repository_classes()
        for repo_cls in repos:
            assert issubclass(repo_cls, BaseRepository), \
                f"{repo_cls.__name__} should inherit from BaseRepository"


@pytest.mark.integration
class TestRepositoryDataIsolation:
    """Integration tests: verify repositories enforce tenant isolation."""

    @pytest.fixture(scope="function")
    def tenant_db_url(self):
        """Setup: create tenant schemas with videos table."""
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:test@postgres-test:5432/deepSightAI-Trinetra_test"
        )
        engine = create_engine(database_url)

        # Create schemas and tables
        with engine.begin() as conn:
            for schema in ["tenant_alpha", "tenant_beta"]:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                conn.execute(text(f"CREATE SCHEMA {schema}"))
                # Create videos table in this schema
                conn.execute(text(f"""
                    CREATE TABLE {schema}.videos (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(255) NOT NULL,
                        duration INTEGER NOT NULL,
                        source_type VARCHAR(50) NOT NULL,
                        source_path VARCHAR NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        processed_at TIMESTAMP
                    )
                """))

        yield database_url

        # Teardown
        with engine.begin() as conn:
            for schema in ["tenant_alpha", "tenant_beta"]:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()

    def test_video_repository_uses_tenant_session(self, tenant_db_url):
        """VideoRepository should use tenant-scoped session."""
        import os
        os.environ["DATABASE_URL"] = tenant_db_url

        from shared.repositories.video_repository import VideoRepository
        from shared.db import clear_engine_pool

        clear_engine_pool()

        repo = VideoRepository(tenant_id="tenant-alpha")
        # Should have a Session factory
        assert hasattr(repo, 'Session')
        # Should have tenant_id stored
        assert repo.tenant_id == "tenant-alpha"

        clear_engine_pool()

    def test_video_repository_data_isolation(self, tenant_db_url):
        """Videos created in one tenant should not be visible in another."""
        import os
        os.environ["DATABASE_URL"] = tenant_db_url

        from shared.repositories.video_repository import VideoRepository
        from shared.db import clear_engine_pool

        clear_engine_pool()

        # Create videos in tenant-alpha
        repo_alpha = VideoRepository(tenant_id="tenant-alpha")
        video1 = repo_alpha.create(
            title="Alpha Video 1",
            duration=120,
            source_type="upload",
            source_path="videos/alpha1.mp4"
        )
        video2 = repo_alpha.create(
            title="Alpha Video 2",
            duration=90,
            source_type="upload",
            source_path="videos/alpha2.mp4"
        )
        assert video1.id is not None
        assert video2.id is not None

        # Query from tenant-beta should return empty
        repo_beta = VideoRepository(tenant_id="tenant-beta")
        beta_videos = repo_beta.list_all()
        assert len(beta_videos) == 0, "Tenant-beta should see no videos from alpha"

        # Alpha should see its own videos
        alpha_videos = repo_alpha.list_all()
        assert len(alpha_videos) == 2
        titles = {v.title for v in alpha_videos}
        assert titles == {"Alpha Video 1", "Alpha Video 2"}

        clear_engine_pool()

    def test_repository_operations_are_scoped(self, tenant_db_url):
        """Operations on repository affect only its own tenant."""
        import os
        os.environ["DATABASE_URL"] = tenant_db_url

        from shared.repositories.video_repository import VideoRepository
        from shared.db import clear_engine_pool

        clear_engine_pool()

        # Create in alpha
        repo_alpha = VideoRepository(tenant_id="tenant-alpha")
        video = repo_alpha.create(title="Alpha Only", duration=100, source_type="upload", source_path="path")

        # Retrieve from alpha
        fetched = repo_alpha.get(video.id)
        assert fetched is not None
        assert fetched.title == "Alpha Only"

        # Delete from alpha
        repo_alpha.delete(fetched)

        # Verify gone from alpha
        assert repo_alpha.get(video.id) is None

        # Verify never existed in beta
        repo_beta = VideoRepository(tenant_id="tenant-beta")
        assert repo_beta.get(video.id) is None

        clear_engine_pool()

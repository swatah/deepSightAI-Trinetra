"""
Pytest configuration for tests under deepSightAI.Trinetra.
Suppresses known benign warnings and registers deepSightAI package aliases.
"""

import warnings
import sys
import importlib
from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import ModuleSpec

# Suppress DeprecationWarning from Python's crypt module (imported by passlib)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="crypt")

# Suppress DeprecationWarning from argon2.cffi about __version__ access
warnings.filterwarnings("ignore", category=DeprecationWarning, message="Accessing argon2.__version__")


class _DeepSightAliasLoader(Loader):
    def __init__(self, target):
        self.target = target

    def create_module(self, spec):
        mod = importlib.import_module(self.target)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass


class _DeepSightAliasFinder(MetaPathFinder):
    MAP = {
        "shared.streaming.consumer": "deepSightAI.Trinetra.Shared.Streaming.Consumer",
        "Shared.streaming.consumer": "deepSightAI.Trinetra.Shared.Streaming.Consumer",
        "shared.streaming.producer": "deepSightAI.Trinetra.Shared.Streaming.Producer",
        "Shared.streaming.producer": "deepSightAI.Trinetra.Shared.Streaming.Producer",
        "shared.streaming.schema": "deepSightAI.Trinetra.Shared.Streaming.Schema",
        "Shared.streaming.schema": "deepSightAI.Trinetra.Shared.Streaming.Schema",
        "shared.streaming.replay": "deepSightAI.Trinetra.Shared.Streaming.Replay",
        "Shared.streaming.replay": "deepSightAI.Trinetra.Shared.Streaming.Replay",
        "shared.streaming.redis_client": "deepSightAI.Trinetra.Shared.Streaming.RedisClient",
        "Shared.streaming.redis_client": "deepSightAI.Trinetra.Shared.Streaming.RedisClient",
        "shared.streaming": "deepSightAI.Trinetra.Shared.Streaming",
        "Shared.streaming": "deepSightAI.Trinetra.Shared.Streaming",
        "shared.milvus": "deepSightAI.Trinetra.Shared.Milvus",
        "Shared.milvus": "deepSightAI.Trinetra.Shared.Milvus",
        "deepSightAI.Trinetra.Shared.milvus": "deepSightAI.Trinetra.Shared.Milvus",
        "shared.middleware": "deepSightAI.Trinetra.Shared.Middleware",
        "Shared.middleware": "deepSightAI.Trinetra.Shared.Middleware",
        "deepSightAI.Trinetra.Shared.middleware": "deepSightAI.Trinetra.Shared.Middleware",
        "shared.config": "deepSightAI.Trinetra.Shared.Config",
        "Shared.config": "deepSightAI.Trinetra.Shared.Config",
        "deepSightAI.Trinetra.Shared.config": "deepSightAI.Trinetra.Shared.Config",
        "shared.storage": "deepSightAI.Trinetra.Shared.Storage",
        "Shared.storage": "deepSightAI.Trinetra.Shared.Storage",
        "deepSightAI.Trinetra.Shared.storage": "deepSightAI.Trinetra.Shared.Storage",
        "shared.db": "deepSightAI.Trinetra.Shared.DB",
        "Shared.db": "deepSightAI.Trinetra.Shared.DB",
        "deepSightAI.Trinetra.Shared.db": "deepSightAI.Trinetra.Shared.DB",
        "shared.minio": "deepSightAI.Trinetra.Shared.Minio",
        "Shared.minio": "deepSightAI.Trinetra.Shared.Minio",
        "deepSightAI.Trinetra.Shared.minio": "deepSightAI.Trinetra.Shared.Minio",
        "shared.redis_utils": "deepSightAI.Trinetra.Shared.RedisUtils",
        "Shared.redis_utils": "deepSightAI.Trinetra.Shared.RedisUtils",
        "deepSightAI.Trinetra.Shared.redis_utils": "deepSightAI.Trinetra.Shared.RedisUtils",
        "shared.tenant_context": "deepSightAI.Trinetra.Shared.TenantContext",
        "Shared.tenant_context": "deepSightAI.Trinetra.Shared.TenantContext",
        "deepSightAI.Trinetra.Shared.tenant_context": "deepSightAI.Trinetra.Shared.TenantContext",
        "shared.repositories.base": "deepSightAI.Trinetra.Shared.Repositories.Base",
        "shared.repositories.camera_repository": "deepSightAI.Trinetra.Shared.Repositories.CameraRepository",
        "shared.repositories.plate_repository": "deepSightAI.Trinetra.Shared.Repositories.PlateRepository",
        "shared.repositories.video_repository": "deepSightAI.Trinetra.Shared.Repositories.VideoRepository",
        "shared.repositories.watchlist_repository": "deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository",
        "shared.repositories": "deepSightAI.Trinetra.Shared.Repositories",
        "Shared.repositories": "deepSightAI.Trinetra.Shared.Repositories",
        "deepSightAI.Trinetra.Shared.repositories.base": "deepSightAI.Trinetra.Shared.Repositories.Base",
        "deepSightAI.Trinetra.Shared.repositories.camera_repository": "deepSightAI.Trinetra.Shared.Repositories.CameraRepository",
        "deepSightAI.Trinetra.Shared.repositories.plate_repository": "deepSightAI.Trinetra.Shared.Repositories.PlateRepository",
        "deepSightAI.Trinetra.Shared.repositories.video_repository": "deepSightAI.Trinetra.Shared.Repositories.VideoRepository",
        "deepSightAI.Trinetra.Shared.repositories.watchlist_repository": "deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository",
        "deepSightAI.Trinetra.Shared.repositories": "deepSightAI.Trinetra.Shared.Repositories",
        "deepSightAI.Trinetra.Shared.streaming.consumer": "deepSightAI.Trinetra.Shared.Streaming.Consumer",
        "deepSightAI.Trinetra.Shared.streaming.producer": "deepSightAI.Trinetra.Shared.Streaming.Producer",
        "deepSightAI.Trinetra.Shared.streaming.schema": "deepSightAI.Trinetra.Shared.Streaming.Schema",
        "deepSightAI.Trinetra.Shared.streaming.replay": "deepSightAI.Trinetra.Shared.Streaming.Replay",
        "deepSightAI.Trinetra.Shared.streaming.redis_client": "deepSightAI.Trinetra.Shared.Streaming.RedisClient",
        "deepSightAI.Trinetra.Shared.streaming": "deepSightAI.Trinetra.Shared.Streaming",
        "shared.errors": "deepSightAI.Trinetra.Shared.Errors",
        "Shared.errors": "deepSightAI.Trinetra.Shared.Errors",
        "deepSightAI.Trinetra.Shared.errors": "deepSightAI.Trinetra.Shared.Errors",
        "shared.logging_setup": "deepSightAI.Trinetra.Shared.LoggingSetup",
        "Shared.logging_setup": "deepSightAI.Trinetra.Shared.LoggingSetup",
        "deepSightAI.Trinetra.Shared.logging_setup": "deepSightAI.Trinetra.Shared.LoggingSetup",
        "shared": "deepSightAI.Trinetra.Shared",
        "Shared": "deepSightAI.Trinetra.Shared",
        "ServerAndExtractor": "deepSightAI.Trinetra.ServerAndExtractor",
        "extractor": "deepSightAI.Trinetra.ServerAndExtractor.extractor",
        "registry": "deepSightAI.Trinetra.ServerAndExtractor.registry",
        "ingest_service": "deepSightAI.Trinetra.ServerAndExtractor.ingest_service",
        "main_api": "deepSightAI.Trinetra.ServerAndExtractor.main_api",
        "adapters": "deepSightAI.Trinetra.ServerAndExtractor.adapters",
        "AuthService": "deepSightAI.Trinetra.AuthService",
        "auth_service": "deepSightAI.Trinetra.AuthService.auth_service",
        "SearchService": "deepSightAI.Trinetra.SearchService",
        "Embedder": "deepSightAI.Trinetra.Embedder",
        "AuditService": "deepSightAI.Trinetra.AuditService",
        "audit_service": "deepSightAI.Trinetra.AuditService.audit_service",
        "UI": "deepSightAI.Trinetra.UI",
        "VisionProcessingService": "deepSightAI.Trinetra.VisionProcessingService",
        "WatchlistMatcherService": "deepSightAI.Trinetra.WatchlistMatcherService",
        "watchlist_matcher_service": "deepSightAI.Trinetra.WatchlistMatcherService",
    }


    def find_spec(self, fullname, path, target=None):
        if fullname in self.MAP:
            return ModuleSpec(fullname, _DeepSightAliasLoader(self.MAP[fullname]))
        prefix = fullname.split(".")[0]
        if prefix in self.MAP:
            target_prefix = self.MAP[prefix]
            suffix = fullname[len(prefix):]
            target_name = target_prefix + suffix
            return ModuleSpec(fullname, _DeepSightAliasLoader(target_name))
        return None


# Install meta path finder if not already present
if not any(isinstance(finder, _DeepSightAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _DeepSightAliasFinder())


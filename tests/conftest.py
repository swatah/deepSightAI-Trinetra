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
    }

    def find_spec(self, fullname, path, target=None):
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


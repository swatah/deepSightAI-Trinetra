"""
Shared utilities package for Trinetra under deepSightAI.
"""

import sys

from . import config
from . import db
from . import milvus
from . import minio
from . import middleware
from . import redis_utils
from . import storage
from . import tenant_context
from . import repositories
from . import streaming

# Register as 'shared' and 'Shared' so existing submodule imports resolve seamlessly
_this = sys.modules[__name__]
sys.modules['shared'] = _this
sys.modules['Shared'] = _this

for _sub in ["config", "db", "milvus", "minio", "middleware", "redis_utils", "storage", "tenant_context", "repositories", "streaming"]:
    _m = getattr(_this, _sub, None)
    if _m is not None:
        sys.modules[f"shared.{_sub}"] = _m
        sys.modules[f"Shared.{_sub}"] = _m

for _name, _mod in list(sys.modules.items()):
    if _name.startswith(__name__ + "."):
        _suffix = _name[len(__name__):]
        sys.modules[f"shared{_suffix}"] = _mod
        sys.modules[f"Shared{_suffix}"] = _mod

__all__ = [
    "config",
    "db",
    "milvus",
    "minio",
    "middleware",
    "redis_utils",
    "storage",
    "tenant_context",
    "repositories",
    "streaming",
]
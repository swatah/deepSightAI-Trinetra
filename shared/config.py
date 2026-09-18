"""
Loader for the global config file (config/global_config.yaml).

Every service reads shared defaults through here instead of duplicating
numbers. Per-node overrides still go through environment variables, e.g.:

    from shared.config import get as get_config
    FPS = int(os.getenv("EXTRACTION_FPS", get_config("extraction.fps", 5)))
"""
import os
import threading

import yaml

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "global_config.yaml",
)

_lock = threading.Lock()
_cached_config = None


def _config_path() -> str:
    return os.getenv("TRINETRA_CONFIG_PATH", _DEFAULT_CONFIG_PATH)


def load_config(force_reload: bool = False) -> dict:
    """Load and cache the global config file for this process."""
    global _cached_config
    with _lock:
        if _cached_config is None or force_reload:
            with open(_config_path()) as f:
                _cached_config = yaml.safe_load(f) or {}
        return _cached_config


def get(key_path: str, default=None):
    """Dotted-path lookup, e.g. get('extraction.fps')."""
    node = load_config()
    for part in key_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node

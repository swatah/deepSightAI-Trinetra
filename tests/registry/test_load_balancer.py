"""
Test cases for round-robin load balancer in registry.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add the current directory to the path so we can import registry
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Server and Extractor'))

@patch('registry.r')
def test_get_available_extractor_round_robin(mock_r):
    # Setup: create three extractors
    extractors = [
        {"extractor_id": "ext1", "extractor_url": "http://ext1:8000"},
        {"extractor_id": "ext2", "extractor_url": "http://ext2:8000"},
        {"extractor_id": "ext3", "extractor_url": "http://ext3:8000"},
    ]

    # We'll create a list of keys
    keys = [f"extractor:{ext['extractor_id']}" for ext in extractors]

    # We'll keep a state dictionary for each key
    state = {}
    for key in keys:
        state[key] = {
            "extractor_id": key.split(':')[1],
            "extractor_url": "http://"+key.split(':')[1]+":8000",
            "status": "available"
        }

    def scan_iter_side_effect(match):
        return keys

    def hgetall_side_effect(key):
        return state.get(key, {})

    def hset_side_effect(key, field, value):
        if key in state:
            state[key][field] = value
        return True

    def exists_side_effect(key):
        return key in state

    def get_side_effect(key):
        # For the index keys, return None so that we start at 0
        if key in ["extractor:index", "embedder:index"]:
            return None
        # For other keys, we don't expect them in this test, but just in case
        return None

    def set_side_effect(key, value):
        # We don't need to do anything, just accept the call
        return True

    mock_r.scan_iter.side_effect = scan_iter_side_effect
    mock_r.hgetall.side_effect = hgetall_side_effect
    mock_r.hset.side_effect = hset_side_effect
    mock_r.exists.side_effect = exists_side_effect
    mock_r.get.side_effect = get_side_effect
    mock_r.set.side_effect = set_side_effect

    # Import the function inside the patch so that it uses our mock
    from registry import get_available_extractor

    # We will call the function 6 times (two full rounds) and after each call we set the status of the returned extractor back to available.
    # We expect the order: ext1, ext2, ext3, ext1, ext2, ext3
    results = []
    for i in range(6):
        result = get_available_extractor()
        results.append(result["extractor_id"])
        # Reset the status of the extracted extractor to available for the next round
        key = f"extractor:{result['extractor_id']}"
        state[key]["status"] = "available"

    assert results == ["ext1", "ext2", "ext3", "ext1", "ext2", "ext3"]


@patch('registry.r')
def test_get_available_extractor_no_available(mock_r):
    # Setup: no extractors
    mock_r.scan_iter.return_value = []
    from registry import get_available_extractor
    with pytest.raises(Exception) as exc_info:
        get_available_extractor()
    assert "No available extractors" in str(exc_info.value)


@patch('registry.r')
def test_get_available_embedder_round_robin(mock_r):
    # Setup: create three embedders
    embedders = [
        {"embedder_id": "emb1", "embedder_url": "http://emb1:8000"},
        {"embedder_id": "emb2", "embedder_url": "http://emb2:8000"},
        {"embedder_id": "emb3", "embedder_url": "http://emb3:8000"},
    ]

    # We'll create a list of keys
    keys = [f"embedder:{emb['embedder_id']}" for emb in embedders]

    # We'll keep a state dictionary for each key
    state = {}
    for key in keys:
        state[key] = {
            "embedder_id": key.split(':')[1],
            "embedder_url": "http://"+key.split(':')[1]+":8000",
            "status": "available"
        }

    def scan_iter_side_effect(match):
        return keys

    def hgetall_side_effect(key):
        return state.get(key, {})

    def hset_side_effect(key, field, value):
        if key in state:
            state[key][field] = value
        return True

    def exists_side_effect(key):
        return key in state

    def get_side_effect(key):
        # For the index keys, return None so that we start at 0
        if key in ["extractor:index", "embedder:index"]:
            return None
        # For other keys, we don't expect them in this test, but just in case
        return None

    def set_side_effect(key, value):
        # We don't need to do anything, just accept the call
        return True

    mock_r.scan_iter.side_effect = scan_iter_side_effect
    mock_r.hgetall.side_effect = hgetall_side_effect
    mock_r.hset.side_effect = hset_side_effect
    mock_r.exists.side_effect = exists_side_effect
    mock_r.get.side_effect = get_side_effect
    mock_r.set.side_effect = set_side_effect

    # Import the function inside the patch so that it uses our mock
    from registry import get_available_embedder

    # We will call the function 6 times (two full rounds) and after each call we set the status of the returned embedder back to available.
    # We expect the order: emb1, emb2, emb3, emb1, emb2, emb3
    results = []
    for i in range(6):
        result = get_available_embedder()
        results.append(result["embedder_id"])
        # Reset the status of the extracted embedder to available for the next round
        key = f"embedder:{result['embedder_id']}"
        state[key]["status"] = "available"

    assert results == ["emb1", "emb2", "emb3", "emb1", "emb2", "emb3"]


@patch('registry.r')
def test_get_available_embedder_no_available(mock_r):
    # Setup: no embedders
    mock_r.scan_iter.return_value = []
    from registry import get_available_embedder
    with pytest.raises(Exception) as exc_info:
        get_available_embedder()
    assert "No available embedders" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
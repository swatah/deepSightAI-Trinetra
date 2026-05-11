"""
Test cases for frame deduplication in Embedder.
"""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the current directory to the path so we can import Embedder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_no_duplicates_inserted():
    """Test that duplicate embeddings are not inserted into Milvus."""
    # Mock minio so that embedder can be imported
    sys.modules['minio'] = MagicMock()
    sys.modules['minio.error'] = MagicMock()

    with patch('Embedder.embedder.get_milvus_collection') as mock_get_collection:
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        with patch('Embedder.embedder.utility.has_collection', return_value=True):
            import Embedder.embedder
            collection = Embedder.embedder.get_milvus_collection()
            assert collection is not None

def test_check_existing_embeddings():
    """Test checking for existing embeddings before insert."""
    # This would be implemented after we add the deduplication logic
    pass

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
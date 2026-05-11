"""
Test cases for Query API (SearchService)
"""
import pytest
from fastapi.testclient import TestClient
import sys
import os
from unittest.mock import patch, MagicMock
import torch

# Add the current directory to the path so we can import SearchService
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import the app directly from the SearchService module
from SearchService.main import app

client = TestClient(app)

def test_health_endpoint():
    """Test the health check endpoint."""
    response = client.get("/health")
    # Note: This might fail if Milvus is not running, but we're testing the endpoint exists
    assert response.status_code in [200, 503]  # Healthy or unhealthy (if Milvus down)

def test_search_endpoint_exists():
    """Test that the search endpoint exists."""
    response = client.post("/search/text", json={"query_text": "test query", "top_k": 5})
    # Should return 422 (validation error) if Milvus is not connected, or 200/500
    # The important thing is that the endpoint exists and doesn't return 404
    assert response.status_code != 404

def test_search_request_model():
    """Test the SearchRequest model validation."""
    from SearchService.main import SearchRequest
    
    # Valid request
    valid_request = SearchRequest(query_text="test query", top_k=10)
    assert valid_request.query_text == "test query"
    assert valid_request.top_k == 10
    
    # Default top_k
    default_request = SearchRequest(query_text="test query")
    assert default_request.top_k == 10
    
    # Test that query_text is required
    with pytest.raises(Exception):
        SearchRequest(top_k=5)  # Missing required field

def test_search_result_model():
    """Test the SearchResult model."""
    from SearchService.main import SearchResult
    
    result = SearchResult(
        video_id="test_video",
        frame_path="test_video/segment_0000/frame-00001.jpg",
        score=0.95
    )
    
    assert result.video_id == "test_video"
    assert result.frame_path == "test_video/segment_0000/frame-00001.jpg"
    assert result.score == 0.95

@patch('SearchService.main.model')
@patch('SearchService.main.preprocess')
@patch('SearchService.main.get_milvus_collection')
def test_search_returns_results(mock_get_collection, mock_preprocess, mock_model):
    """Test that search returns results in expected format."""
    # Setup environment variables for the test
    with patch.dict('os.environ', {
        'USE_ONNX': '0',  # Use PyTorch path
        'MILVUS_HOST': 'localhost',
        'MILVUS_PORT': '19530',
        'MILVUS_COLLECTION': 'video_frames',
        'EMBEDDING_DIM': '512'
    }):
        # Mock preprocessing to return dummy tensor
        mock_preprocess.return_value = torch.zeros((1, 3, 224, 224))  # dummy image tensor
        
        # Mock model encoding to return normalized features
        mock_model.encode_text.return_value = torch.tensor([[0.0] * 512])  # dummy features
        
        # Mock Milvus collection and search results
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        
        # Create mock hit
        mock_hit = MagicMock()
        mock_hit.entity.get.side_effect = lambda key: {
            "video_id": "test_video_123",
            "frame_path": "test_video_123/segment_0001/frame-00005.jpg"
        }.get(key)
        mock_hit.score = 0.87
        
        mock_collection.search.return_value = [[mock_hit]]
        
        # Make the request
        response = client.post("/search/text", json={"query_text": "test query", "top_k": 5})
        
        # Assertions
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["video_id"] == "test_video_123"
        assert results[0]["frame_path"] == "test_video_123/segment_0001/frame-00005.jpg"
        assert results[0]["score"] == 0.87
        
        # Verify that Milvus search was called with correct parameters
        mock_collection.search.assert_called_once()
        call_args = mock_collection.search.call_args
        assert call_args[1]['anns_field'] == "embedding"
        assert call_args[1]['limit'] == 5
        assert "output_fields" in call_args[1]

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

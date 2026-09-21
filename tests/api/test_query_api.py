"""
Test cases for Query API (SearchService)
"""
import pytest
from fastapi.testclient import TestClient
import sys
import os
from unittest.mock import patch, MagicMock
import torch

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
    """Test the SearchResult model (SR-40)."""
    from SearchService.main import SearchResult
    
    result = SearchResult(
        video_id="test_video",
        thumbnail_url="http://localhost:9000/frames/test_video/segment_0000/frame-00001.jpg",
        score=0.95
    )
    
    assert result.video_id == "test_video"
    assert result.thumbnail_url == "http://localhost:9000/frames/test_video/segment_0000/frame-00001.jpg"
    assert result.score == 0.95
    assert "frame_path" not in SearchResult.model_fields

@patch('SearchService.main.model')
@patch('SearchService.main.preprocess')
@patch('SearchService.main.get_milvus_collection')
def test_search_returns_results(mock_get_collection, mock_preprocess, mock_model):
    """Test that search returns results in expected format."""
    # Setup environment variables for the test
    with patch.dict('os.environ', {
        'MILVUS_HOST': 'localhost',
        'MILVUS_PORT': '19530',
        'MINIO_URL': 'localhost:9000',
        'FRAME_BUCKET': 'frames',
    }):
        # Mock Milvus search response
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        
        mock_hit = MagicMock()
        mock_hit.score = 0.87
        mock_hit.entity = {
            "video_id": "test_video_123",
            "frame_path": "test_video_123/segment_0001/frame-00005.jpg"
        }
        mock_collection.search.return_value = [[mock_hit]]
        
        # Test unauthenticated request returns 401 (SR-43, Verification Criteria)
        unauth_response = client.post("/search/text", json={"query_text": "test query", "top_k": 5})
        assert unauth_response.status_code == 401

        # Test authenticated request returns 200 (SR-43)
        from deepSightAI.Trinetra.Shared.Middleware import require_auth
        app.dependency_overrides[require_auth] = lambda: {"sub": "test", "tenant_id": "default", "roles": ["admin", "search:read"]}
        try:
            response = client.post("/search/text", json={"query_text": "test query", "top_k": 5})
            assert response.status_code == 200
            results = response.json()
            assert len(results) == 1
            assert results[0]["video_id"] == "test_video_123"
            assert "frame_path" not in results[0]
            assert results[0]["score"] == 0.87
            assert "thumbnail_url" in results[0]

            # Verify that Milvus search was called with correct parameters
            mock_collection.search.assert_called_once()
            call_args = mock_collection.search.call_args
            assert call_args[1]['anns_field'] == "embedding"
            assert call_args[1]['limit'] == 5
            assert "output_fields" in call_args[1]

            # Test hard ceiling on top_k returns 422 (SR-44)
            invalid_top_k_resp = client.post("/search/text", json={"query_text": "test", "top_k": 500})
            assert invalid_top_k_resp.status_code == 422
        finally:
            app.dependency_overrides.pop(require_auth, None)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

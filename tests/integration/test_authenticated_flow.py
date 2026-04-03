"""
T1.2.8: Integration - All APIs require auth

This test verifies that the main API and Extractor service
have been configured to enforce JWT authentication globally.

Since full integration would require running multiple services,
we perform static analysis to confirm the code changes are in place.
"""

import pathlib

def test_main_api_has_auth_dependency():
    """Main API should include require_auth in its FastAPI app dependencies."""
    main_api_file = pathlib.Path("Server and Extractor/main_api.py")
    assert main_api_file.exists(), "main_api.py not found"
    content = main_api_file.read_text()
    # Check that FastAPI app initialization includes dependencies with require_auth
    assert "dependencies=[Depends(require_auth)]" in content or "dependencies = [Depends(require_auth)]" in content, \
        "main_api.py should set dependencies=[Depends(require_auth)] on FastAPI app"

def test_extractor_has_auth_dependency():
    """Extractor service should include require_auth in its FastAPI app dependencies."""
    extractor_file = pathlib.Path("Server and Extractor/extractor.py")
    assert extractor_file.exists(), "extractor.py not found"
    content = extractor_file.read_text()
    assert "dependencies=[Depends(require_auth)]" in content or "dependencies = [Depends(require_auth)]" in content, \
        "extractor.py should set dependencies=[Depends(require_auth)] on FastAPI app"

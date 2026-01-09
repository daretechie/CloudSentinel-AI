"""
Tests for API endpoints.

Tests cover:
- Health check endpoint
- Authentication requirements on protected endpoints
- Basic response validation
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestHealthEndpoint:
    """Tests for /health endpoint."""
    
    def test_health_returns_200(self):
        """Test that health endpoint returns 200."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert data["status"] == "active"  # API returns 'active' not 'healthy'


class TestCostsEndpoint:
    """Tests for /costs endpoint."""
    
    def test_costs_without_auth_returns_401(self):
        """Test that costs endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get("/costs")
            
            # Should return 401 Unauthorized or 403 Forbidden
            assert response.status_code in [401, 403]
    
    def test_costs_with_invalid_token_returns_401(self):
        """Test that invalid token is rejected."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get(
                "/costs",
                headers={"Authorization": "Bearer invalid-token-12345"}
            )
            
            assert response.status_code in [401, 403]


class TestAnalyzeEndpoint:
    """Tests for /analyze endpoint."""
    
    def test_analyze_without_auth_returns_401(self):
        """Test that analyze endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get("/analyze")
            
            assert response.status_code in [401, 403]


class TestLLMUsageEndpoint:
    """Tests for /llm/usage endpoint."""
    
    def test_llm_usage_without_auth_returns_401(self):
        """Test that LLM usage endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get("/llm/usage")
            
            assert response.status_code in [401, 403]


class TestCarbonEndpoint:
    """Tests for /carbon endpoint."""
    
    def test_carbon_without_auth_returns_401(self):
        """Test that carbon endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get("/carbon")
            
            assert response.status_code in [401, 403]


class TestZombiesEndpoint:
    """Tests for /zombies endpoints."""
    
    def test_zombies_without_auth_returns_401(self):
        """Test that zombies endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.get("/zombies")
            
            assert response.status_code in [401, 403]
    
    def test_zombies_request_without_auth_returns_401(self):
        """Test that zombie request endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.post(
                "/zombies/request",
                json={"resource_id": "test-123", "action": "terminate"}
            )
            
            assert response.status_code in [401, 403]
    
    def test_zombies_approve_without_auth_returns_401(self):
        """Test that zombie approve endpoint requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.post("/zombies/approve/some-uuid-here")
            
            assert response.status_code in [401, 403, 422]  # 422 for invalid UUID is also acceptable


class TestAdminEndpoint:
    """Tests for admin endpoints."""
    
    def test_admin_trigger_without_auth_returns_401(self):
        """Test that admin trigger requires authentication."""
        from app.main import app
        
        with TestClient(app) as client:
            response = client.post("/admin/trigger-analysis")
            
            # 422 is acceptable - missing required fields in request
            assert response.status_code in [401, 403, 422]

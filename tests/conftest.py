import os
import sys
from unittest.mock import MagicMock
import pytest

# Ensure all models are registered for SQLAlchemy relationship mapping
import app.models.tenant
import app.models.aws_connection
import app.models.azure_connection
import app.models.gcp_connection
import app.models.llm
import app.models.notification_settings
import app.models.remediation
import app.models.background_job
import app.models.attribution
import app.models.carbon_settings
import app.models.cost_audit
import app.models.discovered_account
import app.models.pricing
import app.models.security
import app.models.anomaly_marker
import app.modules.governance.domain.security.audit_log

# Set TESTING environment variable for tests
os.environ["TESTING"] = "true"

# GLOBAL MOCKING FOR PROBLEM ENVIRONMENT
# Removed global mocks for pandas, numpy, etc. as they are installed in the environment.
# Only mock if strictly necessary and missing.
if "tiktoken" not in sys.modules:
    sys.modules["tiktoken"] = MagicMock()

# Global tenacity mock to prevent long waits and recursion issues
import tenacity
def mock_retry(*args, **kwargs):
    def decorator(f):
        return f
    return decorator
tenacity.retry = mock_retry

@pytest.fixture(autouse=True)
def set_testing_env():
    """Ensure TESTING is set for all tests"""
    os.environ["TESTING"] = "true"
    yield
    # No need to unset, cleaner to leave it or use a better config override mechanism

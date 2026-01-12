from typing import Optional, Dict, Any

class CloudSentinelException(Exception):
    """Base exception for all CloudSentinel errors."""
    def __init__(
        self, 
        message: str, 
        code: str = "internal_error", 
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

class AdapterError(CloudSentinelException):
    """Raised when an external cloud adapter fails."""
    pass

class AuthError(CloudSentinelException):
    """Raised when authentication or authorization fails."""
    pass

class ConfigurationError(CloudSentinelException):
    """Raised when application configuration is invalid or missing."""
    pass

class ResourceNotFoundError(CloudSentinelException):
    """Raised when a requested resource (DB record, cloud resource) is not found."""
    pass

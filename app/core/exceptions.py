from typing import Optional, Dict, Any

class ValdrixException(Exception):
    """Base exception for all Valdrix errors."""
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

class AdapterError(ValdrixException):
    """Raised when an external cloud adapter fails."""
    pass

class AuthError(ValdrixException):
    """Raised when authentication or authorization fails."""
    pass

class ConfigurationError(ValdrixException):
    """Raised when application configuration is invalid or missing."""
    pass

class ResourceNotFoundError(ValdrixException):
    """Raised when a requested resource (DB record, cloud resource) is not found."""
    pass

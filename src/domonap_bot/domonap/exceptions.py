class DomonapError(Exception):
    """Base exception for all Domonap-related errors."""


class AuthenticationError(DomonapError):
    """Raised when authentication fails."""


class NetworkError(DomonapError):
    """Raised on network connectivity issues."""


class ApiError(DomonapError):
    """Raised when the Domonap API returns an unexpected response."""


class TokenExpiredError(AuthenticationError):
    """Raised when the stored token has expired and refresh failed."""

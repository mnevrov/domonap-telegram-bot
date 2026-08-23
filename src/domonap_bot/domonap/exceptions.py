import re

_HTTP_STATUS_RE = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)


def _safe_error_message(prefix: str, message: str) -> str:
    """Keep only a useful HTTP status from an upstream-controlled error string."""
    match = _HTTP_STATUS_RE.search(message)
    if match:
        return f"{prefix} (HTTP {match.group(1)})"
    return prefix


class DomonapError(Exception):
    """Base exception for all Domonap-related errors."""


class AuthenticationError(DomonapError):
    """Raised when authentication fails without retaining upstream response bodies."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(_safe_error_message("Domonap authentication failed", message))


class NetworkError(DomonapError):
    """Raised on network connectivity issues."""


class ApiError(DomonapError):
    """Raised for API failures without retaining upstream-controlled response bodies."""

    def __init__(self, message: str = "API request failed") -> None:
        super().__init__(_safe_error_message("Domonap API request failed", message))


class TokenExpiredError(AuthenticationError):
    """Raised when the stored token has expired and refresh failed."""


class SessionExpiredError(AuthenticationError):
    """Raised when the refresh token itself is expired or invalid."""

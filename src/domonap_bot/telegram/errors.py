import json
import re

from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)


def extract_api_error_text(exc: ApiError) -> str | None:
    """Parse the Domonap API JSON error body for a user-facing errorText field."""
    msg = str(exc)
    match = re.search(r"\{.*\}", msg)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data.get("errorText")


def describe_error(exc: DomonapError) -> str:
    if isinstance(exc, (TokenExpiredError, SessionExpiredError)):
        return "Session expired. Re-authentication required."
    if isinstance(exc, NetworkError):
        return "Network unavailable. Please try again later."
    if isinstance(exc, ApiError):
        api_text = extract_api_error_text(exc)
        if api_text:
            return api_text
        return f"API error: {exc}"
    return f"API error: {exc}"

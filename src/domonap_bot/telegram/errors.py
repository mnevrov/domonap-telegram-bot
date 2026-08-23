from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)


def describe_error(exc: DomonapError) -> str:
    if isinstance(exc, (TokenExpiredError, SessionExpiredError)):
        return "Session expired. Re-authentication required."
    if isinstance(exc, NetworkError):
        return "Network unavailable. Please try again later."
    if isinstance(exc, ApiError):
        return "Domonap API error. Please try again later."
    return "Domonap API error. Please try again later."

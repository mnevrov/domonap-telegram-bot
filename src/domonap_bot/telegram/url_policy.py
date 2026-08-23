from urllib.parse import urlsplit

_MAX_MEDIA_URL_LENGTH = 2048


def safe_http_url(value: str | None) -> str | None:
    """Return a media URL only when it is safe to expose to Telegram clients."""
    if not value or len(value) > _MAX_MEDIA_URL_LENGTH:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return None

    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return value

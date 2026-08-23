import logging
import sys

_THIRD_PARTY_LOGGERS = (
    "aiogram",
    "aiohttp",
    "aiosqlite",
    "httpcore",
    "httpx",
)


def setup_logging(level: str = "INFO") -> None:
    level_name = level.upper()
    requested_level = logging.getLevelNamesMapping().get(level_name)
    if requested_level is None:
        raise ValueError(f"Unknown log level: {level}")

    logging.basicConfig(
        level=requested_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    third_party_level = max(requested_level, logging.INFO)
    for logger_name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(third_party_level)

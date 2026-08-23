import logging
from unittest.mock import MagicMock, patch

from domonap_bot.logging_config import _THIRD_PARTY_LOGGERS, setup_logging


def _logger_mocks() -> dict[str, MagicMock]:
    return {name: MagicMock() for name in _THIRD_PARTY_LOGGERS}


def test_debug_keeps_third_party_loggers_at_info_or_above() -> None:
    loggers = _logger_mocks()

    with (
        patch("domonap_bot.logging_config.logging.basicConfig") as basic_config,
        patch(
            "domonap_bot.logging_config.logging.getLogger",
            side_effect=lambda name: loggers[name],
        ),
    ):
        setup_logging("DEBUG")

    assert basic_config.call_args.kwargs["level"] == logging.DEBUG
    for logger in loggers.values():
        logger.setLevel.assert_called_once_with(logging.INFO)


def test_third_party_floor_does_not_lower_requested_error_level() -> None:
    loggers = _logger_mocks()

    with (
        patch("domonap_bot.logging_config.logging.basicConfig") as basic_config,
        patch(
            "domonap_bot.logging_config.logging.getLogger",
            side_effect=lambda name: loggers[name],
        ),
    ):
        setup_logging("ERROR")

    assert basic_config.call_args.kwargs["level"] == logging.ERROR
    for logger in loggers.values():
        logger.setLevel.assert_called_once_with(logging.ERROR)

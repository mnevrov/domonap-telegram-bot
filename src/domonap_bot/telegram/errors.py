from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)


def describe_error(exc: DomonapError) -> str:
    if isinstance(exc, (TokenExpiredError, SessionExpiredError)):
        return "Сессия истекла. Подключите Domonap заново."
    if isinstance(exc, NetworkError):
        return "Сеть недоступна. Повторите позже."
    if isinstance(exc, ApiError):
        return "Ошибка Domonap API. Повторите позже."
    return "Ошибка Domonap API. Повторите позже."

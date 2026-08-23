from collections import OrderedDict
from dataclasses import dataclass

_MAX_NAVIGATION_USERS = 2048


@dataclass(slots=True)
class NavigationState:
    door_page: int = 0
    call_page: int = 0
    call_filter_missed: bool = False


class NavigationStore:
    """Small in-memory LRU store for non-sensitive Telegram UI state."""

    def __init__(self, max_users: int = _MAX_NAVIGATION_USERS) -> None:
        if max_users <= 0:
            raise ValueError("max_users must be positive")
        self._max_users = max_users
        self._states: OrderedDict[int, NavigationState] = OrderedDict()

    def get(self, user_id: int) -> NavigationState:
        state = self._states.get(user_id)
        if state is None:
            state = NavigationState()
            self._states[user_id] = state
        self._states.move_to_end(user_id)
        while len(self._states) > self._max_users:
            self._states.popitem(last=False)
        return state

    def set_door_page(self, user_id: int, page: int) -> None:
        self.get(user_id).door_page = max(0, page)

    def set_call_view(self, user_id: int, *, page: int, missed: bool) -> None:
        state = self.get(user_id)
        state.call_page = max(0, page)
        state.call_filter_missed = missed

    def __len__(self) -> int:
        return len(self._states)

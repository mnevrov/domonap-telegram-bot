import pytest

from domonap_bot.telegram.navigation import NavigationStore


def test_navigation_defaults_are_stable() -> None:
    store = NavigationStore()
    state = store.get(42)

    assert state.door_page == 0
    assert state.call_page == 0
    assert state.call_filter_missed is False


def test_navigation_preserves_door_and_call_state() -> None:
    store = NavigationStore()
    store.set_door_page(42, 3)
    store.set_call_view(42, page=2, missed=True)

    state = store.get(42)
    assert state.door_page == 3
    assert state.call_page == 2
    assert state.call_filter_missed is True


def test_navigation_is_lru_bounded() -> None:
    store = NavigationStore(max_users=2)
    store.set_door_page(1, 1)
    store.set_door_page(2, 2)

    # Touch user 1, so user 2 becomes the least recently used entry.
    assert store.get(1).door_page == 1
    store.set_door_page(3, 3)

    assert len(store) == 2
    assert store.get(1).door_page == 1
    assert store.get(3).door_page == 3
    # User 2 was evicted and therefore receives a fresh default state.
    assert store.get(2).door_page == 0
    assert len(store) == 2


def test_navigation_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError):
        NavigationStore(max_users=0)

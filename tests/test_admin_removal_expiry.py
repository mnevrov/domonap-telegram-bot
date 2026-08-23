from domonap_bot.telegram.admin import _expire_pending_removal, _pending_removals


def test_stale_expiry_does_not_clear_newer_removal_confirmation() -> None:
    _pending_removals.clear()
    _pending_removals[1] = 200

    _expire_pending_removal(admin_id=1, user_id=100)

    assert _pending_removals == {1: 200}


def test_matching_expiry_clears_removal_confirmation() -> None:
    _pending_removals.clear()
    _pending_removals[1] = 200

    _expire_pending_removal(admin_id=1, user_id=200)

    assert _pending_removals == {}

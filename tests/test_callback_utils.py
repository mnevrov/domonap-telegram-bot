from domonap_bot.telegram.callback_utils import compact_callback_id, resolve_callback_id


def test_short_callback_id_is_kept_unchanged() -> None:
    assert compact_callback_id("open:", "door-1") == "door-1"


def test_long_callback_id_is_compacted_and_resolved() -> None:
    original = "x" * 128

    compact = compact_callback_id("answer:", original)

    assert len(f"answer:{compact}".encode("utf-8")) <= 64
    assert compact != original
    assert resolve_callback_id(compact) == original

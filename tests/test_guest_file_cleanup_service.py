from pathlib import Path

import pytest

from PushShoppingList.services import guest_file_cleanup_service as cleanup


def test_preview_is_read_only_and_delete_is_exact_and_idempotent(tmp_path):
    base = tmp_path / "guests"
    target = base / "expired-guest"
    unrelated = base / "active-guest"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "owned.json").write_text("owned", encoding="utf-8")
    unrelated.mkdir(parents=True)
    (unrelated / "keep.json").write_text("keep", encoding="utf-8")

    preview = cleanup.preview_guest_workspace_cleanup("expired-guest", base_dir=base)

    assert preview == {
        "ok": True,
        "dry_run": True,
        "code": "preview_complete",
        "exists": True,
        "workspace_name": "expired-guest",
        "workspace_relative_path": "expired-guest",
        "file_count": 1,
        "directory_count": 1,
        "size_bytes": 5,
    }
    assert (target / "nested" / "owned.json").exists()

    first = cleanup.delete_guest_workspace("expired-guest", base_dir=base)
    second = cleanup.delete_guest_workspace("expired-guest", base_dir=base)

    assert first["ok"] is True
    assert first["applied"] is True
    assert first["no_op"] is False
    assert second["ok"] is True
    assert second["no_op"] is True
    assert not target.exists()
    assert (unrelated / "keep.json").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "guest_session_id",
    ["", "../account", "guest/name", " guest", "guest ", "guest:name"],
)
def test_unsafe_guest_identity_never_selects_a_workspace(tmp_path, guest_session_id):
    result = cleanup.delete_guest_workspace(
        guest_session_id,
        base_dir=tmp_path / "guests",
    )

    assert result["ok"] is False
    assert result["applied"] is False
    assert result["code"] == "unsafe_workspace"


def test_delete_failure_is_reported_for_retry_without_touching_unrelated_data(tmp_path):
    base = tmp_path / "guests"
    target = base / "expired-guest"
    unrelated = base / "active-guest"
    target.mkdir(parents=True)
    unrelated.mkdir(parents=True)
    (target / "owned").write_text("owned", encoding="utf-8")
    (unrelated / "keep").write_text("keep", encoding="utf-8")

    def fail(stage, _context):
        if stage == "before_delete":
            raise OSError("injected filesystem failure")

    result = cleanup.delete_guest_workspace(
        "expired-guest",
        base_dir=base,
        failure_injector=fail,
    )

    assert result["ok"] is True
    assert result["applied"] is False
    assert result["code"] == "delete_failed"
    assert "injected filesystem failure" in result["error"]
    assert (target / "owned").exists()
    assert (unrelated / "keep").exists()


def test_linked_workspace_fails_closed_when_supported(tmp_path):
    base = tmp_path / "guests"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    (outside / "do-not-delete").write_text("safe", encoding="utf-8")
    link = base / "expired-guest"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are not available on this host.")

    result = cleanup.delete_guest_workspace("expired-guest", base_dir=base)

    assert result["ok"] is False
    assert (outside / "do-not-delete").read_text(encoding="utf-8") == "safe"

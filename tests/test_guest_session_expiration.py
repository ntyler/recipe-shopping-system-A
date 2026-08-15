from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from PushShoppingList.services import guest_session_service as guests


@pytest.fixture
def isolated_guest_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(guests, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guests, "GUEST_DATA_DIR", tmp_path / "guests")
    return tmp_path


def guest_record(*, expires_at, active=True):
    return {
        "id": "existing-guest-id",
        "session_id": "existing-guest-id",
        "created_at": "2026-08-14T12:00:00Z",
        "expires_at": expires_at,
        "used_at": "2026-08-14T12:00:00Z",
        "is_active": active,
        "lifecycle_state": "active" if active else "inactive",
        "temporary_data_json": {},
    }


@pytest.mark.parametrize(
    ("offset_seconds", "expected_valid", "expected_expired"),
    [
        (-1, True, False),
        (0, False, True),
        (1, False, True),
    ],
    ids=["before-cutoff", "exact-cutoff", "after-cutoff"],
)
def test_expiration_boundary_is_inclusive(
    offset_seconds,
    expected_valid,
    expected_expired,
):
    cutoff = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    record = guest_record(expires_at="2026-08-15T12:00:00Z")
    observed_at = cutoff + timedelta(seconds=offset_seconds)

    assert guests.guest_session_is_valid(record, at_time=observed_at) is expected_valid
    assert guests.guest_session_is_expired(record, at_time=observed_at) is expected_expired


def test_inactive_future_session_is_invalid_but_not_expired():
    record = guest_record(expires_at="2026-08-16T12:00:00Z", active=False)
    cutoff = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

    assert guests.guest_session_is_valid(record, at_time=cutoff) is False
    assert guests.guest_session_is_expired(record, at_time=cutoff) is False


@pytest.mark.parametrize("expires_at", ["", None, "not-a-timestamp"])
def test_invalid_expiration_fails_closed(expires_at):
    record = guest_record(expires_at=expires_at)

    assert guests.guest_session_is_valid(record) is False
    assert guests.guest_session_is_expired(record) is True


def test_timezone_offset_expiration_is_normalized_to_utc():
    record = guest_record(expires_at="2026-08-15T08:00:00-04:00")

    assert guests.guest_session_is_valid(
        record,
        at_time=datetime(2026, 8, 15, 11, 59, 59, tzinfo=timezone.utc),
    ) is True
    assert guests.guest_session_is_expired(
        record,
        at_time=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    ) is True


def test_expiration_scan_revokes_access_without_deleting_workspace(isolated_guest_registry):
    record = guest_record(expires_at="2026-08-15T12:00:00Z")
    guests.save_guest_sessions({"guest_sessions": [record]})
    owned_file = isolated_guest_registry / "guests" / record["id"] / "keep-until-purge.txt"
    owned_file.parent.mkdir(parents=True)
    owned_file.write_text("owned", encoding="utf-8")

    result = guests.cleanup_expired_guest_sessions(
        at_time=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    assert result["guest_sessions"][0]["is_active"] is False
    assert result["guest_sessions"][0]["lifecycle_state"] == "inactive"
    assert owned_file.read_text(encoding="utf-8") == "owned"


def test_used_at_update_never_extends_expiration(isolated_guest_registry, monkeypatch):
    record = guest_record(expires_at="2026-08-15T12:00:00Z")
    guests.save_guest_sessions({"guest_sessions": [record]})
    monkeypatch.setattr(guests, "now_iso", lambda: "2026-08-15T11:30:00Z")

    updated = guests.update_guest_used_at(record)

    assert updated["used_at"] == "2026-08-15T11:30:00Z"
    assert updated["expires_at"] == "2026-08-15T12:00:00Z"


def test_corrupt_registry_is_not_silently_treated_as_empty(isolated_guest_registry):
    guests.GUEST_SESSIONS_FILE.write_text("{broken", encoding="utf-8")

    with pytest.raises(guests.GuestSessionStorageError):
        guests.load_guest_sessions()

    assert guests.GUEST_SESSIONS_FILE.read_text(encoding="utf-8") == "{broken"

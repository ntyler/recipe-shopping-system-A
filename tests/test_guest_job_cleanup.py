import hashlib

from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.workers import job_worker


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_guest_job_preview_is_read_only_and_scoped(monkeypatch, tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", db_path)
    job_service.create_job(
        "recipe-import",
        guest_session_id="expired-guest",
        job_id="target-job",
    )
    job_service.create_job(
        "recipe-import",
        guest_session_id="active-guest",
        job_id="unrelated-job",
    )
    before_hash = file_hash(db_path)
    before_mtime = db_path.stat().st_mtime_ns

    result = job_service.preview_guest_jobs_cleanup("expired-guest")

    assert result == {
        "ok": True,
        "dry_run": True,
        "code": "preview_complete",
        "job_count": 1,
        "active_job_count": 1,
    }
    assert file_hash(db_path) == before_hash
    assert db_path.stat().st_mtime_ns == before_mtime
    assert job_service.get_job("unrelated-job")["guest_session_id"] == "active-guest"


def test_guest_job_preview_does_not_create_missing_database(tmp_path):
    db_path = tmp_path / "missing" / "jobs.sqlite3"

    result = job_service.preview_guest_jobs_cleanup(
        "expired-guest",
        db_path=db_path,
    )

    assert result["ok"] is True
    assert result["code"] == "database_not_found"
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_guest_job_cancellation_and_delete_leave_other_guest_unchanged(monkeypatch, tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", db_path)
    target = job_service.create_job(
        "recipe-import",
        guest_session_id="expired-guest",
        job_id="target-job",
    )
    unrelated = job_service.create_job(
        "recipe-import",
        guest_session_id="active-guest",
        job_id="unrelated-job",
    )

    cancellation = job_service.request_guest_job_cancellation("expired-guest")
    deleted = job_service.delete_guest_jobs("expired-guest")

    assert cancellation["ok"] is True
    assert cancellation["jobs"][0]["status"] == "cancelled"
    assert deleted == 1
    assert job_service.get_job(target["id"]) is None
    assert job_service.get_job(unrelated["id"])["status"] == "queued"


def test_worker_refuses_job_for_expired_or_purging_guest(monkeypatch, tmp_path):
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    guest_session_service.save_guest_sessions({
        "guest_sessions": [{
            "id": "purging-guest",
            "session_id": "purging-guest",
            "created_at": "2026-08-14T00:00:00Z",
            "expires_at": "2099-08-15T00:00:00Z",
            "used_at": "2026-08-14T00:00:00Z",
            "is_active": False,
            "lifecycle_state": "purging",
            "temporary_data_json": {},
        }],
    })
    job_service.create_job(
        "recipe-import",
        guest_session_id="purging-guest",
        job_id="late-job",
    )

    result = job_worker.run_job("late-job")

    assert result == {
        "ok": False,
        "cancelled": True,
        "guest_session_expired": True,
    }
    assert job_service.get_job("late-job")["status"] == "cancelled"

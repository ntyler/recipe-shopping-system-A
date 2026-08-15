import json
from pathlib import Path

import pytest

from scripts import preview_durable_data_migration as cli


GUEST_ID = "0123456789abcdef0123456789abcdef"


def _environment(tmp_path):
    return {
        "SHOPPING_APP_USERS_FILE": str(tmp_path / "legacy" / "users.json"),
        "SHOPPING_APP_GUEST_SESSIONS_FILE": str(
            tmp_path / "legacy" / "guest_sessions.json"
        ),
        "SHOPPING_APP_USER_DATA_DIR": str(tmp_path / "workspaces" / "users"),
        "SHOPPING_APP_GUEST_DATA_DIR": str(tmp_path / "workspaces" / "guests"),
        "SHOPPING_APP_FEEDBACK_FILE": str(tmp_path / "legacy" / "feedback.json"),
        "SHOPPING_APP_ADMIN_SUPPORT_AUDIT_FILE": str(
            tmp_path / "legacy" / "admin_audit.json"
        ),
        "SHOPPING_APP_FEEDBACK_UPLOAD_DIR": str(tmp_path / "uploads" / "feedback"),
        "SHOPPING_APP_AVATAR_UPLOAD_DIR": str(tmp_path / "uploads" / "avatars"),
    }


def _snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            result[relative] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
        else:
            result[relative] = ("directory",)
    return result


def test_preview_is_redacted_and_does_not_create_or_change_data(tmp_path, monkeypatch):
    environment = _environment(tmp_path)
    legacy = tmp_path / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "users.json").write_text(
        json.dumps({"users": []}),
        encoding="utf-8",
    )
    (legacy / "guest_sessions.json").write_text(
        json.dumps(
            {
                "guest_sessions": [
                    {
                        "id": GUEST_ID,
                        "session_id": GUEST_ID,
                        "created_at": "2026-08-14T00:00:00Z",
                        "expires_at": "2099-08-15T00:00:00Z",
                        "used_at": "2026-08-14T01:00:00Z",
                        "is_active": True,
                        "temporary_data_json": {"private": "must-not-be-reported"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "workspaces" / "guests" / GUEST_ID).mkdir(parents=True)

    # Keep the PDF-share source inside the test boundary. It is intentionally
    # absent, which is a valid empty migration phase.
    monkeypatch.setattr(
        cli.data_migration_inventory_service,
        "EXTRACTOR_DATA_DIR",
        tmp_path / "extractor-data",
    )
    database = tmp_path / "database-must-not-be-created" / "application.sqlite3"
    before = _snapshot(tmp_path)

    report = cli.build_preview_report(
        environment=environment,
        db_path=database,
        include_entries=True,
    )

    after = _snapshot(tmp_path)
    serialized = json.dumps(report, sort_keys=True)
    assert before == after
    assert not database.exists()
    assert not database.parent.exists()
    assert report["dry_run"] is True
    assert report["write_performed"] is False
    assert report["migration_ready"] is True
    assert report["validation_counts"]["guest_sessions"] == 1
    assert report["validation_counts"]["active_unexpired_guest_sessions"] == 1
    assert report["phases"]["artifact_ownership"]["migration_ready"] is True
    assert report["validation_counts"]["blocked_artifacts"] == 0
    assert GUEST_ID not in serialized
    assert "must-not-be-reported" not in serialized
    assert str(tmp_path) not in serialized
    assert report["phases"]["application_schema"]["dry_run_plan"][
        "would_create_database"
    ] is True


def test_cli_has_no_apply_option():
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["--apply"])

    assert raised.value.code == 2


def test_require_ready_exit_status_is_machine_checkable(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "build_preview_report",
        lambda **_kwargs: {
            "command": cli.READ_ONLY_COMMAND,
            "dry_run": True,
            "migration_ready": False,
            "report_version": cli.REPORT_VERSION,
            "write_performed": False,
        },
    )

    exit_status = cli.main(["--require-ready", "--compact"])

    assert exit_status == 3
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["write_performed"] is False

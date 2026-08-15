import hashlib
import json
import sqlite3

import pytest

from PushShoppingList.services import account_data_migration_service as migration
from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor


ACCOUNT_ID = " Account / opaque 01 "
PASSWORD_HASH = "scrypt:legacy-password-hash-exact"
FIREBASE_UID = " firebase-uid-exact "
TOTP_SECRET = "JBSWY3DPEHPK3PXP"
SETUP_SECRET = "SETUPSECRETEXACT"
NOTIFICATION_TOPIC = "private-notification-topic"
NTFY_TOPIC = "private-legacy-topic"
PUSH_ENDPOINT = "https://push.example.test/private-capability"
RESET_HASH = "scrypt:reset-hash-exact"
VERIFICATION_HASH = "scrypt:verification-hash-exact"
DELETE_HASH = "scrypt:delete-hash-exact"
RECOVERY_HASH = "scrypt:recovery-hash-exact"
PHONE_HASH = "scrypt:phone-code-hash-exact"
BACKUP_HASH = "scrypt:backup-code-hash-exact"
TRUSTED_HASH = "scrypt:trusted-device-hash-exact"


def account_record(account_id=ACCOUNT_ID, email="MixedCase@Example.test "):
    return {
        "user_id": account_id,
        "first_name": "Exact",
        "last_name": "Profile",
        "username": "ExactUsername",
        "email": email,
        "account_status": "pending_email_verification",
        "auth_provider": "firebase",
        "firebase_uid": FIREBASE_UID,
        "firebase_provider_ids": ["password", "google.com"],
        "firebase_sign_in_provider": "google.com",
        "firebase_email_verified": False,
        "firebase_last_login_at": "2026-01-02T03:04:05.123456Z",
        "picture": "https://images.example.test/profile.png",
        "email_verified_at": "",
        "phone": "+15555550100",
        "phone_verified_at": "2026-01-01T00:00:00Z",
        "password_hash": PASSWORD_HASH,
        "account_verification": {
            "token_hash": VERIFICATION_HASH,
            "created_at": "2026-01-01T00:00:00Z",
            "expires_at": "2026-01-02T00:00:00Z",
        },
        "password_reset": {
            "token_hash": RESET_HASH,
            "created_at": "2026-01-01T01:00:00Z",
            "expires_at": "2026-01-01T02:00:00Z",
        },
        "phone_verification": {
            "code_hash": PHONE_HASH,
            "phone": "+15555550100",
            "created_at": "2026-01-01T01:00:00Z",
            "expires_at": "2026-01-01T01:10:00Z",
        },
        "account_delete": {
            "token_hash": DELETE_HASH,
            "created_at": "2026-01-01T02:00:00Z",
            "expires_at": "2026-01-01T03:00:00Z",
        },
        "two_factor": {
            "enabled": True,
            "secret": TOTP_SECRET,
            "enabled_at": "2026-01-01T00:00:00Z",
            "setup_confirmation_required": False,
            "setup_confirmed_at": "2026-01-01T00:01:00Z",
            "backup_codes": [{"code_hash": BACKUP_HASH, "used_at": ""}],
            "trusted_devices": [{
                "token_hash": TRUSTED_HASH,
                "created_at": "2026-01-01T00:00:00Z",
                "expires_at": "2026-02-01T00:00:00Z",
            }],
        },
        "two_factor_setup": {
            "secret": SETUP_SECRET,
            "created_at": "2026-01-01T00:00:00Z",
        },
        "two_factor_recovery": {
            "token_hash": RECOVERY_HASH,
            "created_at": "2026-01-01T04:00:00Z",
            "expires_at": "2026-01-01T04:30:00Z",
        },
        "notification_topic": NOTIFICATION_TOPIC,
        "ntfy_topic": NTFY_TOPIC,
        "notification_topic_created_at": "2026-01-01T00:00:00Z",
        "ntfy_topic_created_at": "2026-01-01T00:00:00Z",
        "notifications_enabled": True,
        "notification_preferences": {"security_alerts": True},
        "notification_devices": [{
            "key": "browser",
            "name": "Browser",
            "status": "Connected",
            "last_seen_at": "2026-01-02T00:00:00Z",
        }],
        "browser_push_subscription": {
            "endpoint": PUSH_ENDPOINT,
            "keys": {"auth": "private-auth", "p256dh": "private-p256dh"},
        },
        "browser_notification_permission": "granted",
        "browser_push_subscription_updated_at": "2026-01-02T00:00:00Z",
        "last_notification_sent": "2026-01-02T01:00:00Z",
        "last_notification_received": "2026-01-02T01:01:00Z",
        "last_test_notification": "2026-01-02T01:02:00Z",
        "avatar_path": "uploads/avatars/exact.png",
        "last_login_at": "2026-01-02T03:04:05Z",
        "admin_access_enabled": True,
        "created_at": "2025-12-31T23:59:59.987654Z",
        "updated_at": "2026-01-02T03:04:06.654321Z",
    }


def write_users(path, users, *, bom=True):
    raw = json.dumps({"users": users}, ensure_ascii=False, indent=2).encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw
    path.write_bytes(raw)
    return raw


def test_preview_accepts_utf8_bom_and_reports_security_requirements_without_values(
    tmp_path,
):
    users_path = tmp_path / "users.json"
    raw = write_users(users_path, [account_record()])

    preview = migration.preview_account_data_migration(users_path)

    assert preview.ready is True
    assert preview.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert preview.account_count == 1
    assert preview.accounts_requiring_encryption == 1
    assert preview.secret_field_counts == {
        "browser_push_subscription": 1,
        "notification_topic": 1,
        "ntfy_topic": 1,
        "two_factor.secret": 1,
        "two_factor_setup.secret": 1,
    }
    assert preview.preserved_hash_counts == {
        "account_delete.token_hash": 1,
        "account_verification.token_hash": 1,
        "password_hash": 1,
        "password_reset.token_hash": 1,
        "phone_verification.code_hash": 1,
        "two_factor.backup_codes.code_hash": 1,
        "two_factor.trusted_devices.token_hash": 1,
        "two_factor_recovery.token_hash": 1,
    }
    report = json.dumps(preview.to_dict(), sort_keys=True)
    for private_value in (
        TOTP_SECRET,
        SETUP_SECRET,
        NOTIFICATION_TOPIC,
        NTFY_TOPIC,
        PUSH_ENDPOINT,
        PASSWORD_HASH,
        RESET_HASH,
    ):
        assert private_value not in report


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        (
            b'{"users":[{"user_id":"first","user_id":"second"}]}',
            "duplicate_json_key",
        ),
        (
            b'{"users":[{"user_id":"account","api_token":"raw-secret"}]}',
            "unknown_account_field",
        ),
        (b'{"users":[{"user_id":"account","created_at":NaN}]}', "invalid_json_value"),
        (b'{"users":{}}', "users_not_array"),
    ],
)
def test_preview_fails_closed_on_ambiguous_or_unclassified_source(
    tmp_path,
    raw,
    error_code,
):
    users_path = tmp_path / "users.json"
    users_path.write_bytes(raw)

    preview = migration.preview_account_data_migration(users_path)

    assert preview.ready is False
    assert preview.status == "invalid"
    assert preview.error_code == error_code
    assert preview.account_count == 0


@pytest.mark.parametrize(
    ("alias_kind", "error_code"),
    [
        ("username", "duplicate_normalized_username"),
        ("cross_login", "duplicate_login_identity"),
        ("firebase", "duplicate_firebase_uid"),
        ("phone", "duplicate_phone_identity"),
    ],
)
def test_preview_rejects_ambiguous_legacy_login_and_recovery_aliases(
    tmp_path,
    alias_kind,
    error_code,
):
    users_path = tmp_path / "users.json"
    first = account_record(account_id="first", email="first@example.test")
    first.update({
        "username": "first-user",
        "firebase_uid": "firebase-first",
        "phone": "+13175550100",
    })
    second = account_record(account_id="second", email="second@example.test")
    second.update({
        "username": "second-user",
        "firebase_uid": "firebase-second",
        "phone": "+13175550101",
    })

    if alias_kind == "username":
        first["username"] = " Shared Login "
        second["username"] = "shared login"
    elif alias_kind == "cross_login":
        first["username"] = " second@example.test "
    elif alias_kind == "firebase":
        first["firebase_uid"] = " firebase-shared "
        second["firebase_uid"] = "firebase-shared"
    elif alias_kind == "phone":
        first["phone"] = "+1 (317) 555-0199"
        second["phone"] = "3175550199"

    write_users(users_path, [first, second])
    preview = migration.preview_account_data_migration(users_path)

    assert preview.ready is False
    assert preview.error_code == error_code
    assert preview.account_count == 0
    report = json.dumps(preview.to_dict(), sort_keys=True)
    assert "Shared Login" not in report
    assert "firebase-shared" not in report
    assert "3175550199" not in report


def decrypted_secrets(account, encryptor):
    return encryptor.decrypt_json(
        migration.canonical_json(account["encrypted_secrets"]),
        associated_data=migration.account_secret_associated_data(account["id"]),
    )


def stored_plaintext(account):
    return "\n".join((
        migration.canonical_json(account["profile"]),
        migration.canonical_json(account["auth_metadata"]),
        migration.canonical_json(account["encrypted_secrets"]),
        account["password_hash"],
    ))


def test_apply_preserves_identity_and_hashes_while_encrypting_recoverable_secrets(
    tmp_path,
):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    original_bytes = write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)
    encryptor = AesGcmDataEncryptor(b"a" * 32, key_id="account-test-key-v1")

    result = migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=db_path,
        encryptor=encryptor,
    )

    assert result.inserted_accounts == 1
    assert result.unchanged_accounts == 0
    assert result.no_op is False
    assert result.validation == {
        "accounts": 1,
        "coverage": 1,
        "encrypted_accounts": 1,
        "preserved_hashes": 8,
    }
    assert users_path.read_bytes() == original_bytes

    account = application_data.get_account(ACCOUNT_ID, db_path=db_path)
    assert account["id"] == ACCOUNT_ID
    assert account["workspace_id"] == ACCOUNT_ID
    assert account["username"] == "ExactUsername"
    assert account["normalized_email"] == "mixedcase@example.test"
    assert account["status"] == "pending_email_verification"
    assert account["password_hash"] == PASSWORD_HASH
    assert account["firebase_uid"] == FIREBASE_UID
    assert account["provider"] == "firebase"
    assert account["created_at"] == "2025-12-31T23:59:59.987654Z"
    assert account["updated_at"] == "2026-01-02T03:04:06.654321Z"
    assert account["profile"]["email"] == "MixedCase@Example.test "
    assert account["encryption_key_id"] == "account-test-key-v1"

    auth = account["auth_metadata"]
    assert "secret" not in auth["two_factor"]
    assert "secret" not in auth["two_factor_setup"]
    assert auth["account_verification"]["token_hash"] == VERIFICATION_HASH
    assert auth["password_reset"]["token_hash"] == RESET_HASH
    assert auth["phone_verification"]["code_hash"] == PHONE_HASH
    assert auth["account_delete"]["token_hash"] == DELETE_HASH
    assert auth["two_factor_recovery"]["token_hash"] == RECOVERY_HASH
    assert auth["two_factor"]["backup_codes"][0]["code_hash"] == BACKUP_HASH
    assert auth["two_factor"]["trusted_devices"][0]["token_hash"] == TRUSTED_HASH

    assert decrypted_secrets(account, encryptor) == {
        "browser_push_subscription": {
            "endpoint": PUSH_ENDPOINT,
            "keys": {"auth": "private-auth", "p256dh": "private-p256dh"},
        },
        "notification_topic": NOTIFICATION_TOPIC,
        "ntfy_topic": NTFY_TOPIC,
        "two_factor": {"secret": TOTP_SECRET},
        "two_factor_setup": {"secret": SETUP_SECRET},
    }

    plaintext = stored_plaintext(account)
    for recoverable_value in (
        TOTP_SECRET,
        SETUP_SECRET,
        NOTIFICATION_TOPIC,
        NTFY_TOPIC,
        PUSH_ENDPOINT,
        "private-auth",
        "private-p256dh",
    ):
        assert recoverable_value not in plaintext

    with sqlite3.connect(db_path) as connection:
        workspace = connection.execute(
            "SELECT id, workspace_type, external_id FROM workspaces WHERE id = ?",
            (ACCOUNT_ID,),
        ).fetchone()
    assert workspace == (ACCOUNT_ID, "user", ACCOUNT_ID)


def test_apply_reuses_canonical_user_workspace_without_clobbering_it(tmp_path):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)
    application_data.install_application_schema(
        db_path=db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    with application_data.application_data_write_connection(db_path) as connection:
        application_data.ensure_workspace(
            ACCOUNT_ID,
            "user",
            ACCOUNT_ID,
            lifecycle_state="active",
            metadata={"source_kind": "durable_json"},
            source_sha256="1" * 64,
            created_at="2026-07-01T00:00:00Z",
            updated_at="2026-07-02T00:00:00Z",
            connection=connection,
        )
    with sqlite3.connect(db_path) as connection:
        before = connection.execute(
            """
            SELECT workspace_type, external_id, created_at, updated_at,
                   metadata_json, source_sha256, row_version
            FROM workspaces WHERE id = ?
            """,
            (ACCOUNT_ID,),
        ).fetchone()

    result = migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=db_path,
        encryptor=AesGcmDataEncryptor(b"i" * 32, key_id="account-test-key-v1"),
    )

    assert result.inserted_workspaces == 0
    assert result.updated_workspaces == 0
    assert result.unchanged_workspaces == 1
    with sqlite3.connect(db_path) as connection:
        after = connection.execute(
            """
            SELECT workspace_type, external_id, created_at, updated_at,
                   metadata_json, source_sha256, row_version
            FROM workspaces WHERE id = ?
            """,
            (ACCOUNT_ID,),
        ).fetchone()
    assert after == before


def test_dynamic_paths_and_apply_rerun_are_idempotent(
    tmp_path,
    monkeypatch,
):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    write_users(users_path, [account_record()])
    monkeypatch.setattr(migration.user_account_service, "USERS_FILE", users_path)
    monkeypatch.setattr(
        application_data,
        "application_data_db_path",
        lambda requested=None: requested if requested is not None else db_path,
    )
    preview = migration.preview_account_data_migration()
    assert not db_path.exists()
    encryptor = AesGcmDataEncryptor(b"b" * 32, key_id="account-test-key-v1")

    first = migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        encryptor=encryptor,
    )
    first_account = application_data.get_account(ACCOUNT_ID)
    second = migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        encryptor=encryptor,
    )
    second_account = application_data.get_account(ACCOUNT_ID)

    assert first.no_op is False
    assert second.no_op is True
    assert second.inserted_accounts == 0
    assert second.unchanged_accounts == 1
    assert second.migration_run_id is None
    assert second_account["encrypted_secrets"] == first_account["encrypted_secrets"]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


@pytest.mark.parametrize(
    "wrong_encryptor",
    [
        AesGcmDataEncryptor(b"x" * 32, key_id="different-key-id"),
        AesGcmDataEncryptor(b"y" * 32, key_id="account-test-key-v1"),
    ],
)
def test_rerun_rejects_an_unavailable_or_wrong_existing_encryption_key(
    tmp_path,
    wrong_encryptor,
):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)
    original_encryptor = AesGcmDataEncryptor(
        b"f" * 32,
        key_id="account-test-key-v1",
    )
    migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=db_path,
        encryptor=original_encryptor,
    )
    before = application_data.get_account(ACCOUNT_ID, db_path=db_path)

    with pytest.raises(migration.AccountMigrationCollisionError):
        migration.apply_account_data_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=users_path,
            db_path=db_path,
            encryptor=wrong_encryptor,
        )

    after = application_data.get_account(ACCOUNT_ID, db_path=db_path)
    assert after["encrypted_secrets"] == before["encrypted_secrets"]
    assert decrypted_secrets(after, original_encryptor)["two_factor"]["secret"] == (
        TOTP_SECRET
    )


def test_rerun_authenticates_existing_ciphertext_and_rejects_tampering(tmp_path):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)
    encryptor = AesGcmDataEncryptor(b"g" * 32, key_id="account-test-key-v1")
    migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=db_path,
        encryptor=encryptor,
    )

    with sqlite3.connect(db_path) as connection:
        (encoded_envelope,) = connection.execute(
            "SELECT encrypted_secrets_json FROM accounts WHERE id = ?",
            (ACCOUNT_ID,),
        ).fetchone()
        envelope = json.loads(encoded_envelope)
        ciphertext = envelope["ciphertext"]
        envelope["ciphertext"] = (
            ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
        )
        connection.execute(
            "UPDATE accounts SET encrypted_secrets_json = ? WHERE id = ?",
            (migration.canonical_json(envelope), ACCOUNT_ID),
        )

    with pytest.raises(migration.AccountMigrationCollisionError):
        migration.apply_account_data_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=users_path,
            db_path=db_path,
            encryptor=encryptor,
        )


def test_source_change_during_apply_rolls_back_the_entire_transaction(tmp_path):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)
    encryptor = AesGcmDataEncryptor(b"h" * 32, key_id="account-test-key-v1")

    def mutate_source(stage, _context):
        if stage == "after_account":
            changed = account_record()
            changed["username"] = "changed-during-transaction"
            write_users(users_path, [changed])

    with pytest.raises(migration.StaleAccountMigrationPreviewError):
        migration.apply_account_data_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=users_path,
            db_path=db_path,
            encryptor=encryptor,
            failure_injector=mutate_source,
        )

    with sqlite3.connect(db_path) as connection:
        for table in (
            "workspaces",
            "accounts",
            "application_source_coverage",
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM %s" % table
            ).fetchone()[0] == 0
        schema_audit_rows = connection.execute(
            "SELECT migration_kind, status FROM migration_runs"
        ).fetchall()
    assert schema_audit_rows == [
        ("application_schema_install", "succeeded"),
        ("application_schema_upgrade", "succeeded"),
    ]


def test_stale_source_and_missing_encryption_fail_before_schema_install(
    tmp_path,
    monkeypatch,
):
    users_path = tmp_path / "users.json"
    stale_db = tmp_path / "stale.sqlite3"
    encryption_db = tmp_path / "encryption.sqlite3"
    write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)
    changed = account_record()
    changed["username"] = "changed-after-preview"
    write_users(users_path, [changed])

    with pytest.raises(migration.StaleAccountMigrationPreviewError):
        migration.apply_account_data_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=users_path,
            db_path=stale_db,
            encryptor=AesGcmDataEncryptor(b"c" * 32, key_id="v1"),
        )
    assert not stale_db.exists()

    write_users(users_path, [account_record()])
    fresh_preview = migration.preview_account_data_migration(users_path)
    monkeypatch.delenv("SHOPPING_APP_DATA_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SHOPPING_APP_DATA_ENCRYPTION_KEY_ID", raising=False)
    with pytest.raises(migration.AccountMigrationEncryptionError):
        migration.apply_account_data_migration(
            fresh_preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=users_path,
            db_path=encryption_db,
        )
    assert not encryption_db.exists()


def test_apply_requires_the_exact_approval_phrase_before_any_database_write(tmp_path):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    write_users(users_path, [account_record()])
    preview = migration.preview_account_data_migration(users_path)

    with pytest.raises(migration.AccountMigrationApprovalError):
        migration.apply_account_data_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE.lower(),
            source_path=users_path,
            db_path=db_path,
            encryptor=AesGcmDataEncryptor(b"e" * 32, key_id="v1"),
        )

    assert not db_path.exists()


def test_collision_rolls_back_accounts_inserted_earlier_in_the_same_apply(tmp_path):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "application.sqlite3"
    encryptor = AesGcmDataEncryptor(b"d" * 32, key_id="account-test-key-v1")

    original = account_record(account_id="existing", email="existing@example.test")
    original["firebase_uid"] = "firebase-existing"
    write_users(users_path, [original])
    initial_preview = migration.preview_account_data_migration(users_path)
    migration.apply_account_data_migration(
        initial_preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=db_path,
        encryptor=encryptor,
    )
    with sqlite3.connect(db_path) as connection:
        before_counts = tuple(
            connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            for table in (
                "workspaces",
                "accounts",
                "application_source_coverage",
                "migration_runs",
            )
        )

    inserted_first = account_record(account_id="new-account", email="new@example.test")
    inserted_first["firebase_uid"] = "firebase-new"
    inserted_first["phone"] = "+15555550101"
    conflicting = account_record(account_id="existing", email="existing@example.test")
    conflicting["firebase_uid"] = "firebase-existing"
    conflicting["username"] = "different-existing-content"
    write_users(users_path, [inserted_first, conflicting])
    collision_preview = migration.preview_account_data_migration(users_path)

    with pytest.raises(migration.AccountMigrationCollisionError):
        migration.apply_account_data_migration(
            collision_preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=users_path,
            db_path=db_path,
            encryptor=encryptor,
        )

    assert application_data.get_account("new-account", db_path=db_path) is None
    stored = application_data.get_account("existing", db_path=db_path)
    assert stored["username"] == "ExactUsername"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        after_counts = tuple(
            connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            for table in (
                "workspaces",
                "accounts",
                "application_source_coverage",
                "migration_runs",
            )
        )
    assert after_counts == before_counts

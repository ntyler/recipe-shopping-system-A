# Durable data migration and rollback runbook

This runbook covers the staged move of mutable, durable JSON data into the
application SQLite database. It does **not** authorize a production migration,
deployment, guest purge, or removal of a legacy file. Every apply phase requires
a separately reviewed change window and the exact approval enforced by that
phase's service.

The migration preserves JSON or object storage for caches, exports, raw
extraction snapshots, generated files, uploads, PDFs, browser profiles, and
other file artifacts. The database stores durable business records and artifact
ownership/lifecycle metadata; it does not turn generated binary content into
database blobs.

## Safety invariants

- All runtime backend flags default to `json`.
- `scripts/preview_durable_data_migration.py` has no apply option and does not
  create a database or directory. It prints counts, digests, schema status, and
  hashed workspace references only. It never prints account UUIDs, guest IDs,
  tokens, credentials, document payloads, or source paths.
- Schema changes are additive, ordered, checksummed migrations. A missing or
  incompatible checksum is a blocker, not a reason to rewrite schema history.
- Every backfill re-hashes its source after acquiring a SQLite
  `BEGIN IMMEDIATE` write lock. A source that changed after preview fails closed.
- Account IDs, guest-session IDs, workspace IDs, recipe IDs, timestamps, and
  expiration boundaries are copied verbatim. Migration code must not generate
  replacement identifiers for existing records. Cutover coverage includes a
  redacted identity manifest so a later missing migrated row fails closed;
  durable guest tombstones are the only valid substitute for purged identities.
- Legacy JSON is retained throughout preview, shadow, `db_preferred`, and
  `db_only` validation. Removing it is a later, separately approved retention
  operation.
- Raw share tokens and recoverable credentials are encrypted with AES-256-GCM;
  token lookup uses a SHA-256 digest. The encryption key is never stored in the
  database, a report, or a backup manifest.

## Data classification

Move these durable domains to SQLite: accounts and authentication metadata;
guest sessions and expiration state; guest-owned recipes and their ownership
rows; share-link metadata; cookbooks; recipes; menus; pantry inventory and
receipt history; meal plans; shopping selections, item state, and product
choices; store settings and encrypted credentials; usage; feedback; and audit
records.

Keep these as files or objects: progress/results caches; raw recipe extraction
snapshots; logs; uploads; videos; generated images/PDFs; menu PDFs; browser
profiles; exports; and other reproducible artifacts. Register owner, storage
key, checksum, size, kind, and lifecycle state in `artifacts` when an artifact
must participate in guest deletion.

## Runtime backend modes

Four independent environment variables control cutover:

| Domain | Environment variable | Allowed modes |
| --- | --- | --- |
| Accounts/auth | `SHOPPING_APP_ACCOUNT_BACKEND` | `json`, `shadow`, `db_preferred`, `db_only` |
| Guest sessions | `SHOPPING_APP_GUEST_SESSION_BACKEND` | `json`, `shadow`, `db_preferred`, `db_only` (`legacy` is a compatibility alias) |
| PDF share links | `SHOPPING_APP_PDF_SHARE_BACKEND` | `json`, `shadow`, `db_preferred`, `db_only` |
| Other durable documents | `SHOPPING_APP_DURABLE_DATA_BACKEND` | `json`, `shadow`, `db_preferred`, `db_only` |

Mode behavior:

- `json`: legacy files are authoritative. This is the default and immediate
  pre-cutover rollback setting.
- `shadow`: reads remain on JSON; writes update JSON and attempt the database.
  Inspect structured shadow-write failures and re-run the relevant backfill
  before proceeding. Guest-session shadow mutations use the registry file lock,
  an atomic file replacement, and a SQLite transaction; other domains use
  coverage to prevent cutover after a missed shadow update.
- `db_preferred`: read/write from the database only when source coverage proves
  that the exact document or registry is authoritative. An uninitialized source
  falls back to JSON; ambiguous or incompatible state fails closed.
- `db_only`: require a compatible schema and complete authoritative rows. There
  is no JSON fallback.

Change one domain at a time. Restart every web and worker process after a flag
change so all processes use the same mode. Do not run mixed backend modes for
the same domain across instances.

## Phase 0: maintenance window and verified backups

1. Choose a staging copy first. Record the source revision, deployed commit,
   SQLite path (`SHOPPING_APP_RECIPE_MASTER_DB`), jobs database path
   (`SHOPPING_APP_JOBS_DB`), object-storage bucket/versioning state, and all
   legacy source roots.
2. Stop or drain application writers, scheduled guest cleanup, workers, and
   queue consumers. A Python `RLock` protects only one process; the SQLite write
   lock protects database writers but cannot freeze unrelated JSON writers.
3. Create an online SQLite backup with SQLite's backup API or the `sqlite3`
   `.backup` command. Do not byte-copy a live WAL database. Back up the jobs
   database separately if it is a different file.
4. Copy every legacy JSON/text source and owned artifact tree into a dated,
   immutable backup location. Preserve relative paths and timestamps. Create a
   manifest containing relative path, byte count, and SHA-256 checksum. Do not
   put raw content, UUIDs, tokens, or credentials in the manifest.
5. Snapshot/version the corresponding object-storage prefixes. Verify that the
   service identity can restore versions, not only create new objects.
6. Back up the encryption key in the approved secrets system, separately from
   database/file backups. `SHOPPING_APP_DATA_ENCRYPTION_KEY` must decode from
   URL-safe base64 to exactly 32 bytes; set a stable
   `SHOPPING_APP_DATA_ENCRYPTION_KEY_ID` for rotation/auditability.
7. Restore the database, one JSON sample set, and one object version into an
   isolated directory/bucket and verify their checksums. A backup that has not
   been restore-tested does not satisfy this approval prerequisite.

Keep the application in `json` mode during this phase.

## Phase 1: read-only inventory and schema preview

Run from the repository root. Supplying `--database` is recommended so the
operator report cannot inspect an unintended default:

```powershell
python scripts/preview_durable_data_migration.py `
  --database "D:\staging\recipe_master.sqlite3" `
  --require-ready
```

Use the source override flags when validating a restored staging copy. Add
`--include-entries` only when document-level investigation is needed; entries
contain hashed workspace references but no payloads. Exit status `3` means the
report was produced but has a blocker. Exit status `2` means preflight itself
failed. The report always contains `dry_run: true` and
`write_performed: false`.

Archive the report as change evidence. Resolve all blocking inventory issues,
including unmapped user directories, invalid registries, document-key
collisions, encryption configuration, incompatible schema/checksums, and
unexpected sensitive fields. Do not “fix” an identity by renaming it during
migration.

## Migration phases and approval gates

Apply exactly one phase per reviewed operation. Re-run and archive the complete
preview immediately before each apply. The implementation services enforce the
following exact inner approval phrases:

| Order | Phase | Apply entry point | Exact inner approval |
| --- | --- | --- | --- |
| 1 | Additive schema | `application_data_service.install_application_schema` | `INSTALL APPLICATION DATA SCHEMA` plus `dry_run=False` and `authorized=True` |
| 2 | Accounts/auth | `account_data_migration_service.apply_account_data_migration` | `APPLY ACCOUNT DATA MIGRATION` |
| 3 | Guest sessions | `guest_session_migration_service.apply_guest_session_migration` | `APPLY GUEST SESSION MIGRATION` |
| 4 | Guest-owned recipe/durable documents | `durable_data_migration_service.apply_durable_data` with only reviewed guest source keys | `APPLY DURABLE JSON MIGRATION` |
| 5 | Artifact ownership metadata | `artifact_ownership_service.apply_artifact_ownership` | `APPLY ARTIFACT OWNERSHIP BACKFILL` |
| 6 | PDF share links | `pdf_share_migration_service.apply_pdf_share_migration` | `APPLY PDF SHARE MIGRATION` |
| 7 | Remaining durable documents | `durable_data_migration_service.apply_durable_data` with only reviewed source keys | `APPLY DURABLE JSON MIGRATION` |
| Later | One expired guest purge | `guest_purge_service.purge_guest_session` | `PURGE EXPIRED GUEST DATA` plus `dry_run=False` and `authorized=True` |

There is intentionally no broad “apply everything” CLI. The change runner must
name one phase, provide the reviewed preview object, use the explicit database
path, and pass the service's approval. Never import a preview saved days earlier:
rebuild it in the same controlled run so the source-hash recheck is meaningful.

### 1. Additive schema

Install the ordered pending versions only after the dry-run plan reports a
compatible existing layout. The installer holds a SQLite
`BEGIN IMMEDIATE` transaction and stores the immutable version checksum.

Validate:

- installed version equals the target version;
- `pending_versions` and `missing_tables` are empty;
- `checksum_matches` and `available` are true;
- `PRAGMA foreign_key_check` returns no rows.

Do not attempt a down migration. Schema rollback is restoration of the verified
pre-phase SQLite backup to a separate path, followed by an explicit path switch.

### 2. Accounts and authentication metadata

Inject the configured AES-GCM encryptor. The backfill imports all accounts in
one transaction, preserves account UUIDs and one-way password/token/device
hashes, and encrypts recoverable factors and notification credentials. It does
not rewrite `users.json`.

Validate the apply result and database counts:

- source account count equals `accounts` count and account coverage count;
- inserted plus unchanged equals preview account count;
- encryption-required count equals encrypted account count;
- preserved-hash counts match the preview;
- a sample of existing UUIDs is byte-for-byte equal before/after;
- login, password reset, two-factor, trusted-device, Firebase, and notification
  tests pass against the staging copy.

### 3. Guest sessions and expiration

Supply the guest migration's backup callback so it creates and re-verifies a
byte-identical registry backup. The source is rechecked after the write lock is
held. Existing session IDs, guest IDs, `created_at`, `used_at`, `expires_at`,
active flags, and temporary-data ownership are preserved. A newer database
`used_at` may be preserved to avoid moving activity backward; expiration is
never extended.

Validate:

- session count, active count, inactive count, and expired count match preview;
- the apply result's `active_unexpired_count` and
  `active_unexpired_sha256` exactly match preview;
- registry coverage has the exact source SHA-256;
- active browser sessions continue to resolve to their existing guest UUID;
- an inactive/expired session cannot be resurrected.

### 4. Guest-owned recipes, rows, and artifact ownership

Backfill each guest workspace's cookbooks, recipe documents, and related recipe
master ownership rows before enabling database reads. Apply only the reviewed
guest source keys in this operation. Then run the artifact-ownership preview and
backfill as its own approval-gated transaction. Register every local or object
artifact that must be deleted with an exact owner, immutable storage identity,
and available checksum, ETag, or version. Reject blocked references, unscoped
files, cross-workspace paths, and owners that cannot be mapped without guessing.

For each guest, compare source counts to database counts by workspace. Also
inventory recipe-master rows whose guest owner is no longer in the registry;
these are purge candidates, not records to assign to another user.

Missing artifact references are recorded in validation counts but are not
invented or registered. Shared artifacts are non-exclusive and guest purge may
remove only their ownership metadata. R2 references discovered in mutable JSON
remain non-exclusive even when the document contains a checksum, ETag, or
version: those values do not prove tenant ownership. Physical R2 deletion
requires an owner-bound trusted upload receipt, an approved object prefix, and
successful immutable metadata verification.

### 5. Share links and credentials

Run share migration only with the AES-GCM key preflight passing. The raw token
is encrypted; its SHA-256 digest remains the lookup/uniqueness key. Preserve
revocation, expiration, access count, last-access time, file ownership, and
creator ownership. Store credentials use the encrypted durable-document path.

Validate active/revoked/expired/access counts, coverage hash, encryption key ID,
and token authentication with a staging token. Never print a raw token or
decrypted credential in validation output.

### 6. Remaining durable business documents

Apply explicitly selected safe source keys in small batches. Do not select
delegated, skipped, cache, or artifact descriptors. Credential sources require
the encryptor. One transaction covers the selected document batch and its
source-coverage rows.

Compare, by domain and workspace, preview record counts with
`durable_documents` and `application_source_coverage`. Re-preview after each
batch; a second apply should be a no-op. Keep artifacts in file/object storage
and validate only their ownership metadata and checksums in SQLite.

## Validation queries and acceptance record

Run read-only queries on the explicit staging/production database path and save
counts, not row payloads:

```sql
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
SELECT COUNT(*) AS accounts FROM accounts;
SELECT lifecycle_state, COUNT(*) FROM guest_sessions GROUP BY lifecycle_state;
SELECT COUNT(*) AS share_links FROM share_links;
SELECT domain, COUNT(*) FROM durable_documents GROUP BY domain ORDER BY domain;
SELECT domain, status, COUNT(*)
  FROM application_source_coverage
 GROUP BY domain, status
 ORDER BY domain, status;
SELECT lifecycle_state, COUNT(*) FROM artifacts GROUP BY lifecycle_state;
```

The acceptance record must include:

- source and database backup manifest digests;
- preview report digests and validation counts;
- migration run IDs and source-coverage counts;
- schema version/checksum and empty foreign-key check;
- account UUID sample comparison;
- exact active-unexpired guest count/hash comparison;
- idempotent second-run/no-op results;
- application test results and shadow error count;
- approver, operator, start/end timestamps, commit, and rollback decision.

## Compatibility cutover

For each domain independently:

1. Apply and validate its backfill while runtime remains `json`.
2. Set only that domain to `shadow`. Run representative reads/writes and at
   least one full expiration boundary. Alert on any structured shadow failure.
3. Re-run the backfill. Require matching source coverage and a no-op repeat.
4. Set that domain to `db_preferred`. Validate reads for covered records and
   JSON fallback only for deliberately uninitialized sources.
5. Re-preview and reconcile counts/digests after the observation window.
6. Set that domain to `db_only` only when every required source is covered and
   restore drills have passed.

Never switch all four flags at once. Accounts and active guest sessions go
first because a bad cutover can lock users out; share tokens and credentials
follow only after encryption recovery is tested.

## Structured logging and monitoring

Migration state belongs in `migration_runs` and
`application_source_coverage`. Maintenance logs use JSON events from
`shopping_app.maintenance` with `event`, `run_id`, `phase`, `mode`, `outcome`,
integer `counts`, optional `duration_ms`, a hashed `workspace_fingerprint`,
`source_sha256`, and a stable `error_code`.

Do not log raw UUIDs, filesystem paths, JSON payloads, emails, tokens,
credentials, encryption envelopes, exception messages that may contain paths,
or object-storage secrets. Alert on failed shadow writes, stale previews,
coverage mismatches, schema checksum changes, guest-purge retries, and any
attempted tombstone resurrection.

## Transactional expired-guest deletion

Guest logout, explicit demo-access revocation, and the expiration scan revoke
access only. They intentionally retain files and rows until this saga runs, so
no legacy partial cleanup can leave orphan records.

Guest deletion is a separately approved post-migration operation. First call
`purge_guest_session(..., dry_run=True)` for one exact expired/inactive guest.
Review eligibility, target manifest digest, database/job/artifact/file counts,
and paths outside the report through the secured operator channel.

Application and recipe ownership tables must be in the same SQLite database for
the database deletion phase; otherwise the purge reports
`non_atomic_database_layout` and does not apply. The purge fences the guest,
creates a tombstone, deletes all owned application and recipe-master rows in one
`BEGIN IMMEDIATE` transaction (including orphaned recipe-master records), then
completes exact job and artifact/file targets through a persistent saga.

External queue, filesystem, and object-storage operations cannot share the
SQLite transaction. Their target state and retry information are durable. A
partial failure returns a retryable result; re-run the same guest purge. A
completed run is an idempotent no-op. Never manually delete the tombstone to
make a retry “work.”

Acceptance tests must prove all guest-owned rows/files are gone, unrelated user
and guest data is unchanged, a second cleanup is safe, every injected partial
failure can be retried, and orphaned recipe-master rows for that guest are gone.

## Rollback

Choose rollback by the furthest completed step:

- **Before `db_preferred`:** set the affected backend to `json`, restart all
  processes, and investigate. JSON is still authoritative. Database rows may be
  retained for diagnosis or the whole staging database restored.
- **After `db_preferred` or `db_only`:** stop writers first. Database-only writes
  may be newer than legacy JSON. Do not simply flip to `json`; export/reconcile
  those writes into a restored legacy tree, validate counts/digests, then change
  the flag. Alternatively restore the pre-cutover database and JSON/object
  snapshots together to a new path/prefix and atomically switch configuration.
- **Schema problem:** restore the entire verified SQLite backup. Do not edit
  `schema_versions`, delete tables, or substitute a new checksum.
- **Encryption problem:** keep the database unchanged, restore access to the
  matching key ID from the secrets system, and validate decryption in isolation.
  Re-encryption/key rotation is a separate migration.
- **Guest purge partial failure:** retry the durable saga. Do not restore only
  some database rows or files. If a completed purge must be reversed for legal
  or operational reasons, restore the coordinated pre-purge database, jobs,
  JSON, and object snapshots into an isolated environment and perform a new,
  explicitly reviewed recovery.

Record the rollback reason, last successful phase/run ID, backup manifest,
validation differences, and who authorized the rollback.

## Legacy retention and final removal

Keep legacy JSON read-only for an agreed retention window that includes backup
restore testing and at least one full guest-expiration/cleanup cycle. Restrict
permissions because legacy account, share, and credential files may contain
plaintext secrets. Continue checksumming them so unexpected post-cutover writes
are detected.

Removal requires a new explicit approval naming exact files/prefixes, a final
`db_only` coverage report, legal/retention confirmation, and a verified archival
backup. Prefer a recoverable quarantine move before deletion. Never recursively
delete a workspace root, object bucket, broad environment-variable target, or
legacy file set as part of the migration apply itself.

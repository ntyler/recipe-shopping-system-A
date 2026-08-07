# Phase 4D owner-authenticated read canary

This runner is code-only and disabled by default. It does not authorize a live
canary, a feature-flag change, an application restart, or structured UI/write
enablement.

## Security model

The runner is a first-party page served by the existing application. The owner
signs in through the normal account flow and must deliberately press **Start**.
The browser then performs normal same-origin `GET /api/recipe` requests. The
runner never reads `document.cookie`, local storage, session storage,
authentication headers, or browser-session state.

The Flask authentication middleware remains authoritative. The canary route
derives its tenant only from the validated registered-user session and rejects
guest, signed-out, wrong-tenant, and non-allowlisted requests. A signed,
short-lived correlation token binds the run to the tenant, manifest, expiry,
recipe ordinal, source hash, and approved structured-state fingerprint. The
token cannot authenticate a request without the normal application session.

Do not expose this local application through a LAN alias, tunnel, proxy, public
hostname, or alternate browser automation path merely to run the canary.

### Read-path database immutability

Store-section metadata used by `/api/recipe` is loaded through a SQLite
`mode=ro` connection with `PRAGMA query_only=ON`. Nominal reads do not run
schema setup or default-section seeding and therefore do not advance
`sqlite_sequence`. Missing databases or required tables return deterministic
in-memory defaults without creating files, tables, or rows. Explicit
administrative write paths retain their existing transactional seeding
behavior.

Phase 4D-R2B.3 extends that boundary to every recipe-master consumer reached
from a GET or logically read-only operation. Master-data pages, reference and
usage previews, unit and ingredient-type registries, duplicate-review lists,
image candidate lists, global-search lookups, editor loads, and recipe reads
open the existing database with SQLite `mode=ro` and `PRAGMA query_only=ON`.
The read connection first verifies the non-additive recipe-master schema and
fails closed when it is incomplete.

Read operations never call `ensure_recipe_master_schema`, seed canonical units
or aliases, create workspace unit/type rows, insert default store sections, or
commit a transaction. When a registry has not yet been explicitly seeded, the
UI receives the same built-in unit, ingredient-type, or store-section data from
an in-memory payload. This fallback does not create a database file or advance
`sqlite_sequence`.

Schema initialization and seeding remain available only through explicit
mutation operations. Unit/type saves, store-section administration, recipe
synchronization, migrations, and other authorized writes retain their prior
transaction boundaries and validation rules.

Recipe GETs also do not opportunistically create normalized ingredient
requirements. When the normalized ingredient synchronization ledger has no
entry for a saved recipe, the response uses the existing legacy JSON view and
leaves synchronization to an explicit save or migration operation.

## Default-off configuration

All of the following are required for one exact tenant:

- `RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_ENABLED=true`
- `RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_TENANTS=<exact-workspace-id>`
- `RECIPE_EQUIPMENT_STRUCTURED_SHADOW_ENABLED=true` and its exact allowlist
- `RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_AUDIT_DIR=<approved-local-directory>`

With structured reads disabled and a blank read allowlist, the signed plan is
`legacy_baseline`. With structured reads enabled for the exact tenant, the
signed plan is `structured_read`. A mode change invalidates the run boundary;
each mode requires a fresh page load and owner click.

Blank allowlists, wildcard entries, absent audit configuration, or a mismatch
between the session tenant and allowlist fail closed. The canary never toggles
these settings itself.

## Bounded workload

At page creation the server reads the synchronization ledger and requires the
approved Phase 4D scope: 88 recipes, 306 requirements, 337 options, no pending
requirements/options, 30 AND requirements, 31 OR requirements, 84 attributed
options, five supply options, and two facility options. Database integrity,
foreign keys, ready state, parser versions, synchronization counts, structured
fingerprints, and tenant boundaries must also pass.

One owner click performs six sequential passes over the server-controlled
88-recipe order, for exactly 528 requests in one signed selection mode.
Requests are lightly throttled and
stop on the first authentication, token, tenant, manifest, structured-state,
eligibility, fallback, equivalence, HTTP, JSON, or audit failure. **Stop safely**
aborts the active request and prevents further samples.

Each HTTP sample requires exactly one primary `editor_api` structured
observation. Nested read-only consumers such as PDF-asset hydration may emit
additional observations for the same recipe. Those ancillary observations are
accepted only when every one belongs to the authenticated tenant and expected
recipe, is eligible, has the approved structured-state fingerprint, and reports
zero fallback, pending-set, tenant, or equivalence differences. Observation
order does not matter, but a missing or duplicate primary observation—or any
malformed, cross-tenant, cross-recipe, ineligible, stale, or differing
ancillary observation—fails closed and stops the run.

## Audit contract

One append-only JSONL file is created per valid run in the configured audit
directory. It contains only the run/workspace identifiers, manifest and recipe
hashes, ordinal and sequence coverage, consumer, eligibility, fallback reason,
comparison and request latency, equivalence counters, response hashes, HTTP
status, and lifecycle summaries.

It never stores cookies, session identifiers, authorization values, passwords,
correlation tokens, response bodies, recipe bodies, browser storage, email
addresses, or arbitrary request headers. Repeated response hashes prove
determinism without retaining the response. The run summary calculates exact
coverage, duplicate samples, errors, fallbacks, differences, and p50/p95/p99
structured, handler, and browser round-trip latency.

The audit file is the only new operational output created by the runner. The
runner opens the recipe-master database in query-only mode and contains no
database, recipe-output, equipment, requirement, option, association, review,
image, or synchronization write path.

## Live-phase boundary and rollback

A separately approved live phase must verify the checkpoint, backups, database
and output fingerprints, exact process, exact allowlists, and an empty new run
audit before enabling the runner. The owner must sign in normally after any
restart and press Start; Codex must not handle authentication state.

### Future Phase 4D-R2C retry controls

The R3 restart reconciliation failed because existing browser activity changed
tenant-owned device-status and image-progress files before the canary began. A
future retry therefore requires separate authorization and all of these
additional controls:

- Perform a server-only restart with `SHOPPING_APP_OPEN_BROWSER=false`. This
  disables only the launcher's automatic URL opening; the owner performs any
  later navigation manually.
- Set
  `SHOPPING_APP_DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS=6700fb164ae645e29cc592cccc101bc7`
  for the retry. Suppression applies only to exact, validated registered
  workspace IDs. Blank, malformed, sanitized-alias, and wildcard entries never
  match or broaden its scope; other registered tenants and guests retain their
  existing behavior.
- Keep `RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_ENABLED=false` and
  `RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED=false`, with both allowlists empty,
  until the separately authorized retry procedure reaches the approved gate
  transition.
- Fingerprint the complete protected tenant-file set after server startup and
  before manual navigation, then fingerprint it again immediately after manual
  navigation and before enabling or starting the canary.
- Treat every unexplained tenant-file change as a fail-closed condition: stop
  the verified process, restore the disabled gates and empty allowlists,
  preserve evidence, and do not continue the retry.

For request-regression evidence, first run the 528-read `legacy_baseline` with
structured reads disabled. After reconciling that run, stop the exact app,
enable structured reads only for the approved tenant, restart, sign in normally
again, and run the separate 528-read `structured_read` plan. Compare server
handler and browser round-trip percentiles between those two audit files. The
structured comparison itself must also remain at or below 50 ms p95 and 100 ms
p99.

On any failure, disable structured reads and the authenticated-canary gate for
the tenant, clear their allowlists, preserve the audit evidence, verify legacy
reads, and reconcile the database and outputs before another attempt. Do not
delete synchronization rows during ordinary rollback and do not proceed to
Phase 4E without a complete approved report.

# Structured equipment Phase 4B runtime

Phase 4B installs code paths only. It does not authorize a migration, a
backfill, a review decision, a shadow request, a dual write, a structured read,
or a UI cutover.

## Default-deny gates

Each runtime capability requires both its global switch and an exact tenant in
its comma-separated allowlist:

| Capability | Global switch | Tenant allowlist |
| --- | --- | --- |
| Shadow comparison | `RECIPE_EQUIPMENT_STRUCTURED_SHADOW_ENABLED` | `RECIPE_EQUIPMENT_STRUCTURED_SHADOW_TENANTS` |
| Transactional dual write | `RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_ENABLED` | `RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_TENANTS` |
| Structured read | `RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED` | `RECIPE_EQUIPMENT_STRUCTURED_READ_TENANTS` |
| Structured UI | `RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED` | `RECIPE_EQUIPMENT_STRUCTURED_UI_TENANTS` |

Blank allowlists, wildcard entries, unknown tenants, and false global switches
all deny operation. Schema and review writes remain independently locked. The
Phase 4B UI contains no review-write endpoint and its decision controls remain
disabled.

## Read behavior

The repository selects requirements and options by both tenant and recipe. A
recipe falls back in full when the structured schema, hierarchy, ready state,
same-tenant targets, JSON attributes or metadata, synchronization ledger,
source hash, parser version, count, authored ordering, wording, optionality, or
recipe metadata cannot be validated.

AND requirements and Phase 3C-1 derived rows are grouped into their one
authored source row. OR alternatives remain options of one source row.
Recipe-authored equipment rows remain the presentation source of truth, so
their arbitrary metadata and images are preserved exactly and master-equipment
images are never injected. Supply, facility, ingredient, and instruction
classifications stay in the structured domain and do not change shopping-list
behavior or equipment registry counts.

The central recipe-output loader applies the disabled read decision after the
normalized ingredient overlay. Editor/API, display, cookbook/search, and
PDF/export consumers already converge on this loader. Shadow comparison emits
observability data but always returns the original legacy recipe object.

## Dual-write behavior

The existing master-data SQL transaction is the integration point for imports,
manual/API saves, AI and cookbook updates, image updates, and explicit master
synchronization. Identity moves and recipe deletion use dedicated hooks;
duplicate merge/delete already invokes those same sync and deletion services.

Reconciliation is incremental. Unchanged stable requirements and options keep
their approved equipment targets, aliases, attributes, classifications, and
audit records. Approved derived requirements and options remain while their
authored source row remains. Only deterministic, pre-existing, same-tenant
equipment or aliases resolve automatically. A legacy equipment row created by
the current save is excluded as a structured canonical target; uncertain new
wording becomes pending review and does not create a structured canonical row.

The synchronization ledger is populated only under the tenant-approved dual-
write gate and records the equipment/instruction source hash, parser version,
requirement count, and sync time. Reconciliation uses a savepoint so a failure
rolls back every structured change and propagates to the surrounding legacy SQL
transaction.

## Observability and rollback

Shadow events include tenant, recipe, consumer, eligibility, fallback reason,
pending identifier fingerprint, row counts, wording/order, optional, image,
connector and attribute validation differences, and latency. Structured-write
events report staged, idempotent-noop, or rolled-back outcomes.

The immediate rollback for a canary is to set the affected global switch to
`false` (or remove the tenant from its allowlist). Legacy data remains
authoritative, so disabling structured reads restores legacy presentation and
disabling dual writes stops new structured synchronization without a data
rewrite.

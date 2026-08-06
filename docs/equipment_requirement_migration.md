# Equipment requirement migration

The structured equipment model is dark-launched and additive. Importing its
services does not create tables, alter the database, or rewrite recipe JSON.

## Safety gates

All gates default to `false`:

- `RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED` shows the read-only review preview.
- `RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED` permits future structured reads.
- `RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED` permits explicit structured writes.
- `RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED` permits explicit schema installation.
- `RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED` permits future review decisions.

Schema installation additionally requires an explicit `authorized=True` call.
Requirement persistence independently requires `authorized=True`. Enabling one
gate never enables another.

## Required rollout order

1. Run the read-only preview command.
2. Review identity collisions and unresolved equipment proposals.
3. Approve the proposed migration report.
4. Back up the database and recipe-output roots.
5. Install the additive schema explicitly.
6. Run an approved, idempotent backfill.
7. Compare legacy and structured reads in shadow mode.
8. Enable dual writes, then structured reads, through separate gates.

Never run the legacy broad master-data backfill against menu output whose
recipe identity has not been reconciled.

Run the preview from the repository root:

```powershell
python scripts/preview_equipment_requirement_migration.py
```

The command supports no apply mode. It opens SQLite with `mode=ro`, enables
`PRAGMA query_only`, reads recipe JSON, prints JSON to stdout, and verifies the
database hash is unchanged before exiting.

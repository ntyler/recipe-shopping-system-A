# Recipe ingredient requirements migration

## Source of truth and compatibility

SQLite is the authoritative store for the relational ingredient hierarchy after a recipe is synchronized:

- `recipe_ingredient_requirements`: one top-level recipe requirement
- `recipe_ingredient_options`: original, recipe-choice, substitution, or custom choices
- `recipe_ingredient_option_items`: the ordered ingredient components in each choice

Rows are isolated by `user_id` and normalized `recipe_id`. The existing `ingredients` master catalog remains in use, and the legacy `recipe_ingredients` table remains synchronized for existing master-data features.

Complete recipe output JSON remains a backward-compatible export/cache. Its `ingredients` value continues to use one top-level ingredient with a flat `substitutions` array, so existing editor and frontend code can read it. When synchronized SQL data exists, application reads prefer SQL and reconstruct that legacy shape; otherwise they fall back to output JSON. `recipe_ingredients.json` remains a derived shopping/index snapshot and is never a source for option backfill. Meal and shopping-instance selections remain separate from recipe defaults.

There is no startup or deployment-time bulk production backfill. The command below is a dry-run unless `--apply` is explicitly supplied. Existing JSON-only recipes remain readable; opening or saving one recipe may lazily synchronize that recipe through the normal application flow, but it does not initiate an all-user migration.

## Ingredient Choices editor

The Ingredient Choices view uses the existing tables and compatibility shape; it requires no new schema or bulk migration. Standard ingredients remain ordinary top-level requirements. A choice group remains one requirement and is never also emitted as a standard ingredient.

- `source_text` preserves the original recipe requirement. `requirement_label` is its editable display heading; neither is a purchasable option component.
- Every explicit option is represented by one or more flat `substitutions` rows sharing `alternative_id`, `alternative_order`, and `alternative_label`. `alternative_component_order` preserves the ingredients' order within that option, including repeated ingredient names with separate quantities or preparation.
- One explicit option has `option_type: "original"`. This compatibility marker suppresses the synthetic option derived from the top-level source row; it does not require that option to be the default. Other authored options use `recipe_choice`.
- `default_option_id` selects exactly one option. The saved `preferred` and `is_default` component flags are synchronized to that ID. Shopping/meal selections can override the default without changing it.
- Quantities, units, preparation, and notes belong to each component. Missing component amounts remain unspecified, even if the source requirement contains an amount. No quantity is inherited from the group heading.

The editor requires two or more nonempty options for an authored choice group. Persistence remains compatible with older single-option and unresolved-choice records; these are not silently deleted or rewritten during bulk reads. Existing legacy alternatives become explicit bundles when edited in the new view. Saves and reopen operations continue through the existing SQL hierarchy and JSON compatibility export.

Saving recipe edits retains valid shopping-instance selections and updates their selected ingredient names and derived quantities together. If an option or group is removed, its obsolete shopping selection is cleared so the recipe's current default can apply. Editing the recipe default does not change a shopping instance that already selected another valid option.

The legacy `scaled_ingredients` cache is keyed by ingredient name and cannot represent two separate rows named, for example, `egg`. Choice scaling therefore uses selected component rows directly, leaves unspecified quantities blank, and omits ambiguous duplicate-name cache entries. Shopping quantity calculation scales those rows individually before aggregation. This requires no database migration, but callers must not treat the legacy name-keyed cache as the authoritative bundle structure.

## Before applying

Run commands from the repository root. Stop application processes before copying or restoring the database. The default database is `PushShoppingList/user_data/recipe_master.sqlite3`; use the path in `SHOPPING_APP_RECIPE_MASTER_DB` instead when that variable is set.

Make a database copy before an apply run. The migration automatically backs up candidate output JSON files, but it does not create a SQLite backup.

```powershell
Copy-Item PushShoppingList/user_data/recipe_master.sqlite3 PushShoppingList/user_data/recipe_master.pre-requirements.sqlite3
```

## Dry-run and apply

The normal Corn Spoon Bread dry-run command is:

```powershell
python -m PushShoppingList.scripts.migrate_recipe_ingredient_requirements --user-id 6700fb164ae645e29cc592cccc101bc7 --recipe-url "https://vegetablerecipes.com/corn-spoon-bread/"
```

If that reports `skipped_records: 1` because the recipe already has a sync marker, use this exact read-only validation command to project the hierarchy again:

```powershell
python -m PushShoppingList.scripts.migrate_recipe_ingredient_requirements --user-id 6700fb164ae645e29cc592cccc101bc7 --recipe-url "https://vegetablerecipes.com/corn-spoon-bread/" --force
```

Without `--apply`, `--force` only bypasses the idempotency skip check; it still performs no writes or backups. Review the JSON summary before proceeding. The forced dry-run should report one recipe scanned, 10 requirements, 12 options, 15 option items, and no malformed records.

Apply only that recipe with:

```powershell
python -m PushShoppingList.scripts.migrate_recipe_ingredient_requirements --user-id 6700fb164ae645e29cc592cccc101bc7 --recipe-url "https://vegetablerecipes.com/corn-spoon-bread/" --apply
```

Other useful scopes are:

```powershell
# One user's entire workspace (dry-run)
python -m PushShoppingList.scripts.migrate_recipe_ingredient_requirements --user-id <user-id>

# Every signed-in, guest, and local workspace (dry-run)
python -m PushShoppingList.scripts.migrate_recipe_ingredient_requirements --all-users
```

Use `--apply` only after reviewing the corresponding dry-run. Already synchronized recipes are skipped; `--force` deliberately replaces them. A one-user run may use `--data-root <recipe-extractor-data-directory>` when operating on copied fixture data. Guest and legacy scopes use `--user-id guest:<session-id>` and `--user-id local`, respectively.

## Backups and transactions

Before an apply transaction begins, every candidate output JSON file is copied to:

```text
<recipe-extractor-data-root>/requirement-migration-backups/<UTC-run-stamp>/
```

The returned `backup_files` list contains the exact paths. Migration does not rewrite the source output JSON.

A one-user apply replaces all selected requirements, options, option items, and legacy compatibility rows in one SQLite transaction. Any failure rolls back that user's entire batch. A failed audit record is written separately when possible. `--all-users` runs these transactions one workspace at a time, so a later workspace failure does not undo earlier committed workspaces.

Normal editor saves also commit the normalized hierarchy and legacy SQLite rows together before updating the JSON compatibility file. A JSON write failure is surfaced and triggers best-effort SQL compensation rather than being silently ignored.

## Verification

For Corn Spoon Bread, verify all of the following:

1. The apply summary reports `requirements_inserted: 10`, `options_inserted: 12`, `option_items_inserted: 15`, and `malformed_records: 0`.
2. Run the dry-run command again. It should scan one recipe, skip one synchronized recipe, and report zero new requirement, option, and item inserts.
3. In SQLite, the user/recipe hierarchy contains 10 requirement rows, 12 joined option rows, and 15 joined option-item rows. The normalized recipe ID is `https://vegetablerecipes.com/corn-spoon-bread` (without the trailing slash).
4. The corn requirement has two grouped choices. Cumin and onion are option components, not independent requirements.
5. Open the recipe editor and recipe view. The UI still shows 10 top-level ingredients, not 12.
6. Confirm the output JSON still has the compatible top-level ingredient plus flat `substitutions` shape and that meal/shopping contextual selections did not change the recipe default.

Every applied run is also recorded in `recipe_ingredient_requirement_migration_runs`, including its user, source root, status, timestamps, and summary.

## Rollback

The safest exact rollback is to stop the application and restore the pre-apply SQLite copy. The migration leaves the original output JSON unchanged; its timestamped copies are available if later application edits also need to be reversed.

For a logical single-recipe fallback, delete that user's rows from `recipe_ingredient_requirements` and `recipe_ingredient_requirement_sync` in one transaction. Options and option items cascade from the requirement deletion. With no sync marker, reads fall back to the existing output JSON. This logical rollback intentionally leaves the schema, master ingredient catalog, and legacy compatibility rows in place, so restore the SQLite backup when an exact pre-migration database state is required.

"""Idempotent Units category order backfill; run before serving an older database."""

import argparse
import json
import sqlite3
from pathlib import Path

from PushShoppingList.services import recipe_master_data_service as master_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=master_data.recipe_master_db_path())
    parser.add_argument("--dry-run", action="store_true", help="Report changes and roll them back.")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("The database must already exist.")
    with sqlite3.connect(str(args.database), timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        changed = master_data.migrate_workspace_unit_order(connection)
        if args.dry_run:
            connection.rollback()
    print(json.dumps({"changed_rows": changed, "dry_run": args.dry_run}))


if __name__ == "__main__":
    main()

"""Create verified backups and stage the approved additive equipment migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from PushShoppingList.services.equipment_migration_apply_service import (  # noqa: E402
    CLI_APPROVAL_PHRASE,
    stage_phase3a_migration,
)


def parser():
    value = argparse.ArgumentParser(
        description=(
            "Create verified backups, install the additive structured-equipment "
            "schema, and stage requirements without changing legacy rows."
        )
    )
    value.add_argument("--repository-root", default=str(REPOSITORY_ROOT))
    value.add_argument("--database", default="")
    value.add_argument("--backup-base", default="")
    value.add_argument(
        "--approval",
        required=True,
        help=f"Required exact approval phrase: {CLI_APPROVAL_PHRASE}",
    )
    value.add_argument("--compact", action="store_true")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    summary = stage_phase3a_migration(
        args.repository_root,
        db_path=args.database or None,
        backup_base=args.backup_base or None,
        approval_phrase=args.approval,
    )
    print(json.dumps(
        summary,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

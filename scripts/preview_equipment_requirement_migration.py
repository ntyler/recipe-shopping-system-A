"""Print the structured equipment migration preview without writing data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from PushShoppingList.services.equipment_migration_preview_service import (  # noqa: E402
    build_equipment_migration_preview,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Read the current equipment database and recipe JSON, print the "
            "proposed structured migration, and perform no writes."
        )
    )
    parser.add_argument(
        "--repository-root",
        default=str(REPOSITORY_ROOT),
        help="Repository root to inspect.",
    )
    parser.add_argument(
        "--database",
        default="",
        help="Optional recipe_master.sqlite3 path.",
    )
    parser.add_argument(
        "--review-sample-limit",
        type=int,
        default=50,
        help="Maximum unresolved proposals included in the stdout report.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = build_equipment_migration_preview(
        args.repository_root,
        db_path=args.database or None,
        review_sample_limit=max(0, args.review_sample_limit),
    )
    print(json.dumps(
        report,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Dry-run or apply the normalized recipe ingredient requirement backfill."""

import argparse
import json
from pathlib import Path

from PushShoppingList.services.recipe_ingredient_requirement_service import (
    backfill_all_recipe_ingredient_requirements,
    backfill_recipe_ingredient_requirements_for_user,
)
from PushShoppingList.services.recipe_master_data_service import scoped_recipe_user_id


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Backfill normalized ingredient requirements/options from complete "
            "recipe output JSON. The default is a no-write dry-run."
        )
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--user-id",
        help="Backfill one signed-in user id, guest:<session-id>, or local.",
    )
    scope.add_argument(
        "--all-users",
        action="store_true",
        help="Scan every registered, guest, and optional legacy workspace.",
    )
    parser.add_argument(
        "--recipe-url",
        help="Limit a one-user run to one exact normalized recipe URL.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Override the one-user recipe-extractor data directory.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the backfill. Without this flag, no DB rows or backups are written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace recipes already marked as synchronized.",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="When using --all-users, skip the local legacy workspace.",
    )
    parser.add_argument(
        "--skip-guests",
        action="store_true",
        help="When using --all-users, skip guest workspaces.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.all_users and (args.recipe_url or args.data_root):
        parser.error("--recipe-url and --data-root require a one-user run.")

    dry_run = not args.apply
    if args.all_users:
        result = backfill_all_recipe_ingredient_requirements(
            dry_run=dry_run,
            force=args.force,
            include_legacy=not args.skip_legacy,
            include_guests=not args.skip_guests,
        )
    else:
        result = backfill_recipe_ingredient_requirements_for_user(
            scoped_recipe_user_id(args.user_id),
            extractor_data_root=args.data_root,
            recipe_url=args.recipe_url,
            dry_run=dry_run,
            force=args.force,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

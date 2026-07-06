import argparse
import json

from PushShoppingList.services.recipe_master_data_service import backfill_all_recipe_master_records


def main():
    parser = argparse.ArgumentParser(
        description="Backfill user-scoped ingredient and equipment master records."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run the backfill even if the migration marker is already present.",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Skip legacy non-account recipe-extractor data.",
    )
    args = parser.parse_args()

    result = backfill_all_recipe_master_records(
        include_legacy=not args.skip_legacy,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

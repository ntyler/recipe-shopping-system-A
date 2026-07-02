import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PushShoppingList.services.pantry_service import send_due_pantry_reminders


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send due AI Pantry expiration and freeze-by reminders."
    )
    parser.add_argument(
        "--user-id",
        action="append",
        default=[],
        help="Limit reminders to one user id. Repeat for multiple users.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Reference date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print due reminders without sending notifications.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    result = send_due_pantry_reminders(
        user_ids=args.user_id,
        reference_date=args.date,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

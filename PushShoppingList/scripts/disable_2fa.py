"""Local-only break-glass helper for disabling account two-factor authentication.

Run this from the app host when an admin account is locked out. This script is
not exposed through Flask and should not be made available as a web route.
"""

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PushShoppingList.services.user_account_service import admin_disable_two_factor_for_identity  # noqa: E402
from PushShoppingList.services.user_account_service import find_user_by_identity  # noqa: E402
from PushShoppingList.services.user_account_service import is_admin_user  # noqa: E402
from PushShoppingList.services.user_account_service import public_user  # noqa: E402
from PushShoppingList.services.user_account_service import two_factor_enabled  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(
        description="Disable two-factor authentication for an account from the local app host."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--email", help="Email address of the account to unlock.")
    target.add_argument("--identity", help="Username or email address of the account to unlock.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required before the script writes changes to the account file.",
    )
    parser.add_argument(
        "--allow-non-admin",
        action="store_true",
        help="Allow unlocking a non-admin account. Omit this for admin-only break-glass use.",
    )
    parser.add_argument(
        "--reason",
        default="local emergency two-factor unlock",
        help="Short reason stored on the account record.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without changing the account file.",
    )
    return parser


def target_identity(args):
    return (args.email or args.identity or "").strip()


def print_account_preview(user):
    account = public_user(user) or {}
    print(f"Account: {account.get('email') or account.get('username') or account.get('user_id')}")
    print(f"Name: {account.get('display_name') or '(none)'}")
    print(f"Role: {account.get('role') or 'User'}")
    print(f"Two-factor enabled: {'yes' if two_factor_enabled(user) else 'no'}")


def run_dry_run(identity, allow_non_admin):
    user = find_user_by_identity(identity)

    if not user:
        print(f"No account was found for {identity}.", file=sys.stderr)
        return 1

    print_account_preview(user)

    if not is_admin_user(user) and not allow_non_admin:
        print(
            "Dry run: this non-admin account would be refused without --allow-non-admin.",
            file=sys.stderr,
        )
        return 2

    print("Dry run: no account file changes were made.")
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    identity = target_identity(args)

    if args.dry_run:
        return run_dry_run(identity, args.allow_non_admin)

    if not args.confirm:
        parser.error("add --confirm to write this two-factor unlock")

    result = admin_disable_two_factor_for_identity(
        identity,
        allow_non_admin=args.allow_non_admin,
        reason=args.reason,
    )

    if not result.get("ok"):
        for error in result.get("errors", ["Two-factor unlock failed."]):
            print(error, file=sys.stderr)
        return 1

    user = result.get("user") or {}
    print(f"Account: {user.get('email') or user.get('username') or identity}")
    print(f"Role: {user.get('role') or 'User'}")

    if result.get("changed"):
        print("Two-factor authentication was disabled.")
    else:
        print("Two-factor authentication was already disabled.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

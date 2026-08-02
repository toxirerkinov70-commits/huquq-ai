"""Put an account on the owner plan by hand.

The owner plan is normally granted on sight of a configured owner email, which only
works for someone who signed in with Google. An account registered by phone has no
email, so this exists to grant it directly — and to take it back.

    python scripts/grant_owner.py --phone 901234567
    python scripts/grant_owner.py --email toxirerkinov70@gmail.com
    python scripts/grant_owner.py --phone 901234567 --revoke
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db import sqlite  # noqa: E402
from backend.app.services import otp, plans  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Hisobga owner tarifini berish")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phone", help="+998 XX XXX XX XX")
    group.add_argument("--email")
    group.add_argument("--user-id")
    parser.add_argument("--revoke", action="store_true", help="bepul tarifga qaytarish")
    args = parser.parse_args()

    sqlite.init_db()

    if args.phone:
        try:
            phone = otp.normalize_phone(args.phone)
        except otp.OtpError as exc:
            print(exc.message, file=sys.stderr)
            return 2
        user = sqlite.find_user_by("phone", phone)
        needle = phone
    elif args.email:
        user = sqlite.find_user_by("email", args.email.strip().lower())
        needle = args.email
    else:
        user = sqlite.get_user(args.user_id)
        needle = args.user_id

    if user is None:
        print(f"Hisob topilmadi: {needle}", file=sys.stderr)
        print("Avval shu raqam yoki pochta bilan tizimga kiring, keyin qayta urinib ko'ring.")
        return 1

    target = "free" if args.revoke else "owner"
    sqlite.set_plan(user["id"], target, None)
    plan = plans.get(target)
    print(f"{user['id']} -> {plan.name} ({target})")
    if not args.revoke:
        print("Cheksiz savol, barcha rejimlar va vositalar ochildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

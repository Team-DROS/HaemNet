"""
Reset a donor's sign-in password.

Donors sign in with their mobile number and a password, and there is no SMS
or email recovery. When a donor forgets the password, an admin runs this
(locally with the production .env, or from the Render shell):

    python -m backend.tools.reset_donor_password 9876543210

It removes the stored password only. The donor profile, donation history and
cooldown stay. The donor then opens the app, taps "Create account" with the
same number and picks a new password.

Confirm the request came from the real owner of the number (for example by
calling that number) before resetting it.
"""

from __future__ import annotations

import asyncio
import sys

from backend.db_services import close, db_clear_donor_password
from backend.services.phone import normalise_phone


async def _main(raw: str) -> int:
    phone = normalise_phone(raw)
    if not phone:
        print(f"Not a valid mobile number: {raw}")
        return 2
    try:
        removed = await db_clear_donor_password(phone)
    finally:
        await close()
    if removed:
        print(f"Password removed for {phone}. The donor can now create a new one in the app.")
        return 0
    print(f"No password was set for {phone}; nothing to reset.")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m backend.tools.reset_donor_password <mobile number>")
        sys.exit(2)
    sys.exit(asyncio.run(_main(sys.argv[1])))

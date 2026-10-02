"""
Recover the latest OTP for an email — for local testing only.

You cannot just read the code out of the database: `email_otps` stores a
SHA-256 hash, never the code itself, so a leaked database hands an attacker
nothing. That is deliberate and worth keeping.

But a 6-digit code only has a million possibilities, so for a DEV box we can
hash all of them and find the match in about a second. That is exactly why
six digits is safe only alongside the expiry and attempt limits — not on
its own.

    python scripts/show_last_otp.py udupi@yopmail.com
    python scripts/show_last_otp.py udupi@yopmail.com --purpose login

Use it when the mail is slow, blocked, or the sending quota is exhausted.
"""
import hashlib
import os
import sys
from datetime import datetime

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings        # noqa: E402
from app.core.database import write_engine  # noqa: E402


def main() -> int:
    if settings.ENV == "production":
        print("Refusing to run with ENV=production — this is a development helper.")
        return 1

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    email = args[0].strip().lower()
    purpose = "login" if "--purpose" in sys.argv and "login" in sys.argv else None

    sql = """SELECT code_hash, purpose, expires_at, consumed_at, attempts, max_attempts, created_at
             FROM email_otps WHERE email = :e {} ORDER BY id DESC LIMIT 1"""
    sql = sql.format("AND purpose = :p" if purpose else "")
    params = {"e": email}
    if purpose:
        params["p"] = purpose

    with write_engine.connect() as conn:
        row = conn.execute(text(sql), params).first()

    if not row:
        print(f"No code has been requested for {email}.")
        print("Request one first, then run this again.")
        return 1

    code_hash, purp, expires, consumed, attempts, max_attempts, created = row

    print(f"  email     : {email}")
    print(f"  purpose   : {purp}")
    print(f"  requested : {created}")
    print(f"  expires   : {expires}", "(EXPIRED)" if expires and expires < datetime.utcnow() else "")
    print(f"  attempts  : {attempts}/{max_attempts}")
    if consumed:
        print(f"  consumed  : {consumed}  — already used, request a new one")

    print("\n  recovering the code from its hash...")
    for i in range(1_000_000):
        candidate = f"{i:06d}"
        if hashlib.sha256(candidate.encode()).hexdigest() == code_hash:
            print(f"\n  CODE: {candidate}\n")
            if consumed:
                print("  (this one is already used — it will be rejected)")
            elif expires and expires < datetime.utcnow():
                print("  (this one has expired — request a new code)")
            return 0

    print("  No match. The code may not be 6 digits, or the row is from an older format.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Seed 5 staff user accounts into MongoDB.

Passwords are read from the STAFF_PASSWORDS environment secret
(comma-separated, one per account in declaration order):

    STAFF_PASSWORDS=pass1,pass2,pass3,pass4,pass5

Run from the backend root:
    python scripts/seed_staff_users.py               # create missing accounts
    python scripts/seed_staff_users.py --update      # also update passwords for existing accounts

Each account gets role='staff', plan='free', is_admin=False.
When --update is passed, only the password_hash is changed on existing rows.
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME   = os.environ.get("DB_NAME", "syrabit")

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

STAFF_EMAILS = [
    "priya.sharma@syrabit.ai",
    "rahul.bora@syrabit.ai",
    "ananya.das@syrabit.ai",
    "kunal.bhuyan@syrabit.ai",
    "riya.gogoi@syrabit.ai",
]

STAFF_NAMES = [
    "Rohan Sahu",
    "Prakash Sahu",
    "Pari Saikia",
    "Nahida Ahmed",
    "Rashmita Sharma",
]


def _load_passwords() -> list[str]:
    raw = os.environ.get("STAFF_PASSWORDS", "").strip()
    if not raw:
        print(
            "ERROR: STAFF_PASSWORDS environment secret is not set.\n"
            "Set it as a comma-separated list of 5 passwords:\n"
            "  STAFF_PASSWORDS=pass1,pass2,pass3,pass4,pass5",
            file=sys.stderr,
        )
        sys.exit(1)
    passwords = [p.strip() for p in raw.split(",") if p.strip()]
    if len(passwords) < len(STAFF_EMAILS):
        print(
            f"ERROR: STAFF_PASSWORDS has {len(passwords)} value(s) but "
            f"{len(STAFF_EMAILS)} staff accounts are defined. "
            "Provide one password per account, comma-separated.",
            file=sys.stderr,
        )
        sys.exit(1)
    return passwords


async def seed(update_existing: bool = False):
    if not MONGO_URL:
        print("ERROR: MONGO_URL not set", file=sys.stderr)
        sys.exit(1)

    passwords = _load_passwords()

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    now = datetime.now(timezone.utc).isoformat()

    created = skipped = updated = 0
    for i, email in enumerate(STAFF_EMAILS):
        name     = STAFF_NAMES[i]
        password = passwords[i]
        pw_hash  = pwd_ctx.hash(password)

        existing = await db.users.find_one({"email": email}, {"id": 1})
        if existing:
            if update_existing:
                await db.users.update_one(
                    {"email": email},
                    {"$set": {"password_hash": pw_hash, "name": name, "updated_at": now}},
                )
                print(f"  updated  {email}  (password rehashed)")
                updated += 1
            else:
                print(f"  skip     {email}  (already exists; use --update to rehash)")
                skipped += 1
            continue

        user_id = str(uuid.uuid4())
        doc = {
            "id":                    user_id,
            "name":                  name,
            "email":                 email,
            "password_hash":         pw_hash,
            "plan":                  "free",
            "credits_used":          0,
            "credits_limit":         9999,
            "document_access":       "full",
            "onboarding_done":       True,
            "is_admin":              False,
            "role":                  "staff",
            "status":                "active",
            "bio":                   "",
            "phone":                 "",
            "saved_subjects":        [],
            "has_free_credits_issued": True,
            "consent_dpdp":          True,
            "consent_dpdp_version":  "1.0",
            "consent_dpdp_at":       now,
            "created_at":            now,
        }
        await db.users.insert_one(doc)
        print(f"  created  {email}  (id={user_id})")
        created += 1

    client.close()
    print(f"\nDone — {created} created, {updated} updated, {skipped} skipped.")


if __name__ == "__main__":
    update_flag = "--update" in sys.argv
    asyncio.run(seed(update_existing=update_flag))

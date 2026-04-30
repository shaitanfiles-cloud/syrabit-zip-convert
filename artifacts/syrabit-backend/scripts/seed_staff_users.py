#!/usr/bin/env python3
"""Seed 5 staff user accounts into MongoDB.

Run from the backend root:
    python scripts/seed_staff_users.py

Each account gets role='staff', plan='free', is_admin=False.
Existing accounts with the same email are left untouched.
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

STAFF_USERS = [
    {"name": "Rohan Sahu",      "email": "priya.sharma@syrabit.ai",  "password": "Syrabit@Staff1"},
    {"name": "Prakash Sahu",    "email": "rahul.bora@syrabit.ai",    "password": "Syrabit@Staff2"},
    {"name": "Pari Saikia",     "email": "ananya.das@syrabit.ai",    "password": "Syrabit@Staff3"},
    {"name": "Nahida Ahmed",    "email": "kunal.bhuyan@syrabit.ai",  "password": "Syrabit@Staff4"},
    {"name": "Rashmita Sharma", "email": "riya.gogoi@syrabit.ai",    "password": "Syrabit@Staff5"},
]


async def seed():
    if not MONGO_URL:
        print("ERROR: MONGO_URL not set", file=sys.stderr)
        sys.exit(1)

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    now = datetime.now(timezone.utc).isoformat()

    created = skipped = 0
    for u in STAFF_USERS:
        existing = await db.users.find_one({"email": u["email"]}, {"id": 1})
        if existing:
            print(f"  skip  {u['email']}  (already exists)")
            skipped += 1
            continue

        user_id = str(uuid.uuid4())
        pw_hash = pwd_ctx.hash(u["password"])
        doc = {
            "id":                    user_id,
            "name":                  u["name"],
            "email":                 u["email"],
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
        print(f"  created  {u['email']}  (id={user_id})")
        created += 1

    client.close()
    print(f"\nDone — {created} created, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(seed())

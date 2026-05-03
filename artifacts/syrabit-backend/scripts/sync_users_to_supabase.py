#!/usr/bin/env python3
"""Sync all local-DB users to Supabase Auth.

As of Task #156, Supabase is the sole auth provider.  The frontend login
calls supabase.auth.signInWithPassword() — so any user without a Supabase
Auth account cannot sign in.  This script creates Supabase Auth entries for
every user in the local users table who doesn't already have one, then sends
each a password-reset link so they can regain access.

Usage (run from the backend root):
    python scripts/sync_users_to_supabase.py              # live run
    python scripts/sync_users_to_supabase.py --dry-run    # preview only, no changes
    python scripts/sync_users_to_supabase.py --no-email   # create accounts, skip emails

Google OAuth users (auth_provider='google') are skipped — Supabase creates
their accounts automatically on first Google sign-in.
"""
import asyncio
import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_users_to_supabase")


async def _fetch_all_local_users(pg_pool) -> list[dict]:
    """Return every row from the local users table."""
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, name, auth_provider, is_admin, status "
            "FROM users "
            "ORDER BY created_at ASC"
        )
    return [dict(r) for r in rows]


def _fetch_all_supabase_auth_emails(supa_client) -> set[str]:
    """Return the set of emails already registered in Supabase Auth (paginated)."""
    emails: set[str] = set()
    page = 1
    per_page = 1000
    while True:
        try:
            result = supa_client.auth.admin.list_users(page=page, per_page=per_page)
            users = result if isinstance(result, list) else getattr(result, "users", result)
        except Exception as exc:
            logger.warning("list_users page %d failed: %s", page, exc)
            break
        if not users:
            break
        for u in users:
            email = getattr(u, "email", None) or (u.get("email") if isinstance(u, dict) else None)
            if email:
                emails.add(email.lower().strip())
        if len(users) < per_page:
            break
        page += 1
    return emails


def _create_supabase_user(supa_client, email: str, name: str) -> tuple[bool, str]:
    """
    Create a Supabase Auth user with email_confirm=True (no password set yet).
    Returns (success, error_message).
    """
    try:
        supa_client.auth.admin.create_user({
            "email": email,
            "email_confirm": True,
            "user_metadata": {"name": name or ""},
        })
        return True, ""
    except Exception as exc:
        msg = str(exc)
        if "already been registered" in msg or "already exists" in msg or "duplicate" in msg.lower():
            return True, "already_exists"
        return False, msg


def _generate_recovery_link(supa_client, email: str) -> str | None:
    """Generate a password-reset link for the given email. Returns the URL or None."""
    try:
        result = supa_client.auth.admin.generate_link({
            "type": "recovery",
            "email": email,
        })
        props = getattr(result, "properties", None) or {}
        link = getattr(result, "action_link", None)
        if not link and isinstance(props, dict):
            link = props.get("action_link") or props.get("hashed_token")
        return link
    except Exception as exc:
        logger.warning("generate_link failed for %s: %s", email, exc)
        return None


def _send_reset_email(to: str, name: str, reset_link: str):
    """Send a branded password-setup email via the existing email infrastructure."""
    try:
        from email_templates import _send_sync, _base, _button, _BRAND, _MUTED

        body = _base(f"""
          <h2 style="color:{_BRAND};margin:0 0 8px;">Set your Syrabit.ai password</h2>
          <p style="color:{_MUTED};margin:0 0 20px;">
            Hi {name or 'there'},
          </p>
          <p style="margin:0 0 20px;">
            We have upgraded our sign-in system. To continue using Syrabit.ai,
            please set a new password using the button below. Your study history,
            credits, and all account data are intact.
          </p>
          <p style="margin-bottom:24px;">
            {_button("Set my password", reset_link)}
          </p>
          <p style="color:{_MUTED};font-size:12px;margin:0;">
            This link expires in 24 hours. If you sign in with Google, you can
            ignore this email — your Google account is already linked.
          </p>
        """)
        _send_sync(to, "Action required: set your Syrabit.ai password", body)
    except Exception as exc:
        logger.warning("Failed to send reset email to %s: %s", to, exc)


async def run_sync(dry_run: bool = False, skip_email: bool = False):
    import asyncpg
    from supabase import create_client as _create_supa

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not supabase_url or not supabase_key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)
    if not database_url:
        logger.error("DATABASE_URL must be set")
        sys.exit(1)

    supa_client = _create_supa(supabase_url, supabase_key)
    pg_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)

    logger.info("Fetching all local users from PostgreSQL…")
    local_users = await _fetch_all_local_users(pg_pool)
    logger.info("  Found %d local users", len(local_users))

    logger.info("Fetching existing Supabase Auth users…")
    existing_emails = await asyncio.to_thread(_fetch_all_supabase_auth_emails, supa_client)
    logger.info("  Found %d users already in Supabase Auth", len(existing_emails))

    stats = {"created": 0, "skipped_google": 0, "skipped_exists": 0, "error": 0, "email_sent": 0}

    for user in local_users:
        email = (user.get("email") or "").lower().strip()
        name  = user.get("name") or ""
        provider = user.get("auth_provider") or "email"
        status   = user.get("status") or "active"

        if not email:
            logger.warning("  SKIP (no email): id=%s", user.get("id"))
            continue

        if status == "banned":
            logger.info("  SKIP (banned): %s", email)
            continue

        if provider == "google":
            logger.info("  SKIP (google oauth — handled on first login): %s", email)
            stats["skipped_google"] += 1
            continue

        if email in existing_emails:
            logger.info("  SKIP (already in Supabase Auth): %s", email)
            stats["skipped_exists"] += 1
            continue

        if dry_run:
            logger.info("  [DRY-RUN] Would create Supabase Auth user: %s", email)
            stats["created"] += 1
            continue

        ok, err = await asyncio.to_thread(_create_supabase_user, supa_client, email, name)
        if not ok:
            logger.error("  ERROR creating %s: %s", email, err)
            stats["error"] += 1
            continue

        if err == "already_exists":
            logger.info("  SKIP (already in Supabase Auth, concurrent): %s", email)
            stats["skipped_exists"] += 1
            continue

        logger.info("  CREATED Supabase Auth user: %s", email)
        stats["created"] += 1
        existing_emails.add(email)

        if skip_email:
            continue

        link = await asyncio.to_thread(_generate_recovery_link, supa_client, email)
        if link:
            await asyncio.to_thread(_send_reset_email, email, name, link)
            logger.info("  EMAIL SENT (password-set link): %s", email)
            stats["email_sent"] += 1
        else:
            logger.warning("  Could not generate recovery link for %s", email)

    logger.info("")
    logger.info("=== Migration complete ===")
    logger.info("  Created (or would create): %d", stats["created"])
    logger.info("  Already in Supabase Auth:  %d", stats["skipped_exists"])
    logger.info("  Google OAuth (skipped):    %d", stats["skipped_google"])
    logger.info("  Errors:                    %d", stats["error"])
    if not skip_email:
        logger.info("  Password-set emails sent:  %d", stats["email_sent"])
    logger.info("")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Sync local users to Supabase Auth")
    parser.add_argument("--dry-run",   action="store_true", help="Preview only — make no changes")
    parser.add_argument("--no-email",  action="store_true", help="Create accounts but skip sending emails")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    asyncio.run(run_sync(dry_run=args.dry_run, skip_email=args.no_email))


if __name__ == "__main__":
    main()

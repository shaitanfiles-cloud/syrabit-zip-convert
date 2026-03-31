"""Syrabit.ai — Payments, plan config, API config, webhooks, credit topup"""
import re, json, asyncio, time, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone, timedelta
from fastapi import (
    APIRouter, HTTPException, Depends, Query, Body, Path,
    File, UploadFile, Response, Request, Cookie, BackgroundTasks,
    Form, Header, status,
)
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr
import mistune as _mistune

from models import (
    UserCreate, UserLogin, UserOut, TokenOut, OnboardingData, ChatMessage,
    ConversationCreate, AdminLoginReq, SubjectCreate, ChapterCreate, ChunkCreate,
    DocumentUpload, ProfileUpdate, PasswordResetReq, PasswordResetConfirm,
    UserStatusUpdate, UserPlanUpdate, UserCreditsUpdate, SettingsUpdate, RoadmapItemCreate,
    LibraryBundleOut, ChatResponseOut, SearchResultOut, HealthOut, ReadyOut, ErrorOut,
)
from config import *
from deps import *
import deps
from cache import *
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────
# PLAN CONFIG
# ─────────────────────────────────────────────
DEFAULT_PLAN_CONFIG = {
    "free":    {"price": 0,   "credits": 0,    "validity": "monthly",  "doc_access": "zero"},
    "starter": {"price": 99,  "credits": 300,  "validity": "30 days",  "doc_access": "limited"},
    "pro":     {"price": 999, "credits": 4000, "validity": "365 days", "doc_access": "full"},
}

@router.get("/admin/plan-config")
async def admin_get_plan_config(admin: dict = Depends(get_admin_user)):
    saved = await db.plan_config.find_one({}, {"_id": 0})
    return saved if saved else DEFAULT_PLAN_CONFIG

@router.put("/admin/plan-config")
async def admin_update_plan_config(data: dict, admin: dict = Depends(get_admin_user)):
    await db.plan_config.replace_one({}, data, upsert=True)
    return {"message": "Plan config updated"}

@router.patch("/admin/plan-config/{plan}")
async def admin_patch_plan_tier(plan: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Safely update a single plan tier without touching other tiers."""
    if plan not in ("free", "starter", "pro"):
        raise HTTPException(status_code=400, detail="Unknown plan key")
    existing = await db.plan_config.find_one({}, {"_id": 0}) or DEFAULT_PLAN_CONFIG.copy()
    tier = {**existing.get(plan, {}), **data}
    existing[plan] = tier
    await db.plan_config.replace_one({}, existing, upsert=True)
    return {"message": f"{plan} plan updated", "tier": tier}

# ─────────────────────────────────────────────
# API CONFIG
# ─────────────────────────────────────────────
DEFAULT_API_CONFIG = {
    "groq":        {"key": ""},
    "payment":     {"razorpay_key_id": "", "razorpay_key_secret": "", "razorpay_webhook_secret": ""},
    "email":       {"resend_key": ""},
    "push":        {"onesignal_key": ""},
    "analytics":   {"posthog_key": ""},
    "google_auth": {"client_id": "", "client_secret": "", "enabled": False},
    "supabase":    {"url": "", "service_key": "", "anon_key": ""},
}

@router.get("/admin/api-config")
async def admin_get_api_config(admin: dict = Depends(get_admin_user)):
    saved = await db.api_config.find_one({}, {"_id": 0})
    return saved if saved else DEFAULT_API_CONFIG

@router.put("/admin/api-config")
async def admin_update_api_config(data: dict, admin: dict = Depends(get_admin_user)):
    existing = await db.api_config.find_one({}, {"_id": 0})
    if existing:
        for key in data:
            if isinstance(data[key], dict) and isinstance(existing.get(key), dict):
                existing[key] = {**existing[key], **data[key]}
            else:
                existing[key] = data[key]
        await db.api_config.replace_one({}, existing, upsert=True)
    else:
        merged = {**DEFAULT_API_CONFIG, **data}
        await db.api_config.replace_one({}, merged, upsert=True)
    return {"message": "API config updated"}

# ─────────────────────────────────────────────
# RAZORPAY PAYMENT INTEGRATION
# ─────────────────────────────────────────────
async def _get_razorpay_keys() -> tuple[str, str, str]:
    """Read Razorpay keys from admin api-config stored in MongoDB.
    Returns (key_id, key_secret, webhook_secret).
    Each value is resolved independently: admin config first, then env var fallback."""
    cfg = await db.api_config.find_one({}, {"_id": 0})
    payment = cfg.get("payment", {}) if cfg else {}
    key_id = payment.get("razorpay_key_id", "").strip() or os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = payment.get("razorpay_key_secret", "").strip() or os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    webhook_secret = payment.get("razorpay_webhook_secret", "").strip() or os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
    return key_id, key_secret, webhook_secret

PLAN_PRICES_INR = {"starter": 9900, "pro": 99900}  # amount in paise (₹99 = 9900 paise)
PLAN_CREDITS    = {"starter": 300, "pro": 4000}
PLAN_DOC_ACCESS = {"starter": "limited", "pro": "full"}
PLAN_RANK_MAP   = {"free": 0, "starter": 1, "pro": 2}

class PaymentOrderRequest(BaseModel):
    plan: str  # "starter" or "pro"

class PaymentVerifyRequest(BaseModel):
    razorpay_order_id:   str
    razorpay_payment_id: str
    razorpay_signature:  str
    plan: str

@router.post("/payments/create-order")
async def create_payment_order(body: PaymentOrderRequest, user: dict = Depends(get_current_user)):
    """Create a Razorpay order for the given plan."""
    plan = body.plan.lower()
    if plan not in PLAN_PRICES_INR:
        raise HTTPException(400, f"Invalid plan '{plan}'. Choose 'starter' or 'pro'.")

    # Prevent purchasing a lower-tier plan (downgrade)
    user_plan = user.get("plan", "free")
    if PLAN_RANK_MAP.get(plan, 0) < PLAN_RANK_MAP.get(user_plan, 0):
        raise HTTPException(400, f"You are already on the {user_plan.capitalize()} plan or higher. You cannot purchase a lower-tier plan.")

    key_id, key_secret, _ = await _get_razorpay_keys()
    if not key_id or not key_secret:
        raise HTTPException(503, "Payment gateway not configured. Please contact admin@syrabit.ai.")

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.create({
            "amount":   PLAN_PRICES_INR[plan],
            "currency": "INR",
            "receipt":  f"syrabit_{user['id']}_{plan}_{int(time.time())}",
            "notes": {
                "user_id": str(user["id"]),
                "plan":    plan,
            },
        })
        return {
            "order_id":   order["id"],
            "amount":     order["amount"],
            "currency":   order["currency"],
            "key_id":     key_id,
            "plan":       plan,
            "plan_label": plan.capitalize(),
        }
    except Exception as e:
        logger.error(f"Razorpay create-order error: {e}")
        raise HTTPException(502, "Failed to create payment order. Please try again.")

@router.post("/payments/verify")
async def verify_payment(body: PaymentVerifyRequest, user: dict = Depends(get_current_user)):
    """Verify Razorpay payment signature and activate the plan."""
    plan = body.plan.lower()
    if plan not in PLAN_PRICES_INR:
        raise HTTPException(400, f"Invalid plan '{plan}'.")

    # Safety: block activating a lower-tier plan than the user already has
    user_plan = user.get("plan", "free")
    if PLAN_RANK_MAP.get(plan, 0) < PLAN_RANK_MAP.get(user_plan, 0):
        raise HTTPException(400, f"Cannot activate a lower-tier plan. You are already on {user_plan.capitalize()}.")

    key_id, key_secret, _ = await _get_razorpay_keys()
    if not key_id or not key_secret:
        raise HTTPException(503, "Payment gateway not configured.")

    # Verify HMAC-SHA256 signature
    expected = hmac.new(
        key_secret.encode(),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, body.razorpay_signature):
        logger.warning(f"Payment signature mismatch for user {user['id']}")
        raise HTTPException(400, "Payment verification failed — invalid signature.")

    # Idempotency: check if already processed successfully
    existing = await db.payments.find_one({"razorpay_payment_id": body.razorpay_payment_id})
    if existing and existing.get("status") == "completed":
        return {"success": True, "plan": plan, "credits_added": PLAN_CREDITS[plan], "message": "Payment already processed."}

    # Server-side validation: fetch order from Razorpay and verify amount + notes
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.fetch(body.razorpay_order_id)
        order_notes = order.get("notes", {})
        order_plan = order_notes.get("plan", "")
        order_user = order_notes.get("user_id", "")
        if order_plan != plan:
            logger.warning(f"Plan mismatch: order says '{order_plan}', client says '{plan}' for user {user['id']}")
            raise HTTPException(400, "Plan mismatch — verification failed.")
        if order_user != str(user["id"]):
            logger.warning(f"User mismatch: order for '{order_user}', request from '{user['id']}'")
            raise HTTPException(400, "Order does not belong to this user.")
        if order.get("amount") != PLAN_PRICES_INR[plan]:
            logger.warning(f"Amount mismatch for user {user['id']}: expected {PLAN_PRICES_INR[plan]}, got {order.get('amount')}")
            raise HTTPException(400, "Amount mismatch — verification failed.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay order fetch error: {e}")
        raise HTTPException(502, "Could not verify order details with Razorpay.")

    # Activate plan — compensating transaction: roll back on partial failure
    user_id   = user["id"]
    credits   = PLAN_CREDITS[plan]
    doc_acc   = PLAN_DOC_ACCESS[plan]
    now_iso   = datetime.now(timezone.utc).isoformat()
    new_limit = (user.get("credits_limit") or 30) + credits
    prev_plan = user.get("plan", "free")
    prev_doc  = user.get("document_access", "none")

    payment_record = {
        "user_id":            str(user_id),
        "plan":               plan,
        "provider":           "razorpay",
        "status":             "completed",
        "amount_paise":       PLAN_PRICES_INR[plan],
        "razorpay_order_id":  body.razorpay_order_id,
        "razorpay_payment_id":body.razorpay_payment_id,
        "verified_at":        now_iso,
    }

    _payment_inserted = False
    _pg_updated       = False
    _mongo_updated    = False
    try:
        # 1. Record payment
        await db.payments.insert_one(payment_record)
        _payment_inserted = True

        # 2. Upgrade in PostgreSQL
        if deps.pg_pool:
            async with deps.pg_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE users
                          SET plan=$1, credits_limit=credits_limit+$2, document_access=$3,
                              updated_at=$4
                        WHERE id=$5""",
                    plan, credits, doc_acc, now_iso, user_id,
                )
        _pg_updated = True

        # 3. Upgrade in MongoDB
        await db.users.update_one(
            {"id": str(user_id)},
            {"$set": {"plan": plan, "document_access": doc_acc, "updated_at": now_iso},
             "$inc": {"credits_limit": credits}},
        )
        _mongo_updated = True

        # 4. Mirror to Supabase (best-effort — read fallback only)
        _supa_mirror(lambda: supa.table("users").update({
            "plan": plan, "document_access": doc_acc,
            "credits_limit": new_limit, "updated_at": now_iso,
        }).eq("id", str(user_id)).execute())

        _redis_invalidate_session(user_id)
        logger.info(f"Plan activated: user={user_id} plan={plan} credits+={credits}")
        asyncio.create_task(email_templates.send_plan_activation(
            email=user.get("email", ""),
            name=user.get("name", user.get("email", "")),
            plan=plan,
            credits=credits,
            amount_paise=PLAN_PRICES_INR[plan],
        ))
        return {
            "success": True,
            "plan":    plan,
            "credits_added": credits,
            "message": f"Welcome to {plan.capitalize()}! {credits} credits added.",
        }
    except Exception as e:
        logger.error(
            f"Plan activation error for user {user_id} "
            f"(pg={_pg_updated} mongo={_mongo_updated} payment={_payment_inserted}): {e}"
        )
        # Compensating rollback — undo only what already succeeded
        try:
            if _mongo_updated:
                await db.users.update_one(
                    {"id": str(user_id)},
                    {"$set": {"plan": prev_plan, "document_access": prev_doc, "updated_at": now_iso},
                     "$inc": {"credits_limit": -credits}},
                )
            if _pg_updated and deps.pg_pool:
                async with deps.pg_pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE users
                              SET plan=$1, credits_limit=credits_limit-$2,
                                  document_access=$3, updated_at=$4
                            WHERE id=$5""",
                        prev_plan, credits, prev_doc, now_iso, user_id,
                    )
            if _payment_inserted:
                await db.payments.update_one(
                    {"razorpay_payment_id": body.razorpay_payment_id},
                    {"$set": {"status": "failed", "fail_reason": str(e), "failed_at": now_iso}},
                )
        except Exception as rb_err:
            logger.error(
                f"ROLLBACK FAILED for user {user_id}: {rb_err} — "
                "manual reconciliation required"
            )
        raise HTTPException(
            500,
            "Payment verified but plan activation failed — changes rolled back. "
            "Contact support@syrabit.ai if you were charged.",
        )

# ─────────────────────────────────────────────
# STRIPE PAYMENT (OPTIONAL — configurable via api-config)
# ─────────────────────────────────────────────
PLAN_PRICES_USD = {"starter": 199, "pro": 1299}

async def _get_stripe_key() -> str:
    cfg = await db.api_config.find_one({}, {"_id": 0})
    if cfg:
        sk = cfg.get("payment", {}).get("stripe_secret_key", "").strip()
        if sk:
            return sk
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()

class StripeCheckoutRequest(BaseModel):
    plan: str
    success_url: str = ""
    cancel_url: str = ""

@router.post("/payments/stripe/create-checkout")
async def stripe_create_checkout(body: StripeCheckoutRequest, user: dict = Depends(get_current_user)):
    plan = body.plan.lower()
    if plan not in PLAN_PRICES_USD:
        raise HTTPException(400, f"Invalid plan '{plan}'.")
    stripe_key = await _get_stripe_key()
    if not stripe_key:
        raise HTTPException(503, "Stripe not configured.")
    try:
        import stripe
        stripe.api_key = stripe_key
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Syrabit.ai {plan.capitalize()} Plan"},
                    "unit_amount": PLAN_PRICES_USD[plan],
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=body.success_url or f"{FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=body.cancel_url or f"{FRONTEND_URL}/payment/cancel",
            metadata={"user_id": str(user["id"]), "plan": plan},
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except ImportError:
        raise HTTPException(503, "Stripe SDK not installed.")
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(502, "Failed to create Stripe checkout.")

from starlette.requests import Request as StarletteRequest2

@router.post("/webhooks/stripe")
async def stripe_webhook(request: StarletteRequest2):
    stripe_key = await _get_stripe_key()
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not stripe_key:
        raise HTTPException(503, "Stripe not configured")
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(503, "Stripe webhook secret not configured")
    try:
        import stripe
        stripe.api_key = stripe_key
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        if not sig:
            raise HTTPException(400, "Missing stripe-signature header")
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)

        if event.get("type") == "checkout.session.completed":
            session = event["data"]["object"]
            meta = session.get("metadata", {})
            user_id = meta.get("user_id")
            plan = meta.get("plan")
            stripe_session_id = session.get("id", "")
            if user_id and plan and plan in PLAN_CREDITS:
                existing = await db.payments.find_one({"stripe_session_id": stripe_session_id})
                if existing and existing.get("status") == "completed":
                    logger.info(f"Stripe duplicate event ignored: session={stripe_session_id}")
                    return {"received": True}
                credits = PLAN_CREDITS[plan]
                doc_acc = PLAN_DOC_ACCESS[plan]
                now_iso = datetime.now(timezone.utc).isoformat()
                await db.payments.insert_one({
                    "user_id": user_id,
                    "plan": plan,
                    "provider": "stripe",
                    "status": "completed",
                    "stripe_session_id": stripe_session_id,
                    "amount_cents": session.get("amount_total", 0),
                    "currency": session.get("currency", "usd"),
                    "verified_at": now_iso,
                })
                await db.users.update_one(
                    {"id": user_id},
                    {"$set": {"plan": plan, "document_access": doc_acc, "updated_at": now_iso},
                     "$inc": {"credits_limit": credits}},
                )
                if deps.pg_pool:
                    async with deps.pg_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE users SET plan=$1, credits_limit=credits_limit+$2, document_access=$3, updated_at=$4 WHERE id=$5",
                            plan, credits, doc_acc, now_iso, user_id,
                        )
                _redis_invalidate_session(user_id)
                logger.info(f"Stripe payment: user={user_id} plan={plan} credits+={credits}")
        return {"received": True}
    except ImportError:
        raise HTTPException(503, "Stripe SDK not installed.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(400, f"Webhook error: {str(e)[:100]}")

@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: StarletteRequest2):
    _, _, webhook_secret = await _get_razorpay_keys()
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(503, "Razorpay webhook secret not configured")
    try:
        raw_body = await request.body()
        rp_signature = request.headers.get("x-razorpay-signature", "")
        if not rp_signature:
            raise HTTPException(400, "Missing x-razorpay-signature header")
        expected_sig = hmac.new(
            webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, rp_signature):
            logger.warning("Razorpay webhook signature mismatch")
            raise HTTPException(400, "Invalid webhook signature")

        payload = json.loads(raw_body)
        event = payload.get("event", "")
        if event == "payment.captured":
            entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            notes = entity.get("notes", {})
            user_id = notes.get("user_id")
            plan = notes.get("plan")
            rp_payment_id = entity.get("id", "")
            if not user_id or not rp_payment_id:
                return {"received": True}
            existing = await db.payments.find_one({"razorpay_payment_id": rp_payment_id})
            if existing and existing.get("status") in ("completed", "skipped"):
                logger.info(f"Razorpay duplicate event ignored: payment={rp_payment_id}")
                return {"received": True}
            now_iso = datetime.now(timezone.utc).isoformat()
            if plan == "topup":
                topup_credits = int(notes.get("credits", 0))
                if topup_credits > 0:
                    await db.payments.insert_one({
                        "user_id": user_id,
                        "plan": "topup",
                        "provider": "razorpay",
                        "status": "completed",
                        "razorpay_payment_id": rp_payment_id,
                        "amount_paise": entity.get("amount", 0),
                        "credits_added": topup_credits,
                        "verified_at": now_iso,
                    })
                    await db.users.update_one(
                        {"id": user_id},
                        {"$set": {"updated_at": now_iso},
                         "$inc": {"credits_limit": topup_credits}},
                    )
                    if deps.pg_pool:
                        async with deps.pg_pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE users SET credits_limit=credits_limit+$1, updated_at=$2 WHERE id=$3",
                                topup_credits, now_iso, user_id,
                            )
                    _redis_invalidate_session(user_id)
                    logger.info(f"Razorpay topup webhook: user={user_id} credits+={topup_credits}")
            elif plan and plan in PLAN_CREDITS:
                credits = PLAN_CREDITS[plan]
                doc_acc = PLAN_DOC_ACCESS[plan]
                # Guard: never downgrade a user via webhook (e.g. stale event for lower tier)
                wh_user = await db.users.find_one({"id": user_id}, {"plan": 1})
                wh_current_plan = (wh_user or {}).get("plan", "free")
                if PLAN_RANK_MAP.get(plan, 0) < PLAN_RANK_MAP.get(wh_current_plan, 0):
                    logger.warning(
                        f"Razorpay webhook: skipping downgrade {wh_current_plan}→{plan} "
                        f"for user={user_id} payment={rp_payment_id} — payment logged only"
                    )
                    await db.payments.insert_one({
                        "user_id": user_id, "plan": plan, "provider": "razorpay",
                        "status": "skipped",
                        "razorpay_payment_id": rp_payment_id,
                        "amount_paise": entity.get("amount", 0),
                        "verified_at": now_iso, "activation_skipped": True,
                        "skip_reason": f"user already on higher plan ({wh_current_plan})",
                    })
                else:
                    _wh_payment_inserted = False
                    _wh_mongo_updated    = False
                    _wh_pg_updated       = False
                    try:
                        await db.payments.insert_one({
                            "user_id": user_id, "plan": plan, "provider": "razorpay",
                            "status": "completed",
                            "razorpay_payment_id": rp_payment_id,
                            "amount_paise": entity.get("amount", 0),
                            "verified_at": now_iso,
                        })
                        _wh_payment_inserted = True
                        await db.users.update_one(
                            {"id": user_id},
                            {"$set": {"plan": plan, "document_access": doc_acc, "updated_at": now_iso},
                             "$inc": {"credits_limit": credits}},
                        )
                        _wh_mongo_updated = True
                        if deps.pg_pool:
                            async with deps.pg_pool.acquire() as conn:
                                await conn.execute(
                                    "UPDATE users SET plan=$1, credits_limit=credits_limit+$2, "
                                    "document_access=$3, updated_at=$4 WHERE id=$5",
                                    plan, credits, doc_acc, now_iso, user_id,
                                )
                        _wh_pg_updated = True
                        _redis_invalidate_session(user_id)
                        logger.info(f"Razorpay webhook: user={user_id} plan={plan} credits+={credits}")
                    except Exception as wh_err:
                        logger.error(
                            f"Razorpay webhook activation failed for user={user_id} "
                            f"(mongo={_wh_mongo_updated} pg={_wh_pg_updated}): {wh_err}"
                        )
                        try:
                            if _wh_mongo_updated:
                                await db.users.update_one(
                                    {"id": user_id},
                                    {"$set": {"plan": wh_current_plan, "updated_at": now_iso},
                                     "$inc": {"credits_limit": -credits}},
                                )
                            if _wh_pg_updated and deps.pg_pool:
                                async with deps.pg_pool.acquire() as conn:
                                    await conn.execute(
                                        "UPDATE users SET plan=$1, credits_limit=credits_limit-$2, "
                                        "updated_at=$3 WHERE id=$4",
                                        wh_current_plan, credits, now_iso, user_id,
                                    )
                            if _wh_payment_inserted:
                                await db.payments.update_one(
                                    {"razorpay_payment_id": rp_payment_id},
                                    {"$set": {"status": "failed", "fail_reason": str(wh_err), "failed_at": now_iso}},
                                )
                        except Exception as rb_err:
                            logger.error(f"Webhook rollback failed user={user_id}: {rb_err}")
        return {"received": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay webhook error: {e}")
        raise HTTPException(400, "Webhook error")


# ─────────────────────────────────────────────
# CREDIT TOP-UP (returns order info — actual crediting via webhook)
# ─────────────────────────────────────────────
TOPUP_PRICES_INR = {100: 4900, 500: 19900, 1000: 34900}

class CreditTopUpRequest(BaseModel):
    credits: int
    provider: str = "razorpay"

@router.post("/payments/credit-topup")
async def credit_topup(body: CreditTopUpRequest, user: dict = Depends(get_current_user)):
    if user.get("plan", "free") == "free":
        raise HTTPException(403, "Free plan users cannot top up credits. Upgrade first.")
    if body.credits not in TOPUP_PRICES_INR:
        raise HTTPException(400, "Top-up must be 100, 500, or 1000 credits.")
    user_id = user["id"]
    amount = TOPUP_PRICES_INR[body.credits]
    if body.provider == "razorpay":
        key_id, key_secret, _ = await _get_razorpay_keys()
        if not key_id or not key_secret:
            raise HTTPException(503, "Razorpay not configured.")
        try:
            import razorpay
            client = razorpay.Client(auth=(key_id, key_secret))
            order = client.order.create({
                "amount": amount,
                "currency": "INR",
                "receipt": f"topup_{user_id}_{body.credits}_{int(time.time())}",
                "notes": {"user_id": str(user_id), "plan": "topup", "credits": str(body.credits)},
            })
            return {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": key_id,
                "credits": body.credits,
            }
        except Exception as e:
            logger.error(f"Topup order error: {e}")
            raise HTTPException(502, "Failed to create top-up order.")
    raise HTTPException(400, "Unsupported provider. Use 'razorpay'.")


class CreditTopUpVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    credits: int

@router.post("/payments/credit-topup/verify")
async def credit_topup_verify(body: CreditTopUpVerifyRequest, user: dict = Depends(get_current_user)):
    # Guard: free-plan users must upgrade before they can top up credits
    if user.get("plan", "free") == "free":
        raise HTTPException(403, "Free plan users cannot top up credits. Upgrade to Starter or Pro first.")
    if body.credits not in TOPUP_PRICES_INR:
        raise HTTPException(400, "Invalid top-up amount.")
    key_id, key_secret, _ = await _get_razorpay_keys()
    if not key_id or not key_secret:
        raise HTTPException(503, "Payment gateway not configured.")
    expected = hmac.new(
        key_secret.encode(),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(400, "Payment verification failed — invalid signature.")
    user_id = user["id"]
    existing = await db.payments.find_one({"razorpay_payment_id": body.razorpay_payment_id})
    if existing and existing.get("status") == "completed":
        return {"success": True, "credits_added": body.credits, "message": "Credits already applied."}
    # Server-side validation: verify order amount, user, and credits from Razorpay
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.fetch(body.razorpay_order_id)
        order_notes = order.get("notes", {})
        order_credits = int(order_notes.get("credits", 0))
        order_user = order_notes.get("user_id", "")
        if order_user != str(user_id):
            raise HTTPException(400, "Order does not belong to this user.")
        if order_credits != body.credits:
            logger.warning(f"Topup credits mismatch: order={order_credits}, client={body.credits}")
            raise HTTPException(400, "Credits mismatch — verification failed.")
        if order.get("amount") != TOPUP_PRICES_INR[body.credits]:
            raise HTTPException(400, "Amount mismatch — verification failed.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay order fetch error (topup): {e}")
        raise HTTPException(502, "Could not verify order details with Razorpay.")
    # Apply credits — compensating transaction: roll back on partial failure
    now_iso   = datetime.now(timezone.utc).isoformat()
    new_limit = (user.get("credits_limit") or 0) + body.credits

    _tu_payment_inserted = False
    _tu_pg_updated       = False
    _tu_mongo_updated    = False
    try:
        # 1. Record payment
        await db.payments.insert_one({
            "user_id": str(user_id),
            "plan": "topup",
            "provider": "razorpay",
            "status": "completed",
            "razorpay_order_id": body.razorpay_order_id,
            "razorpay_payment_id": body.razorpay_payment_id,
            "amount_paise": TOPUP_PRICES_INR[body.credits],
            "credits_added": body.credits,
            "verified_at": now_iso,
        })
        _tu_payment_inserted = True

        # 2. Update PostgreSQL
        if deps.pg_pool:
            async with deps.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET credits_limit=credits_limit+$1, updated_at=$2 WHERE id=$3",
                    body.credits, now_iso, user_id,
                )
        _tu_pg_updated = True

        # 3. Update MongoDB
        await db.users.update_one(
            {"id": str(user_id)},
            {"$set": {"updated_at": now_iso},
             "$inc": {"credits_limit": body.credits}},
        )
        _tu_mongo_updated = True

        # 4. Mirror to Supabase (best-effort — non-critical)
        _supa_mirror(lambda: supa.table("users").update({
            "credits_limit": new_limit, "updated_at": now_iso,
        }).eq("id", str(user_id)).execute())

        _redis_invalidate_session(user_id)
        logger.info(f"Credit top-up verified: user={user_id} credits+={body.credits}")
        asyncio.create_task(email_templates.send_topup_confirmation(
            email=user.get("email", ""),
            name=user.get("name", user.get("email", "")),
            credits=body.credits,
            amount_paise=TOPUP_PRICES_INR[body.credits],
        ))
        return {
            "success": True,
            "credits_added": body.credits,
            "message": f"{body.credits} credits added to your account!",
        }
    except Exception as e:
        logger.error(
            f"Topup credit error for user {user_id} "
            f"(pg={_tu_pg_updated} mongo={_tu_mongo_updated} payment={_tu_payment_inserted}): {e}"
        )
        # Compensating rollback
        try:
            if _tu_mongo_updated:
                await db.users.update_one(
                    {"id": str(user_id)},
                    {"$set": {"updated_at": now_iso},
                     "$inc": {"credits_limit": -body.credits}},
                )
            if _tu_pg_updated and deps.pg_pool:
                async with deps.pg_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE users SET credits_limit=credits_limit-$1, updated_at=$2 WHERE id=$3",
                        body.credits, now_iso, user_id,
                    )
            if _tu_payment_inserted:
                await db.payments.update_one(
                    {"razorpay_payment_id": body.razorpay_payment_id},
                    {"$set": {"status": "failed", "fail_reason": str(e), "failed_at": now_iso}},
                )
        except Exception as rb_err:
            logger.error(f"Topup rollback failed for user {user_id}: {rb_err} — manual reconciliation needed")
        raise HTTPException(
            500,
            "Payment verified but credit application failed — changes rolled back. "
            "Contact support@syrabit.ai if you were charged.",
        )


# ─────────────────────────────────────────────
# USAGE TRACKING
# ─────────────────────────────────────────────
@router.get("/usage/me")
async def get_my_usage(user: dict = Depends(get_current_user)):
    credits_info = await get_user_credits(user)
    convs = await supa_get_conversations(user["id"])
    return {
        "user_id": user["id"],
        "plan": user.get("plan", "free"),
        "credits_used": credits_info["used"],
        "credits_limit": credits_info["limit"],
        "credits_remaining": credits_info["remaining"],
        "conversations": len(convs) if convs else 0,
    }

@router.get("/admin/usage/summary")
async def admin_usage_summary(admin: dict = Depends(get_admin_user)):
    total_users = await supa_count_users()
    total_convs = await supa_count_conversations()
    payments = await db.payments.find({}, {"_id": 0}).sort("verified_at", -1).to_list(1000)
    total_revenue_inr = sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe")
    total_revenue_usd = sum(p.get("amount_cents", 0) for p in payments if p.get("provider") == "stripe")
    return {
        "total_users": total_users,
        "total_conversations": total_convs,
        "total_payments": len(payments),
        "revenue_inr_paise": total_revenue_inr,
        "revenue_usd_cents": total_revenue_usd,
        "recent_payments": payments[:20],
    }

@router.post("/admin/supabase/test")
async def admin_test_supabase(data: dict, admin: dict = Depends(get_admin_user)):
    url = data.get("url", "").strip()
    service_key = data.get("service_key", "").strip()
    if not url or not service_key:
        return {"ok": False, "error": "URL and Service Key are required"}
    try:
        test_client = _create_supa(url, service_key)
        test_client.table("users").select("id").limit(1).execute()
        return {"ok": True, "message": "Connected to Supabase successfully"}
    except Exception as e:
        err = str(e)
        if "401" in err or "Invalid API key" in err:
            return {"ok": False, "error": "Invalid API key — check your service_role key"}
        return {"ok": False, "error": f"Connection failed: {err[:200]}"}

@router.post("/admin/supabase/apply")
async def admin_apply_supabase(data: dict, admin: dict = Depends(get_admin_user)):
    global supa, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY
    url = data.get("url", "").strip()
    service_key = data.get("service_key", "").strip()
    anon_key = data.get("anon_key", "").strip()
    if not url or not service_key:
        raise HTTPException(400, "URL and Service Key are required")
    try:
        new_client = _create_supa(url, service_key)
        new_client.table("users").select("id").limit(1).execute()
    except Exception as e:
        raise HTTPException(400, "Connection failed — check your credentials")
    try:
        existing = await db.api_config.find_one({}, {"_id": 0})
        supa_cfg = {"url": url, "service_key": service_key, "anon_key": anon_key}
        if existing:
            existing["supabase"] = supa_cfg
            await db.api_config.replace_one({}, existing, upsert=True)
        else:
            merged = {**DEFAULT_API_CONFIG, "supabase": supa_cfg}
            await db.api_config.replace_one({}, merged, upsert=True)
    except Exception as e:
        raise HTTPException(500, "Credentials verified but failed to save config")
    supa = new_client
    SUPABASE_URL = url
    SUPABASE_SERVICE_KEY = service_key
    if anon_key:
        SUPABASE_ANON_KEY = anon_key
    os.environ["SUPABASE_URL"] = url
    os.environ["SUPABASE_SERVICE_KEY"] = service_key
    if anon_key:
        os.environ["SUPABASE_ANON_KEY"] = anon_key
    logger.info("Supabase client re-initialized with new credentials")
    return {"message": "Supabase credentials applied, verified, and saved"}

# ─────────────────────────────────────────────
# CMS LIBRARY ENDPOINTS
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# MARKDOWN PROCESSING HELPERS (WordPress-style auto-format)
# ─────────────────────────────────────────────────────────────────────────────

_md_renderer = _mistune.create_markdown(
    plugins=["table", "strikethrough", "footnotes", "task_lists"],
    escape=False,
)

def _md_to_html(raw: str) -> str:
    """Convert markdown to safe HTML using mistune with GFM plugins."""
    if not raw:
        return ""
    return _md_renderer(raw) or ""

def _extract_headings_json(raw: str) -> str:
    """Return JSON array of {level, text, anchor} extracted from markdown content."""
    headings = []
    for line in raw.splitlines():
        m = re.match(r'^(#{1,3})\s+(.+)', line.strip())
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            anchor = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
            headings.append({"level": level, "text": text, "anchor": anchor})
    return json.dumps(headings)


def preprocess_markdown(md: str) -> str:
    """wpautop-equivalent: normalise line endings, expand CMS shortcodes to GFM."""
    if not md:
        return ""
    md = md.replace('\r\n', '\n').replace('\r', '\n')
    md = re.sub(r'\[PYQ\s+year=(\d{4})\]', r'> 📋 **Past Year Question (\1)**', md)
    md = re.sub(r'\[IMPORTANT\]', r'> ⚠️ **IMPORTANT**', md)
    md = re.sub(r'\[TIP\]',       r'> 💡 **TIP**',       md)
    md = re.sub(r'\[NOTE\]',      r'> 📌 **NOTE**',      md)
    md = re.sub(r'\[EXAMPLE\]',   r'> 📝 **EXAMPLE**',  md)
    return md


async def merge_subject_content(subject_id: str) -> str:
    """Aggregate a subject's chapters + chunks into a single markdown document."""
    try:
        subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        if not subject:
            return ""
        chapters = await db.chapters.find(
            {"subject_id": subject_id}, {"_id": 0}
        ).sort("chapter_number", 1).to_list(100)

        parts: list[str] = [f"# {subject.get('name', 'Subject')}\n\n"]
        if subject.get("description"):
            parts.append(f"{subject['description']}\n\n")

        for chapter in chapters:
            num   = chapter.get("chapter_number", "")
            title = chapter.get("title", "")
            heading = f"Chapter {num}: {title}" if num else title
            parts.append(f"\n## {heading}\n\n")
            if chapter.get("description"):
                parts.append(f"{chapter['description']}\n\n")
            cks = await db.chunks.find(
                {"chapter_id": chapter["id"]}, {"_id": 0}
            ).sort("order", 1).to_list(500)
            for ck in cks:
                content = (ck.get("content") or "").strip()
                if not content:
                    continue
                ctype = (ck.get("type") or "").lower()
                if ctype == "pyq":
                    parts.append(f"> 📋 **Past Year Question**\n>\n> {content}\n\n")
                elif ctype == "summary":
                    parts.append(f"### Summary\n\n{content}\n\n")
                elif ctype == "formula":
                    parts.append(f"### Formula\n\n{content}\n\n")
                else:
                    parts.append(f"{content}\n\n")

        return preprocess_markdown("".join(parts))
    except Exception as exc:
        logger.error(f"merge_subject_content({subject_id}): {exc}")
        return ""


class CMSDocument(BaseModel):
    title: str
    content: str = ""           # raw markdown (content_raw)
    content_html: Optional[str] = ""   # processed HTML (auto-generated if empty)
    meta_description: Optional[str] = ""  # 160 char SEO description
    description: Optional[str] = ""  # Long description (2000 char)
    seo_tags: Optional[str] = ""
    primary_keyword: Optional[str] = ""
    seo_slug: Optional[str] = ""
    thumbnail_url: Optional[str] = ""
    alt_text: Optional[str] = ""
    category: Optional[str] = ""  # e.g., ahsec/class12/pcm/physics
    headings: Optional[str] = ""  # JSON string of extracted headings
    geo_tags: Optional[str] = ""  # board/class/subject/topic for GEO targeting
    schema_type: Optional[str] = "Article"  # Article, FAQPage, HowTo
    status: str = "draft"

class CMSDocumentUpdate(BaseModel):
    """Partial-update model for PATCH — all fields optional."""
    title: Optional[str] = None
    content: Optional[str] = None
    content_html: Optional[str] = None
    meta_description: Optional[str] = None
    description: Optional[str] = None
    seo_tags: Optional[str] = None
    primary_keyword: Optional[str] = None
    seo_slug: Optional[str] = None
    thumbnail_url: Optional[str] = None
    alt_text: Optional[str] = None
    category: Optional[str] = None
    headings: Optional[str] = None
    geo_tags: Optional[str] = None
    schema_type: Optional[str] = None
    status: Optional[str] = None
    is_published: Optional[bool] = None


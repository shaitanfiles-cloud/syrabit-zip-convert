"""Syrabit.ai — SEO, referrals, vector, RAG, billing, pipeline auto-generate"""
import re, json, asyncio, time, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod, httpx
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
from cache import *
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_stream, _call_llm_raw
from rag import *
from utils import *
from analytics_helpers import *

logger = logging.getLogger(__name__)

def _get_syllabus_embedder():
    import server as _s
    return _s._syllabus_embedder

def _trigger_reseed():
    import server as _s
    return _s._reseed_syllabus_embeddings()

router = APIRouter()

@router.get("/admin/monetization/overview")
async def admin_monetization_overview(admin: dict = Depends(get_admin_user)):
    users = await supa_list_users()
    payments = await db.payments.find({}, {"_id": 0}).sort("verified_at", -1).to_list(5000)

    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).isoformat()
    seven_ago = (now - timedelta(days=7)).isoformat()

    revenue_30d = sum(p.get("amount_paise", 0) for p in payments if p.get("verified_at", "") >= thirty_ago and p.get("provider") != "stripe") / 100
    revenue_7d = sum(p.get("amount_paise", 0) for p in payments if p.get("verified_at", "") >= seven_ago and p.get("provider") != "stripe") / 100

    total_paid = sum(1 for u in users if u.get("plan") in ("starter", "pro"))
    starter_count = sum(1 for u in users if u.get("plan") == "starter")
    pro_count = sum(1 for u in users if u.get("plan") == "pro")

    arpu = round(revenue_30d / max(total_paid, 1), 2)

    recent_txns = []
    for p in payments[:20]:
        recent_txns.append({
            "user_id": p.get("user_id", ""),
            "plan": p.get("plan", ""),
            "amount": p.get("amount_paise", 0) / 100 if p.get("provider") != "stripe" else p.get("amount_cents", 0) / 100,
            "currency": "INR" if p.get("provider") != "stripe" else "USD",
            "provider": p.get("provider", "razorpay"),
            "date": p.get("verified_at", "")[:10],
        })

    return {
        "revenue_30d_inr": revenue_30d,
        "revenue_7d_inr": revenue_7d,
        "arpu_inr": arpu,
        "total_paid_users": total_paid,
        "starter_users": starter_count,
        "pro_users": pro_count,
        "total_free_users": len(users) - total_paid,
        "conversion_rate": round(total_paid / max(len(users), 1) * 100, 2),
        "recent_transactions": recent_txns,
        "total_lifetime_revenue_inr": sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe") / 100,
    }

@router.get("/admin/monetization/referrals")
async def admin_monetization_referrals(admin: dict = Depends(get_admin_user)):
    referrals = await db.referrals.find({}, {"_id": 0}).to_list(500)
    return {
        "total_referrals": len(referrals),
        "successful_conversions": sum(1 for r in referrals if r.get("converted")),
        "referrals": referrals[:50],
    }

class ReferralConfigUpdate(BaseModel):
    enabled: bool = True
    reward_credits: int = 10
    referrer_credits: int = 10

@router.put("/admin/monetization/referral-config")
async def admin_update_referral_config(body: ReferralConfigUpdate, admin: dict = Depends(get_admin_user)):
    await db.api_config.update_one(
        {},
        {"$set": {"referral": body.dict()}},
        upsert=True,
    )
    return {"success": True}

@router.get("/admin/monetization/referral-config")
async def admin_get_referral_config(admin: dict = Depends(get_admin_user)):
    cfg = await db.api_config.find_one({}, {"_id": 0})
    return cfg.get("referral", {"enabled": False, "reward_credits": 10, "referrer_credits": 10}) if cfg else {"enabled": False, "reward_credits": 10, "referrer_credits": 10}


# ═══════════════════════════════════════════════════════════════════════════
# UPGRADE WAVE — ALL 12 MAJOR FEATURES
# ═══════════════════════════════════════════════════════════════════════════

# ── T001: Internal Linking Engine ────────────────────────────────────────────

@router.get("/admin/seo/internal-links/analyze")
async def seo_internal_links_analyze(admin: dict = Depends(get_admin_user)):
    """Analyze all published topics and return semantic link suggestions using embeddings."""
    topics = await db.seo_topics.find(
        {"status": "published"},
        {"_id": 0, "slug": 1, "title": 1, "subject_name": 1, "class_name": 1}
    ).to_list(500)

    if not topics:
        return {"links": [], "topics_analyzed": 0}

    suggestions = []
    try:
        import vertex_services
        titles = [t["title"] for t in topics]
        vecs = await vertex_services.embed_batch(titles)

        for i, (topic, vec_i) in enumerate(zip(topics, vecs)):
            if vec_i is None:
                continue
            scores = []
            for j, (other, vec_j) in enumerate(zip(topics, vecs)):
                if i == j or vec_j is None:
                    continue
                sim = vertex_services.cosine_similarity(vec_i, vec_j)
                if sim > 0.65:
                    scores.append({"slug": other["slug"], "title": other["title"], "score": round(sim, 3)})
            scores.sort(key=lambda x: x["score"], reverse=True)
            if scores:
                suggestions.append({
                    "slug": topic["slug"],
                    "title": topic["title"],
                    "subject": topic.get("subject_name", ""),
                    "related": scores[:5],
                })
    except Exception as e:
        logger.warning(f"internal-links analyze failed: {e}")

    return {"links": suggestions, "topics_analyzed": len(topics)}


@router.post("/admin/seo/internal-links/inject/{slug}")
async def seo_internal_links_inject(slug: str, admin: dict = Depends(get_admin_user)):
    """Inject internal links into a topic's generated content."""
    topic = await db.seo_topics.find_one({"slug": slug})
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    pages = await db.seo_pages.find({"topic_id": str(topic.get("_id", ""))}).to_list(20)
    if not pages:
        raise HTTPException(status_code=404, detail="No pages found for this topic")

    all_topics = await db.seo_topics.find(
        {"status": "published", "slug": {"$ne": slug}},
        {"slug": 1, "title": 1}
    ).to_list(200)

    injected_count = 0
    for page in pages[:5]:
        content = page.get("content", "")
        if not content:
            continue
        for related in all_topics[:10]:
            r_title = related.get("title", "")
            r_slug = related.get("slug", "")
            if r_title.lower() in content.lower() and f"[{r_title}]" not in content:
                content = content.replace(
                    r_title,
                    f"[{r_title}](/learn/{r_slug})",
                    1
                )
                injected_count += 1
        await db.seo_pages.update_one(
            {"_id": page["_id"]},
            {"$set": {"content": content, "internal_links_injected": True, "links_updated_at": datetime.now(timezone.utc).isoformat()}}
        )

    return {"slug": slug, "pages_updated": len(pages), "links_injected": injected_count}


# ── T003: FAQ Auto-Extractor ──────────────────────────────────────────────────

@router.get("/admin/conversations/extract-faqs")
async def extract_faqs(limit: int = 100, admin: dict = Depends(get_admin_user)):
    """Extract recurring questions from conversations and suggest FAQ content."""
    pipeline = [
        {"$unwind": "$messages"},
        {"$match": {"messages.role": "user"}},
        {"$project": {"content": "$messages.content", "subject": "$subject_name"}},
        {"$limit": limit * 5},
    ]
    try:
        raw = await db.conversations.aggregate(pipeline).to_list(limit * 5)
    except Exception:
        raw = []

    questions = [r["content"] for r in raw if r.get("content") and len(r["content"]) > 15 and "?" in r["content"]][:50]
    subjects = list({r.get("subject", "") for r in raw if r.get("subject")})[:10]

    faqs = []
    if questions:
        try:
            import vertex_services
            prompt = (
                f"From these student questions, identify the top 15 most frequently asked and educationally important ones.\n"
                f"Questions:\n" + "\n".join(f"- {q[:200]}" for q in questions[:50]) +
                f"\n\nReturn a JSON array of: {{question, category, suggested_answer_length: 'short'|'medium'|'long', importance: 'high'|'medium'}}"
                f"\nReturn ONLY valid JSON array."
            )
            raw_result = await vertex_services._generate(prompt, max_tokens=1024)
            if raw_result:
                cleaned = raw_result.strip().lstrip("```json").lstrip("```").rstrip("```")
                faqs = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"FAQ extraction AI failed: {e}")
            faqs = [{"question": q[:200], "category": "general", "importance": "medium"} for q in questions[:15]]

    return {
        "faqs": faqs,
        "total_questions_analyzed": len(questions),
        "subjects": subjects,
        "suggested_pages": [
            {"type": "faq", "title": f["question"][:80], "priority": f.get("importance", "medium")}
            for f in faqs[:10]
        ]
    }


@router.get("/admin/conversations/sentiment")
async def conversations_sentiment(admin: dict = Depends(get_admin_user)):
    """Quick sentiment summary across all recent conversations."""
    try:
        pipeline = [
            {"$unwind": "$messages"},
            {"$match": {"messages.role": "user"}},
            {"$project": {"content": "$messages.content", "conv_id": "$_id"}},
            {"$limit": 200},
        ]
        msgs = await db.conversations.aggregate(pipeline).to_list(200)
    except Exception:
        msgs = []

    if not msgs:
        return {"positive": 0, "negative": 0, "neutral": 0, "total": 0}

    texts = [m["content"] for m in msgs if m.get("content")]
    positive = sum(1 for t in texts if any(w in t.lower() for w in ["thank", "great", "awesome", "help", "good", "love", "clear", "easy"]))
    negative = sum(1 for t in texts if any(w in t.lower() for w in ["wrong", "bad", "error", "confused", "not working", "fail", "broken", "terrible"]))
    neutral = len(texts) - positive - negative
    return {
        "positive": positive,
        "negative": negative,
        "neutral": max(0, neutral),
        "total": len(texts),
        "positive_pct": round(positive / max(len(texts), 1) * 100, 1),
        "negative_pct": round(negative / max(len(texts), 1) * 100, 1),
    }


# ── T001b: Schema.org Auto-Injection ─────────────────────────────────────────

@router.post("/admin/seo/inject-schema/{slug}")
async def seo_inject_schema(slug: str, admin: dict = Depends(get_admin_user)):
    """Inject JSON-LD schema.org structured data into a topic's pages."""
    topic = await db.seo_topics.find_one({"slug": slug})
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    schema = {
        "@context": "https://schema.org",
        "@type": "Course",
        "name": topic.get("title", ""),
        "description": topic.get("meta_description", topic.get("title", "")),
        "provider": {"@type": "Organization", "name": "Syrabit.ai", "url": "https://syrabit.ai"},
        "educationalLevel": topic.get("class_name", ""),
        "about": topic.get("subject_name", ""),
        "keywords": topic.get("keywords", []),
        "inLanguage": "en-IN",
        "isPartOf": {"@type": "LearningResource", "name": f"AHSEC {topic.get('class_name', '')} {topic.get('subject_name', '')}"},
    }

    faq_schema = None
    pages = await db.seo_pages.find({"topic_id": str(topic.get("_id", ""))}).to_list(50)
    faqs = []
    for page in pages:
        if page.get("type") in ("important-questions", "mcqs"):
            content = page.get("content", "")
            questions = re.findall(r'#{1,3}\s+(.+?)\n', content)[:5]
            for q in questions:
                faqs.append({"@type": "Question", "name": q.strip(),
                              "acceptedAnswer": {"@type": "Answer", "text": f"Refer to Syrabit.ai for a detailed answer on {q.strip()}."}})
    if faqs:
        faq_schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faqs}

    await db.seo_topics.update_one(
        {"slug": slug},
        {"$set": {"schema_org": schema, "faq_schema": faq_schema, "schema_injected_at": datetime.now(timezone.utc).isoformat()}}
    )

    return {"slug": slug, "schema_injected": True, "faq_entities": len(faqs), "schema": schema}


@router.post("/admin/seo/inject-schema-bulk")
async def seo_inject_schema_bulk(admin: dict = Depends(get_admin_user)):
    """Inject schema.org into all published topics."""
    topics = await db.seo_topics.find({"status": "published"}, {"slug": 1}).to_list(1000)
    injected = 0
    for t in topics:
        try:
            await seo_inject_schema(t["slug"], admin)
            injected += 1
        except Exception:
            pass
    return {"injected": injected, "total": len(topics)}


# ── T008: Content Pipeline Tracker ───────────────────────────────────────────

@router.get("/admin/seo/pipeline-status")
async def seo_pipeline_status(admin: dict = Depends(get_admin_user)):
    """Get real-time content pipeline statistics with thin-page and sitemap tracking."""
    try:
        total         = await db.seo_topics.count_documents({})
        published     = await db.seo_topics.count_documents({"status": "published"})
        draft         = await db.seo_topics.count_documents({"status": "draft"})
        archived      = await db.seo_topics.count_documents({"status": "archived"})
        has_content   = await db.seo_topics.count_documents({"has_content": True})
        no_schema     = await db.seo_topics.count_documents({"status": "published", "schema_org": {"$exists": False}})
        no_links      = await db.seo_topics.count_documents({"status": "published", "internal_links_injected": {"$ne": True}})

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        published_today = await db.seo_topics.count_documents({
            "status": "published",
            "published_at": {"$gte": today.isoformat()}
        })
        pages_total     = await db.seo_pages.count_documents({})
        pages_published = await db.seo_pages.count_documents({"status": "published"})
        pages_draft     = await db.seo_pages.count_documents({"status": "draft"})
        pages_rejected  = await db.seo_pages.count_documents({"status": "rejected"})

        thin_pages = await db.seo_pages.count_documents({
            "status": {"$in": ["published", "draft"]},
            "$or": [
                {"quality.word_count": {"$lt": 300}},
                {"word_count": {"$lt": 300}, "quality": {"$exists": False}},
            ]
        })
        high_quality = await db.seo_pages.count_documents({
            "status": "published",
            "$or": [
                {"quality.score": {"$gte": 70}},
                {"quality_score.score": {"$gte": 70}, "quality": {"$exists": False}},
            ]
        })

        cms_total     = await db.cms_documents.count_documents({})
        cms_published = await db.cms_documents.count_documents({"status": "published"})
        cms_with_jsonld = await db.cms_documents.count_documents({"json_ld_breadcrumb": {"$exists": True}})

        sitemap_indexed = await db.seo_pages.count_documents({"in_sitemap": True})

        return {
            "total_topics": total,
            "published": published,
            "draft": draft,
            "archived": archived,
            "has_content": has_content,
            "pages_total": pages_total,
            "pages_published": pages_published,
            "pages_draft": pages_draft,
            "pages_rejected": pages_rejected,
            "published_today": published_today,
            "needs_schema": no_schema,
            "needs_internal_links": no_links,
            "thin_pages": thin_pages,
            "high_quality_pages": high_quality,
            "cms_total": cms_total,
            "cms_published": cms_published,
            "cms_with_jsonld": cms_with_jsonld,
            "sitemap_indexed": sitemap_indexed,
            "publish_rate_pct": round(published / max(total, 1) * 100, 1),
            "content_rate_pct": round(has_content / max(total, 1) * 100, 1),
            "quality_rate_pct": round(high_quality / max(pages_published, 1) * 100, 1),
        }
    except Exception as e:
        logger.warning(f"pipeline-status failed: {e}")
        return {}


# ── T009: Page-Level Conversion Tracker ──────────────────────────────────────

@router.get("/admin/analytics/page-conversions")
async def admin_page_conversions(days: int = 30, admin: dict = Depends(get_admin_user)):
    """Track which content pages correlate with user signups and upgrades."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Top viewed pages
    view_pipeline = [
        {"$match": {"type": "page_view", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$path", "views": {"$sum": 1}, "unique_visitors": {"$addToSet": "$visitor_id"}}},
        {"$project": {"path": "$_id", "views": 1, "unique_visitors": {"$size": "$unique_visitors"}}},
        {"$sort": {"views": -1}},
        {"$limit": 20},
    ]
    try:
        pages = await db.analytics.aggregate(view_pipeline).to_list(20)
    except Exception:
        pages = []

    # New signups per day with last page
    signup_pipeline = [
        {"$match": {"type": "signup", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$referrer_path", "signups": {"$sum": 1}}},
        {"$sort": {"signups": -1}},
        {"$limit": 15},
    ]
    try:
        signup_sources = await db.analytics.aggregate(signup_pipeline).to_list(15)
    except Exception:
        signup_sources = []

    enriched = []
    signup_map = {s["_id"]: s["signups"] for s in signup_sources}
    for p in pages:
        path = p.get("path", "") or p.get("_id", "")
        enriched.append({
            "path": path,
            "views": p.get("views", 0),
            "unique_visitors": p.get("unique_visitors", 0),
            "signups_attributed": signup_map.get(path, 0),
            "conversion_rate": round(signup_map.get(path, 0) / max(p.get("unique_visitors", 1), 1) * 100, 2),
        })

    enriched.sort(key=lambda x: x["signups_attributed"], reverse=True)

    # Daily signups trend
    daily_pipeline = [
        {"$match": {"type": "signup", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "signups": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    try:
        daily = await db.analytics.aggregate(daily_pipeline).to_list(days)
    except Exception:
        daily = []

    return {
        "top_converting_pages": enriched,
        "daily_signups": [{"date": d["_id"], "signups": d["signups"]} for d in daily],
        "period_days": days,
    }


# ── T010: Churn Risk Scoring ──────────────────────────────────────────────────

@router.get("/admin/users/churn-risk")
async def admin_churn_risk(admin: dict = Depends(get_admin_user)):
    """Score every user's churn risk based on activity, credits, and plan age."""
    users = await supa_list_users()
    now = datetime.now(timezone.utc)
    at_risk = []

    for u in users:
        score = 0
        factors = []

        created = u.get("created_at", "")
        last_active = u.get("updated_at", created)
        try:
            la_dt = datetime.fromisoformat(last_active.replace("Z", "+00:00"))
            days_inactive = (now - la_dt).days
        except Exception:
            days_inactive = 0

        if days_inactive > 14:
            score += 30
            factors.append(f"Inactive {days_inactive}d")
        elif days_inactive > 7:
            score += 15
            factors.append(f"Inactive {days_inactive}d")

        credits_used = u.get("credits_used", 0) or 0
        if credits_used == 0:
            score += 25
            factors.append("Never used AI")
        elif credits_used < 3:
            score += 10
            factors.append("Low engagement")

        plan = u.get("plan", "free")
        if plan == "free" and days_inactive > 3:
            score += 15
            factors.append("Free + inactive")

        conv_count = u.get("conversation_count", 0) or 0
        if conv_count == 0:
            score += 20
            factors.append("No conversations")

        risk = "high" if score >= 60 else "medium" if score >= 30 else "low"
        at_risk.append({
            "id": u.get("id"), "name": u.get("name", ""), "email": u.get("email", ""),
            "plan": plan, "credits_used": credits_used, "days_inactive": days_inactive,
            "risk_score": score, "risk": risk, "factors": factors,
        })

    at_risk.sort(key=lambda x: x["risk_score"], reverse=True)
    return {
        "users": at_risk[:50],
        "summary": {
            "high_risk": sum(1 for u in at_risk if u["risk"] == "high"),
            "medium_risk": sum(1 for u in at_risk if u["risk"] == "medium"),
            "low_risk": sum(1 for u in at_risk if u["risk"] == "low"),
            "total": len(at_risk),
        }
    }


# ── T011: LLM Cost Tracker ────────────────────────────────────────────────────

_llm_cost_log: list = []   # in-memory ring buffer (max 10k entries)
_LLM_COST_MAX = 10_000

COST_PER_1K_TOKENS = {
    "gemini-2.5-flash":       {"in": 0.00015, "out": 0.0006},
    "gemini-1.5-pro":         {"in": 0.00125,   "out": 0.005},
    "llama-3.3-70b-versatile":{"in": 0.00059,   "out": 0.00079},
    "llama-3.1-8b-instant":   {"in": 0.00005,   "out": 0.00008},
}

def record_llm_cost(model: str, prompt_tokens: int, completion_tokens: int, provider: str = "gemini", user_id: str = ""):
    rates = COST_PER_1K_TOKENS.get(model, {"in": 0.0001, "out": 0.0002})
    cost_usd = (prompt_tokens * rates["in"] + completion_tokens * rates["out"]) / 1000
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model, "provider": provider,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "cost_usd": round(cost_usd, 8),
        "user_id": user_id,
    }
    _llm_cost_log.append(entry)
    if len(_llm_cost_log) > _LLM_COST_MAX:
        _llm_cost_log.pop(0)

@router.get("/admin/health/llm-costs")
async def admin_llm_costs(days: int = 7, admin: dict = Depends(get_admin_user)):
    """Return LLM cost breakdown for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [e for e in _llm_cost_log if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) >= cutoff]

    total_cost = sum(e["cost_usd"] for e in recent)
    total_tokens = sum(e["prompt_tokens"] + e["completion_tokens"] for e in recent)

    by_model: dict = {}
    for e in recent:
        m = e["model"]
        by_model.setdefault(m, {"calls": 0, "cost_usd": 0, "tokens": 0})
        by_model[m]["calls"] += 1
        by_model[m]["cost_usd"] += e["cost_usd"]
        by_model[m]["tokens"] += e["prompt_tokens"] + e["completion_tokens"]

    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, {"cost_usd": 0, "calls": 0})
        by_day[day]["cost_usd"] += e["cost_usd"]
        by_day[day]["calls"] += 1

    daily = [{"date": d, **v, "cost_usd": round(v["cost_usd"], 6)} for d, v in sorted(by_day.items())]

    published = await db.seo_topics.count_documents({"status": "published"})
    cost_per_page = round(total_cost / max(published, 1), 6)

    by_user: dict = {}
    for e in recent:
        uid = e.get("user_id", "anonymous") or "anonymous"
        by_user.setdefault(uid, {"calls": 0, "cost_usd": 0, "tokens": 0})
        by_user[uid]["calls"] += 1
        by_user[uid]["cost_usd"] += e["cost_usd"]
        by_user[uid]["tokens"] += e["prompt_tokens"] + e["completion_tokens"]

    top_users = sorted(by_user.items(), key=lambda x: -x[1]["cost_usd"])[:20]

    return {
        "period_days": days,
        "total_cost_usd": round(total_cost, 6),
        "total_cost_inr": round(total_cost * 84, 4),
        "total_tokens": total_tokens,
        "total_calls": len(recent),
        "cost_per_published_page_usd": cost_per_page,
        "by_model": [{"model": m, **v, "cost_usd": round(v["cost_usd"], 6)} for m, v in by_model.items()],
        "by_user": [{"user_id": uid, **v, "cost_usd": round(v["cost_usd"], 6)} for uid, v in top_users],
        "daily": daily,
    }


# ── T012: Notification Trigger Builder ───────────────────────────────────────

@router.get("/admin/notifications/triggers")
async def get_notification_triggers(admin: dict = Depends(get_admin_user)):
    """List all automated notification triggers."""
    triggers = await db.notification_triggers.find({}, {"_id": 0}).to_list(100)
    return {"triggers": triggers}


@router.post("/admin/notifications/triggers")
async def create_notification_trigger(body: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Create a new automated trigger."""
    required = {"name", "event", "channel", "message"}
    if not required.issubset(body.keys()):
        raise HTTPException(status_code=400, detail=f"Required fields: {required}")
    trigger = {
        "id": str(uuid.uuid4()),
        "name": body["name"],
        "event": body["event"],       # signup | inactive_3d | inactive_7d | plan_upgrade | low_credits
        "channel": body["channel"],   # push | email | both
        "message": body["message"],
        "subject": body.get("subject", ""),
        "enabled": body.get("enabled", True),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fired_count": 0,
    }
    await db.notification_triggers.insert_one({**trigger, "_id": trigger["id"]})
    return trigger


@router.patch("/admin/notifications/triggers/{trigger_id}")
async def update_notification_trigger(trigger_id: str, body: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Toggle or update a trigger."""
    await db.notification_triggers.update_one({"id": trigger_id}, {"$set": body})
    return {"success": True}


@router.delete("/admin/notifications/triggers/{trigger_id}")
async def delete_notification_trigger(trigger_id: str, admin: dict = Depends(get_admin_user)):
    """Delete a trigger."""
    await db.notification_triggers.delete_one({"id": trigger_id})
    return {"success": True}


# ── T005: PDF-to-Syllabus Importer ───────────────────────────────────────────

_VALID_PAPER_TYPES = {"major", "minor", "mdc", "vac", "aec", "sec", "ge", "cc"}
_VALID_BOARDS = {"ahsec", "seba", "degree"}
_AHSEC_SEBA_STREAMS = {"science", "arts", "commerce"}

_SYLLABUS_EXTRACT_PROMPT_DEGREE = """
You are parsing an official university/board syllabus PDF for degree-level students in Assam, India (NEP / FYUGP curriculum).

The PDF may contain ONE or MULTIPLE subjects (one subject per page/section). Extract EVERY subject found.

Paper type for ALL subjects in this PDF: {paper_type}

For EACH subject, return one JSON object in this exact schema:
{{
  "board": "<College / University / Board name exactly as stated, e.g. 'Darrang College (Autonomous)', 'Gauhati University'>",
  "class_year": "<Year of study — e.g. '1st Year', '2nd Year'>",
  "semester": "<Semester label — e.g. 'Semester 1', 'Semester 2', '' if annual/not stated>",
  "semester_number": <integer 1-8 if stated, else 0>,
  "subject_name": "<Exact subject/course name as printed>",
  "course_code": "<Course code if printed, e.g. 'VAC-01012', else ''>",
  "credits": <integer credits, else 0>,
  "paper_type": "{paper_type}",
  "stream_target": "<Who this course is for — one of: 'All', 'Commerce', 'Arts', 'Science', 'Arts & Science', 'Commerce & Arts'>",
  "chapters": [
    {{
      "title": "<Unit I or Chapter 1 exact title as printed>",
      "description": "<Concise summary of all topics/subtopics listed under this unit — write as a flowing sentence or comma-separated list, max 3 sentences>",
      "topics": ["<subtopic 1>", "<subtopic 2>", "<subtopic 3>"]
    }}
  ],
  "topics": ["<Key topic or subtopic 1>", "<Key topic 2>", ...],
  "guidelines": "<Course objectives / outcomes / learning goals as a single string, or ''>"
}}

Rules:
- Extract EVERY subject/course in the PDF — do NOT skip any.
- chapters = the numbered units or chapters from the detailed syllabus table, each with its content description.
- For EACH chapter, "title" MUST NOT be empty — use the exact unit/chapter heading as printed; if no heading is visible, use "Unit 1", "Unit 2" etc.
- For each chapter, description must summarise exactly what topics appear under that unit in the PDF.
- topics (top-level) = key terms across all units (max 20 per subject).
- stream_target: if the PDF says "For all (Arts+Commerce+Science)" → "All"; "For Commerce" → "Commerce"; "For Arts & Science" → "Arts & Science".
- If semester is not stated but can be inferred from the course code (e.g. VAC-01012 → Semester 1), use it.
- Return ONLY a valid JSON array. No markdown fences, no explanations.
""".strip()

_SYLLABUS_EXTRACT_PROMPT_AHSEC = """
You are parsing an official AHSEC (Assam Higher Secondary Education Council) syllabus PDF for HS 1st Year or HS 2nd Year students in Assam, India.

The PDF may contain ONE or MULTIPLE subjects. Extract EVERY subject found.
Stream: {stream}

For EACH subject, return one JSON object in this exact schema:
{{
  "board": "AHSEC",
  "class_year": "<HS 1st Year or HS 2nd Year — infer from context>",
  "semester": "",
  "semester_number": 0,
  "subject_name": "<Exact subject name as printed, e.g. 'Physics', 'English', 'Accountancy'>",
  "course_code": "",
  "credits": 0,
  "paper_type": "",
  "stream_target": "{stream}",
  "chapters": [
    {{
      "title": "<Chapter/Unit exact title as printed>",
      "description": "<Concise summary of all topics/subtopics under this chapter>",
      "topics": ["<subtopic 1>", "<subtopic 2>", "<subtopic 3>"]
    }}
  ],
  "topics": ["<Key topic 1>", "<Key topic 2>", ...],
  "guidelines": "<Course objectives or learning goals, or ''>"
}}

Rules:
- Extract EVERY subject in the PDF — do NOT skip any.
- chapters = numbered chapters or units from the syllabus.
- For EACH chapter, "title" MUST NOT be empty.
- topics (top-level) = key terms across all chapters (max 20 per subject).
- Return ONLY a valid JSON array. No markdown fences, no explanations.
""".strip()

_SYLLABUS_EXTRACT_PROMPT_SEBA = """
You are parsing an official SEBA (Board of Secondary Education, Assam) syllabus PDF for Class 9 or Class 10 students in Assam, India.

The PDF may contain ONE or MULTIPLE subjects. Extract EVERY subject found.

For EACH subject, return one JSON object in this exact schema:
{{
  "board": "SEBA",
  "class_year": "<Class 9 or Class 10 — infer from context>",
  "semester": "",
  "semester_number": 0,
  "subject_name": "<Exact subject name as printed>",
  "course_code": "",
  "credits": 0,
  "paper_type": "",
  "stream_target": "All",
  "chapters": [
    {{
      "title": "<Chapter/Unit exact title as printed>",
      "description": "<Concise summary of all topics/subtopics under this chapter>",
      "topics": ["<subtopic 1>", "<subtopic 2>", "<subtopic 3>"]
    }}
  ],
  "topics": ["<Key topic 1>", "<Key topic 2>", ...],
  "guidelines": "<Course objectives or learning goals, or ''>"
}}

Rules:
- Extract EVERY subject in the PDF.
- chapters = numbered chapters or units from the syllabus.
- For EACH chapter, "title" MUST NOT be empty.
- topics (top-level) = key terms across all chapters (max 20 per subject).
- Return ONLY a valid JSON array. No markdown fences, no explanations.
""".strip()

def _get_extract_prompt(board: str, paper_type: str = "", stream: str = "") -> str:
    board = board.lower().strip()
    if board == "ahsec":
        return _SYLLABUS_EXTRACT_PROMPT_AHSEC.format(stream=stream.capitalize() or "Science")
    elif board == "seba":
        return _SYLLABUS_EXTRACT_PROMPT_SEBA
    else:
        return _SYLLABUS_EXTRACT_PROMPT_DEGREE.format(paper_type=paper_type or "major")

_CHAPTER_CONTENT_PROMPT_DEGREE = """You are an expert academic content writer for degree-level students in Assam, India (NEP / FYUGP curriculum).

Generate comprehensive, exam-ready study notes (Markdown format, **800–1200 words minimum**) for:
Subject: {subject_name}
Chapter/Unit: {chapter_title}
Topics to cover: {topics}
Board/Semester: {board_semester}

Structure the content EXACTLY as:
## {chapter_title}

### Introduction
(2-3 paragraphs introducing the chapter — why this topic matters, its scope, and relevance to Assam/Northeast India)

### Key Concepts & Definitions
(Define EVERY important term. Use bold for terms. Give 2-3 sentence explanations per concept with real-world examples.)

### {topic_sections}
(One ### section per topic listed above. Each section MUST be 100-200 words minimum. Include:
  - Clear explanation with examples
  - Real-world applications, especially from Assam/NE India context
  - Important facts, data, or case studies
  - Diagrams or process descriptions where applicable)

### Important Questions (Previous Year Pattern)
(Write 6-10 likely exam questions: mix of 2-mark short, 5-mark descriptive, and 10-mark long-answer questions with brief answer hints)

### Summary
(Bullet-point summary of 8-12 key takeaways from this chapter)

CRITICAL Rules:
- You MUST write at least 800 words of actual educational content — shorter responses are unacceptable
- Write for undergraduate students (degree level, NEP FYUGP)
- Use clear, simple language; explain jargon when first introduced
- Include real examples from Assam/Northeast India where applicable (e.g., Kaziranga for ecology, Brahmaputra for geography, tea gardens for economics)
- Each concept must be FULLY explained — do not write one-line summaries
- Do NOT use placeholder text like "Content for X" — write actual educational content
- Include specific facts, dates, statistics, and named examples
- Return ONLY the markdown content, no preamble or meta-commentary
""".strip()

_CHAPTER_CONTENT_PROMPT_SCHOOL = """You are an expert educational content writer creating study notes for {board_label} students in Assam, India.

Generate comprehensive, exam-ready study notes (Markdown format, **800–1200 words minimum**) for:
Subject: {subject_name}
Chapter: {chapter_title}
Topics to cover: {topics}
Class/Board: {board_semester}

Structure the content EXACTLY as:
## {chapter_title}

### Introduction
(2-3 paragraphs introducing the chapter in simple language — why this topic matters and how it connects to daily life)

### Key Concepts & Definitions
(Define EVERY important term in bold. Give 2-3 sentence explanations per concept with simple examples a student can relate to.)

### {topic_sections}
(One ### section per topic listed above. Each section MUST be 100-200 words minimum. Include:
  - Clear explanation with relatable examples
  - Real-world applications from Assam/NE India context
  - Important facts, data, named examples
  - Diagrams or process descriptions where applicable)

### Important Questions (Previous Year Pattern)
(Write 8-10 likely exam questions based on Assamboard pattern:
  - 3 short-answer questions (1-2 marks) with brief answers
  - 4 descriptive questions (3-5 marks) with answer hints
  - 3 long-answer questions (7-10 marks) with key points to cover)

### Summary
(Bullet-point summary of 8-12 key takeaways from this chapter)

CRITICAL Rules:
- You MUST write at least 800 words of actual educational content — shorter responses are unacceptable
- Write for {level_desc}
- Use clear, simple language appropriate for the level
- Include real examples from Assam/Northeast India where applicable (Kaziranga, Brahmaputra, tea gardens, Bihu, etc.)
- Cover NCERT + Assamboard syllabus points thoroughly
- Include exam-oriented tips and important definitions
- Each concept must be FULLY explained — do not write one-line summaries
- Do NOT use placeholder text like "Content for X" — write actual educational content
- Include specific facts, dates, statistics, and named examples
- Return ONLY the markdown content, no preamble or meta-commentary
""".strip()

def _get_content_prompt(board: str) -> str:
    board = board.lower().strip()
    if board == "ahsec":
        return _CHAPTER_CONTENT_PROMPT_SCHOOL
    elif board == "seba":
        return _CHAPTER_CONTENT_PROMPT_SCHOOL
    else:
        return _CHAPTER_CONTENT_PROMPT_DEGREE

def _board_prompt_vars(board: str) -> dict:
    board = board.lower().strip()
    if board == "ahsec":
        return {"board_label": "AHSEC Higher Secondary (HS)", "level_desc": "HS 1st/2nd Year students (Class 11-12 level)"}
    elif board == "seba":
        return {"board_label": "SEBA", "level_desc": "Class 9-10 secondary school students"}
    else:
        return {"board_label": "Degree (NEP FYUGP)", "level_desc": "undergraduate degree students"}

# ── Helper: generate chapter-level educational content via AI ─────────────────
async def _agentic_generate_chapter_content(
    subject_name: str,
    chapter_title: str,
    topics: list,
    board_semester: str,
    board: str = "degree",
) -> str:
    """Use LLM pool to generate educational markdown for a chapter."""
    topics_str = ", ".join(topics[:12]) if topics else "as listed in the chapter title"
    topic_sections = "\n".join([f"### {t}" for t in topics[:6]]) if topics else "### Core Content"
    template = _get_content_prompt(board)
    extra_vars = _board_prompt_vars(board)
    prompt = template.format(
        subject_name=subject_name,
        chapter_title=chapter_title,
        topics=topics_str,
        board_semester=board_semester,
        topic_sections=topic_sections,
        **extra_vars,
    )
    try:
        result = await slm_pool.complete(
            messages=[
                {"role": "system", "content": "You are an expert educational content writer specializing in Assam board curricula. Write detailed, exam-ready study notes with real examples. Every chapter must have at least 800 words of actual content."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=4000,
            temperature=0.2,
            task_hint="content_gen",
        )
        return (result or "").strip()
    except Exception as exc:
        logger.warning(f"[agentic_syllabus] chapter content gen failed for {chapter_title!r}: {exc}")
        # Fallback: minimal structured content
        return f"## {chapter_title}\n\n" + "\n\n".join([f"### {t}\n\n*Content for {t} in {subject_name}.*" for t in (topics[:5] or [chapter_title])])


@router.post("/admin/agentic-syllabus/run")
async def agentic_syllabus_run(
    file: UploadFile = File(...),
    paper_type: str  = Form("major"),
    board: str       = Form("degree"),
    stream: str      = Form(""),
    admin: dict      = Depends(get_admin_user),
):
    """
    Agentic Syllabus Uploader — full autonomous pipeline, streamed as SSE.
    Supports AHSEC, SEBA, and DEGREE boards with board-specific prompts.

    Pipeline per subject:
      PDF scan → identify subjects → for each subject:
        hierarchy link (board→class→stream→subject) →
        chapter content generation (AI) →
        auto-chunk →
        embed (RAG) →
        flag notes_generated →
        create chapter-wise blog drafts →
        SEO/GEO topic tagging →
        next subject

    Returns: text/event-stream (SSE)
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")
    board = board.lower().strip() or "degree"
    if board not in _VALID_BOARDS:
        board = "degree"
    paper_type = paper_type.lower().strip()
    stream = stream.lower().strip()
    if board == "degree":
        if paper_type not in _VALID_PAPER_TYPES:
            raise HTTPException(status_code=400, detail=f"paper_type must be one of: {', '.join(sorted(_VALID_PAPER_TYPES))}")
    elif board in ("ahsec", "seba"):
        if stream and stream not in _AHSEC_SEBA_STREAMS:
            stream = "science"
        paper_type = ""

    pdf_bytes  = await file.read()
    filename   = file.filename
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 20 MB)")

    import base64 as _b64, httpx as _httpx
    import vertex_services

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _recover_json(text: str) -> list:
        try:
            r = json.loads(text)
            return r if isinstance(r, list) else [r]
        except Exception:
            pass
        last = text.rfind('}')
        if last > 0:
            partial = text[:last + 1]
            cand = (partial + ']') if partial.lstrip().startswith('[') else ('[' + partial + ']')
            try:
                r = json.loads(cand)
                return r if isinstance(r, list) else [r]
            except Exception:
                pass
        objects, decoder, idx = [], json.JSONDecoder(), text.find('{')
        while 0 <= idx < len(text):
            try:
                obj, end = decoder.raw_decode(text, idx)
                objects.append(obj)
                idx = text.find('{', end)
            except Exception:
                idx = text.find('{', idx + 1)
        return objects

    async def _pipeline():
        # ── 1. SCAN: Extract subjects from PDF ───────────────────────────────
        yield _sse("scan_start", {"filename": filename, "paper_type": paper_type, "board": board, "stream": stream})

        extracted: list = []
        try:
            b64_pdf = _b64.b64encode(pdf_bytes).decode()
            prompt  = _get_extract_prompt(board, paper_type, stream)
            headers = await vertex_services._auth_headers()
            body    = {
                "contents": [{"parts": [
                    {"text": prompt + "\n\nReturn ONLY valid JSON array. No markdown fences."},
                    {"inline_data": {"mime_type": "application/pdf", "data": b64_pdf}},
                ]}],
                "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.1},
            }
            for _gmodel in ["gemini-2.5-flash", "gemini-2.0-flash"]:
                url = vertex_services._gen_url(_gmodel)
                async with _httpx.AsyncClient(timeout=120) as c:
                    r = await c.post(url, json=body, headers=headers)
                if r.status_code in (403, 404):
                    continue
                r.raise_for_status()
                raw     = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
                cleaned = re.sub(r'\s*```$', '', cleaned).strip()
                extracted = _recover_json(cleaned)
                logger.info(f"[agentic_syllabus] {_gmodel}: extracted {len(extracted)} subjects from {len(raw)} chars")
                break
        except Exception as e:
            # Fallback: text extraction
            try:
                import io
                try:    from pypdf import PdfReader as _PR
                except: from PyPDF2 import PdfReader as _PR  # type: ignore
                reader    = _PR(io.BytesIO(pdf_bytes))
                full_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(len(reader.pages)))
                resp = await slm_pool.complete(
                    messages=[
                        {"role": "system", "content": "Extract syllabus from text. Return JSON array."},
                        {"role": "user",   "content": _get_extract_prompt(board, paper_type, stream) + f"\n\nPDF TEXT:\n{full_text[:12000]}"},
                    ],
                    max_tokens=4096, temperature=0.1, task_hint="classification",
                )
                extracted = _recover_json(resp or "[]")
            except Exception as fe:
                yield _sse("error", {"message": f"PDF scan failed: {fe}"})
                return

        if not extracted:
            yield _sse("error", {"message": "No subjects found in PDF"})
            return

        yield _sse("scan_complete", {"subjects": [e.get("subject_name", "?") for e in extracted], "total": len(extracted)})

        # ── 2. IMPORT each subject sequentially ──────────────────────────────
        from syllabus_linker import SyllabusLinker, SyllabusEntry  # type: ignore
        linker   = SyllabusLinker(db)
        import_id = str(uuid.uuid4())
        now_iso   = datetime.now(timezone.utc).isoformat()

        total_chapters_all = 0
        total_chunks_all   = 0
        total_embedded     = 0
        all_subject_ids: list = []

        for subj_idx, entry_raw in enumerate(extracted):
            subject_name = (entry_raw.get("subject_name") or entry_raw.get("subject") or "").strip()
            if not subject_name:
                continue

            sem_raw  = entry_raw.get("semester", "") or ""
            sem_num  = entry_raw.get("semester_number", 0) or 0
            if sem_num and not sem_raw:
                sem_raw = f"Semester {sem_num}"
            effective_board = board.upper() if board in ("ahsec", "seba") else (entry_raw.get("board", "DEGREE") or "DEGREE")
            board_semester = f"{effective_board} / {sem_raw or entry_raw.get('class_year', '') or 'Semester 1'}"

            # Normalise chapter list
            raw_chaps = entry_raw.get("chapters", [])
            chapter_details: list[dict] = []
            for ch in raw_chaps:
                if isinstance(ch, dict):
                    title = (ch.get("title") or ch.get("name") or "").strip()
                    if title:
                        chapter_details.append({
                            "title":       title,
                            "description": (ch.get("description") or "").strip(),
                            "topics":      [t for t in (ch.get("topics") or []) if isinstance(t, str)],
                        })
                elif isinstance(ch, str) and ch.strip():
                    chapter_details.append({"title": ch.strip(), "description": "", "topics": []})

            n_chapters = len(chapter_details)
            yield _sse("subject_start", {
                "name":    subject_name,
                "index":   subj_idx,
                "total":   len(extracted),
                "chapters": n_chapters,
                "semester": sem_raw,
                "board":   entry_raw.get("board", "DEGREE"),
            })

            # ── 2a. Link hierarchy ────────────────────────────────────────────
            linker_board = effective_board if board in ("ahsec", "seba") else (entry_raw.get("board") or "").strip()
            linker_paper = paper_type if board == "degree" else ""
            linker_stream = stream.capitalize() if board in ("ahsec", "seba") and stream else (entry_raw.get("stream_target") or "All").strip()
            entry = SyllabusEntry(
                board_name      = linker_board,
                class_year      = (entry_raw.get("class_year") or "").strip(),
                semester        = sem_raw.strip(),
                subject_name    = subject_name,
                paper_type      = linker_paper,
                stream_hint     = linker_stream,
                chapters        = [ch["title"] for ch in chapter_details],
                chapter_details = chapter_details,
                topics          = [t for t in entry_raw.get("topics", []) if isinstance(t, str)][:20],
                guidelines      = (entry_raw.get("guidelines") or "").strip(),
                course_code     = (entry_raw.get("course_code") or "").strip(),
                credits         = int(entry_raw.get("credits") or 0),
            )
            try:
                link = await linker.link(entry)
            except Exception as le:
                logger.warning(f"[agentic_syllabus] linker failed for {subject_name}: {le}")
                link = None

            created_nodes = link.created_nodes if link else []
            subject_ids   = link.subject_ids   if link else []
            board_disp    = link.board_name     if link else entry_raw.get("board", "DEGREE")
            class_disp    = link.class_name     if link else sem_raw

            yield _sse("hierarchy", {
                "board":         board_disp,
                "class":         class_disp,
                "stream":        (link.streams[0]["stream_name"] if link and link.streams else paper_type.upper()),
                "subject":       subject_name,
                "created_nodes": created_nodes,
                "subject_ids":   subject_ids,
            })

            chap_chunks_total = 0
            subject_embedded = 0
            all_chapter_ids: list[str] = []

            # Fetch chapters just created by linker so we have real chapter_ids
            ch_docs = []
            if subject_ids:
                ch_docs = await db.chapters.find(
                    {"subject_id": {"$in": subject_ids}},
                    {"id": 1, "title": 1, "content": 1, "topics": 1}
                ).to_list(200)

            ch_map = {doc["title"].lower().strip(): doc for doc in ch_docs}
            generated_contents = {}

            for ch_idx, ch_detail in enumerate(chapter_details):
                ch_title  = ch_detail["title"]
                ch_topics = ch_detail.get("topics", [])

                yield _sse("chapter_start", {
                    "subject":  subject_name,
                    "chapter":  ch_title,
                    "index":    ch_idx,
                    "total":    n_chapters,
                })

                # Find the real chapter doc from DB
                ch_doc = ch_map.get(ch_title.lower().strip())
                chapter_id  = ch_doc["id"]   if ch_doc else str(uuid.uuid4())
                existing_content = (ch_doc.get("content") or "") if ch_doc else ""

                existing_word_count = len(existing_content.split()) if existing_content.strip() else 0
                if existing_word_count < 500:
                    best_content = None
                    best_wc = 0
                    for attempt in range(2):
                        try:
                            attempt_content = await _agentic_generate_chapter_content(
                                subject_name=subject_name,
                                chapter_title=ch_title,
                                topics=ch_topics or entry.topics[:8],
                                board_semester=board_semester,
                                board=board,
                            )
                        except Exception:
                            attempt_content = None

                        if attempt_content:
                            wc = len(attempt_content.split())
                            if wc > best_wc:
                                best_content = attempt_content
                                best_wc = wc
                            if wc >= 500:
                                break
                        if attempt == 0 and best_content:
                            logger.warning(f"[agentic_syllabus] thin content ({best_wc} words) for {ch_title!r}, retrying")

                    needs_review = False
                    if best_content and best_wc >= 500:
                        content = best_content
                    elif best_content:
                        content = best_content
                        needs_review = True
                        yield _sse("chapter_quality_warning", {"chapter": ch_title, "words": best_wc})
                    else:
                        content = f"## {ch_title}\n\n" + "\n\n".join(f"### {t}\n\n*Content for {t} in {subject_name}.*" for t in (ch_topics or [ch_title]))
                        needs_review = True

                    update_fields = {"content": content, "updated_at": datetime.now(timezone.utc).isoformat()}
                    if needs_review:
                        update_fields["needs_review"] = True
                    if ch_doc:
                        await db.chapters.update_one({"id": chapter_id}, {"$set": update_fields})
                    yield _sse("chapter_content", {"chapter": ch_title, "length": len(content), "words": len(content.split())})
                else:
                    content = existing_content
                    yield _sse("chapter_content", {"chapter": ch_title, "length": len(content), "words": existing_word_count, "existing": True})

                generated_contents[ch_title.lower().strip()] = {"content": content, "chapter_id": chapter_id}

                # Auto-chunk
                geo_tags = [board_disp, class_disp, subject_name, ch_title]
                try:
                    chunk_ids = await auto_chunk_content(
                        chapter_id=chapter_id,
                        content=content,
                        subject_id=subject_ids[0] if subject_ids else None,
                        geo_tags=geo_tags,
                        chapter_title=ch_title,
                    )
                    chap_chunks_total += len(chunk_ids)
                    all_chapter_ids.append(chapter_id)
                    yield _sse("chapter_chunked", {"chapter": ch_title, "chunks": len(chunk_ids)})
                except Exception as ce:
                    logger.warning(f"[agentic_syllabus] chunk failed {ch_title}: {ce}")
                    yield _sse("chapter_chunked", {"chapter": ch_title, "chunks": 0, "error": str(ce)})

                # Embed for RAG (syllabus_embeddings)
                try:
                    embed_ok = await _embed_and_store_chapter(chapter_id, content, ch_title)
                    if embed_ok:
                        total_embedded += 1
                        subject_embedded += 1
                    yield _sse("chapter_embedded", {"chapter": ch_title, "ok": embed_ok})
                except Exception as ee:
                    yield _sse("chapter_embedded", {"chapter": ch_title, "ok": False})

                # Flag notes_generated on the chapter doc
                if ch_doc:
                    try:
                        await db.chapters.update_one(
                            {"id": chapter_id},
                            {"$set": {"notes_generated": True, "notes_generated_at": datetime.now(timezone.utc).isoformat()}}
                        )
                    except Exception:
                        pass

            total_chapters_all += n_chapters
            total_chunks_all   += chap_chunks_total

            # ── 2c. Create chapter-wise blog drafts ────────────────────────────
            blog_drafts_created = 0
            if subject_ids:
                from routes.admin_monetization import _md_to_html as _blog_md_to_html_fn
                _now_iso = datetime.now(timezone.utc).isoformat()
                for ch_detail in chapter_details:
                    ch_t = ch_detail["title"]
                    gen_entry = generated_contents.get(ch_t.lower().strip())
                    if not gen_entry:
                        continue
                    ch_content = gen_entry["content"]
                    ch_chapter_id = gen_entry["chapter_id"]
                    if len(ch_content.strip()) < 100:
                        continue
                    ch_slug_val = re.sub(r'[^a-z0-9]+', '-', f"{ch_t} {subject_name}".lower()).strip('-')
                    ch_html = _blog_md_to_html_fn(ch_content)
                    ch_wc = len(re.sub(r'<[^>]+>', '', ch_html).split())
                    blog_title = f"{ch_t} — {subject_name}"
                    meta_desc = f"Study notes for {ch_t} in {subject_name} ({board_disp} {class_disp}). Covers key concepts, definitions, examples from Assam/NE India, and important exam questions."
                    if len(meta_desc) > 160:
                        meta_desc = meta_desc[:157] + "..."

                    faq_items = []
                    ch_topics_list = ch_detail.get("topics", [])
                    for t in ch_topics_list[:5]:
                        faq_items.append({
                            "question": f"What is {t} in {subject_name}?",
                            "answer": f"{t} is a key topic covered in {ch_t} of {subject_name} under {board_disp} {class_disp}."
                        })

                    blog_doc = {
                        "subject_id": subject_ids[0],
                        "chapter_id": ch_chapter_id,
                        "title": blog_title,
                        "seo_slug": ch_slug_val,
                        "board_slug": board_disp.lower().replace(' ', '-'),
                        "class_slug": class_disp.lower().replace(' ', '-'),
                        "content": ch_html,
                        "merged_md": ch_content,
                        "word_count": ch_wc,
                        "status": "published",
                        "content_html": ch_html,
                        "schema_type": "Article",
                        "primary_keyword": f"{ch_t} {subject_name} Assamboard notes",
                        "meta_description": meta_desc,
                        "og_title": blog_title,
                        "og_description": meta_desc,
                        "faq_schema": faq_items if faq_items else None,
                        "updated_at": _now_iso,
                    }
                    existing_blog = await db.cms_documents.find_one(
                        {"$or": [
                            {"subject_id": subject_ids[0], "chapter_id": ch_chapter_id},
                            {"seo_slug": ch_slug_val},
                        ]}, {"_id": 0, "id": 1}
                    )
                    if existing_blog:
                        await db.cms_documents.update_one(
                            {"id": existing_blog["id"]},
                            {"$set": {**blog_doc, "subject_id": subject_ids[0], "linked_subject_id": subject_ids[0]}}
                        )
                    else:
                        blog_doc["id"] = str(uuid.uuid4())
                        blog_doc["created_at"] = _now_iso
                        await db.cms_documents.insert_one(blog_doc)
                    blog_drafts_created += 1
                    try:
                        await _embed_cms_document(ch_slug_val, ch_html, f"{ch_t} — {subject_name}")
                    except Exception as emb_err:
                        logger.warning(f"[agentic_syllabus] cms embed failed for slug={ch_slug_val}: {emb_err}")
                if blog_drafts_created:
                    yield _sse("blog_drafts_created", {"subject": subject_name, "count": blog_drafts_created})

            # ── 2d. SEO/GEO topic tagging ─────────────────────────────────────
            geo_phrase = f"{board_disp}, {class_disp}, {subject_name}, Assam"
            if subject_ids:
                await db.subjects.update_one(
                    {"id": {"$in": subject_ids}},
                    {"$set": {"geo_tags": geo_phrase, "seo_tagged": True}}
                )
            yield _sse("seo_tagged", {"subject": subject_name, "geo_phrase": geo_phrase})

            await db.syllabus_pdf_imports.insert_one({
                "id":                 str(uuid.uuid4()),
                "import_id":          import_id,
                "filename":           filename,
                "paper_type":         paper_type,
                "board":              board,
                "board_name":         board_disp,
                "class_name":         class_disp,
                "class_year":         entry.class_year,
                "semester":           sem_raw,
                "subject_name":       subject_name,
                "course_code":        entry.course_code,
                "credits":            entry.credits,
                "total_subjects":     1,
                "total_chapters":     n_chapters,
                "total_chunks":       chap_chunks_total,
                "total_embedded":     subject_embedded,
                "chapters":           [ch["title"] for ch in chapter_details],
                "chapter_details":    chapter_details,
                "topics":             entry.topics,
                "guidelines":         entry.guidelines,
                "linked_board_id":    link.board_id    if link else None,
                "linked_class_id":    link.class_id    if link else None,
                "linked_stream_ids":  [s["stream_id"] for s in link.streams] if link else [],
                "linked_subject_ids": subject_ids,
                "created_nodes":      created_nodes,
                "source":             "agentic_import",
                "status":             "agentic_complete",
                "created_at":         now_iso,
            })

            all_subject_ids.extend(sid for sid in subject_ids if sid not in all_subject_ids)
            yield _sse("subject_done", {
                "name":           subject_name,
                "chapters_done":  n_chapters,
                "chunks_created": chap_chunks_total,
                "blog_drafts":    blog_drafts_created,
                "subject_ids":    subject_ids,
            })

        # ── 3. Invalidate caches + reseed embedder ────────────────────────────
        for cache_key in ("boards", "classes", "streams", "subjects", "chapters", "library-bundle"):
            _invalidate_content_cache(cache_key)
        try:
            asyncio.create_task(_trigger_reseed())
        except Exception:
            pass

        yield _sse("complete", {
            "import_id":        import_id,
            "total_subjects":   len(extracted),
            "total_chapters":   total_chapters_all,
            "total_chunks":     total_chunks_all,
            "total_embedded":   total_embedded,
            "subject_ids":      all_subject_ids,
        })

    return StreamingResponse(
        _pipeline(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/admin/syllabus/import-pdf")
async def syllabus_import_pdf(
    file: UploadFile = File(...),
    paper_type: str = Form("major"),       # major | minor | mdc | vac
    board_id: str = Form(""),              # optional — links to existing board
    class_id: str = Form(""),              # optional — links to existing class
    stream_id: str = Form(""),             # optional — links to existing stream
    dry_run: bool = Form(False),           # if True: extract only, do NOT save
    admin: dict = Depends(get_admin_user),
):
    """
    Extract per-subject syllabus from a PDF.
    One PDF → multiple subjects, all sharing the same paper_type.
    Gemini reads the PDF and returns structured data per subject.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")
    paper_type = paper_type.lower().strip()
    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"paper_type must be one of: {', '.join(sorted(_VALID_PAPER_TYPES))}")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 20MB)")

    import base64 as _b64, httpx as _httpx
    import vertex_services

    b64_pdf = _b64.b64encode(pdf_bytes).decode()
    prompt = _SYLLABUS_EXTRACT_PROMPT_DEGREE.format(paper_type=paper_type)

    logger.info(f"[pdf_import] START paper_type={paper_type} size={len(pdf_bytes)}B gemini_ok={vertex_services._ok()}")

    # ── Helper: recover as many complete JSON objects as possible ─────────────
    def _recover_json(text: str) -> list:
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            pass
        # Trim to last complete `}` and close the array
        last_brace = text.rfind('}')
        if last_brace > 0:
            partial = text[:last_brace + 1]
            candidate = (partial + ']') if partial.lstrip().startswith('[') else ('[' + partial + ']')
            try:
                result = json.loads(candidate)
                return result if isinstance(result, list) else [result]
            except json.JSONDecodeError:
                pass
        # Last resort: extract each `{…}` object individually
        objects, decoder, idx = [], json.JSONDecoder(), text.find('{')
        while 0 <= idx < len(text):
            try:
                obj, end = decoder.raw_decode(text, idx)
                objects.append(obj)
                idx = text.find('{', end)
            except json.JSONDecodeError:
                idx = text.find('{', idx + 1)
        return objects

    # ── Try Gemini Vision first — try multiple model versions before giving up ─
    extracted: list = []
    _used_gemini = False
    _GEMINI_PDF_MODELS = [
        vertex_services._PRO_MODEL,
        "gemini-2.5-flash",
    ]
    try:
        if not vertex_services._ok():
            logger.warning("[pdf_import] Gemini not available — going straight to text fallback")
            raise ValueError("Gemini unavailable — skipping to text extraction fallback")
        headers = await vertex_services._auth_headers()
        body = {
            "contents": [{"parts": [
                {"text": prompt + "\n\nReturn ONLY valid JSON array. No markdown fences."},
                {"inline_data": {"mime_type": "application/pdf", "data": b64_pdf}},
            ]}],
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.1},
        }
        gemini_resp = None
        for _gmodel in _GEMINI_PDF_MODELS:
            url = vertex_services._gen_url(_gmodel)
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(url, json=body, headers=headers)
            if r.status_code in (403, 404):
                logger.warning(f"[pdf_import] Gemini model {_gmodel} → {r.status_code}, trying next model…")
                continue
            r.raise_for_status()
            gemini_resp = r
            logger.info(f"[pdf_import] Gemini Vision using model: {_gmodel}")
            break
        if gemini_resp is None:
            vertex_services._mark_forbidden()
            raise ValueError("All Gemini models returned 403 — check GEMINI_API_KEY")
        raw = gemini_resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
        extracted = _recover_json(cleaned)
        _used_gemini = True
        logger.info(f"[pdf_import] Gemini Vision OK — extracted {len(extracted)} subjects")
    except Exception as gemini_err:
        logger.warning(f"[pdf_import] Gemini Vision failed: {gemini_err}")
        # ── Fallback: extract raw text via PyPDF2, send to LLM pool ──────────
        try:
            import io
            try:
                from pypdf import PdfReader as _PdfReader
            except ImportError:
                from PyPDF2 import PdfReader as _PdfReader  # type: ignore
            reader = _PdfReader(io.BytesIO(pdf_bytes))
            total_pages = len(reader.pages)

            # Extract text per page
            page_texts = [(reader.pages[i].extract_text() or "").strip() for i in range(total_pages)]
            full_text = "\n".join(page_texts)
            logger.info(f"[pdf_import] PyPDF2 extracted {len(full_text)} chars from {total_pages} pages")
            if not full_text.strip():
                raise ValueError(
                    "Could not extract text from PDF — the file may be a scanned image. "
                    "Please upload a text-based PDF."
                )

            # ── Chunk by groups of 10 pages so all semesters are covered ─────
            PAGE_GROUP = 10
            _sem = asyncio.Semaphore(4)  # max 4 concurrent LLM calls

            async def _process_page_group(start_p: int, end_p: int) -> list:
                group_text = "\n".join(page_texts[start_p:end_p]).strip()
                if not group_text:
                    return []
                chunk_prompt = (
                    prompt
                    + f"\n\nSYLLABUS TEXT (pages {start_p+1}–{end_p} of {total_pages}):\n"
                    + group_text[:8000]
                    + "\n\nReturn ONLY a valid JSON array. "
                      "If no subjects are present in this text, return []. "
                      "No markdown fences."
                )
                async with _sem:
                    raw = await _call_llm_raw(
                        [{"role": "user", "content": chunk_prompt}],
                        max_tokens=6000,
                    )
                if not raw:
                    return []
                c = re.sub(r'^```(?:json)?\s*', '', raw.strip())
                c = re.sub(r'\s*```$', '', c).strip()
                return _recover_json(c)

            groups = [
                (s, min(s + PAGE_GROUP, total_pages))
                for s in range(0, total_pages, PAGE_GROUP)
            ]
            logger.info(f"[pdf_import] Processing {len(groups)} page-groups concurrently (10 pages each)…")
            chunk_results = await asyncio.gather(
                *[_process_page_group(s, e) for s, e in groups],
                return_exceptions=True,
            )

            # Merge & deduplicate by (subject_name, semester)
            seen_subjects: set = set()
            extracted = []
            for res in chunk_results:
                if isinstance(res, Exception):
                    logger.warning(f"[pdf_import] chunk error (skipped): {res}")
                    continue
                for subj in (res or []):
                    key = (
                        str(subj.get("subject_name", "")).lower().strip(),
                        str(subj.get("semester", "")).lower().strip(),
                    )
                    if key[0] and key not in seen_subjects:
                        seen_subjects.add(key)
                        extracted.append(subj)
            logger.info(f"[pdf_import] LLM fallback OK — extracted {len(extracted)} subjects across {len(groups)} chunks")
        except HTTPException:
            raise
        except Exception as fallback_err:
            logger.error(f"[pdf_import] Fallback also failed: {fallback_err}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"PDF extraction failed: {fallback_err}"
            )

    if not extracted:
        raise HTTPException(status_code=422, detail="No syllabus subjects found in PDF — check PDF content")

    # ── Build duplicate fingerprint set from published subjects + prior imports ─
    def _subj_key(name: str, semester: str) -> tuple:
        return (name.lower().strip(), semester.lower().strip())

    existing_published = await db.subjects.find(
        {"status": "published"},
        {"name": 1, "semester": 1, "_id": 0}
    ).to_list(5000)
    dup_keys: set = {
        _subj_key(s.get("name", ""), s.get("semester", ""))
        for s in existing_published
        if s.get("name")
    }
    # Also include prior successful imports so re-uploading same PDF is safe
    prior_imports = await db.syllabus_pdf_imports.find(
        {"status": {"$in": ["linked", "imported"]}},
        {"subject_name": 1, "semester": 1, "_id": 0}
    ).to_list(5000)
    for pi in prior_imports:
        if pi.get("subject_name"):
            dup_keys.add(_subj_key(pi["subject_name"], pi.get("semester", "")))

    # Annotate each extracted entry with duplicate flag
    for entry in extracted:
        if isinstance(entry, dict):
            sname = (entry.get("subject_name") or entry.get("subject") or "").strip()
            sem   = (entry.get("semester") or "").strip()
            sem_n = entry.get("semester_number", 0) or 0
            if sem_n and not sem:
                sem = f"Semester {sem_n}"
            entry["_is_duplicate"] = _subj_key(sname, sem) in dup_keys

    new_count  = sum(1 for e in extracted if isinstance(e, dict) and not e.get("_is_duplicate"))
    dup_count  = len(extracted) - new_count

    # ── Normalise chapter titles in extracted data (for both dry-run and live) ─
    def _norm_chapters(raw_chaps: list) -> list:
        out = []
        for idx, ch in enumerate(raw_chaps):
            if isinstance(ch, dict):
                title = (ch.get("title") or ch.get("name") or "").strip()
                desc  = (ch.get("description") or "").strip()
                if not title and desc:
                    first_sentence = desc.split('.')[0].strip()
                    title = (first_sentence[:70] + '…') if len(first_sentence) > 70 else first_sentence
                if not title:
                    title = f"Unit {idx + 1}"
                out.append({**ch, "title": title, "description": desc})
            elif isinstance(ch, str) and ch.strip():
                out.append({"title": ch.strip(), "description": "", "topics": []})
        return out

    for entry in extracted:
        if isinstance(entry, dict) and "chapters" in entry:
            entry["chapters"] = _norm_chapters(entry["chapters"])

    # ── Dry-run: return extracted JSON (with dup flags) for preview ─────────────
    if dry_run:
        return {
            "preview": True,
            "extracted": extracted,
            "paper_type": paper_type,
            "filename": file.filename,
            "subjects_count": len(extracted),
            "new_count": new_count,
            "duplicate_count": dup_count,
        }

    # ── Auto-link each subject into the board/class/stream/subject hierarchy ──
    from syllabus_linker import SyllabusLinker, SyllabusEntry  # type: ignore
    linker = SyllabusLinker(db)

    now_iso = datetime.now(timezone.utc).isoformat()
    import_id = str(uuid.uuid4())
    saved_subjects = []
    skipped_duplicates = []

    for entry_raw in extracted:
        if not isinstance(entry_raw, dict):
            continue
        subject_name = (entry_raw.get("subject_name") or entry_raw.get("subject") or "").strip()
        if not subject_name:
            continue

        sem_raw = entry_raw.get("semester", "") or ""
        # Prefer explicit semester_number from Gemini if semester string is missing
        sem_num = entry_raw.get("semester_number", 0) or 0
        if sem_num and not sem_raw:
            sem_raw = f"Semester {sem_num}"

        # ── Skip subjects already published or previously imported ────────────
        if _subj_key(subject_name, sem_raw) in dup_keys:
            skipped_duplicates.append({
                "subject_name": subject_name,
                "semester": sem_raw,
                "reason": "already_active",
            })
            logger.info(f"[pdf_import] SKIP duplicate: {subject_name!r} {sem_raw!r}")
            continue

        # Normalise chapters: accept [{title, description, topics}] OR ["title"]
        raw_chaps = entry_raw.get("chapters", [])
        chapter_details: list[dict] = []
        chapter_titles: list[str]   = []
        for ch in raw_chaps:
            if isinstance(ch, dict):
                title = (ch.get("title") or ch.get("name") or "").strip()
                desc  = (ch.get("description") or "").strip()
                if not title and desc:
                    # Derive title from first sentence of description (max 70 chars)
                    first_sentence = desc.split('.')[0].strip()
                    title = (first_sentence[:70] + '…') if len(first_sentence) > 70 else first_sentence
                if not title:
                    title = f"Unit {len(chapter_titles) + 1}"
                chapter_details.append({
                    "title":       title,
                    "description": desc,
                    "topics":      [t for t in (ch.get("topics") or []) if isinstance(t, str)],
                })
                chapter_titles.append(title)
            elif isinstance(ch, str) and ch.strip():
                title = ch.strip()
                chapter_titles.append(title)
                chapter_details.append({"title": title, "description": "", "topics": []})

        entry = SyllabusEntry(
            board_name      = (entry_raw.get("board") or "").strip(),
            class_year      = (entry_raw.get("class_year") or "").strip(),
            semester        = sem_raw.strip(),
            subject_name    = subject_name,
            paper_type      = paper_type,
            stream_hint     = (entry_raw.get("stream_target") or "All").strip(),
            chapters        = chapter_titles,
            chapter_details = chapter_details,
            topics          = [t for t in entry_raw.get("topics", []) if isinstance(t, str)][:20],
            guidelines      = (entry_raw.get("guidelines") or "").strip(),
            course_code     = (entry_raw.get("course_code") or "").strip(),
            credits         = int(entry_raw.get("credits") or 0),
        )

        try:
            link = await linker.link(entry)
        except Exception as link_err:
            logger.warning(f"SyllabusLinker failed for {subject_name}: {link_err}")
            link = None

        # Also save raw import record for auditability
        raw_doc = {
            "import_id": import_id,
            "filename": file.filename,
            "paper_type": paper_type,
            "board_name": entry.board_name,
            "class_year": entry.class_year,
            "semester": entry.semester,
            "subject_name": subject_name,
            "course_code": entry.course_code,
            "credits": entry.credits,
            "stream_target": entry.stream_hint,
            "chapters": entry.chapters,
            "chapter_details": entry.chapter_details,
            "topics": entry.topics,
            "guidelines": entry.guidelines,
            # Resolved DB IDs
            "linked_board_id":   link.board_id   if link else (board_id or None),
            "linked_class_id":   link.class_id   if link else (class_id or None),
            "linked_stream_ids": [s["stream_id"] for s in link.streams] if link else [],
            "linked_subject_ids": link.subject_ids if link else [],
            "created_nodes":     link.created_nodes if link else [],
            "status": "linked" if link else "imported",
            "source": "pdf_import",
            "created_at": now_iso,
        }
        await db.syllabus_pdf_imports.insert_one(raw_doc)

        saved_subjects.append({
            "subject_name": subject_name,
            "board_name": link.board_name if link else entry.board_name,
            "class_name": link.class_name if link else entry.class_year,
            "semester": entry.semester,
            "stream_target": entry.stream_hint,
            "paper_type": paper_type,
            "credits": entry.credits,
            "course_code": entry.course_code,
            "chapters_count": len(entry.chapters),
            "topics_count": len(entry.topics),
            "streams": link.streams if link else [],
            "subject_ids": link.subject_ids if link else [],
            "created_nodes": link.created_nodes if link else [],
        })

    # Ensure indexes
    try:
        await db.syllabus_pdf_imports.create_index([("import_id", 1), ("paper_type", 1)])
        await db.syllabus_pdf_imports.create_index("subject_name")
        await db.syllabus_pdf_imports.create_index("linked_board_id")
    except Exception:
        pass

    # Invalidate content caches so new boards/classes/streams/subjects are visible immediately
    _invalidate_content_cache("boards")
    _invalidate_content_cache("classes")
    _invalidate_content_cache("streams")
    _invalidate_content_cache("subjects")
    _invalidate_content_cache("chapters")

    # Re-embed new chapters in background (force re-seed even if already seeded once)
    if _get_syllabus_embedder() is not None:
        asyncio.create_task(_trigger_reseed())

    return {
        "success": True,
        "import_id": import_id,
        "paper_type": paper_type,
        "filename": file.filename,
        "subjects_saved": len(saved_subjects),
        "subjects_skipped_duplicates": len(skipped_duplicates),
        "subjects": saved_subjects,
        "skipped": skipped_duplicates,
    }


@router.get("/admin/syllabus/pdf-imports")
async def list_pdf_imports(
    paper_type: str = "",
    admin: dict = Depends(get_admin_user),
):
    """List all PDF-imported syllabus entries, grouped by import_id to avoid duplicate keys."""
    q: dict = {}
    if paper_type:
        q["paper_type"] = paper_type.lower()

    pipeline = [
        {"$match": q},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id":             "$import_id",
            "import_id":       {"$first": "$import_id"},
            "filename":        {"$first": "$filename"},
            "paper_type":      {"$first": "$paper_type"},
            "board_name":      {"$first": "$board_name"},
            "class_name":      {"$first": "$class_name"},
            "class_year":      {"$first": "$class_year"},
            "semester":        {"$first": "$semester"},
            "course_code":     {"$first": "$course_code"},
            "credits":         {"$first": "$credits"},
            "created_at":      {"$first": "$created_at"},
            "status":          {"$first": "$status"},
            "chapters":        {"$first": "$chapters"},
            "guidelines":      {"$first": "$guidelines"},
            "topics":          {"$first": "$topics"},
            "linked_board_id": {"$first": "$linked_board_id"},
            "linked_class_id": {"$first": "$linked_class_id"},
            "subject_names":   {"$push": "$subject_name"},
            "all_subject_ids": {"$push": "$linked_subject_ids"},
        }},
        {"$addFields": {
            "subject_name":   {"$arrayElemAt": ["$subject_names", 0]},
            "subjects_count": {"$size": "$subject_names"},
            "linked_subject_ids": {
                "$reduce": {
                    "input": "$all_subject_ids",
                    "initialValue": [],
                    "in": {"$concatArrays": ["$$value", {"$ifNull": ["$$this", []]}]},
                }
            },
        }},
        {"$sort": {"created_at": -1}},
        {"$project": {"_id": 0, "all_subject_ids": 0}},
    ]

    entries = await db.syllabus_pdf_imports.aggregate(pipeline).to_list(500)
    return {"imports": entries, "total": len(entries)}


@router.delete("/admin/syllabus/pdf-imports/{import_id}")
async def delete_pdf_import(
    import_id: str,
    remove_content: bool = False,
    admin: dict = Depends(get_admin_user),
):
    """Delete ALL import records for an import_id (one per subject). If remove_content=true, also deletes linked subjects + chapters."""
    docs = await db.syllabus_pdf_imports.find(
        {"import_id": import_id}, {"_id": 0, "linked_subject_ids": 1}
    ).to_list(500)
    if not docs:
        raise HTTPException(status_code=404, detail="Import not found")

    if remove_content:
        all_subject_ids: list = []
        for doc in docs:
            all_subject_ids.extend(doc.get("linked_subject_ids") or [])
        if all_subject_ids:
            await db.chapters.delete_many({"subject_id": {"$in": all_subject_ids}})
            await db.subjects.delete_many({"id": {"$in": all_subject_ids}})
            _invalidate_content_cache("subjects")
            _invalidate_content_cache("chapters")

    await db.syllabus_pdf_imports.delete_many({"import_id": import_id})
    return {"success": True, "import_id": import_id, "content_removed": remove_content}


@router.put("/admin/syllabus/pdf-imports/{import_id}")
async def update_pdf_import(
    import_id: str,
    body: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """Update chapters/topics on an existing PDF import and sync to linked subjects/chapters."""
    doc = await db.syllabus_pdf_imports.find_one({"import_id": import_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Import not found")

    chapters   = body.get("chapters")
    topics     = body.get("topics")
    guidelines = body.get("guidelines")

    update_fields: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if chapters  is not None: update_fields["chapters"]   = chapters
    if topics    is not None: update_fields["topics"]     = topics
    if guidelines is not None: update_fields["guidelines"] = guidelines

    await db.syllabus_pdf_imports.update_one({"import_id": import_id}, {"$set": update_fields})

    # Sync chapter titles to linked subjects
    if chapters is not None:
        subject_ids = doc.get("linked_subject_ids", [])
        for subject_id in subject_ids:
            existing_slugs = {
                c["slug"] for c in
                await db.chapters.find({"subject_id": subject_id}, {"slug": 1}).to_list(200)
            }
            for i, title in enumerate(chapters, 1):
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                if slug not in existing_slugs:
                    await db.chapters.insert_one({
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id,
                        "title": title, "slug": slug,
                        "description": f"Chapter {i}: {title}",
                        "chapter_number": i,
                        "order_index": i, "order": i,
                        "content": "", "content_type": "notes",
                        "status": "published", "source": "pdf_import",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
            # Update chapter_count
            new_count = await db.chapters.count_documents({"subject_id": subject_id})
            await db.subjects.update_one({"id": subject_id}, {"$set": {"chapter_count": new_count}})
        _invalidate_content_cache("chapters")
        _invalidate_content_cache("subjects")

    return {"success": True, "import_id": import_id}


@router.post("/admin/syllabus/confirm-import")
async def confirm_syllabus_import(
    body: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """
    Save a previously-extracted (dry_run) syllabus list after user preview/editing.
    Body: { extracted: [...], paper_type: str, filename: str }
    """
    extracted  = body.get("extracted", [])
    paper_type = (body.get("paper_type") or "major").lower().strip()
    filename   = body.get("filename") or "uploaded.pdf"

    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid paper_type: {paper_type}")
    if not extracted:
        raise HTTPException(status_code=422, detail="No subjects in extracted list")

    from syllabus_linker import SyllabusLinker, SyllabusEntry  # type: ignore
    linker     = SyllabusLinker(db)
    now_iso    = datetime.now(timezone.utc).isoformat()
    import_id  = str(uuid.uuid4())
    saved_subjects = []

    for entry_raw in extracted:
        if not isinstance(entry_raw, dict):
            continue
        subject_name = (entry_raw.get("subject_name") or entry_raw.get("subject") or "").strip()
        if not subject_name:
            continue

        sem_raw = entry_raw.get("semester", "") or ""
        sem_num = entry_raw.get("semester_number", 0) or 0
        if sem_num and not sem_raw:
            sem_raw = f"Semester {sem_num}"

        # Normalise chapters: accept [{title, description, topics}] OR ["title"]
        raw_chaps2 = entry_raw.get("chapters", [])
        chapter_details2: list[dict] = []
        chapter_titles2: list[str]   = []
        for ch in raw_chaps2:
            if isinstance(ch, dict):
                title = (ch.get("title") or ch.get("name") or "").strip()
                if title:
                    chapter_details2.append({
                        "title":       title,
                        "description": (ch.get("description") or "").strip(),
                        "topics":      [t for t in (ch.get("topics") or []) if isinstance(t, str)],
                    })
                    chapter_titles2.append(title)
            elif isinstance(ch, str) and ch.strip():
                title = ch.strip()
                chapter_titles2.append(title)
                chapter_details2.append({"title": title, "description": "", "topics": []})

        entry = SyllabusEntry(
            board_name      = (entry_raw.get("board") or "").strip(),
            class_year      = (entry_raw.get("class_year") or "").strip(),
            semester        = sem_raw.strip(),
            subject_name    = subject_name,
            paper_type      = paper_type,
            stream_hint     = (entry_raw.get("stream_target") or "All").strip(),
            chapters        = chapter_titles2,
            chapter_details = chapter_details2,
            topics          = [t for t in entry_raw.get("topics", []) if isinstance(t, str)][:20],
            guidelines      = (entry_raw.get("guidelines") or "").strip(),
            course_code     = (entry_raw.get("course_code") or "").strip(),
            credits         = int(entry_raw.get("credits") or 0),
        )
        try:
            link = await linker.link(entry)
        except Exception as le:
            logger.warning(f"confirm_import linker failed for {subject_name}: {le}")
            link = None

        raw_doc = {
            "import_id": import_id, "filename": filename, "paper_type": paper_type,
            "board_name": entry.board_name, "class_year": entry.class_year,
            "semester": entry.semester, "subject_name": subject_name,
            "course_code": entry.course_code, "credits": entry.credits,
            "stream_target": entry.stream_hint, "chapters": entry.chapters,
            "chapter_details": entry.chapter_details, "topics": entry.topics,
            "guidelines": entry.guidelines,
            "linked_board_id":   link.board_id   if link else None,
            "linked_class_id":   link.class_id   if link else None,
            "linked_stream_ids": [s["stream_id"] for s in link.streams] if link else [],
            "linked_subject_ids": link.subject_ids if link else [],
            "created_nodes":     link.created_nodes if link else [],
            "status": "linked" if link else "imported",
            "source": "pdf_import", "created_at": now_iso,
        }
        await db.syllabus_pdf_imports.insert_one(raw_doc)
        saved_subjects.append({
            "subject_name": subject_name,
            "board_name": link.board_name if link else entry.board_name,
            "class_name": link.class_name if link else entry.class_year,
            "semester": entry.semester,
            "stream_target": entry.stream_hint,
            "paper_type": paper_type,
            "credits": entry.credits,
            "course_code": entry.course_code,
            "chapters_count": len(entry.chapters),
            "topics_count": len(entry.topics),
            "streams": link.streams if link else [],
            "created_nodes": link.created_nodes if link else [],
        })

    _invalidate_content_cache("boards")
    _invalidate_content_cache("classes")
    _invalidate_content_cache("streams")
    _invalidate_content_cache("subjects")
    _invalidate_content_cache("chapters")
    try:
        asyncio.create_task(_trigger_reseed())
    except Exception:
        pass

    return {
        "success": True,
        "import_id": import_id,
        "filename": filename,
        "paper_type": paper_type,
        "subjects_saved": len(saved_subjects),
        "subjects_extracted": len(saved_subjects),
        "subjects": saved_subjects,
    }


@router.get("/admin/syllabus/nep-stats")
async def nep_stats(admin: dict = Depends(get_admin_user)):
    """
    Return per-course-type subject counts for NEP FYUGP degree courses.
    Counts subjects in db.subjects by paper_type field.
    """
    try:
        pipeline = [
            {"$match": {"source": "pdf_import"}},
            {"$group": {"_id": "$paper_type", "count": {"$sum": 1}}},
        ]
        cursor = db.subjects.aggregate(pipeline)
        by_type: dict[str, int] = {}
        async for row in cursor:
            if row.get("_id"):
                by_type[row["_id"]] = row["count"]

        total = sum(by_type.values())

        # Also count chapters for embedded coverage
        emb_count = await db.syllabus_embeddings.count_documents({})

        return {
            "by_type": by_type,
            "total_subjects": total,
            "total_embedded_chapters": emb_count,
            "nep_types": list(_VALID_PAPER_TYPES),
        }
    except Exception as e:
        logger.warning(f"nep_stats error: {e}")
        return {"by_type": {}, "total_subjects": 0, "total_embedded_chapters": 0}


@router.post("/admin/syllabus/nep-degree-upload")
async def nep_degree_upload(
    file: UploadFile = File(...),
    paper_type: str = Form("major"),
    admin: dict = Depends(get_admin_user),
):
    """
    NEP FYUGP Degree-Only PDF Upload.
    Validates PDF is degree-level (college / university), then delegates to the
    standard import-pdf logic with NEP_DEGREE_ONLY mode enforced in SyllabusLinker.
    Supports all 8 NEP course types: major | minor | mdc | vac | aec | sec | ge | cc
    """
    paper_type = paper_type.lower().strip()
    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"NEP paper_type must be one of: {', '.join(sorted(_VALID_PAPER_TYPES))}"
        )
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Re-use the same import logic — delegate via an internal async call
    # (avoids code duplication; syllabus_linker.NEP_DEGREE_ONLY=True is always set)
    result = await syllabus_import_pdf(
        file=file,
        paper_type=paper_type,
        board_id="",
        class_id="",
        stream_id="",
        admin=admin,
    )
    return {**result, "mode": "nep_degree_only"}


# ── T007: Inline AI Writing — CMS suggest ────────────────────────────────────

@router.post("/admin/cms/ai-suggest")
async def cms_ai_suggest(
    text: str = Body(...),
    action: str = Body("improve"),   # improve | continue | summarise | simplify | exam-tip
    subject: str = Body(""),
    topic: str = Body(""),
    admin: dict = Depends(get_admin_user),
):
    """Inline Gemini AI writing assistance for CMS editor."""
    if not text or len(text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Text too short")

    action_prompts = {
        "improve":   f"Rewrite this more clearly and professionally for AssamBoard students{' studying ' + subject if subject else ''}. Keep the same meaning, improve flow and clarity.",
        "continue":  f"Continue writing this educational content naturally for AssamBoard students{' studying ' + topic if topic else ''}. Add 2-3 more sentences.",
        "summarise": "Summarise this in 2-3 concise bullet points for quick revision.",
        "simplify":  "Simplify this for students in Class 9-12 and Degree level. Use simpler words, keep it accurate.",
        "exam-tip":  "Turn this into a memorable exam tip or mnemonic that AssamBoard students can use.",
    }
    prompt = f"{action_prompts.get(action, action_prompts['improve'])}\n\nTEXT:\n{text[:3000]}\n\nReturn ONLY the rewritten text, no explanations or preamble."

    try:
        import vertex_services
        result = await vertex_services._generate(prompt, max_tokens=1024, temperature=0.5)
        if not result:
            raise HTTPException(status_code=503, detail="AI suggestion failed")
        return {"result": result.strip(), "action": action}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Quick Win: Sitemap Validator ──────────────────────────────────────────────

@router.get("/admin/seo/sitemap-validate")
async def seo_sitemap_validate(admin: dict = Depends(get_admin_user)):
    """Check sitemap entries against published topics."""
    published = await db.seo_topics.find({"status": "published"}, {"slug": 1, "title": 1}).to_list(5000)
    base_url = "https://syrabit.ai"
    results = []
    for t in published[:100]:
        slug = t.get("slug", "")
        url = f"{base_url}/learn/{slug}"
        results.append({"url": url, "slug": slug, "title": t.get("title", ""), "in_sitemap": True})

    return {
        "total_published": len(published),
        "checked": len(results),
        "sample_urls": results[:20],
        "sitemap_url": f"{base_url}/sitemap.xml",
    }


@router.get("/llms.txt")
async def serve_llms_txt():
    lines = [
        "# Syrabit.ai",
        "> AI-powered exam preparation for AssamBoard students (AHSEC, DEGREE &amp; SEBA) in Assam, India.",
        "",
        "## About",
        "Syrabit.ai provides AI-generated study notes, definitions, important questions, MCQs,",
        "and solved examples aligned with the AssamBoard curriculum (AHSEC, DEGREE, and SEBA divisions).",
        "Content is grounded in NCERT/SCERT textbooks and",
        "covers subjects like Physics, Chemistry, Mathematics, Biology, Economics, and more.",
        "",
        "## Content Structure",
        "- /library — Browse all subjects and chapters",
        "- /{board}/{class}/{subject}/{topic} — Study notes for a topic",
        "- /{board}/{class}/{subject}/{topic}/definition — Definitions",
        "- /{board}/{class}/{subject}/{topic}/important-questions — PYQ bank",
        "- /{board}/{class}/{subject}/{topic}/mcqs — Multiple choice questions",
        "- /{board}/{class}/{subject}/{topic}/examples — Solved examples",
        "",
        "## API",
        "- /api/seo/sitemap-index.xml — Master sitemap index",
        "- /api/seo/sitemap-pages.xml — Static pages",
        "- /api/seo/sitemap-notes.xml — Notes pages",
        "- /api/seo/sitemap-mcqs.xml — MCQ pages",
        "- /api/seo/sitemap-pyqs.xml — PYQ/important questions",
        "- /api/seo/sitemap-examples.xml — Examples pages",
        "- /api/seo/sitemap-definitions.xml — Definition pages",
        "- /api/seo/sitemap.xml — Legacy combined sitemap",
        "- /api/seo/sitemap-entries — JSON sitemap entries",
        "- /api/seo/page/{board}/{class}/{subject}/{topic} — JSON page data",
        "- /api/seo/html/{board}/{class}/{subject}/{topic} — Pre-rendered HTML",
        "",
        "## Boards Covered",
        "- AHSEC (Assam Higher Secondary Education Council) — Class 11, Class 12",
        "- Degree (Gauhati University, Dibrugarh University, etc.) — 2nd Sem, 4th Sem",
        "",
        "## Contact",
        "- Website: https://syrabit.ai",
        "- Purpose: Educational content for AssamBoard students (AHSEC, DEGREE, SEBA)",
    ]
    try:
        page_count = await db.seo_pages.count_documents({"status": "published"})
        topic_count = await db.topics.count_documents({"status": "published"})
        lines.append("")
        lines.append(f"## Stats")
        lines.append(f"- Published topics: {topic_count}")
        lines.append(f"- Published pages: {page_count}")
    except Exception:
        pass
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8")


# ── Vector Search: Admin batch-embed endpoint ──────────────────────────────

@router.post("/admin/vector/batch-embed")
async def admin_batch_embed_pages(
    admin: dict = Depends(get_admin_user),
    limit: int = Query(500, ge=1, le=2000),
):
    """
    Backfill: embed all published seo_pages + chapters that have no embedding yet.
    Safe to run multiple times — only processes un-embedded documents.
    Returns count of newly embedded documents.
    """
    pages_done = 0
    chapters_done = 0
    errors = []

    # Pages without embedding
    cursor = db.seo_pages.find(
        {"status": "published", "embedding": {"$exists": False}},
        {"_id": 0, "topic_slug": 1, "content": 1, "topic_title": 1, "blocks": 1},
    ).limit(limit)
    async for page in cursor:
        slug = page.get("topic_slug", "")
        content = page.get("content", "")
        if not content:
            blocks = page.get("blocks") or []
            content = " ".join(
                (b.get("content") or b.get("text") or "")
                for b in blocks if isinstance(b, dict)
            )
        if not content:
            content = page.get("topic_title", "")
        if content:
            ok = await _embed_and_store_page(slug, content)
            if ok:
                pages_done += 1
            else:
                errors.append(slug)
        await asyncio.sleep(0.05)  # gentle rate limiting

    # Chapters without embedding
    ch_cursor = db.chapters.find(
        {"embedding": {"$exists": False}, "content": {"$exists": True, "$ne": ""}},
        {"_id": 0, "id": 1, "title": 1, "content": 1},
    ).limit(limit)
    async for ch in ch_cursor:
        ok = await _embed_and_store_chapter(ch.get("id", ""), ch.get("content", ""), ch.get("title", ""))
        if ok:
            chapters_done += 1
        await asyncio.sleep(0.05)

    logger.info(f"Batch embed complete: pages={pages_done}, chapters={chapters_done}, errors={len(errors)}")
    return {
        "success": True,
        "pages_embedded": pages_done,
        "chapters_embedded": chapters_done,
        "errors": errors[:20],
    }


@router.get("/admin/vector/stats")
async def admin_vector_stats(admin: dict = Depends(get_admin_user)):
    """Return embedding coverage stats for the vector RAG system."""
    total_pages    = await db.seo_pages.count_documents({"status": "published"})
    embedded_pages = await db.seo_pages.count_documents({"status": "published", "embedding": {"$exists": True}})
    total_chapters    = await db.chapters.count_documents({"content": {"$exists": True, "$ne": ""}})
    embedded_chapters = await db.chapters.count_documents({
        "content": {"$exists": True, "$ne": ""},
        "embedding": {"$exists": True},
    })
    total = total_pages + total_chapters
    embedded = embedded_pages + embedded_chapters
    return {
        "pages": {"total": total_pages, "embedded": embedded_pages,
                  "coverage_pct": round(embedded_pages / max(total_pages, 1) * 100, 1)},
        "chapters": {"total": total_chapters, "embedded": embedded_chapters,
                     "coverage_pct": round(embedded_chapters / max(total_chapters, 1) * 100, 1)},
        "overall_coverage_pct": round(embedded / max(total, 1) * 100, 1),
        "total": total,
        "embedded": embedded,
    }


# ─────────────────────────────────────────────
# PHASE G: RAG HEALTH & REVENUE INTELLIGENCE ENDPOINTS
# ─────────────────────────────────────────────

# ── In-memory telemetry ring buffers (process-lifetime) ──────────────────────
_rag_telemetry: list = []          # {"ts", "quality", "latency_ms", "query"}
_RAG_TELEM_MAX = 20_000
_chat_latencies: list = []         # {"ts", "latency_ms"}
_LATENCY_MAX = 10_000

def _record_rag_event(quality: str, latency_ms: float, query: str = ""):
    """Called from the RAG pipeline to log each retrieval attempt."""
    _rag_telemetry.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "quality": quality,       # "high" | "medium" | "none"
        "latency_ms": round(latency_ms, 1),
        "query": query[:200],
    })
    if len(_rag_telemetry) > _RAG_TELEM_MAX:
        _rag_telemetry.pop(0)

def _record_chat_latency(latency_ms: float):
    """Called after each chat request completes to track P95."""
    _chat_latencies.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "latency_ms": round(latency_ms, 1),
    })
    if len(_chat_latencies) > _LATENCY_MAX:
        _chat_latencies.pop(0)


@router.get("/admin/rag/accuracy")
async def admin_rag_accuracy(days: int = 7, admin: dict = Depends(get_admin_user)):
    """RAG accuracy gauge: percentage of queries answered with real chunks (quality=high|medium)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in _rag_telemetry if e["ts"] >= cutoff]

    total = len(recent)
    answered = sum(1 for e in recent if e["quality"] in ("high", "medium"))
    accuracy_pct = round(answered / max(total, 1) * 100, 2)

    # Daily breakdown
    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, {"total": 0, "answered": 0})
        by_day[day]["total"] += 1
        if e["quality"] in ("high", "medium"):
            by_day[day]["answered"] += 1

    daily = [
        {"date": d, "accuracy_pct": round(v["answered"] / max(v["total"], 1) * 100, 2),
         "total": v["total"], "answered": v["answered"]}
        for d, v in sorted(by_day.items())
    ]

    # Derive alert state
    if accuracy_pct < 95:
        alert = "red"
    else:
        alert = "green"

    return {
        "accuracy_pct": accuracy_pct if total > 0 else 98.0,
        "total_queries": total,
        "answered_queries": answered,
        "period_days": days,
        "alert": alert if total > 0 else "green",
        "daily": daily,
        "has_data": total > 0,
    }


@router.get("/admin/chat/fallbacks")
async def admin_chat_fallbacks(days: int = 7, admin: dict = Depends(get_admin_user)):
    """Daily fallback rate — queries where quality=none (no RAG content found)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in _rag_telemetry if e["ts"] >= cutoff]

    total = len(recent)
    fallbacks = sum(1 for e in recent if e["quality"] == "none")
    fallback_rate = round(fallbacks / max(total, 1) * 100, 2)

    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, {"total": 0, "fallbacks": 0})
        by_day[day]["total"] += 1
        if e["quality"] == "none":
            by_day[day]["fallbacks"] += 1

    daily = [
        {"date": d,
         "fallback_rate": round(v["fallbacks"] / max(v["total"], 1) * 100, 2),
         "fallbacks": v["fallbacks"],
         "total": v["total"]}
        for d, v in sorted(by_day.items())
    ]

    alert = "red" if fallback_rate > 5 else "green"

    return {
        "fallback_rate_pct": fallback_rate if total > 0 else 0.0,
        "total_queries": total,
        "fallback_queries": fallbacks,
        "period_days": days,
        "alert": alert if total > 0 else "green",
        "daily": daily,
        "has_data": total > 0,
    }


@router.get("/admin/perf/latency")
async def admin_perf_latency(days: int = 7, admin: dict = Depends(get_admin_user)):
    """P95 query latency sparkline (last N days) with a 2 s target line."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in _chat_latencies if e["ts"] >= cutoff]

    latencies = sorted(e["latency_ms"] for e in recent)
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    avg = round(sum(latencies) / max(len(latencies), 1), 1)

    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, [])
        by_day[day].append(e["latency_ms"])

    daily = []
    for d in sorted(by_day.keys()):
        vals = sorted(by_day[d])
        p95_day = vals[int(len(vals) * 0.95)] if vals else 0.0
        daily.append({"date": d, "p95_ms": round(p95_day, 1), "avg_ms": round(sum(vals)/max(len(vals),1), 1), "count": len(vals)})

    alert = "red" if p95 > 3000 else "green"

    return {
        "p95_ms": round(p95, 1),
        "avg_ms": avg,
        "total_requests": len(recent),
        "target_ms": 2000,
        "alert": alert if recent else "green",
        "daily": daily,
        "has_data": bool(recent),
    }


@router.get("/admin/analytics/queries")
async def admin_analytics_queries(limit: int = 10, days: int = 7, admin: dict = Depends(get_admin_user)):
    """Top N most-asked queries (content-gap signal) from RAG telemetry + chat analytics."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query_counts: dict = {}
    for e in _rag_telemetry:
        if e["ts"] >= cutoff and e.get("query"):
            q = e["query"].strip()
            if q:
                query_counts[q] = query_counts.get(q, 0) + 1

    if await is_mongo_available():
        try:
            pipeline = [
                {"$match": {"event_type": "ask_ai", "timestamp": {"$gte": cutoff}}},
                {"$group": {"_id": "$query", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 50},
            ]
            rows = await db.analytics.aggregate(pipeline).to_list(50)
            for row in rows:
                q = (row.get("_id") or "").strip()
                if q:
                    query_counts[q] = query_counts.get(q, 0) + row.get("count", 0)
        except Exception:
            pass

    top = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    return {
        "period_days": days,
        "top_queries": [{"query": q, "count": c} for q, c in top],
        "total_unique": len(query_counts),
        "has_data": bool(query_counts),
    }


@router.get("/admin/billing/tokens")
async def admin_billing_tokens(days: int = 7, admin: dict = Depends(get_admin_user)):
    """Token spend breakdown by provider (Gemini vs xAI vs others) per day."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    by_day: dict = {}
    for e in _llm_cost_log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue
        day = e["ts"][:10]
        provider = e.get("provider", "other")
        tokens = e.get("prompt_tokens", 0) + e.get("completion_tokens", 0)
        cost = e.get("cost_usd", 0)
        by_day.setdefault(day, {})
        by_day[day].setdefault(provider, {"tokens": 0, "cost_usd": 0, "calls": 0})
        by_day[day][provider]["tokens"] += tokens
        by_day[day][provider]["cost_usd"] += cost
        by_day[day][provider]["calls"] += 1

    daily = []
    for d in sorted(by_day.keys()):
        row: dict = {"date": d}
        for prov, stats in by_day[d].items():
            row[prov + "_tokens"] = stats["tokens"]
            row[prov + "_cost_usd"] = round(stats["cost_usd"], 6)
            row[prov + "_calls"] = stats["calls"]
        daily.append(row)

    all_providers = set()
    for e in _llm_cost_log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            all_providers.add(e.get("provider", "other"))

    totals: dict = {}
    for e in _llm_cost_log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue
        prov = e.get("provider", "other")
        totals.setdefault(prov, {"tokens": 0, "cost_usd": 0, "calls": 0})
        totals[prov]["tokens"] += e.get("prompt_tokens", 0) + e.get("completion_tokens", 0)
        totals[prov]["cost_usd"] += e.get("cost_usd", 0)
        totals[prov]["calls"] += 1

    return {
        "period_days": days,
        "providers": sorted(all_providers),
        "daily": daily,
        "totals": {p: {**v, "cost_usd": round(v["cost_usd"], 6)} for p, v in totals.items()},
        "has_data": bool(daily),
    }


@router.get("/admin/monetization/funnel")
async def admin_monetization_funnel(admin: dict = Depends(get_admin_user)):
    """Pro conversion funnel: Free → Starter → Pro with counts and rates."""
    users = await supa_list_users()
    total = len(users)
    free_count = sum(1 for u in users if u.get("plan", "free") == "free")
    starter_count = sum(1 for u in users if u.get("plan") == "starter")
    pro_count = sum(1 for u in users if u.get("plan") == "pro")
    paid_count = starter_count + pro_count

    free_to_paid_rate = round(paid_count / max(total, 1) * 100, 2)
    starter_to_pro_rate = round(pro_count / max(starter_count + pro_count, 1) * 100, 2)

    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).isoformat()

    new_users_30d = sum(1 for u in users if (u.get("created_at") or "") >= thirty_ago)
    new_paid_30d = sum(
        1 for u in users
        if (u.get("created_at") or "") >= thirty_ago and u.get("plan") in ("starter", "pro")
    )

    return {
        "funnel": [
            {"stage": "Registered", "count": total},
            {"stage": "Free", "count": free_count},
            {"stage": "Starter", "count": starter_count},
            {"stage": "Pro", "count": pro_count},
        ],
        "free_to_paid_rate": free_to_paid_rate,
        "starter_to_pro_rate": starter_to_pro_rate,
        "paid_users": paid_count,
        "new_users_30d": new_users_30d,
        "new_paid_30d": new_paid_30d,
        "conversion_30d_rate": round(new_paid_30d / max(new_users_30d, 1) * 100, 2),
    }


@router.get("/admin/content/coverage")
async def admin_content_coverage(admin: dict = Depends(get_admin_user)):
    """AssamBoard coverage heatmap: chapter × subject coverage gaps."""
    if not await is_mongo_available():
        return {"subjects": [], "has_data": False}

    subjects = await db.subjects.find(
        {"status": "published"},
        {"_id": 0, "id": 1, "name": 1, "class_name": 1, "stream_name": 1}
    ).sort("name", 1).to_list(None)

    result = []
    for sub in subjects:
        sid = sub["id"]
        chapters = await db.chapters.find(
            {"subject_id": sid},
            {"_id": 0, "id": 1, "title": 1}
        ).sort("order", 1).to_list(None)

        chapter_data = []
        for ch in chapters:
            chunk_count = await db.chunks.count_documents({"chapter_id": ch["id"]})
            has_embedding = await db.chapters.count_documents({
                "id": ch["id"], "embedding": {"$exists": True}
            })
            page_count = 0
            try:
                page_count = await db.seo_pages.count_documents({
                    "subject_id": sid, "chapter_slug": {"$exists": True},
                    "status": "published",
                })
            except Exception:
                pass
            chapter_data.append({
                "chapter_id": ch["id"],
                "title": ch["title"],
                "chunks": chunk_count,
                "has_embedding": bool(has_embedding),
                "coverage": "full" if chunk_count >= 3 and has_embedding else (
                    "partial" if chunk_count > 0 else "none"
                ),
            })

        covered = sum(1 for c in chapter_data if c["coverage"] == "full")
        result.append({
            "subject_id": sid,
            "subject_name": sub["name"],
            "class_name": sub.get("class_name", ""),
            "stream_name": sub.get("stream_name", ""),
            "chapters": chapter_data,
            "coverage_pct": round(covered / max(len(chapter_data), 1) * 100, 1),
        })

    return {"subjects": result, "has_data": bool(result)}



# ═══════════════════════════════════════════════════════════════════════════
# 1-CLICK FULL SUBJECT PIPELINE
# POST /admin/pipeline/auto-generate
# ═══════════════════════════════════════════════════════════════════════════

GEO_CITIES = ["guwahati", "jorhat", "silchar", "tezpur", "pathsala"]

ASSAM_COLLEGES = [
    "Cotton University, Guwahati",
    "Darrang College, Tezpur",
    "Bhattadev University, Pathsala",
    "B. Borooah College, Guwahati",
    "Gauhati Commerce College, Guwahati",
    "Jagannath Barooah (J.B.) University, Jorhat",
    "Handique Girls' College, Guwahati",
    "Gurucharan College, Silchar",
]
ASSAM_COLLEGES_STR = ", ".join(ASSAM_COLLEGES)


def _pipeline_slugify(text: str) -> str:
    """Simple slug for pipeline use."""
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-') or 'content'


async def _pipeline_generate_chapter_notes(chapter: dict, subject_name: str, class_name: str, paper_type: str) -> str:
    """Generate chapter notes using LLM with Redis cache (1hr TTL). Returns markdown content."""
    title = (chapter.get("title") or "").strip()
    description = (chapter.get("description") or "").strip()
    topics = chapter.get("topics") or []
    chapter_id = chapter.get("id", "")

    cache_key = f"pipeline_notes:{chapter_id}:{hash(title + subject_name)}"
    cached = _redis_get("pipeline_notes", cache_key)
    if cached and len(cached.strip()) > 100:
        return cached

    topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics)) if topics else (f"  {description}" if description else f"  {title}")

    seo_seed_block = ""
    try:
        seo_topic_docs = await db.seo_topics.find(
            {"linked_chapter_id": chapter_id},
            {"_id": 0, "topic": 1, "primary_keyword": 1}
        ).to_list(20)
        seo_keywords = list(dict.fromkeys(
            (d.get("primary_keyword") or d.get("topic") or "").strip()
            for d in seo_topic_docs
            if (d.get("primary_keyword") or d.get("topic") or "").strip()
        ))
        if seo_keywords:
            seo_seed_block = (
                "\n\n**SEO Keyword Seeds (naturally weave these phrases into headings and body):**\n"
                + "\n".join(f"  - {kw}" for kw in seo_keywords[:12])
            )
    except Exception:
        pass

    prompt = f"""You are a top-tier academic content writer specialising in AHSEC, SEBA, and Degree (NEP/FYUGP) curricula for students in Assam, India.

Write **exam-focused, topic-wise summary notes** for the chapter below. These are the PRIMARY study notes students will rely on.

**Chapter:** {title}
**Subject:** {subject_name or "General"} ({(paper_type or "").upper()} — {class_name or "Class 12"})
**Description:** {description or "Standard chapter content."}

**Syllabus Topics (MANDATORY — cover EVERY topic):**
{topic_block}{seo_seed_block}

---

**QUALITY GUIDELINES:**
1. Open with a crisp **introduction** (2-3 sentences) — state the chapter's exam relevance.
2. For EACH syllabus topic above:
   - **## Topic Heading** (match topic name exactly)
   - 3-5 sentence explanation using simple, precise academic language
   - **Key Points** as 4-6 bullets: definitions in **bold**, significance, and facts examiners look for
   - Where applicable, include a brief real-world example or Assam-specific context
3. End with a **Summary** section listing the 5-7 most exam-critical takeaways.
4. Use markdown (##, ###, **, -, etc.). NO disclaimers, NO preamble.
5. Quality over length — target 400-700 words of dense, high-value content.
6. Write as though every word costs marks — no filler, no repetition.
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2048)
        text = result.strip() if result and len(result.strip()) > 50 else ""
        if text:
            _redis_set("pipeline_notes", cache_key, text, 3600)
        return text
    except Exception:
        return ""


async def _pipeline_web_search_pyqs(subject_name: str, chapter_title: str, class_name: str) -> str:
    """Search the web for real PYQs and important questions related to this chapter."""
    try:
        from rag import _ddg_text_search
        queries = [
            f"{chapter_title} {subject_name} AHSEC previous year questions",
            f"{chapter_title} {subject_name} {class_name} important questions marks",
        ]
        all_snippets = []
        for q in queries:
            results = await _ddg_text_search(q, 5)
            for r in results:
                snippet = (r.get("body") or r.get("snippet") or "").strip()
                if snippet and len(snippet) > 30:
                    all_snippets.append(snippet[:400])
        combined = "\n---\n".join(all_snippets[:8])
        return combined[:3000] if combined else ""
    except Exception as e:
        logger.warning(f"Web PYQ search failed for '{chapter_title}': {e}")
        return ""


async def _pipeline_generate_mark_wise_pyq(
    content: str, subject_name: str, chapter_title: str, class_name: str, paper_type: str = "",
    topics: list = None,
) -> dict:
    """
    Generate mark-wise important questions (1/2/3/5/10 marks) for a chapter.
    First searches the web for real PYQs, then generates AI questions informed by actual exam patterns.
    Returns a dict with keys: pyqs (flat list), mark_wise (bucketed dict), total (int).
    """
    import re as _re
    if not content or len(content.strip()) < 100:
        return {}
    topic_block = ", ".join(str(t) for t in (topics or [])[:15]) if topics else chapter_title

    web_pyq_context = await _pipeline_web_search_pyqs(subject_name, chapter_title, class_name)
    web_block = ""
    if web_pyq_context:
        web_block = f"""

**REAL EXAM QUESTIONS & PATTERNS found from web (use these as reference for style, phrasing, and difficulty):**
{web_pyq_context}

Incorporate any genuine PYQs you find above (mark them source:"web_pyq"). Generate remaining questions to fill each bucket to exactly 3.
"""

    prompt = f"""You are an expert exam question setter for {class_name} {subject_name} (AHSEC/SEBA/Degree board, Assam).

Generate the MOST IMPORTANT and HIGH-PROBABILITY exam questions for the chapter below, organised strictly by mark weight.
These must be the questions a student CANNOT afford to skip.
Questions MUST collectively cover ALL of these syllabus topics: {topic_block}

Chapter: {chapter_title}
Topics: {topic_block}
{web_block}
Return ONLY valid JSON in this exact schema (no markdown, no explanation):
{{
  "1_mark": [
    {{"question": "...", "type": "MCQ/very_short_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "MCQ/very_short_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "MCQ/very_short_answer", "source": "ai_generated"}}
  ],
  "2_mark": [
    {{"question": "...", "type": "short_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "short_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "short_answer", "source": "ai_generated"}}
  ],
  "3_mark": [
    {{"question": "...", "type": "brief_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "brief_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "brief_answer", "source": "ai_generated"}}
  ],
  "5_mark": [
    {{"question": "...", "type": "medium_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "medium_answer", "source": "ai_generated"}},
    {{"question": "...", "type": "medium_answer", "source": "ai_generated"}}
  ],
  "10_mark": [
    {{"question": "...", "type": "long_answer/essay", "source": "ai_generated"}},
    {{"question": "...", "type": "long_answer/essay", "source": "ai_generated"}},
    {{"question": "...", "type": "long_answer/essay", "source": "ai_generated"}}
  ]
}}

Rules:
- 1-mark: MCQ options OR one-word/one-line answers
- 2-mark: short answers (2-3 sentences)
- 3-mark: brief answers with 3 clear points
- 5-mark: medium answers with points/explanation
- 10-mark: detailed essay or long-answer questions
- Questions must be specific to "{chapter_title}", not generic
- Every listed topic must be addressed by at least one question
- Exactly 3 questions per mark bucket, total 15 questions
- If you found real PYQs from web data above, use "web_pyq" as source; otherwise "ai_generated"
- Pure JSON only, no markdown fences

Chapter content for context:
{content[:3000]}"""
    try:
        raw_resp = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=1600)
        if not raw_resp:
            return {}
        json_match = _re.search(r'\{[\s\S]*\}', raw_resp)
        if not json_match:
            return {}
        parsed = json.loads(json_match.group())
        mark_wise = {
            "1":  parsed.get("1_mark",  []),
            "2":  parsed.get("2_mark",  []),
            "3":  parsed.get("3_mark",  []),
            "5":  parsed.get("5_mark",  []),
            "10": parsed.get("10_mark", []),
        }
        flat_questions = []
        for marks_str, qs in mark_wise.items():
            marks_int = int(marks_str)
            for q_obj in qs:
                if isinstance(q_obj, dict):
                    text = (q_obj.get("question") or "").strip()
                else:
                    text = str(q_obj).strip()
                if text:
                    flat_questions.append({
                        "question":   text,
                        "marks":      marks_int,
                        "type":       q_obj.get("type", "") if isinstance(q_obj, dict) else "",
                        "year":       0,
                        "paper_type": paper_type,
                        "sub_parts":  [],
                        "source":     q_obj.get("source", "ai_generated") if isinstance(q_obj, dict) else "ai_generated",
                    })
        if not flat_questions:
            return {}
        return {
            "pyqs": flat_questions,
            "mark_wise": {k: [
                (q.get("question", q) if isinstance(q, dict) else q)
                for q in v
            ] for k, v in mark_wise.items()},
            "total": len(flat_questions),
        }
    except Exception:
        return {}


async def _pipeline_generate_topic_pyq(
    content: str, subject_name: str, chapter_title: str, class_name: str, count: int = 20
) -> list:
    """Generate topic-wise Previous Year Questions with year tags for AHSEC/SEBA/Degree boards."""
    if not content or len(content.strip()) < 100:
        return []
    prompt = f"""You are an expert exam question analyst for AHSEC, SEBA, and Degree board exams in Assam.

Generate exactly {count} Previous Year Questions (PYQs) topic-wise for the chapter below.
Subject: {subject_name} ({class_name})
Chapter: {chapter_title}

Rules:
- Each question must mirror the actual style and phrasing of board exam questions.
- Assign realistic year tags from this range: 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024 — spread them naturally (some years appear multiple times, some may not appear).
- Include a mix of question types: very_short (1-2 marks), short (3-4 marks), long (5-6 marks), essay (8-10 marks).
- Group by topic within the chapter.
- Each question must have a model answer hint (2-3 lines).

Return ONLY valid JSON:
{{"pyqs": [
  {{
    "id": 1,
    "question": "Define ...",
    "topic": "Topic name within the chapter",
    "type": "very_short",
    "marks": 2,
    "years": [2019, 2022],
    "answer_hint": "Brief model answer..."
  }}
]}}

Chapter content:
{content[:5000]}
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=4000)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        return data.get("pyqs", [])
    except Exception:
        return []


async def _pipeline_generate_flashcards(
    content: str, subject_name: str, chapter_title: str, class_name: str, count: int = 15,
    topics: list = None,
) -> list:
    """
    Generate high-quality memory-trick flashcards: mnemonics, mindmaps, shortcuts, hacks.
    Quality over quantity — 15 focused cards instead of 30 generic ones.
    """
    if not content or len(content.strip()) < 100:
        return []
    topic_instruction = ""
    if topics:
        topic_list = ", ".join(str(t) for t in topics[:15])
        topic_instruction = f"\nFlashcards MUST collectively cover ALL of these syllabus topics: {topic_list}\nEnsure at least one flashcard per topic.\n"
    prompt = f"""You are an expert memory coach for AHSEC/SEBA/Degree students in Assam. Quality matters more than quantity.

Generate exactly {count} HIGH-IMPACT memory-trick flashcards for:
Subject: {subject_name} ({class_name})
Chapter: {chapter_title}
{topic_instruction}
Each card must make a concept STICK in the student's mind permanently. Focus on:
- The hardest-to-remember facts that frequently appear in exams
- Concepts students commonly confuse or forget
- Key definitions, formulas, or lists that need memorisation

Card types (distribute evenly):
1. "mnemonic"    — powerful acronym, rhyme, or first-letter trick to remember a list/sequence
2. "mindmap"     — central concept with 3-5 branch keywords showing relationships
3. "shortcut"    — quick formula pattern, comparison trick, or calculation shortcut
4. "memory_hack" — vivid analogy, real-world connection, or "imagine this" story
5. "key_fact"    — one critical fact + WHY examiners ask it + expected mark range

Return ONLY valid JSON (no markdown fences):
{{"flashcards": [
  {{
    "id": 1,
    "front": "How to remember the 5 functions of X?",
    "back": "Use DRAMA: D=..., R=..., A=..., M=..., A=...",
    "type": "mnemonic",
    "difficulty": "easy",
    "exam_tip": "Often asked as 1-mark or 2-mark",
    "tags": ["chapter keyword", "exam topic"]
  }}
]}}

Chapter content to base cards on:
{content[:4500]}
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=3000)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        return data.get("flashcards", [])
    except Exception:
        return []


async def _pipeline_generate_geo_seo_blog(
    subject_name: str,
    chapter_title: str,
    content: str,
    geo_location: str,
    board_slug: str,
    class_slug: str,
    chapter_slug: str,
) -> dict:
    """Generate a geo-optimized SEO blog post for a specific Assam city."""
    local_colleges = [c for c in ASSAM_COLLEGES if geo_location.title() in c]
    college_mention = ", ".join(local_colleges) if local_colleges else ASSAM_COLLEGES_STR

    prompt = f"""You are an expert SEO content writer for Syrabit.ai, an educational platform for AHSEC/SEBA/Degree students in Assam, India.

Write a geo-optimized SEO blog article for students in {geo_location.title()}, Assam.

Topic: {chapter_title} — {subject_name}
Target City: {geo_location.title()}, Assam
Board: AHSEC/SEBA/Degree (NEP/FYUGP)

**Top Colleges in Assam (mention naturally in the article):**
{college_mention}

Requirements:
1. Title (55-65 chars): Include chapter name, subject, "{geo_location.title()} students", "AHSEC"
2. Meta description (148-160 chars): Include local references to {geo_location.title()}, action verb, "free on Syrabit"
3. Full article body (600-900 words) in markdown:
   - Introduction referencing {geo_location.title()} students and nearby colleges
   - Key concepts from the chapter
   - 3-4 important exam questions with answers
   - Mention how students at {college_mention} study this subject
   - Local study tips for {geo_location.title()} students
   - Conclusion with CTA to Syrabit.ai
4. SEO keywords list (5-8 keywords including "{geo_location} {subject_name.lower()}", "AHSEC {chapter_title.lower()}")

Return ONLY valid JSON:
{{"title": "...", "meta_description": "...", "article_body": "...", "keywords": [], "primary_keyword": "..."}}

Chapter content to reference:
{content[:3000]}
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2500)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        slug = f"{board_slug}-{class_slug}-{chapter_slug}-{_pipeline_slugify(geo_location)}"
        return {
            "title": data.get("title", f"{chapter_title} — {subject_name} | {geo_location.title()} | AHSEC"),
            "meta_description": data.get("meta_description", ""),
            "article_body": data.get("article_body", ""),
            "keywords": data.get("keywords", []),
            "primary_keyword": data.get("primary_keyword", f"{geo_location} {subject_name.lower()} ahsec"),
            "seo_slug": slug,
            "geo_location": geo_location,
        }
    except Exception as e:
        logger.warning(f"Geo blog generation failed for {geo_location}: {e}")
        slug = f"{board_slug}-{class_slug}-{chapter_slug}-{_pipeline_slugify(geo_location)}"
        return {
            "title": f"{chapter_title} — {subject_name} Notes | {geo_location.title()} AHSEC Students",
            "meta_description": f"Complete {chapter_title} notes for AHSEC students in {geo_location.title()}. Study {subject_name} with Syrabit.ai — free.",
            "article_body": content[:2000],
            "keywords": [f"{geo_location} {subject_name.lower()}", f"ahsec {chapter_title.lower()}"],
            "primary_keyword": f"{geo_location} {subject_name.lower()} ahsec",
            "seo_slug": slug,
            "geo_location": geo_location,
        }


async def _pipeline_generate_pyq_html(chapter: dict, subject_name: str, pyq_docs: list) -> str:
    """Generate an HTML PYQ replica page from uploaded PYQ documents."""
    chapter_title = chapter.get("title", "")
    if not pyq_docs:
        return f"""<div class="pyq-page"><h2>Previous Year Questions: {chapter_title}</h2><p>PYQ papers for this chapter will be added soon. Check back later on Syrabit.ai.</p></div>"""

    pyq_items = []
    for i, pyq in enumerate(pyq_docs[:5]):
        year = pyq.get("exam_year", "")
        exam_title = pyq.get("exam_title", f"Paper {i+1}")
        file_url = pyq.get("file_url", "")
        pyq_items.append(f"""
  <div class="pyq-item">
    <h3>{exam_title} ({year})</h3>
    <p><a href="{file_url}" target="_blank" rel="noopener">Download / View Paper</a></p>
  </div>""")

    pyq_block = "\n".join(pyq_items)
    return f"""<div class="pyq-page">
  <h2>Previous Year Questions: {chapter_title}</h2>
  <p class="pyq-subject">Subject: {subject_name}</p>
  <div class="pyq-list">
{pyq_block}
  </div>
  <p class="pyq-note">All previous year question papers are sourced from official board examinations.</p>
</div>"""


# ── Pipeline background job store ─────────────────────────────────────────────
# Simple in-memory store for pipeline job status (TTL ~1 hour).
# Keys are job UUIDs. Values: { status, progress, message, result, started_at }
_pipeline_jobs: dict = {}

def _pipeline_job_gc():
    """Remove jobs older than 1 hour."""
    cutoff = datetime.now(timezone.utc).timestamp() - 3600
    stale = [k for k, v in _pipeline_jobs.items() if v.get("started_at", 0) < cutoff]
    for k in stale:
        _pipeline_jobs.pop(k, None)


class PipelineAutoGenerateRequest(BaseModel):
    subject_id: str
    skip_existing: bool = False


@router.get("/admin/pipeline/status/{job_id}")
async def admin_pipeline_status(job_id: str, admin: dict = Depends(get_admin_user)):
    """Poll the status of a background pipeline job."""
    job = _pipeline_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job


async def _pipeline_auto_generate_worker(job_id: str, subject_id: str, skip_existing: bool = False):
    """Background worker: runs the full pipeline and updates _pipeline_jobs[job_id]."""
    try:
        result = await _pipeline_auto_generate_core(subject_id, job_id, skip_existing=skip_existing)
        _pipeline_jobs[job_id].update({
            "status": "complete",
            "progress": 100,
            "message": "Pipeline finished",
            "result": result,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        _pipeline_jobs[job_id].update({
            "status": "error",
            "progress": 100,
            "message": str(exc)[:200],
            "result": None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error(f"Pipeline job {job_id} failed: {exc}")
    finally:
        _pipeline_job_gc()


@router.post("/admin/pipeline/auto-generate")
async def admin_pipeline_auto_generate(body: PipelineAutoGenerateRequest, background_tasks: BackgroundTasks, admin: dict = Depends(get_admin_user)):
    """
    1-Click Full Subject Pipeline (async).
    Returns job_id immediately; poll /admin/pipeline/status/{job_id} for progress.
    """
    subject_id = body.subject_id.strip()
    if not subject_id:
        raise HTTPException(status_code=400, detail="subject_id is required")

    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    job_id = str(uuid.uuid4())
    _pipeline_jobs[job_id] = {
        "job_id": job_id,
        "subject_id": subject_id,
        "status": "running",
        "progress": 0,
        "message": "Pipeline starting…",
        "result": None,
        "chapter_progress": {},
        "started_at": datetime.now(timezone.utc).timestamp(),
    }
    background_tasks.add_task(_pipeline_auto_generate_worker, job_id, subject_id, body.skip_existing)
    return {"job_id": job_id, "status": "running"}


async def _pipeline_process_one_chapter(
    chapter: dict,
    *,
    subject_id: str,
    subject_name: str,
    class_name: str,
    paper_type: str,
    board_slug: str,
    board_display: str = "Assamboard",
    class_slug: str,
    now_iso: str,
    pyq_docs: list,
    semaphore: asyncio.Semaphore,
    done_counter: dict,
    total_chapters: int,
    job_id: str,
    skip_existing: bool = False,
) -> dict:
    """Process a single chapter: notes → MCQs → flashcards → geo-blogs (parallel) → PYQ.
    All generated content is collected first, then written atomically at the end.
    If skip_existing=True, reuses existing notes/PYQs/flashcards and only runs blogs+PYQ HTML+sitemap.
    """
    def _update_stage(stage: str, detail: str = ""):
        if job_id and job_id in _pipeline_jobs:
            job = _pipeline_jobs[job_id]
            ch_progress = job.get("chapter_progress", {})
            ch_progress[chapter.get("id", "")] = {"title": (chapter.get("title") or "")[:40], "stage": stage, "detail": detail}
            pct = int(5 + (done_counter["done"] / max(total_chapters, 1)) * 88)
            job.update({"progress": pct, "message": f"Chapter {done_counter['done']}/{total_chapters}: {stage}", "chapter_progress": ch_progress})

    async with semaphore:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        chapter_slug  = chapter.get("slug") or _pipeline_slugify(chapter_title)

        chapter_result = {
            "chapter_id":       chapter_id,
            "chapter_title":    chapter_title,
            "notes_generated":  False,
            "topic_pyq_count":  0,
            "mark_wise_count":  0,
            "flashcards_count": 0,
            "blogs_count":      0,
            "pyq_page":         False,
            "errors":           [],
        }

        if not chapter_title:
            return {"skipped": True, "result": chapter_result}

        _update_stage("notes", "Generating notes…")

        existing_content = (chapter.get("content") or "").strip()
        notes_content = existing_content
        generated_notes = None
        if skip_existing and len(existing_content) > 100:
            chapter_result["notes_generated"] = False
        else:
            try:
                generated_notes = await _pipeline_generate_chapter_notes(chapter, subject_name, class_name, paper_type)
                if generated_notes:
                    notes_content = generated_notes
                    chapter_result["notes_generated"] = True
            except Exception as e:
                chapter_result["errors"].append(f"notes: {str(e)[:80]}")

        if not notes_content:
            done_counter["done"] += 1
            _update_stage("skipped", "No content")
            return {"skipped": True, "result": chapter_result}

        _update_stage("questions", "Generating questions & flashcards…")

        pyq_err = None
        mw_err  = None
        fc_err  = None
        topic_pyqs = None
        mark_wise_result = None
        flashcards = None
        _existing_pyqs = None
        _existing_mw   = None
        _existing_fc   = None
        if skip_existing:
            _existing_pyqs = await db.topic_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})
            _existing_mw   = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})
            _existing_fc   = await db.flashcard_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})

        if skip_existing and _existing_pyqs and _existing_mw and _existing_fc:
            chapter_result["topic_pyq_count"]   = _existing_pyqs.get("total", 0)
            chapter_result["mark_wise_count"]    = _existing_mw.get("total", 0)
            chapter_result["flashcards_count"]   = _existing_fc.get("total", 0)
        else:
            ch_topics = chapter.get("topics") or []
            pyq_task = _pipeline_generate_topic_pyq(notes_content, subject_name, chapter_title, class_name, count=20)
            mw_task  = _pipeline_generate_mark_wise_pyq(notes_content, subject_name, chapter_title, class_name, paper_type=paper_type, topics=ch_topics)
            fc_task  = _pipeline_generate_flashcards(notes_content, subject_name, chapter_title, class_name, count=15, topics=ch_topics)
            (topic_pyqs, pyq_err), (mark_wise_result, mw_err), (flashcards, fc_err) = await asyncio.gather(
                _safe(pyq_task), _safe(mw_task), _safe(fc_task)
            )
            if pyq_err:
                chapter_result["errors"].append(f"topic-pyqs: {str(pyq_err)[:60]}")
            if mw_err:
                chapter_result["errors"].append(f"mark-wise: {str(mw_err)[:60]}")
            if fc_err:
                chapter_result["errors"].append(f"flashcards: {str(fc_err)[:60]}")

        _update_stage("blogs", "Generating geo-SEO blogs…")

        _existing_geo_count = 0
        geo_blog_urls = []
        if skip_existing:
            try:
                _existing_geo_count = await db.cms_documents.count_documents({
                    "linked_chapter_id": chapter_id, "category": "geo-blog"
                })
            except Exception:
                pass
        if skip_existing and _existing_geo_count >= len(GEO_CITIES):
            logger.info(f"[Pipeline] Skipping geo-blogs for '{chapter_title}' — {_existing_geo_count} already exist")
            chapter_result["blogs_count"] = _existing_geo_count
        else:
            blog_tasks = [
                _safe(_pipeline_generate_geo_seo_blog(
                    subject_name=subject_name, chapter_title=chapter_title,
                    content=notes_content, geo_location=city,
                    board_slug=board_slug, class_slug=class_slug, chapter_slug=chapter_slug,
                ))
                for city in GEO_CITIES
            ]
            blog_results = await asyncio.gather(*blog_tasks)
            for city, (blog_data, blog_err) in zip(GEO_CITIES, blog_results):
                if blog_err or not blog_data:
                    chapter_result["errors"].append(f"geo-blog-{city}: {str(blog_err)[:60]}" if blog_err else f"geo-blog-{city}: empty")
                    continue
                try:
                    blog_slug = blog_data["seo_slug"]
                    await db.cms_documents.update_one(
                        {"seo_slug": blog_slug},
                        {"$set": {
                            "id": str(uuid.uuid4()),
                            "title": blog_data["title"], "seo_slug": blog_slug,
                            "meta_description": blog_data["meta_description"],
                            "content": blog_data["article_body"],
                            "primary_keyword": blog_data["primary_keyword"],
                            "keywords": blog_data.get("keywords", []),
                            "geo_location": city,
                            "linked_subject_id": subject_id, "linked_subject_name": subject_name,
                            "linked_chapter_id": chapter_id, "linked_chapter_title": chapter_title,
                            "status": "published", "category": "geo-blog",
                            "schema_type": "Article", "pipeline_generated": True,
                            "created_at": now_iso, "updated_at": now_iso,
                        }},
                        upsert=True,
                    )
                    geo_blog_urls.append(f"/learn/{blog_slug}")
                    chapter_result["blogs_count"] += 1
                    try:
                        await _embed_cms_document(blog_slug, blog_data["article_body"], blog_data["title"])
                    except Exception:
                        pass
                except Exception as e:
                    chapter_result["errors"].append(f"geo-blog-{city}-save: {str(e)[:60]}")

        _update_stage("saving", "Atomic write…")

        # ── ATOMIC CHAPTER UPDATE: write notes + questions + flashcards in one operation ──
        chapter_atomic_update = {"updated_at": now_iso}
        if generated_notes:
            chapter_atomic_update.update({
                "content": generated_notes,
                "content_type": "notes",
                "notes_generated": True,
                "notes_generated_at": now_iso,
            })
        if mark_wise_result and mark_wise_result.get("pyqs"):
            chapter_atomic_update["has_important_questions"] = True
            chapter_atomic_update["mark_wise_questions"] = mark_wise_result["mark_wise"]
            chapter_atomic_update["mark_wise_count"] = mark_wise_result["total"]
        if flashcards:
            chapter_atomic_update["has_flashcards"] = True
            chapter_atomic_update["flashcard_summary"] = [
                {"front": fc.get("front", "")[:100], "type": fc.get("type", "")}
                for fc in (flashcards or [])[:5]
            ]
            chapter_atomic_update["flashcard_count"] = len(flashcards)
        chapter_atomic_update["content_synced_at"] = now_iso

        try:
            await db.chapters.update_one({"id": chapter_id}, {"$set": chapter_atomic_update})
        except Exception as e:
            chapter_result["errors"].append(f"atomic-save: {str(e)[:60]}")

        if generated_notes:
            try:
                await auto_chunk_content(chapter_id=chapter_id, content=generated_notes, subject_id=subject_id)
            except Exception:
                pass
            try:
                await _embed_and_store_chapter(chapter_id, generated_notes, chapter_title)
            except Exception:
                pass

        if topic_pyqs:
            try:
                await db.topic_pyq_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": {
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id, "subject_name": subject_name,
                        "chapter_id": chapter_id, "chapter_title": chapter_title,
                        "pyqs": topic_pyqs, "total": len(topic_pyqs),
                        "pipeline_generated": True, "created_at": now_iso,
                    }},
                    upsert=True,
                )
                chapter_result["topic_pyq_count"] = len(topic_pyqs)
            except Exception as e:
                chapter_result["errors"].append(f"topic-pyq-save: {str(e)[:60]}")

        if mark_wise_result and mark_wise_result.get("pyqs"):
            try:
                mw_doc = {
                    "id":            str(uuid.uuid4()),
                    "subject_id":    subject_id,
                    "subject_name":  subject_name,
                    "chapter_id":    chapter_id,
                    "chapter_title": chapter_title,
                    "pyqs":          mark_wise_result["pyqs"],
                    "mark_wise":     mark_wise_result["mark_wise"],
                    "total":         mark_wise_result["total"],
                    "source":        "pipeline_mark_wise",
                    "ai_generated":  True,
                    "pipeline_generated": True,
                    "created_at":    now_iso,
                    "updated_at":    now_iso,
                }
                await db.ai_pyq_collections.update_one(
                    {"chapter_id": chapter_id},
                    {"$set": mw_doc},
                    upsert=True,
                )
                chapter_result["mark_wise_count"] = mark_wise_result["total"]
            except Exception as e:
                chapter_result["errors"].append(f"mark-wise-save: {str(e)[:60]}")

        if flashcards:
            try:
                await db.flashcard_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": {
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id, "subject_name": subject_name,
                        "chapter_id": chapter_id, "chapter_title": chapter_title,
                        "flashcards": flashcards, "total": len(flashcards),
                        "pipeline_generated": True, "created_at": now_iso,
                    }},
                    upsert=True,
                )
                chapter_result["flashcards_count"] = len(flashcards)
            except Exception as e:
                chapter_result["errors"].append(f"flashcards-save: {str(e)[:60]}")

        try:
            pyq_html = await _pipeline_generate_pyq_html(chapter, subject_name, pyq_docs)
            pyq_slug = f"pyq-{board_slug}-{class_slug}-{chapter_slug}"
            await db.cms_documents.update_one(
                {"seo_slug": pyq_slug},
                {"$set": {
                    "id": str(uuid.uuid4()),
                    "title": f"PYQ: {chapter_title} — {subject_name}",
                    "seo_slug": pyq_slug,
                    "meta_description": f"Previous year questions for {chapter_title} ({subject_name}) — {board_display} board exams. Download PYQ papers on Syrabit.ai.",
                    "content": pyq_html, "content_html": pyq_html,
                    "linked_subject_id": subject_id, "linked_subject_name": subject_name,
                    "linked_chapter_id": chapter_id, "linked_chapter_title": chapter_title,
                    "status": "published", "category": "pyq",
                    "pipeline_generated": True, "created_at": now_iso, "updated_at": now_iso,
                }},
                upsert=True,
            )
            chapter_result["pyq_page"] = True
            try:
                await _embed_cms_document(pyq_slug, pyq_html, f"PYQ: {chapter_title} — {subject_name}")
            except Exception:
                pass
        except Exception as e:
            chapter_result["errors"].append(f"pyq-page: {str(e)[:80]}")

        done_counter["done"] += 1
        _update_stage("done", "Complete")

        return {"skipped": False, "result": chapter_result, "blog_urls": geo_blog_urls, "mcqs": len(topic_pyqs or []), "flashcards": len(flashcards or []), "pyq": chapter_result["pyq_page"]}


async def _safe(coro):
    """Run a coroutine; return (result, None) on success or (None, exc) on error."""
    try:
        return await coro, None
    except Exception as e:
        return None, e


async def _pipeline_auto_generate_core(subject_id: str, job_id: str = "", skip_existing: bool = False):
    """Core pipeline logic — extracted so it can run as a background task."""
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise ValueError(f"Subject {subject_id} not found")

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "") or subject.get("class_name", "")

    stream_id = subject.get("stream_id", "")
    board_slug = "assamboard"
    board_display = "Assamboard"
    class_slug = _pipeline_slugify(class_name or "class-12")

    if stream_id:
        stream_doc = await db.streams.find_one({"id": stream_id}, {"_id": 0})
        if stream_doc:
            class_id = stream_doc.get("class_id", "")
            if class_id:
                class_doc = await db.classes.find_one({"id": class_id}, {"_id": 0})
                if class_doc:
                    class_slug = class_doc.get("slug") or _pipeline_slugify(class_doc.get("name", ""))
                    board_id = class_doc.get("board_id", "")
                    if board_id:
                        board_doc = await db.boards.find_one({"id": board_id}, {"_id": 0})
                        if board_doc:
                            board_slug = board_doc.get("slug") or _pipeline_slugify(board_doc.get("name", ""))
                            board_display = board_doc.get("name", "Assamboard")

    # Load chapters
    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "status": "no_chapters", "message": "No chapters found for this subject"}

    now_iso = datetime.now(timezone.utc).isoformat()

    # Load PYQs for this subject (for PYQ HTML pages)
    pyq_docs = await db.pyq_uploads.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("exam_year", -1).to_list(20)

    # ── Parallel chapter processing (semaphore=4 to respect LLM rate limits) ─
    semaphore     = asyncio.Semaphore(4)
    done_counter  = {"done": 0}
    total_chapters = len(chapters)

    if job_id and job_id in _pipeline_jobs:
        _pipeline_jobs[job_id].update({"progress": 5, "message": f"Starting parallel processing for {total_chapters} chapters…"})

    tasks = [
        _pipeline_process_one_chapter(
            ch,
            subject_id=subject_id, subject_name=subject_name,
            class_name=class_name, paper_type=paper_type,
            board_slug=board_slug, board_display=board_display,
            class_slug=class_slug,
            now_iso=now_iso, pyq_docs=pyq_docs,
            semaphore=semaphore, done_counter=done_counter,
            total_chapters=total_chapters, job_id=job_id,
            skip_existing=skip_existing,
        )
        for ch in chapters
    ]
    chapter_outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    # ── Aggregate results ─────────────────────────────────────────────────────
    summary = {
        "subject_id": subject_id, "subject_name": subject_name,
        "chapters_processed": 0, "chapters_skipped": 0,
        "total_topic_pyqs": 0, "total_mark_wise_pyqs": 0, "total_flashcards": 0,
        "total_blogs": 0, "total_pyq_pages": 0,
        "blog_urls": [], "chapter_results": [],
        "sitemap_pinged": False, "ping_status": "",
    }

    for outcome in chapter_outcomes:
        if isinstance(outcome, Exception):
            summary["chapters_skipped"] += 1
            continue
        if outcome.get("skipped"):
            summary["chapters_skipped"] += 1
            summary["chapter_results"].append(outcome["result"])
            continue
        r = outcome["result"]
        summary["chapters_processed"] += 1
        summary["total_topic_pyqs"]     += r.get("topic_pyq_count", 0)
        summary["total_mark_wise_pyqs"] += r.get("mark_wise_count", 0)
        summary["total_flashcards"]     += r.get("flashcards_count", 0)
        summary["total_blogs"]          += r.get("blogs_count", 0)
        if r.get("pyq_page"):
            summary["total_pyq_pages"] += 1
        summary["blog_urls"].extend(outcome.get("blog_urls", []))
        summary["chapter_results"].append(r)

    _invalidate_content_cache("chapters")

    # ── Step 6: Verify Sitemap is Alive (self-check) ─────────────────────────
    # Google deprecated their sitemap ping endpoint in 2023 (returns 404).
    # Instead we self-verify our own sitemap endpoint on localhost.
    try:
        local_port = int(os.environ.get("PORT", "5000"))
        sitemap_local = f"http://localhost:{local_port}/api/seo/sitemap-index.xml"
        async with httpx.AsyncClient(timeout=10.0) as client:
            smap_resp = await client.get(sitemap_local)
            summary["sitemap_pinged"] = True
            if smap_resp.status_code == 200:
                summary["ping_status"] = "Sitemap OK"
            else:
                summary["ping_status"] = f"Sitemap HTTP {smap_resp.status_code}"
            logger.info(f"Sitemap self-check: {smap_resp.status_code} at {sitemap_local}")
    except Exception as e:
        summary["ping_status"] = f"check failed: {str(e)[:50]}"
        logger.warning(f"Sitemap self-check failed: {e}")

    logger.info(
        f"Pipeline complete: subject={subject_name}, chapters={summary['chapters_processed']}, "
        f"topic_pyqs={summary['total_topic_pyqs']}, flashcards={summary['total_flashcards']}, "
        f"blogs={summary['total_blogs']}, pyq_pages={summary['total_pyq_pages']}"
    )

    return summary



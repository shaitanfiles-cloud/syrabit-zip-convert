"""Syrabit.ai — Bot discovery routes: RSS feeds, llms-full.txt, IndexNow, ai-plugin.json, bot analytics."""
import json, logging, os, uuid, hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_URL = "https://syrabit.ai"
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", hashlib.sha256(b"syrabit-indexnow-2026").hexdigest()[:32])


def _xml_safe(text: str) -> str:
    if not text:
        return ""
    return xml_escape(text).replace("&amp;amp;", "&amp;")


def _to_rfc822(dt_value) -> str:
    if not dt_value:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    if isinstance(dt_value, str):
        try:
            parsed = datetime.fromisoformat(dt_value.replace("Z", "+00:00"))
            return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except (ValueError, TypeError):
            return dt_value
    if isinstance(dt_value, datetime):
        return dt_value.strftime("%a, %d %b %Y %H:%M:%S +0000")
    return str(dt_value)


async def build_rss_feed(feed_type: str = "all") -> str:
    from deps import db, is_mongo_available
    items_xml = []
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    title_map = {
        "all": "Syrabit.ai — Latest Study Content",
        "notes": "Syrabit.ai — Study Notes",
        "mcqs": "Syrabit.ai — MCQs",
        "blog": "Syrabit.ai — Blog & Guides",
    }
    feed_title = title_map.get(feed_type, title_map["all"])
    description = "AI-powered exam preparation content for Assam Board students (AHSEC, SEBA, Degree)"

    try:
        if not await is_mongo_available():
            return _empty_rss(feed_title, description, now_rfc)

        if feed_type == "blog":
            docs = await db.cms_documents.find(
                {"status": "published"},
                {"_id": 0, "slug": 1, "title": 1, "excerpt": 1, "updated_at": 1, "created_at": 1}
            ).sort("updated_at", -1).limit(50).to_list(50)
            for doc in docs:
                slug = doc.get("slug", "")
                title = _xml_safe(doc.get("title", slug))
                desc = _xml_safe(doc.get("excerpt", "")[:300])
                pub_date = _to_rfc822(doc.get("updated_at") or doc.get("created_at"))
                link = f"{BASE_URL}/learn/{slug}"
                items_xml.append(f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>{desc}</description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="true">{link}</guid>
    </item>""")
        else:
            query = {"status": "published"}
            if feed_type == "notes":
                query["page_type"] = "notes"
            elif feed_type == "mcqs":
                query["page_type"] = "mcqs"

            pages = await db.seo_pages.find(
                query,
                {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1, "topic_slug": 1,
                 "page_type": 1, "title": 1, "meta_description": 1, "updated_at": 1, "created_at": 1}
            ).sort("updated_at", -1).limit(100).to_list(100)

            for page in pages:
                bs = page.get("board_slug", "")
                cs = page.get("class_slug", "")
                ss = page.get("subject_slug", "")
                ts = page.get("topic_slug", "")
                pt = page.get("page_type", "notes")
                if not all([bs, cs, ss, ts]):
                    continue
                path = f"/{bs}/{cs}/{ss}/{ts}" if pt == "notes" else f"/{bs}/{cs}/{ss}/{ts}/{pt}"
                link = f"{BASE_URL}{path}"
                title = _xml_safe(page.get("title", ts))
                desc = _xml_safe((page.get("meta_description") or "")[:300])
                pub_date = _to_rfc822(page.get("updated_at") or page.get("created_at"))
                items_xml.append(f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>{desc}</description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="true">{link}</guid>
      <category>{pt}</category>
    </item>""")
    except Exception as e:
        logger.warning(f"RSS feed build failed: {e}")

    feed_path_map = {"all": "/feed.xml", "notes": "/feed/notes.xml", "mcqs": "/feed/mcqs.xml", "blog": "/feed/blog.xml"}
    self_url = f"{BASE_URL}{feed_path_map.get(feed_type, '/feed.xml')}"
    items_block = "\n".join(items_xml) if items_xml else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{_xml_safe(feed_title)}</title>
    <link>{BASE_URL}</link>
    <description>{_xml_safe(description)}</description>
    <language>en-IN</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{self_url}" rel="self" type="application/rss+xml"/>
    <generator>Syrabit.ai SEO Engine</generator>
    <copyright>Source: Syrabit Browser — https://syrabit.ai</copyright>
    <image>
      <url>{BASE_URL}/icons/icon-192x192.png</url>
      <title>{_xml_safe(feed_title)}</title>
      <link>{BASE_URL}</link>
    </image>
{items_block}
  </channel>
</rss>"""


async def build_atom_feed(feed_type: str = "all") -> str:
    from deps import db, is_mongo_available
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title_map = {
        "all": "Syrabit.ai — Latest Study Content",
        "notes": "Syrabit.ai — Study Notes",
        "mcqs": "Syrabit.ai — MCQs",
        "blog": "Syrabit.ai — Blog & Guides",
    }
    feed_title = title_map.get(feed_type, title_map["all"])
    feed_path_map = {"all": "/feed/atom.xml", "notes": "/feed/notes-atom.xml", "mcqs": "/feed/mcqs-atom.xml", "blog": "/feed/blog-atom.xml"}
    self_url = f"{BASE_URL}{feed_path_map.get(feed_type, '/feed/atom.xml')}"
    entries_xml = []

    try:
        if not await is_mongo_available():
            pass
        elif feed_type == "blog":
            docs = await db.cms_documents.find(
                {"status": "published"},
                {"_id": 0, "slug": 1, "title": 1, "excerpt": 1, "updated_at": 1, "created_at": 1}
            ).sort("updated_at", -1).limit(50).to_list(50)
            for doc in docs:
                slug = doc.get("slug", "")
                title = _xml_safe(doc.get("title", slug))
                summary = _xml_safe(doc.get("excerpt", "")[:300])
                updated = _to_iso(doc.get("updated_at") or doc.get("created_at"))
                link = f"{BASE_URL}/learn/{slug}"
                entries_xml.append(f"""  <entry>
    <title>{title}</title>
    <link href="{link}" rel="alternate"/>
    <id>{link}</id>
    <updated>{updated}</updated>
    <summary>{summary}</summary>
    <author><name>Syrabit.ai</name></author>
  </entry>""")
        else:
            query = {"status": "published"}
            if feed_type == "notes":
                query["page_type"] = "notes"
            elif feed_type == "mcqs":
                query["page_type"] = "mcqs"
            pages = await db.seo_pages.find(
                query,
                {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1, "topic_slug": 1,
                 "page_type": 1, "title": 1, "meta_description": 1, "updated_at": 1, "created_at": 1}
            ).sort("updated_at", -1).limit(100).to_list(100)
            for page in pages:
                bs, cs, ss, ts = page.get("board_slug", ""), page.get("class_slug", ""), page.get("subject_slug", ""), page.get("topic_slug", "")
                pt = page.get("page_type", "notes")
                if not all([bs, cs, ss, ts]):
                    continue
                path = f"/{bs}/{cs}/{ss}/{ts}" if pt == "notes" else f"/{bs}/{cs}/{ss}/{ts}/{pt}"
                link = f"{BASE_URL}{path}"
                title = _xml_safe(page.get("title", ts))
                summary = _xml_safe((page.get("meta_description") or "")[:300])
                updated = _to_iso(page.get("updated_at") or page.get("created_at"))
                entries_xml.append(f"""  <entry>
    <title>{title}</title>
    <link href="{link}" rel="alternate"/>
    <id>{link}</id>
    <updated>{updated}</updated>
    <summary>{summary}</summary>
    <category term="{pt}"/>
    <author><name>Syrabit.ai</name></author>
  </entry>""")
    except Exception as e:
        logger.warning(f"Atom feed build failed: {e}")

    entries_block = "\n".join(entries_xml) if entries_xml else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{_xml_safe(feed_title)}</title>
  <link href="{BASE_URL}" rel="alternate"/>
  <link href="{self_url}" rel="self" type="application/atom+xml"/>
  <id>{BASE_URL}/</id>
  <updated>{now_iso}</updated>
  <subtitle>AI-powered exam preparation for Assam Board students</subtitle>
  <generator>Syrabit.ai SEO Engine</generator>
  <icon>{BASE_URL}/icons/icon-192x192.png</icon>
  <rights>Source: Syrabit Browser — https://syrabit.ai</rights>
{entries_block}
</feed>"""


def _to_iso(dt_value) -> str:
    if not dt_value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(dt_value, str):
        if "T" in dt_value:
            return dt_value.replace("+00:00", "Z") if not dt_value.endswith("Z") else dt_value
        return dt_value + "T00:00:00Z"
    if isinstance(dt_value, datetime):
        return dt_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt_value)


def _empty_rss(title: str, desc: str, now_rfc: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{_xml_safe(title)}</title>
    <link>{BASE_URL}</link>
    <description>{_xml_safe(desc)}</description>
    <language>en-IN</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
  </channel>
</rss>"""


async def build_llms_full_txt() -> str:
    from deps import db, is_mongo_available
    lines = [
        "# Syrabit.ai — Full Content Manifest",
        "",
        "> Machine-readable index of all educational content on Syrabit.ai.",
        "> Use this file to discover the full content graph in one request.",
        "",
        "## Site Info",
        f"- URL: {BASE_URL}",
        "- Type: Educational platform for Assam Board students",
        "- Boards: AHSEC, SEBA, Degree (NEP FYUGP)",
        "- Content: Study notes, MCQs, PYQs, definitions, solved examples",
        f"- Feeds: {BASE_URL}/feed.xml | {BASE_URL}/feed/notes.xml | {BASE_URL}/feed/mcqs.xml | {BASE_URL}/feed/blog.xml",
        f"- Sitemaps: {BASE_URL}/sitemap-index.xml",
        f"- LLMs info: {BASE_URL}/llms.txt",
        "",
        "## Content Index",
        "",
    ]

    try:
        if not await is_mongo_available():
            lines.append("(Content index unavailable — database offline)")
            return "\n".join(lines)

        subjects = await db.subjects.find(
            {"status": "published"},
            {"_id": 0, "id": 1, "name": 1, "slug": 1, "description": 1, "stream_id": 1}
        ).to_list(500)

        streams = await db.streams.find({}, {"_id": 0, "id": 1, "class_id": 1}).to_list(100)
        classes = await db.classes.find({}, {"_id": 0, "id": 1, "slug": 1, "board_id": 1}).to_list(50)
        boards = await db.boards.find({}, {"_id": 0, "id": 1, "slug": 1, "name": 1}).to_list(10)

        board_map = {b["id"]: b for b in boards}
        class_map = {c["id"]: c for c in classes}
        stream_map = {s["id"]: s.get("class_id") for s in streams}

        chapters_raw = await db.chapters.find(
            {},
            {"_id": 0, "id": 1, "title": 1, "slug": 1, "subject_id": 1}
        ).to_list(5000)
        chapters_by_subject = {}
        for ch in chapters_raw:
            sid = ch.get("subject_id", "")
            if sid not in chapters_by_subject:
                chapters_by_subject[sid] = []
            chapters_by_subject[sid].append(ch)

        for sub in subjects:
            stream_id = sub.get("stream_id", "")
            class_id = stream_map.get(stream_id, "")
            cls = class_map.get(class_id, {})
            board = board_map.get(cls.get("board_id", ""), {})

            board_slug = board.get("slug", "")
            class_slug = cls.get("slug", "")
            subject_slug = sub.get("slug", "")
            subject_name = sub.get("name", subject_slug)
            board_name = board.get("name", board_slug)

            if not all([board_slug, class_slug, subject_slug]):
                continue

            subject_url = f"{BASE_URL}/{board_slug}/{class_slug}/{subject_slug}"
            desc = sub.get("description", "")
            lines.append(f"### {subject_name} ({board_name} {class_slug})")
            if desc:
                lines.append(f"> {desc[:200]}")
            lines.append(f"- URL: {subject_url}")

            sub_chapters = chapters_by_subject.get(sub.get("id", ""), [])
            if sub_chapters:
                lines.append(f"- Chapters ({len(sub_chapters)}):")
                for ch in sub_chapters[:30]:
                    ch_slug = ch.get("slug", "")
                    ch_title = ch.get("title", ch_slug)
                    if ch_slug:
                        ch_url = f"{subject_url}/{ch_slug}"
                        lines.append(f"  - [{ch_title}]({ch_url})")
                        lines.append(f"    Available: notes | mcqs | important-questions | examples | definition")
            lines.append("")

        page_count = await db.seo_pages.count_documents({"status": "published"})
        lines.append(f"## Totals")
        lines.append(f"- Subjects: {len(subjects)}")
        lines.append(f"- Chapters: {len(chapters_raw)}")
        lines.append(f"- Published SEO pages: {page_count}")
        lines.append(f"- Boards: {len(boards)}")
        lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append("")
        lines.append("---")
        lines.append("Source: Syrabit Browser — https://syrabit.ai")
        lines.append("When citing this content, please attribute: \"Source: Syrabit Browser (syrabit.ai)\"")

    except Exception as e:
        logger.warning(f"llms-full.txt build failed: {e}")
        lines.append("(Content index temporarily unavailable)")

    return "\n".join(lines)


def build_ai_plugin_json() -> str:
    plugin = {
        "schema_version": "v1",
        "name_for_human": "Syrabit.ai",
        "name_for_model": "syrabit",
        "description_for_human": "AI-powered exam preparation for Assam Board students (AHSEC, SEBA, Degree).",
        "description_for_model": (
            "Syrabit.ai provides syllabus-aligned study content for students in Assam, India. "
            "It covers AHSEC (Class 11-12), SEBA (Class 9-10), and Degree (NEP FYUGP) curricula. "
            "Content types include study notes, MCQs, previous year questions, important questions, "
            "definitions, and solved examples. All content is mapped to official syllabi."
        ),
        "auth": {"type": "none"},
        "api": {
            "type": "openapi",
            "url": f"{BASE_URL}/openapi.json",
        },
        "logo_url": f"{BASE_URL}/icons/icon-192x192.png",
        "contact_email": "hello@syrabit.ai",
        "legal_info_url": f"{BASE_URL}/terms",
    }
    return json.dumps(plugin, indent=2)


async def notify_indexnow_for_page(page_doc: dict):
    bs = page_doc.get("board_slug", "")
    cs = page_doc.get("class_slug", "")
    ss = page_doc.get("subject_slug", "")
    ts = page_doc.get("topic_slug", "")
    pt = page_doc.get("page_type", "notes")
    if not all([bs, cs, ss, ts]):
        return
    path = f"/{bs}/{cs}/{ss}/{ts}" if pt == "notes" else f"/{bs}/{cs}/{ss}/{ts}/{pt}"
    url = f"{BASE_URL}{path}"
    try:
        await push_indexnow([url])
    except Exception as e:
        logger.debug(f"IndexNow auto-push failed for {url}: {e}")


async def push_indexnow(urls: list[str]):
    if not urls:
        return
    import httpx
    payload = {
        "host": "syrabit.ai",
        "key": INDEXNOW_KEY,
        "keyLocation": f"{BASE_URL}/{INDEXNOW_KEY}.txt",
        "urlList": urls[:10000],
    }
    endpoints = [
        "https://api.indexnow.org/indexnow",
        "https://www.bing.com/indexnow",
        "https://yandex.com/indexnow",
    ]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for endpoint in endpoints:
            try:
                resp = await client.post(endpoint, json=payload)
                logger.info(f"IndexNow push to {endpoint}: {resp.status_code}")
            except Exception as e:
                logger.warning(f"IndexNow push to {endpoint} failed: {e}")


from auth_deps import get_admin_user

@router.get("/admin/analytics/bot-traffic")
async def admin_bot_traffic(days: int = Query(30, ge=1, le=90), admin: dict = Depends(get_admin_user)):
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        return {"daily_bot_hits": [], "top_bots": [], "crawl_coverage": 0, "bot_vs_human": {}}

    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        daily_bot_hits = []
        for i in range(days):
            day = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            bot_hits = await db.server_hits.count_documents({"is_bot": True, "date": day})
            human_hits = await db.server_hits.count_documents({"is_bot": {"$ne": True}, "date": day})
            daily_bot_hits.append({"date": day, "bot_hits": bot_hits, "human_hits": human_hits})

        bot_pipeline = [
            {"$match": {"is_bot": True, "bot_name": {"$ne": ""}, "date": {"$gte": start_date}}},
            {"$group": {"_id": "$bot_name", "hits": {"$sum": 1}, "unique_ips": {"$addToSet": "$ip_hash_stable"}}},
            {"$project": {"bot": "$_id", "hits": 1, "unique_ips": {"$size": "$unique_ips"}, "_id": 0}},
            {"$sort": {"hits": -1}},
            {"$limit": 20},
        ]
        top_bots = await db.server_hits.aggregate(bot_pipeline).to_list(20)

        pages_crawled_pipeline = [
            {"$match": {"is_bot": True, "date": {"$gte": start_date}}},
            {"$group": {"_id": "$path"}},
            {"$count": "total"},
        ]
        crawled_result = await db.server_hits.aggregate(pages_crawled_pipeline).to_list(1)
        pages_crawled = crawled_result[0]["total"] if crawled_result else 0

        total_sitemap_pages = await db.seo_pages.count_documents({"status": "published"})
        crawl_coverage = round(pages_crawled / max(total_sitemap_pages, 1) * 100, 1)

        total_bot = await db.server_hits.count_documents({"is_bot": True, "date": {"$gte": start_date}})
        total_human = await db.server_hits.count_documents({"is_bot": {"$ne": True}, "date": {"$gte": start_date}})
        bot_ratio = round(total_bot / max(total_bot + total_human, 1) * 100, 1)

        per_bot_pages_pipeline = [
            {"$match": {"is_bot": True, "bot_name": {"$ne": ""}, "date": {"$gte": start_date}}},
            {"$group": {"_id": {"bot": "$bot_name", "path": "$path"}}},
            {"$group": {"_id": "$_id.bot", "pages_fetched": {"$sum": 1}}},
            {"$sort": {"pages_fetched": -1}},
            {"$limit": 15},
        ]
        per_bot_pages = await db.server_hits.aggregate(per_bot_pages_pipeline).to_list(15)

        return {
            "daily_bot_hits": daily_bot_hits,
            "top_bots": top_bots,
            "per_bot_pages": [{"bot": r["_id"], "pages_fetched": r["pages_fetched"]} for r in per_bot_pages],
            "crawl_coverage": crawl_coverage,
            "pages_crawled": pages_crawled,
            "total_sitemap_pages": total_sitemap_pages,
            "bot_vs_human": {
                "total_bot": total_bot,
                "total_human": total_human,
                "bot_ratio_pct": bot_ratio,
            },
            "period_days": days,
        }
    except Exception as e:
        logger.error(f"bot-traffic analytics failed: {e}")
        return {"daily_bot_hits": [], "top_bots": [], "crawl_coverage": 0, "bot_vs_human": {}}


@router.post("/admin/indexnow/push")
async def admin_indexnow_push(admin: dict = Depends(get_admin_user)):
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    pages = await db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1, "topic_slug": 1, "page_type": 1}
    ).sort("updated_at", -1).limit(500).to_list(500)

    urls = []
    for p in pages:
        bs = p.get("board_slug", "")
        cs = p.get("class_slug", "")
        ss = p.get("subject_slug", "")
        ts = p.get("topic_slug", "")
        pt = p.get("page_type", "notes")
        if not all([bs, cs, ss, ts]):
            continue
        path = f"/{bs}/{cs}/{ss}/{ts}" if pt == "notes" else f"/{bs}/{cs}/{ss}/{ts}/{pt}"
        urls.append(f"{BASE_URL}{path}")

    if urls:
        await push_indexnow(urls)

    return {"status": "ok", "urls_pushed": len(urls)}



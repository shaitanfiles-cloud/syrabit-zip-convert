"""Syrabit.ai — Bot discovery routes: RSS feeds, llms-full.txt, IndexNow, ai-plugin.json, bot analytics."""
import asyncio, json, logging, os, time, uuid, hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_URL = "https://syrabit.ai"
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", hashlib.sha256(b"syrabit-indexnow-2026").hexdigest()[:32])

_INDEXNOW_BATCH_SIZE = 500
_INDEXNOW_COOLDOWN_SECONDS = 300

_BACKOFF_BASE_SECONDS = 30
_BACKOFF_MAX_SECONDS = 600
_DEAD_LETTER_THRESHOLD = 5


_HEALTH_STALE_SECONDS = 3600

class _EndpointHealth:
    __slots__ = ("endpoint", "consecutive_failures", "last_failure_time",
                 "last_success_time", "total_successes", "total_failures",
                 "backoff_until")

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.consecutive_failures = 0
        self.last_failure_time: Optional[float] = None
        self.last_success_time: Optional[float] = None
        self.total_successes = 0
        self.total_failures = 0
        self.backoff_until: Optional[float] = None

    def record_success(self):
        was_failing = self.consecutive_failures > 0
        prev_failures = self.consecutive_failures
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self.total_successes += 1
        self.backoff_until = None
        _schedule_persist(self)
        if was_failing:
            _schedule_health_log(self.endpoint, "recovered", {"previous_consecutive_failures": prev_failures})

    def record_failure(self):
        now = time.time()
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure_time = now
        delay = min(
            _BACKOFF_BASE_SECONDS * (2 ** (self.consecutive_failures - 1)),
            _BACKOFF_MAX_SECONDS,
        )
        self.backoff_until = now + delay
        if self.consecutive_failures >= _DEAD_LETTER_THRESHOLD:
            logger.warning(
                "IndexNow endpoint dead-lettered: endpoint=%s consecutive_failures=%d "
                "total_failures=%d backoff_seconds=%d",
                self.endpoint, self.consecutive_failures, self.total_failures, delay,
            )
            if self.consecutive_failures == _DEAD_LETTER_THRESHOLD:
                _schedule_health_log(self.endpoint, "dead_lettered", {"consecutive_failures": self.consecutive_failures, "backoff_seconds": delay})
        else:
            logger.info(
                "IndexNow endpoint backoff: endpoint=%s consecutive_failures=%d backoff_seconds=%d",
                self.endpoint, self.consecutive_failures, delay,
            )
            if self.consecutive_failures == 1:
                _schedule_health_log(self.endpoint, "failure_started", {"backoff_seconds": delay})
        _schedule_persist(self)

    def is_available(self) -> bool:
        if self.backoff_until is None:
            return True
        return time.time() >= self.backoff_until

    def to_dict(self) -> dict:
        now = time.time()
        remaining = 0.0
        if self.backoff_until and now < self.backoff_until:
            remaining = round(self.backoff_until - now, 1)
        return {
            "endpoint": self.endpoint,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "is_available": self.is_available(),
            "backoff_remaining_seconds": remaining,
            "is_dead_lettered": self.consecutive_failures >= _DEAD_LETTER_THRESHOLD,
        }

    def to_persist_dict(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "consecutive_failures": self.consecutive_failures,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "backoff_until": self.backoff_until,
            "updated_at": datetime.now(timezone.utc),
        }

    @classmethod
    def from_persist_dict(cls, data: dict) -> "_EndpointHealth":
        h = cls(data["endpoint"])
        h.consecutive_failures = data.get("consecutive_failures", 0)
        h.last_failure_time = data.get("last_failure_time")
        h.last_success_time = data.get("last_success_time")
        h.total_successes = data.get("total_successes", 0)
        h.total_failures = data.get("total_failures", 0)
        h.backoff_until = data.get("backoff_until")
        return h


_endpoint_health: Dict[str, _EndpointHealth] = {}


def _get_health(endpoint: str) -> _EndpointHealth:
    if endpoint not in _endpoint_health:
        _endpoint_health[endpoint] = _EndpointHealth(endpoint)
    return _endpoint_health[endpoint]


def _schedule_persist(health: _EndpointHealth):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_health(health))
    except RuntimeError:
        pass


async def _persist_health(health: _EndpointHealth):
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
        await db.indexnow_endpoint_health.update_one(
            {"endpoint": health.endpoint},
            {"$set": health.to_persist_dict()},
            upsert=True,
        )
    except Exception as e:
        logger.debug("Failed to persist endpoint health for %s: %s", health.endpoint, e)


def _schedule_health_log(endpoint: str, event: str, details: Optional[dict] = None):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_log_health_event(endpoint, event, details))
    except RuntimeError:
        pass


async def _log_health_event(endpoint: str, event: str, details: Optional[dict] = None):
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
        doc = {
            "endpoint": endpoint,
            "event": event,
            "timestamp": datetime.now(timezone.utc),
            "details": details or {},
        }
        await db.indexnow_health_log.insert_one(doc)
    except Exception as e:
        logger.debug("Failed to log health event for %s: %s", endpoint, e)


async def load_endpoint_health_from_db():
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            logger.info("Skipping endpoint health load — database unavailable")
            return
        cutoff = time.time() - _HEALTH_STALE_SECONDS
        await db.indexnow_endpoint_health.delete_many({
            "updated_at": {"$lt": datetime.fromtimestamp(cutoff, tz=timezone.utc)}
        })
        docs = await db.indexnow_endpoint_health.find({}, {"_id": 0}).to_list(100)
        loaded = 0
        for doc in docs:
            ep = doc.get("endpoint")
            if not ep:
                continue
            h = _EndpointHealth.from_persist_dict(doc)
            if h.backoff_until and h.backoff_until < cutoff:
                h.consecutive_failures = 0
                h.backoff_until = None
            _endpoint_health[ep] = h
            loaded += 1
        if loaded:
            logger.info("Loaded %d IndexNow endpoint health records from database", loaded)
    except Exception as e:
        logger.warning("Failed to load endpoint health from database: %s", e)


_ENDPOINT_DOWN_ALERT_THRESHOLD_SECONDS = 3600
_ENDPOINT_DOWN_CHECK_INTERVAL_SECONDS = 900
_endpoint_alert_last_fired: Dict[str, float] = {}
_ENDPOINT_ALERT_COOLDOWN_S = 1800


async def _endpoint_health_alert_loop():
    """Background loop: every 15 min, check for endpoints failing >1 hour and fire admin alerts."""
    await asyncio.sleep(120)
    while True:
        try:
            now = time.time()
            for ep, health in list(_endpoint_health.items()):
                if health.consecutive_failures < _DEAD_LETTER_THRESHOLD:
                    continue
                if not health.last_failure_time:
                    continue
                down_duration = now - health.last_failure_time
                if down_duration < _ENDPOINT_DOWN_ALERT_THRESHOLD_SECONDS:
                    continue
                if now - _endpoint_alert_last_fired.get(ep, 0) < _ENDPOINT_ALERT_COOLDOWN_S:
                    continue
                down_minutes = int(down_duration / 60)
                try:
                    from metrics import _dispatch_alert, _alert_last_fired
                    _alert_last_fired.pop("endpoint_down", None)
                    await _dispatch_alert(
                        "endpoint_down",
                        "IndexNow endpoint down",
                        f"Endpoint {ep} has been failing for {down_minutes} min "
                        f"({health.consecutive_failures} consecutive failures, "
                        f"{health.total_failures} total). Last success: "
                        f"{datetime.fromtimestamp(health.last_success_time, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if health.last_success_time else 'never'}.",
                        threshold_snapshot={
                            "metric": "endpoint_down_minutes",
                            "value": _ENDPOINT_DOWN_ALERT_THRESHOLD_SECONDS // 60,
                            "actual": down_minutes,
                            "endpoint": ep,
                            "consecutive_failures": health.consecutive_failures,
                        },
                    )
                    _endpoint_alert_last_fired[ep] = now
                    _schedule_health_log(ep, "admin_alert_fired", {
                        "down_minutes": down_minutes,
                        "consecutive_failures": health.consecutive_failures,
                    })
                except Exception as e:
                    logger.debug("Failed to dispatch endpoint down alert for %s: %s", ep, e)
        except Exception as exc:
            logger.debug("Endpoint health alert loop error: %s", exc)

        await asyncio.sleep(_ENDPOINT_DOWN_CHECK_INTERVAL_SECONDS)


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


def _page_doc_to_url(page_doc: dict) -> Optional[str]:
    bs = page_doc.get("board_slug", "")
    cs = page_doc.get("class_slug", "")
    ss = page_doc.get("subject_slug", "")
    ts = page_doc.get("topic_slug", "")
    pt = page_doc.get("page_type", "notes")
    if not all([bs, cs, ss, ts]):
        return None
    path = f"/{bs}/{cs}/{ss}/{ts}" if pt == "notes" else f"/{bs}/{cs}/{ss}/{ts}/{pt}"
    return f"{BASE_URL}{path}"


async def notify_indexnow_for_page(page_doc: dict):
    url = _page_doc_to_url(page_doc)
    if not url:
        return
    try:
        await push_indexnow([url])
    except Exception as e:
        logger.debug(f"IndexNow auto-push failed for {url}: {e}")


async def _log_indexnow_push(urls: List[str], source: str, results: dict):
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
        await db.indexnow_push_log.insert_one({
            "id": f"inow-{uuid.uuid4().hex[:8]}",
            "url_count": len(urls),
            "urls_sample": urls[:20],
            "source": source,
            "results": results,
            "pushed_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.debug(f"IndexNow log write failed: {e}")


INDEXNOW_ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
    "https://yandex.com/indexnow",
]


async def push_indexnow(
    urls: list[str],
    source: str = "auto",
    target_endpoints: Optional[List[str]] = None,
) -> Dict[str, bool]:
    if not urls:
        return {}
    import httpx
    unique_urls = list(dict.fromkeys(urls))
    endpoints_to_try = target_endpoints or INDEXNOW_ENDPOINTS
    all_results = []
    endpoint_success: Dict[str, bool] = {ep: False for ep in endpoints_to_try}
    for i in range(0, len(unique_urls), 10000):
        batch = unique_urls[i:i + 10000]
        payload = {
            "host": "syrabit.ai",
            "key": INDEXNOW_KEY,
            "keyLocation": f"{BASE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": batch,
        }
        chunk_results = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for endpoint in endpoints_to_try:
                health = _get_health(endpoint)
                if not health.is_available():
                    chunk_results[endpoint] = "skipped:backoff"
                    logger.info(
                        "IndexNow push skipped (backoff): endpoint=%s consecutive_failures=%d",
                        endpoint, health.consecutive_failures,
                    )
                    continue
                try:
                    resp = await client.post(endpoint, json=payload)
                    if resp.status_code < 400:
                        health.record_success()
                        endpoint_success[endpoint] = True
                    else:
                        health.record_failure()
                    chunk_results[endpoint] = resp.status_code
                    logger.info(f"IndexNow push to {endpoint}: {resp.status_code} ({len(batch)} URLs)")
                except Exception as e:
                    health.record_failure()
                    chunk_results[endpoint] = str(e)
                    logger.warning(f"IndexNow push to {endpoint} failed: {e}")
        all_results.append({"chunk_index": i // 10000, "url_count": len(batch), "endpoints": chunk_results})
    results_flat = all_results[0]["endpoints"] if len(all_results) == 1 else {"chunks": all_results}
    asyncio.create_task(_log_indexnow_push(unique_urls, source, results_flat))
    return endpoint_success


class IndexNowBatcher:
    def __init__(self):
        self._pending: List[str] = []
        self._endpoint_retry: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()
        self._last_flush: Optional[datetime] = None
        self._deferred_task: Optional[asyncio.Task] = None
        self._retry_task: Optional[asyncio.Task] = None

    async def queue(self, urls: List[str]):
        async with self._lock:
            self._pending.extend(urls)

    async def queue_page(self, page_doc: dict):
        url = _page_doc_to_url(page_doc)
        if url:
            await self.queue([url])

    async def queue_raw_paths(self, paths: List[str]):
        urls = []
        for p in paths:
            if not p:
                continue
            if p.startswith("http://") or p.startswith("https://"):
                urls.append(p)
            else:
                urls.append(f"{BASE_URL}{p}")
        if urls:
            await self.queue(urls)

    async def _do_push(self, to_push: List[str], source: str) -> int:
        pushed = 0
        for i in range(0, len(to_push), _INDEXNOW_BATCH_SIZE):
            batch = to_push[i:i + _INDEXNOW_BATCH_SIZE]
            try:
                ep_results = await push_indexnow(batch, source=source)
                failed_endpoints = [
                    ep for ep, ok in ep_results.items() if not ok
                ]
                if failed_endpoints:
                    async with self._lock:
                        for ep in failed_endpoints:
                            self._endpoint_retry.setdefault(ep, []).extend(batch)
                    self._ensure_retry_loop()
                if any(ep_results.values()):
                    pushed += len(batch)
            except Exception as e:
                logger.error(f"IndexNow batch flush failed ({len(batch)} URLs): {e}")
                async with self._lock:
                    self._pending.extend(batch)
            if i + _INDEXNOW_BATCH_SIZE < len(to_push):
                await asyncio.sleep(2)
        return pushed

    def _ensure_retry_loop(self):
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry_failed_endpoints())
        elif self._retry_task.cancelled():
            self._retry_task = asyncio.create_task(self._retry_failed_endpoints())

    async def _retry_failed_endpoints(self):
        while True:
            await asyncio.sleep(15)
            async with self._lock:
                if not self._endpoint_retry:
                    return
                retryable: Dict[str, List[str]] = {}
                still_waiting: Dict[str, List[str]] = {}
                for ep, urls in self._endpoint_retry.items():
                    health = _get_health(ep)
                    if health.is_available():
                        retryable[ep] = list(dict.fromkeys(urls))
                    else:
                        still_waiting[ep] = urls
                self._endpoint_retry = still_waiting

            if not retryable:
                async with self._lock:
                    if not self._endpoint_retry:
                        return
                continue

            for ep, urls in retryable.items():
                for i in range(0, len(urls), _INDEXNOW_BATCH_SIZE):
                    batch = urls[i:i + _INDEXNOW_BATCH_SIZE]
                    try:
                        ep_results = await push_indexnow(
                            batch,
                            source="endpoint_retry",
                            target_endpoints=[ep],
                        )
                        if not ep_results.get(ep, False):
                            async with self._lock:
                                self._endpoint_retry.setdefault(ep, []).extend(batch)
                    except Exception as e:
                        logger.error(
                            "IndexNow endpoint retry failed: endpoint=%s urls=%d error=%s",
                            ep, len(batch), e,
                        )
                        async with self._lock:
                            self._endpoint_retry.setdefault(ep, []).extend(batch)
                    if i + _INDEXNOW_BATCH_SIZE < len(urls):
                        await asyncio.sleep(2)

            async with self._lock:
                if not self._endpoint_retry:
                    return

    async def _deferred_flush(self, delay: float, source: str):
        await asyncio.sleep(delay)
        await self.flush_force(source=f"{source}_deferred")

    async def flush(self, source: str = "batch"):
        async with self._lock:
            if not self._pending:
                return 0
            now = datetime.now(timezone.utc)
            if self._last_flush and (now - self._last_flush).total_seconds() < _INDEXNOW_COOLDOWN_SECONDS:
                remaining = _INDEXNOW_COOLDOWN_SECONDS - (now - self._last_flush).total_seconds()
                logger.info(f"IndexNow flush cooldown active ({len(self._pending)} URLs pending, {remaining:.0f}s left)")
                if not self._deferred_task or self._deferred_task.done():
                    self._deferred_task = asyncio.create_task(self._deferred_flush(remaining + 1, source))
                return 0
            to_push = list(dict.fromkeys(self._pending))
            self._pending.clear()
            self._last_flush = now

        return await self._do_push(to_push, source)

    async def flush_force(self, source: str = "batch_force"):
        async with self._lock:
            if not self._pending:
                return 0
            to_push = list(dict.fromkeys(self._pending))
            self._pending.clear()
            self._last_flush = datetime.now(timezone.utc)

        return await self._do_push(to_push, source)

    async def get_pending_count(self) -> int:
        async with self._lock:
            return len(self._pending)

    async def get_retry_counts(self) -> Dict[str, int]:
        async with self._lock:
            return {ep: len(urls) for ep, urls in self._endpoint_retry.items()}


indexnow_batcher = IndexNowBatcher()


from auth_deps import get_admin_user

@router.get("/admin/analytics/bot-traffic")
async def admin_bot_traffic(
    background_tasks: BackgroundTasks,
    days: int = Query(30, ge=1, le=90),
    admin: dict = Depends(get_admin_user),
):
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        return {
            "daily_bot_hits": [], "top_bots": [], "per_bot_pages": [],
            "crawl_coverage": 0, "pages_crawled": 0, "total_sitemap_pages": 0,
            "bot_vs_human": {"total_bot": 0, "total_human": 0, "bot_ratio_pct": 0},
            "period_days": days,
            "alerts": [{"type": "data_unavailable", "severity": "yellow", "message": "Database unavailable — bot analytics data could not be loaded"}],
            "alert_level": "yellow",
        }

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

        try:
            from db_ops import supa_get_settings
            _bot_settings = await supa_get_settings()
        except Exception as _settings_err:
            logger.warning("Failed to load bot alert settings, using defaults: %s", _settings_err)
            _bot_settings = {}

        def _safe_int(val, default, lo=0, hi=100):
            try:
                v = int(val)
                return max(lo, min(hi, v))
            except (TypeError, ValueError):
                return default

        CRAWL_COVERAGE_RED = _safe_int(_bot_settings.get("crawl_coverage_red"), 30)
        CRAWL_COVERAGE_YELLOW = _safe_int(_bot_settings.get("crawl_coverage_yellow"), 50)
        if CRAWL_COVERAGE_RED > CRAWL_COVERAGE_YELLOW:
            CRAWL_COVERAGE_RED, CRAWL_COVERAGE_YELLOW = CRAWL_COVERAGE_YELLOW, CRAWL_COVERAGE_RED
        BOT_MISSING_DAYS = _safe_int(_bot_settings.get("bot_missing_days"), 3, 1, 90)

        alerts = []
        alert_level = "green"

        if crawl_coverage < CRAWL_COVERAGE_RED:
            alerts.append({
                "type": "crawl_coverage",
                "severity": "red",
                "message": f"Crawl coverage critically low at {crawl_coverage}% (threshold: {CRAWL_COVERAGE_RED}%)",
            })
            alert_level = "red"
        elif crawl_coverage < CRAWL_COVERAGE_YELLOW:
            alerts.append({
                "type": "crawl_coverage",
                "severity": "yellow",
                "message": f"Crawl coverage below target at {crawl_coverage}% (threshold: {CRAWL_COVERAGE_YELLOW}%)",
            })
            if alert_level != "red":
                alert_level = "yellow"

        missing_bots = []
        absent_bots = []
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=BOT_MISSING_DAYS)).strftime("%Y-%m-%d")
        for key_bot in ["Googlebot", "Bingbot"]:
            total_key = await db.server_hits.count_documents({
                "is_bot": True,
                "bot_name": {"$regex": f"^{key_bot}$", "$options": "i"},
                "date": {"$gte": start_date},
            })
            if total_key == 0:
                absent_bots.append(key_bot)
                continue
            if days > BOT_MISSING_DAYS:
                recent_hits = await db.server_hits.count_documents({
                    "is_bot": True,
                    "bot_name": {"$regex": f"^{key_bot}$", "$options": "i"},
                    "date": {"$gte": recent_cutoff},
                })
                if recent_hits == 0:
                    missing_bots.append(key_bot)

        if len(absent_bots) == 2 and total_bot > 0:
            alerts.append({
                "type": "key_bot_missing",
                "severity": "red",
                "message": "No Googlebot or Bingbot activity detected in this period",
            })
            alert_level = "red"
        elif absent_bots:
            for ab in absent_bots:
                alerts.append({
                    "type": "key_bot_missing",
                    "severity": "yellow",
                    "message": f"{ab} has no activity in this period",
                })
                if alert_level == "green":
                    alert_level = "yellow"

        for mb in missing_bots:
            alerts.append({
                "type": "bot_inactive",
                "severity": "red",
                "message": f"{mb} was previously active but hasn't crawled in {BOT_MISSING_DAYS}+ days",
            })
            alert_level = "red"

        if len(daily_bot_hits) >= 7:
            first_half = daily_bot_hits[:len(daily_bot_hits)//2]
            second_half = daily_bot_hits[len(daily_bot_hits)//2:]
            avg_first = sum(d["bot_hits"] for d in first_half) / max(len(first_half), 1)
            avg_second = sum(d["bot_hits"] for d in second_half) / max(len(second_half), 1)
            if avg_first > 0 and avg_second < avg_first * 0.5:
                drop_pct = round((1 - avg_second / avg_first) * 100, 1)
                alerts.append({
                    "type": "traffic_drop",
                    "severity": "yellow",
                    "message": f"Bot traffic dropped {drop_pct}% compared to earlier in the period",
                })
                if alert_level == "green":
                    alert_level = "yellow"

        if alerts:
            try:
                from metrics import _dispatch_alert
                for a in alerts:
                    if a["severity"] == "red":
                        background_tasks.add_task(
                            _dispatch_alert,
                            f"bot_{a['type']}",
                            f"Bot Alert: {a['type'].replace('_', ' ').title()}",
                            a["message"],
                        )
            except ImportError:
                pass

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
            "alerts": alerts,
            "alert_level": alert_level,
        }
    except Exception as e:
        logger.error(f"bot-traffic analytics failed: {e}")
        return {
            "daily_bot_hits": [], "top_bots": [], "per_bot_pages": [],
            "crawl_coverage": 0, "pages_crawled": 0, "total_sitemap_pages": 0,
            "bot_vs_human": {"total_bot": 0, "total_human": 0, "bot_ratio_pct": 0},
            "period_days": days,
            "alerts": [{"type": "data_error", "severity": "yellow", "message": "Bot analytics failed to load — data may be incomplete"}],
            "alert_level": "yellow",
        }


@router.post("/admin/indexnow/endpoint/retry")
async def admin_indexnow_endpoint_retry(
    background_tasks: BackgroundTasks,
    body: dict,
    admin: dict = Depends(get_admin_user),
):
    endpoint = body.get("endpoint", "").strip()
    if not endpoint or endpoint not in INDEXNOW_ENDPOINTS:
        raise HTTPException(status_code=400, detail="Invalid or missing endpoint")

    health = _get_health(endpoint)
    prev_failures = health.consecutive_failures
    was_dead = health.consecutive_failures >= _DEAD_LETTER_THRESHOLD

    health.consecutive_failures = 0
    health.backoff_until = None
    _schedule_persist(health)

    if was_dead:
        _schedule_health_log(endpoint, "manual_retry", {
            "previous_consecutive_failures": prev_failures,
            "admin": admin.get("email", "unknown"),
        })

    requeued = 0
    async with indexnow_batcher._lock:
        queued_urls = indexnow_batcher._endpoint_retry.pop(endpoint, [])
        if queued_urls:
            requeued = len(queued_urls)
            indexnow_batcher._pending.extend(queued_urls)

    if requeued > 0:
        background_tasks.add_task(indexnow_batcher.flush, source="manual_retry")

    return {
        "status": "ok",
        "endpoint": endpoint,
        "previous_failures": prev_failures,
        "was_dead_lettered": was_dead,
        "urls_requeued": requeued,
    }


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
        await push_indexnow(urls, source="admin_manual")

    return {"status": "ok", "urls_pushed": len(urls)}


@router.get("/admin/indexnow/history")
async def admin_indexnow_history(
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_admin_user),
):
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        return {"pushes": [], "total": 0}
    try:
        total = await db.indexnow_push_log.count_documents({})
        pushes = await db.indexnow_push_log.find(
            {}, {"_id": 0}
        ).sort("pushed_at", -1).limit(limit).to_list(limit)
        return {"pushes": pushes, "total": total}
    except Exception as e:
        logger.error(f"IndexNow history fetch failed: {e}")
        return {"pushes": [], "total": 0}


@router.get("/admin/indexnow/stats")
async def admin_indexnow_stats(admin: dict = Depends(get_admin_user)):
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        endpoint_health_list = [_get_health(ep).to_dict() for ep in INDEXNOW_ENDPOINTS]
        return {"total_pushes": 0, "total_urls_pushed": 0, "last_push": None, "by_source": [], "pending": 0, "endpoint_health": endpoint_health_list}
    try:
        total_pushes = await db.indexnow_push_log.count_documents({})
        url_sum_pipeline = [
            {"$group": {"_id": None, "total": {"$sum": "$url_count"}}},
        ]
        url_sum = await db.indexnow_push_log.aggregate(url_sum_pipeline).to_list(1)
        total_urls = url_sum[0]["total"] if url_sum else 0

        last_push_doc = await db.indexnow_push_log.find_one(
            {}, {"_id": 0, "pushed_at": 1, "url_count": 1, "source": 1},
            sort=[("pushed_at", -1)],
        )

        by_source_pipeline = [
            {"$group": {"_id": "$source", "count": {"$sum": 1}, "urls": {"$sum": "$url_count"}}},
            {"$sort": {"count": -1}},
            {"$project": {"source": "$_id", "push_count": "$count", "url_count": "$urls", "_id": 0}},
        ]
        by_source = await db.indexnow_push_log.aggregate(by_source_pipeline).to_list(20)

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_pushes = await db.indexnow_push_log.count_documents(
            {"pushed_at": {"$gte": today_start}}
        )
        today_url_pipeline = [
            {"$match": {"pushed_at": {"$gte": today_start}}},
            {"$group": {"_id": None, "total": {"$sum": "$url_count"}}},
        ]
        today_url_sum = await db.indexnow_push_log.aggregate(today_url_pipeline).to_list(1)
        today_urls = today_url_sum[0]["total"] if today_url_sum else 0

        retry_counts = await indexnow_batcher.get_retry_counts()
        endpoint_health_list = []
        for ep in INDEXNOW_ENDPOINTS:
            info = _get_health(ep).to_dict()
            info["pending_retry_urls"] = retry_counts.get(ep, 0)
            endpoint_health_list.append(info)

        per_endpoint_limit = 10
        endpoint_health_history = {}
        try:
            pipeline = [
                {"$sort": {"timestamp": -1}},
                {"$group": {
                    "_id": "$endpoint",
                    "events": {"$push": {
                        "event": "$event",
                        "timestamp": "$timestamp",
                        "details": "$details",
                    }},
                }},
                {"$project": {
                    "_id": 0,
                    "endpoint": "$_id",
                    "events": {"$slice": ["$events", per_endpoint_limit]},
                }},
            ]
            agg_results = await db.indexnow_health_log.aggregate(pipeline).to_list(20)
            for group in agg_results:
                ep = group.get("endpoint", "unknown")
                events = group.get("events", [])
                for evt in events:
                    ts = evt.get("timestamp")
                    if isinstance(ts, datetime):
                        evt["timestamp"] = ts.isoformat()
                endpoint_health_history[ep] = events
        except Exception as hist_err:
            logger.debug("Health history aggregation failed: %s", hist_err)

        return {
            "total_pushes": total_pushes,
            "total_urls_pushed": total_urls,
            "last_push": last_push_doc,
            "by_source": by_source,
            "today_pushes": today_pushes,
            "today_urls_pushed": today_urls,
            "pending": await indexnow_batcher.get_pending_count(),
            "endpoint_health": endpoint_health_list,
            "endpoint_health_history": endpoint_health_history,
        }
    except Exception as e:
        logger.error(f"IndexNow stats fetch failed: {e}")
        return {"total_pushes": 0, "total_urls_pushed": 0, "last_push": None, "by_source": [], "pending": 0, "endpoint_health": []}

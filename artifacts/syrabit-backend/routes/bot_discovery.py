"""Syrabit.ai — Bot discovery routes: RSS feeds, llms-full.txt, IndexNow, ai-plugin.json, bot analytics."""
import asyncio, html as _html, json, logging, os, time, uuid, hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks, Request
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


_endpoint_alert_last_fired: Dict[str, float] = {}
_ENDPOINT_ALERT_COOLDOWN_S = 1800


def _get_endpoint_down_thresholds():
    try:
        from metrics import _ALERT_THRESHOLDS
        down_min = int(_ALERT_THRESHOLDS.get("endpoint_down_minutes", 60))
        check_min = int(_ALERT_THRESHOLDS.get("endpoint_down_check_minutes", 15))
    except Exception:
        down_min, check_min = 60, 15
    return max(down_min, 1) * 60, max(check_min, 1) * 60


async def _endpoint_health_alert_loop():
    """Background loop: check for endpoints failing beyond configured threshold and fire admin alerts."""
    await asyncio.sleep(120)
    while True:
        try:
            threshold_s, _ = _get_endpoint_down_thresholds()
            now = time.time()
            for ep, health in list(_endpoint_health.items()):
                if health.consecutive_failures < _DEAD_LETTER_THRESHOLD:
                    continue
                if not health.last_failure_time:
                    continue
                down_duration = now - health.last_failure_time
                if down_duration < threshold_s:
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
                            "value": threshold_s // 60,
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

        _, check_interval_s = _get_endpoint_down_thresholds()
        await asyncio.sleep(check_interval_s)


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


async def _schedule_indexnow_for_url(url: str, source: str = "fanout") -> bool:
    """Generic IndexNow trigger for a single absolute URL or relative path.

    Used by the SEO Phase A content-time fan-out (and intended as the
    canonical helper for Phase C / Phase E too) so the AI generator does
    not have to reconstruct a page document just to call IndexNow. Returns
    True when the URL is queued + a flush was attempted; False when no URL
    was provided.

    Failures inside the batcher are swallowed by the batcher itself (it
    logs and retries through its endpoint-retry loop), so this helper
    deliberately returns True on a successful enqueue regardless of
    downstream HTTP status.
    """
    if not url:
        return False
    try:
        if url.startswith("http://") or url.startswith("https://"):
            await indexnow_batcher.queue([url])
        else:
            # Defensively normalize: queue_raw_paths concatenates BASE_URL + path
            # without enforcing a leading slash, so e.g. "ahsec/..." would become
            # "https://syrabit.aiahsec/..." (a malformed URL silently dropped by
            # IndexNow). Always send a leading-slash path here.
            normalized = url if url.startswith("/") else f"/{url}"
            await indexnow_batcher.queue_raw_paths([normalized])
        await indexnow_batcher.flush(source=source)
        return True
    except Exception as e:
        logger.warning(f"_schedule_indexnow_for_url failed url={url} source={source}: {e}")
        return False


# ---------------------------------------------------------------------------
# SEO Phase A — synthetic Googlebot prewarm.
#
# After a new page is generated we fire one or two GETs through the public
# origin with the canonical Googlebot user-agent so the edge BOT_HTML_CACHE
# (KV) is populated before the real Googlebot arrives. Without this, the
# first verified-bot crawl always misses the KV and pays the cold-render
# tax — which is why the 7-day Googlebot cache-hit ratio sits at ~33.6%.
# ---------------------------------------------------------------------------

_PREWARM_USER_AGENT = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) "
    "syrabit-prewarm/1.0"
)
_PREWARM_RPS = 1.5
_PREWARM_TIMEOUT = 8.0
_prewarm_lock = asyncio.Lock()
_prewarm_last_at: float = 0.0


async def prewarm_bot_cache(urls: list[str], rps: float = _PREWARM_RPS) -> bool:
    """Fire one GET per URL through the public origin with the Googlebot
    user-agent so the edge BOT_HTML_CACHE is populated. Rate-limited at
    `rps` requests-per-second across all callers (not per-call) to avoid
    self-DoS during bulk regeneration runs.

    Best-effort: returns True if at least one URL responded with 2xx;
    False otherwise. Never raises.
    """
    global _prewarm_last_at
    if not urls:
        return False
    interval = 1.0 / max(rps, 0.1)
    import httpx
    success = 0
    timeout = httpx.Timeout(_PREWARM_TIMEOUT)
    headers = {
        "User-Agent": _PREWARM_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9,as;q=0.8",
        "X-Syrabit-Prewarm": "1",
    }
    deduped = list(dict.fromkeys(u for u in urls if u))
    if not deduped:
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for url in deduped:
                async with _prewarm_lock:
                    now = time.time()
                    wait = interval - (now - _prewarm_last_at)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    _prewarm_last_at = time.time()
                full_url = url if (url.startswith("http://") or url.startswith("https://")) else f"{BASE_URL}{url}"
                try:
                    resp = await client.get(full_url, headers=headers)
                    if 200 <= resp.status_code < 300:
                        success += 1
                        logger.info(
                            "prewarm_bot_cache hit: url=%s status=%d size=%d",
                            full_url, resp.status_code, len(resp.content),
                        )
                    else:
                        logger.info(
                            "prewarm_bot_cache non-2xx: url=%s status=%d",
                            full_url, resp.status_code,
                        )
                except Exception as e:
                    logger.info(f"prewarm_bot_cache request failed url={full_url}: {e}")
    except Exception as e:
        logger.warning(f"prewarm_bot_cache outer error: {e}")
        return False
    return success > 0


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


async def _record_submitted_urls(urls: List[str], source: str):
    """Persist the full set of URLs successfully submitted to at least one
    IndexNow endpoint, so the nightly diff job can identify URLs that have
    never been submitted before."""
    if not urls:
        return
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
        now = datetime.now(timezone.utc)
        ops = []
        from pymongo import UpdateOne
        for u in dict.fromkeys(urls):
            ops.append(UpdateOne(
                {"url": u},
                {"$set": {"url": u, "last_submitted_at": now, "last_source": source},
                 "$inc": {"submit_count": 1}},
                upsert=True,
            ))
        if ops:
            for i in range(0, len(ops), 1000):
                await db.indexnow_submitted_urls.bulk_write(ops[i:i + 1000], ordered=False)
    except Exception as e:
        logger.debug(f"IndexNow submitted-url record failed: {e}")


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
    if any(endpoint_success.values()):
        asyncio.create_task(_record_submitted_urls(unique_urls, source))
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


_SITEMAP_DIFF_INTERVAL_S = 24 * 3600
_SITEMAP_DIFF_INITIAL_DELAY_S = 600
_SITEMAP_DIFF_MAX_QUEUE = 5000
# Re-push cap: when content is meaningfully edited, cap how many edited URLs
# we re-notify IndexNow about per run to avoid hammering the endpoints on mass
# edits (e.g., a bulk chapter rewrite).
_SITEMAP_DIFF_MAX_REPUSH = 1000
# Dedupe window: don't re-push the same URL more than once per this interval,
# even if edits keep happening, to prevent thrashing IndexNow.
_SITEMAP_DIFF_REPUSH_MIN_AGE_S = 7 * 24 * 3600


async def _collect_current_sitemap_urls() -> List[str]:
    """Build the canonical set of URLs we expect search engines to know about
    by mirroring the sitemap generation in `seo_engine.py` exactly:
    STATIC_PAGES, sitemap-subjects, sitemap-chapters, sitemap-learn, and
    every published seo_page (notes/mcqs/pyqs/examples/definition).

    Reusing the seo_engine helpers (rather than re-implementing the queries
    here) guarantees parity with what is actually served at /sitemap*.xml."""
    urls: List[str] = []
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return urls

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Static pages — same set served by /sitemap-pages.xml
        try:
            from seo_engine import STATIC_PAGES
            for path, _freq, _pri in STATIC_PAGES:
                urls.append(f"{BASE_URL}{path}")
        except Exception as e:
            logger.debug(f"sitemap diff: STATIC_PAGES import failed: {e}")

        # Subjects — same logic as /sitemap-subjects.xml
        try:
            lib_subjects = await db.subjects.find({"status": "published"}, {"_id": 0}).to_list(500)
            lib_streams = {s["id"]: s for s in await db.streams.find({}, {"_id": 0}).to_list(500)}
            lib_classes = {c["id"]: c for c in await db.classes.find({}, {"_id": 0}).to_list(500)}
            lib_boards = {b["id"]: b for b in await db.boards.find({}, {"_id": 0}).to_list(500)}
            sub_map: Dict[str, dict] = {}
            for sub in lib_subjects:
                stream = lib_streams.get(sub.get("stream_id", ""))
                cls = lib_classes.get(stream.get("class_id", "")) if stream else None
                board = lib_boards.get(cls.get("board_id", "")) if cls else None
                if not (board and cls and sub.get("slug")):
                    continue
                b_slug = board.get("slug", "")
                c_slug = cls.get("slug", "")
                if not b_slug or not c_slug:
                    continue
                urls.append(f"{BASE_URL}/{b_slug}/{c_slug}/{sub['slug']}")
                sub_map[sub["id"]] = {"b": b_slug, "c": c_slug, "s": sub["slug"]}

            # Chapters — same logic as /sitemap-chapters.xml
            try:
                import re as _re
                chapters = await db.chapters.find(
                    {}, {"_id": 0, "subject_id": 1, "slug": 1, "title": 1},
                ).to_list(5000)
                for ch in chapters:
                    sub = sub_map.get(ch.get("subject_id", ""))
                    if not sub:
                        continue
                    ch_slug = ch.get("slug") or _re.sub(
                        r"[^a-z0-9]+", "-",
                        (ch.get("title") or "").lower(),
                    ).strip("-")
                    if not ch_slug:
                        continue
                    urls.append(f"{BASE_URL}/{sub['b']}/{sub['c']}/{sub['s']}/{ch_slug}")
            except Exception as e:
                logger.debug(f"sitemap diff: chapter fetch failed: {e}")
        except Exception as e:
            logger.debug(f"sitemap diff: subjects fetch failed: {e}")

        # CMS / learn pages — same query as _fetch_learn_entries
        try:
            docs = await db.cms_documents.find(
                {"status": "published", "doc_type": {"$ne": "personalized"}},
                {"_id": 0, "seo_slug": 1, "id": 1},
            ).to_list(5000)
            for d in docs:
                slug = (d.get("seo_slug") or d.get("id") or "").strip()
                if slug:
                    urls.append(f"{BASE_URL}/learn/{slug}")
        except Exception as e:
            logger.debug(f"sitemap diff: cms_documents fetch failed: {e}")

        # Notes / MCQs / PYQs / examples / definitions — every published seo_page
        try:
            valid_chains: Optional[set] = None
            try:
                from seo_engine import _build_valid_slug_chains
                valid_chains = await _build_valid_slug_chains()
            except Exception as e:
                logger.debug(f"sitemap diff: valid_chains load failed: {e}")
            allowed_types = {"notes", "mcqs", "important-questions", "examples", "definition"}
            pages = await db.seo_pages.find(
                {"status": "published"},
                {"_id": 0, "board_slug": 1, "class_slug": 1,
                 "subject_slug": 1, "topic_slug": 1, "page_type": 1},
            ).to_list(50000)
            for p in pages:
                if p.get("page_type", "notes") not in allowed_types:
                    continue
                if valid_chains is not None and (
                    p.get("board_slug"), p.get("class_slug"), p.get("subject_slug")
                ) not in valid_chains:
                    continue
                u = _page_doc_to_url(p)
                if u:
                    urls.append(u)
        except Exception as e:
            logger.debug(f"sitemap diff: seo_pages fetch failed: {e}")
    except Exception as e:
        logger.warning(f"sitemap diff URL collection failed: {e}")

    return list(dict.fromkeys(urls))


def _ensure_utc(dt_value) -> Optional[datetime]:
    """Normalize a Mongo-sourced datetime to a timezone-aware UTC datetime.
    Accepts both `datetime` objects (BSON decoder may return naive ones in
    some codecs — treat those as UTC) and ISO-8601 strings (the `subjects`,
    `chapters`, `seo_pages`, and `cms_documents` collections store
    `datetime.now(timezone.utc).isoformat()`). Returns None for anything
    unparseable so callers can safely skip the URL."""
    if isinstance(dt_value, datetime):
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(timezone.utc)
    if isinstance(dt_value, str) and dt_value:
        s = dt_value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(s)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


async def _collect_edited_url_mtimes(urls: List[str]) -> Dict[str, datetime]:
    """For a list of candidate URLs, look up the `updated_at` of the
    corresponding seo_pages / cms_documents / subjects / chapters record so
    we can tell whether the content has been meaningfully edited since the
    last IndexNow submission. Returns a dict {url: updated_at}. URLs without
    a matching record (static pages with no `updated_at`) are omitted."""
    out: Dict[str, datetime] = {}
    if not urls:
        return out
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return out

        url_set = set(urls)
        learn_prefix = f"{BASE_URL}/learn/"

        # seo_pages: rebuild URL from slug chain and match against candidate set.
        try:
            cursor = db.seo_pages.find(
                {"status": "published"},
                {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1,
                 "topic_slug": 1, "page_type": 1, "updated_at": 1},
            )
            async for p in cursor:
                u = _page_doc_to_url(p)
                if not u or u not in url_set:
                    continue
                ua = _ensure_utc(p.get("updated_at"))
                if ua is not None:
                    out[u] = ua
        except Exception as e:
            logger.debug(f"sitemap diff mtime: seo_pages scan failed: {e}")

        # subjects -> /<board>/<class>/<subject_slug> URLs
        # chapters -> /<board>/<class>/<subject_slug>/<chapter_slug> URLs
        # We need the board+class slug chain for both, so build it once.
        try:
            import re as _re
            lib_streams = {s["id"]: s for s in await db.streams.find({}, {"_id": 0}).to_list(500)}
            lib_classes = {c["id"]: c for c in await db.classes.find({}, {"_id": 0}).to_list(500)}
            lib_boards = {b["id"]: b for b in await db.boards.find({}, {"_id": 0}).to_list(500)}
            lib_subjects = await db.subjects.find(
                {"status": "published"},
                {"_id": 0, "id": 1, "slug": 1, "stream_id": 1, "updated_at": 1},
            ).to_list(2000)

            sub_chain: Dict[str, dict] = {}  # subject_id -> {b, c, s, url, updated_at}
            for sub in lib_subjects:
                stream = lib_streams.get(sub.get("stream_id", ""))
                cls = lib_classes.get(stream.get("class_id", "")) if stream else None
                board = lib_boards.get(cls.get("board_id", "")) if cls else None
                if not (board and cls and sub.get("slug")):
                    continue
                b_slug = board.get("slug", "")
                c_slug = cls.get("slug", "")
                s_slug = sub.get("slug", "")
                if not (b_slug and c_slug and s_slug):
                    continue
                u = f"{BASE_URL}/{b_slug}/{c_slug}/{s_slug}"
                ua = _ensure_utc(sub.get("updated_at"))
                sub_chain[sub["id"]] = {
                    "b": b_slug, "c": c_slug, "s": s_slug, "url": u, "updated_at": ua,
                }
                if u in url_set and ua is not None:
                    out[u] = ua

            # Chapters — pull updated_at and rebuild the URL via subject chain.
            try:
                chapters = await db.chapters.find(
                    {}, {"_id": 0, "subject_id": 1, "slug": 1, "title": 1, "updated_at": 1},
                ).to_list(10000)
                for ch in chapters:
                    sub = sub_chain.get(ch.get("subject_id", ""))
                    if not sub:
                        continue
                    ch_slug = ch.get("slug") or _re.sub(
                        r"[^a-z0-9]+", "-",
                        (ch.get("title") or "").lower(),
                    ).strip("-")
                    if not ch_slug:
                        continue
                    u = f"{BASE_URL}/{sub['b']}/{sub['c']}/{sub['s']}/{ch_slug}"
                    if u not in url_set:
                        continue
                    ua = _ensure_utc(ch.get("updated_at"))
                    if ua is not None:
                        out[u] = ua
            except Exception as e:
                logger.debug(f"sitemap diff mtime: chapters scan failed: {e}")
        except Exception as e:
            logger.debug(f"sitemap diff mtime: subjects scan failed: {e}")

        # cms_documents -> /learn/<slug> URLs
        try:
            cursor = db.cms_documents.find(
                {"status": "published", "doc_type": {"$ne": "personalized"}},
                {"_id": 0, "seo_slug": 1, "id": 1, "updated_at": 1},
            )
            async for d in cursor:
                slug = (d.get("seo_slug") or d.get("id") or "").strip()
                if not slug:
                    continue
                u = f"{learn_prefix}{slug}"
                if u not in url_set:
                    continue
                ua = _ensure_utc(d.get("updated_at"))
                if ua is not None:
                    out[u] = ua
        except Exception as e:
            logger.debug(f"sitemap diff mtime: cms_documents scan failed: {e}")
    except Exception as e:
        logger.warning(f"sitemap diff mtime collection failed: {e}")
    return out


async def _ping_google_sitemap(
    sitemap_url: str = f"{BASE_URL}/sitemap-index.xml",
) -> dict:
    """SEO Phase C helper — delegate to `google_indexing_client.ping_sitemap`.
    Kept as a thin wrapper in this module so the sitemap-diff loop and the
    admin endpoints have a stable local name, and so tests can monkeypatch
    it via `routes.bot_discovery._ping_google_sitemap`."""
    try:
        from google_indexing_client import ping_sitemap
    except Exception as e:  # pragma: no cover — module is always importable
        logger.debug(f"google sitemap ping: client import failed: {e}")
        return {"status": "error", "reason": "import_failed"}
    return await ping_sitemap(sitemap_url)


async def diff_sitemap_against_submitted(source: str = "sitemap_diff") -> dict:
    """Find URLs in the current sitemap that either have never been pushed to
    IndexNow, or whose backing content has been meaningfully edited since the
    last submission, and queue them for batched re-submission. Re-submissions
    are capped per-run and a per-URL dedupe window prevents thrashing IndexNow
    if mass updates happen."""
    from deps import db, is_mongo_available
    now = datetime.now(timezone.utc)
    summary = {
        "sitemap_total": 0,
        "already_submitted": 0,
        "new_queued": 0,
        "skipped_capacity": 0,
        "edited_queued": 0,
        "edited_skipped_dedupe": 0,
        "edited_skipped_capacity": 0,
        "ran_at": now.isoformat(),
    }

    candidates = await _collect_current_sitemap_urls()
    summary["sitemap_total"] = len(candidates)
    if not candidates:
        return summary

    # Fetch last_submitted_at for all candidates so we can detect both
    # "never submitted" and "submitted-but-stale" URLs in one pass.
    submitted_at: Dict[str, datetime] = {}
    try:
        if await is_mongo_available():
            for i in range(0, len(candidates), 5000):
                chunk = candidates[i:i + 5000]
                cursor = db.indexnow_submitted_urls.find(
                    {"url": {"$in": chunk}},
                    {"_id": 0, "url": 1, "last_submitted_at": 1},
                )
                async for doc in cursor:
                    u = doc.get("url")
                    if not u:
                        continue
                    ts = _ensure_utc(doc.get("last_submitted_at"))
                    # Treat missing/invalid timestamp as "just-submitted" so
                    # we don't spuriously classify the URL as edited.
                    submitted_at[u] = ts if ts is not None else now
    except Exception as e:
        logger.warning(f"sitemap diff: submitted-url lookup failed: {e}")

    new_urls = [u for u in candidates if u not in submitted_at]
    summary["already_submitted"] = len(candidates) - len(new_urls)

    if len(new_urls) > _SITEMAP_DIFF_MAX_QUEUE:
        summary["skipped_capacity"] = len(new_urls) - _SITEMAP_DIFF_MAX_QUEUE
        new_urls = new_urls[:_SITEMAP_DIFF_MAX_QUEUE]

    # Determine which already-submitted URLs have been edited since their last
    # submission. Only consider URLs backed by seo_pages / cms_documents where
    # we have a reliable `updated_at` timestamp.
    already_submitted_urls = [u for u in candidates if u in submitted_at]
    mtimes = await _collect_edited_url_mtimes(already_submitted_urls)

    edited_candidates: List[str] = []
    edited_skipped_dedupe = 0
    for u, updated_at in mtimes.items():
        last_sub = submitted_at.get(u)
        if not last_sub:
            continue
        if updated_at <= last_sub:
            continue
        # Dedupe window: if we submitted this URL recently, skip to avoid
        # thrashing IndexNow (e.g., when an author saves many edits in a row).
        if (now - last_sub).total_seconds() < _SITEMAP_DIFF_REPUSH_MIN_AGE_S:
            edited_skipped_dedupe += 1
            continue
        edited_candidates.append(u)

    summary["edited_skipped_dedupe"] = edited_skipped_dedupe

    # Per-run cap on edited re-pushes.
    if len(edited_candidates) > _SITEMAP_DIFF_MAX_REPUSH:
        summary["edited_skipped_capacity"] = len(edited_candidates) - _SITEMAP_DIFF_MAX_REPUSH
        # Prefer the most recently edited URLs first so the freshest changes
        # get re-notified when we hit the cap.
        edited_candidates.sort(key=lambda x: mtimes.get(x) or now, reverse=True)
        edited_candidates = edited_candidates[:_SITEMAP_DIFF_MAX_REPUSH]

    to_queue = new_urls + [u for u in edited_candidates if u not in new_urls]
    if to_queue:
        await indexnow_batcher.queue(to_queue)
        await indexnow_batcher.flush_force(source=source)
    summary["new_queued"] = len(new_urls)
    summary["edited_queued"] = len(edited_candidates)

    # SEO Phase C: when sitemap-diff surfaced any change, ping Google's
    # sitemap endpoint so Googlebot re-fetches the sitemap index sooner
    # than its natural ~24-72h polling cadence. Free, unauthenticated,
    # and failure-tolerant — never raises.
    summary["google_sitemap_ping"] = "skipped"
    if to_queue:
        try:
            ping_result = await _ping_google_sitemap()
            summary["google_sitemap_ping"] = ping_result.get("status", "skipped")
        except Exception as e:
            logger.debug(f"sitemap diff: google sitemap ping failed: {e}")
            summary["google_sitemap_ping"] = "error"

    try:
        if await is_mongo_available():
            await db.indexnow_sitemap_diff_log.insert_one({
                **summary,
                "ran_at": now,
            })
    except Exception as e:
        logger.debug(f"sitemap diff log write failed: {e}")

    logger.info(
        "IndexNow sitemap diff: total=%d submitted=%d new_queued=%d new_skipped=%d "
        "edited_queued=%d edited_dedupe=%d edited_skipped=%d",
        summary["sitemap_total"], summary["already_submitted"],
        summary["new_queued"], summary["skipped_capacity"],
        summary["edited_queued"], summary["edited_skipped_dedupe"],
        summary["edited_skipped_capacity"],
    )
    return summary


async def _sitemap_indexnow_diff_loop():
    """Background loop: nightly compare the live sitemap against the set of
    URLs we have already pushed to IndexNow and queue any missing URLs."""
    await asyncio.sleep(_SITEMAP_DIFF_INITIAL_DELAY_S)
    while True:
        try:
            await diff_sitemap_against_submitted(source="nightly_sitemap_diff")
        except Exception as exc:
            logger.warning("Sitemap-diff IndexNow loop iteration failed: %s", exc)
        await asyncio.sleep(_SITEMAP_DIFF_INTERVAL_S)


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


# The complete list of sitemaps the SEO health probe knows about. Defined
# at module level (rather than inline in `seo_health_check`) so that the
# Task #345 deep-scan endpoint can validate the requested sitemap name
# against this same whitelist — no caller can probe arbitrary URLs.
SEO_SITEMAP_FILENAMES = (
    "sitemap-pages.xml",
    "sitemap-subjects.xml",
    "sitemap-chapters.xml",
    "sitemap-notes.xml",
    "sitemap-mcqs.xml",
    "sitemap-pyqs.xml",
    "sitemap-examples.xml",
    "sitemap-definitions.xml",
    "sitemap-learn.xml",
)


@router.get("/seo/health")
async def seo_health_check(
    request: Request,
    deep_scan: Optional[str] = Query(
        None,
        description=(
            "Task #345: when set to a sitemap filename (e.g. "
            "'sitemap-learn.xml'), return that sitemap's FULL failing "
            "URL list instead of the 10-URL random sample. Requires "
            "admin auth because a full scan probes up to 500 URLs."
        ),
    ),
):
    import httpx
    from deps import db, is_mongo_available

    # Task #345: deep-scan path. Requires admin auth — the standard
    # response is public, but probing up to 500 URLs per call is a
    # DoS vector if exposed to anonymous traffic. We invoke the
    # `get_admin_user` dependency manually because the rest of this
    # endpoint is intentionally unauthenticated.
    if deep_scan is not None:
        if deep_scan not in SEO_SITEMAP_FILENAMES:
            raise HTTPException(status_code=400, detail=f"Unknown sitemap: {deep_scan}")
        await get_admin_user(request)
        return await _deep_scan_sitemap(deep_scan)

    results = {
        "status": "ok",
        "sitemaps": [],
        "d1_sync": {"status": "unknown"},
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    sitemap_urls = [
        f"{BASE_URL}/api/seo/{name}" for name in SEO_SITEMAP_FILENAMES
    ]

    import random
    import xml.etree.ElementTree as ET

    async with httpx.AsyncClient(timeout=15.0) as client:
        for sm_url in sitemap_urls:
            sm_name = sm_url.split("/")[-1]
            sm_result = {"name": sm_name, "url": sm_url, "valid_xml": False, "url_count": 0, "sample_checks": []}

            try:
                resp = await client.get(sm_url)
                if resp.status_code != 200:
                    sm_result["error"] = f"HTTP {resp.status_code}"
                    results["sitemaps"].append(sm_result)
                    continue

                try:
                    root = ET.fromstring(resp.text)
                    sm_result["valid_xml"] = True
                    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                    locs = [loc.text for loc in root.findall(".//sm:loc", ns) if loc.text]
                    sm_result["url_count"] = len(locs)

                    sample_urls = random.sample(locs, min(10, len(locs))) if locs else []
                    for sample_url in sample_urls:
                        try:
                            check_resp = await client.head(sample_url, follow_redirects=True, timeout=10.0)
                            if check_resp.status_code in (405, 403):
                                check_resp = await client.get(sample_url, follow_redirects=True, timeout=10.0)
                            sm_result["sample_checks"].append({
                                "url": sample_url,
                                "status": check_resp.status_code,
                                "ok": check_resp.status_code == 200,
                            })
                        except Exception as check_err:
                            sm_result["sample_checks"].append({
                                "url": sample_url,
                                "status": 0,
                                "ok": False,
                                "error": str(check_err)[:100],
                            })
                except ET.ParseError as parse_err:
                    sm_result["error"] = f"XML parse error: {str(parse_err)[:100]}"
            except Exception as sm_err:
                sm_result["error"] = str(sm_err)[:200]

            results["sitemaps"].append(sm_result)

        try:
            d1_resp = await client.get(f"{BASE_URL}/api/edge/d1-status", timeout=10.0)
            if d1_resp.status_code == 200:
                results["d1_sync"] = d1_resp.json()
            else:
                results["d1_sync"] = {"status": "error", "http_status": d1_resp.status_code}
        except Exception as d1_err:
            results["d1_sync"] = {"status": "error", "error": str(d1_err)[:200]}

    total_sitemaps = len(results["sitemaps"])
    valid_count = sum(1 for s in results["sitemaps"] if s.get("valid_xml"))
    all_checks = [c for s in results["sitemaps"] for c in s.get("sample_checks", [])]
    ok_checks = sum(1 for c in all_checks if c.get("ok"))
    total_checks = len(all_checks)

    if valid_count < total_sitemaps or (total_checks > 0 and ok_checks < total_checks * 0.8):
        results["status"] = "degraded"
    if valid_count < total_sitemaps * 0.5:
        results["status"] = "critical"

    results["summary"] = {
        "total_sitemaps": total_sitemaps,
        "valid_sitemaps": valid_count,
        "total_url_checks": total_checks,
        "ok_url_checks": ok_checks,
        "url_check_success_rate": round(ok_checks / max(total_checks, 1) * 100, 1),
    }

    if await is_mongo_available():
        try:
            seo_published = await db.seo_pages.count_documents({"status": "published"})
            last_updated = await db.seo_pages.find_one(
                {"status": "published"}, {"_id": 0, "updated_at": 1},
                sort=[("updated_at", -1)],
            )
            results["content_stats"] = {
                "published_pages": seo_published,
                "last_content_update": last_updated.get("updated_at") if last_updated else None,
            }
        except Exception:
            pass

    return results


_seo_health_alert_last_fired: float = 0.0
_seo_url_spike_alert_last_fired: float = 0.0
_SEO_HEALTH_ALERT_COOLDOWN_S = 6 * 3600
_SEO_URL_SPIKE_ALERT_COOLDOWN_S = 6 * 3600
_SEO_HEALTH_HISTORY_RETENTION_DAYS = 30

# ── Weekly digest ────────────────────────────────────────────────────────────
# Target: Monday 09:00 IST = Monday 03:30 UTC. The loop polls every 5 minutes
# and only fires inside a tight ±15 minute window around 03:30 UTC so the
# email lands close to 09:00 IST instead of drifting across an hour.
_SEO_WEEKLY_DIGEST_DASHBOARD_URL = "https://syrabit.ai/admin/seo"
_SEO_WEEKLY_DIGEST_API_CONFIG_KEY = "seo_weekly_digest_last_iso_week"
_SEO_WEEKLY_DIGEST_LOCK_ID = "seo_weekly_digest_lock"
# Alert type names that count as "SEO incidents" for the digest. Keep in sync
# with the alert_type strings passed to metrics._dispatch_alert from the SEO
# health/spike loops below (seo_health_degraded, seo_url_spike).
_SEO_DIGEST_ALERT_TYPES = ("seo_health_degraded", "seo_url_spike")
_SEO_WEEKLY_DIGEST_TARGET_WEEKDAY = 0        # Monday
_SEO_WEEKLY_DIGEST_TARGET_HOUR_UTC = 3       # 03:xx UTC
_SEO_WEEKLY_DIGEST_TARGET_MINUTE_UTC = 30    # 03:30 UTC = 09:00 IST
_SEO_WEEKLY_DIGEST_TOLERANCE_MINUTES = 15    # ±15 min window
_SEO_WEEKLY_DIGEST_LOOP_SLEEP_S = 300        # poll every 5 minutes


def _iso_week_tag(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _should_send_weekly_digest_now(now_utc: datetime, last_iso_week: str) -> bool:
    """Pure gate predicate so the schedule logic can be unit-tested.

    Returns True iff ``now_utc`` is within ±_SEO_WEEKLY_DIGEST_TOLERANCE_MINUTES
    of Monday 03:30 UTC AND we have not already sent a digest for the current
    ISO week.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if now_utc.weekday() != _SEO_WEEKLY_DIGEST_TARGET_WEEKDAY:
        return False
    target = now_utc.replace(
        hour=_SEO_WEEKLY_DIGEST_TARGET_HOUR_UTC,
        minute=_SEO_WEEKLY_DIGEST_TARGET_MINUTE_UTC,
        second=0, microsecond=0,
    )
    delta_minutes = abs((now_utc - target).total_seconds()) / 60.0
    if delta_minutes > _SEO_WEEKLY_DIGEST_TOLERANCE_MINUTES:
        return False
    return _iso_week_tag(now_utc) != (last_iso_week or "")


def _format_by_sitemap_html(by_sitemap, threshold_pct: float) -> str:
    """Render an HTML table showing per-sitemap pass/fail counts. Rows where
    the success rate is at or below ``100 - threshold_pct`` are highlighted.

    Each failing row is followed by a sub-row listing the captured failing
    URLs (status code + URL) so admins can jump directly to the offenders
    instead of re-running ``/api/seo/health`` after the alert (Task #299).
    """
    if not by_sitemap:
        return ""
    rows_html = []
    for row in by_sitemap:
        sr = row.get("success_rate", 0)
        bad = sr <= (100.0 - threshold_pct)
        bg = "background:#fdecea;color:#c0392b;font-weight:bold" if bad else ""
        rows_html.append(
            f"<tr style='{bg}'>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{_html.escape(str(row.get('name', 'unknown')))}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{row.get('ok', 0)} / {row.get('total', 0)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{sr}%</td>"
            f"</tr>"
        )
        failing = row.get("failing_urls") or []
        if failing:
            items = []
            for f in failing:
                code = f.get("status") or 0
                url = _html.escape(str(f.get("url", "")))
                items.append(
                    f"<li style='margin:2px 0'>"
                    f"<code style='background:#fff;padding:1px 4px;border-radius:3px;color:#c0392b'>{code}</code> "
                    f"<a href='{url}' style='color:#1f2937;text-decoration:none' target='_blank' rel='noopener'>{url}</a>"
                    f"</li>"
                )
            rows_html.append(
                "<tr style='background:#fff7f7'>"
                "<td colspan='3' style='padding:6px 10px;border:1px solid #ddd;font-family:monospace;font-size:12px;color:#7f1d1d'>"
                "<div style='font-weight:bold;margin-bottom:4px'>Failing URLs:</div>"
                f"<ul style='margin:0;padding-left:18px'>{''.join(items)}</ul>"
                "</td>"
                "</tr>"
            )
    return (
        "<table style='border-collapse:collapse;margin:12px 0;width:100%;max-width:720px;font-family:sans-serif;font-size:13px'>"
        "<tr style='background:#f3f4f6'>"
        "<th style='text-align:left;padding:6px 10px;border:1px solid #ddd'>Sitemap (page-type)</th>"
        "<th style='text-align:left;padding:6px 10px;border:1px solid #ddd'>OK / total</th>"
        "<th style='text-align:left;padding:6px 10px;border:1px solid #ddd'>Success rate</th>"
        "</tr>"
        + "".join(rows_html)
        + "</table>"
    )


def _format_by_sitemap_text(by_sitemap) -> str:
    """Plain-text fallback for the per-sitemap breakdown — includes the
    captured failing URLs (status code + URL) under each broken sitemap
    so admins reading the text/plain part of the alert get the same
    actionable detail (Task #299)."""
    if not by_sitemap:
        return ""
    lines: list[str] = []
    for r in by_sitemap:
        lines.append(
            f"  - {r.get('name', 'unknown')}: {r.get('ok', 0)}/{r.get('total', 0)} OK "
            f"({r.get('success_rate', 0)}%)"
        )
        for f in (r.get("failing_urls") or []):
            lines.append(f"      [{f.get('status', 0)}] {f.get('url', '')}")
    return "\nPer-sitemap breakdown:\n" + "\n".join(lines)


async def _record_seo_health_snapshot() -> Dict:
    """Run seo_health_check, persist a compact snapshot in db.seo_health_history.

    Returns the snapshot doc (including status). Designed to be called every
    hour by the background loop and on-demand via admin endpoint.
    """
    from deps import db, is_mongo_available

    try:
        report = await seo_health_check()
    except Exception as exc:
        logger.warning(f"seo_health_check raised during snapshot: {exc}")
        report = {
            "status": "critical",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "summary": {},
            "error": str(exc)[:200],
        }

    summary = report.get("summary") or {}
    # Per-sitemap pass/fail breakdown — used by the seo_url_spike alert
    # to tell admins which page-type is failing (e.g. only /learn/* URLs).
    by_sitemap = []
    for sm in report.get("sitemaps") or []:
        checks = sm.get("sample_checks") or []
        if not checks:
            continue
        ok = sum(1 for c in checks if c.get("ok"))
        total = len(checks)
        # Capture the first 10 failing URLs so the alert email and admin
        # dashboard can show admins exactly which URLs returned 404 (Task
        # #299) — not just the page-type breakdown. Status code 0 means
        # the request errored out (timeout/DNS) rather than a 4xx/5xx.
        failing_urls = [
            {"url": c.get("url", ""), "status": int(c.get("status") or 0)}
            for c in checks if not c.get("ok") and c.get("url")
        ][:10]
        by_sitemap.append({
            "name": sm.get("name", "unknown"),
            "ok": ok,
            "total": total,
            "success_rate": round(ok / max(total, 1) * 100, 1),
            "failing_urls": failing_urls,
        })
    snapshot = {
        "status": report.get("status", "unknown"),
        "checked_at": report.get("checked_at") or datetime.now(timezone.utc).isoformat(),
        "recorded_at": datetime.now(timezone.utc),
        "summary": {
            "total_sitemaps": summary.get("total_sitemaps", 0),
            "valid_sitemaps": summary.get("valid_sitemaps", 0),
            "total_url_checks": summary.get("total_url_checks", 0),
            "ok_url_checks": summary.get("ok_url_checks", 0),
            "url_check_success_rate": summary.get("url_check_success_rate", 0),
        },
        "by_sitemap": by_sitemap,
        "d1_status": (report.get("d1_sync") or {}).get("status", "unknown"),
        "content_stats": report.get("content_stats", {}),
        "error": report.get("error"),
    }

    if not await is_mongo_available():
        return snapshot

    try:
        await db.seo_health_history.insert_one(dict(snapshot))
        cutoff = datetime.now(timezone.utc) - timedelta(days=_SEO_HEALTH_HISTORY_RETENTION_DAYS)
        await db.seo_health_history.delete_many({"recorded_at": {"$lt": cutoff}})
    except Exception as exc:
        logger.debug(f"Failed to persist seo health snapshot: {exc}")

    return snapshot


def _compose_seo_weekly_digest(history: list, *, dashboard_url: str = _SEO_WEEKLY_DIGEST_DASHBOARD_URL,
                               recent_alerts: int = 0) -> dict:
    """Aggregate the past-7-days seo_health_history snapshots into a digest dict.

    ``history`` is a list of snapshot docs (any order) — usually the previous
    168 hourly snapshots. Returns the stats payload consumed by
    ``_format_seo_weekly_digest_html`` and the manual-trigger admin endpoint.
    Designed to be a pure function so unit tests can drive it with fixtures.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=7)

    in_window = []
    for h in history or []:
        ra = h.get("recorded_at")
        if isinstance(ra, str):
            try:
                ra_dt = datetime.fromisoformat(ra.replace("Z", "+00:00"))
            except ValueError:
                continue
        elif isinstance(ra, datetime):
            ra_dt = ra if ra.tzinfo else ra.replace(tzinfo=timezone.utc)
        else:
            continue
        if ra_dt >= window_start:
            in_window.append((ra_dt, h))

    in_window.sort(key=lambda t: t[0])
    snaps = [h for _, h in in_window]
    total_snapshots = len(snaps)

    status_counts = {"ok": 0, "degraded": 0, "critical": 0, "unknown": 0}
    valid_sitemaps_sum = 0
    total_sitemaps_sum = 0
    url_total_sum = 0
    url_ok_sum = 0
    rate_sum = 0.0
    rate_count = 0

    worst_status = None  # latest non-ok snapshot for quick context
    for snap in snaps:
        st = (snap.get("status") or "unknown").lower()
        if st not in status_counts:
            st = "unknown"
        status_counts[st] += 1
        s = snap.get("summary") or {}
        valid_sitemaps_sum += int(s.get("valid_sitemaps", 0) or 0)
        total_sitemaps_sum += int(s.get("total_sitemaps", 0) or 0)
        url_total_sum += int(s.get("total_url_checks", 0) or 0)
        url_ok_sum += int(s.get("ok_url_checks", 0) or 0)
        try:
            rate = float(s.get("url_check_success_rate", 0) or 0)
            rate_sum += rate
            rate_count += 1
        except (TypeError, ValueError):
            pass
        if st in ("degraded", "critical"):
            worst_status = st

    healthy = status_counts["ok"]
    uptime_pct = round((healthy / total_snapshots) * 100, 1) if total_snapshots else 0.0
    avg_url_success = round(rate_sum / rate_count, 1) if rate_count else 0.0
    avg_valid_sitemaps = round(valid_sitemaps_sum / total_snapshots, 1) if total_snapshots else 0.0
    avg_total_sitemaps = round(total_sitemaps_sum / total_snapshots, 1) if total_snapshots else 0.0

    latest = snaps[-1] if snaps else None
    latest_status = (latest.get("status") or "unknown").lower() if latest else "unknown"

    # Valid-sitemap trend across the window: first vs latest snapshot.
    first = snaps[0] if snaps else None
    first_valid = int(((first or {}).get("summary") or {}).get("valid_sitemaps", 0) or 0) if first else 0
    latest_valid = int(((latest or {}).get("summary") or {}).get("valid_sitemaps", 0) or 0) if latest else 0
    valid_sitemaps_delta = latest_valid - first_valid
    if not snaps:
        valid_sitemaps_trend = "flat"
    elif valid_sitemaps_delta > 0:
        valid_sitemaps_trend = "up"
    elif valid_sitemaps_delta < 0:
        valid_sitemaps_trend = "down"
    else:
        valid_sitemaps_trend = "flat"

    return {
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "total_snapshots": total_snapshots,
        "status_counts": status_counts,
        "uptime_pct": uptime_pct,
        "latest_status": latest_status,
        "worst_status_in_window": worst_status,
        "avg_url_success_rate": avg_url_success,
        "total_url_checks": url_total_sum,
        "ok_url_checks": url_ok_sum,
        "avg_valid_sitemaps": avg_valid_sitemaps,
        "avg_total_sitemaps": avg_total_sitemaps,
        "valid_sitemaps_first": first_valid,
        "valid_sitemaps_latest": latest_valid,
        "valid_sitemaps_delta": valid_sitemaps_delta,
        "valid_sitemaps_trend": valid_sitemaps_trend,
        "recent_alerts": int(recent_alerts or 0),
        "dashboard_url": dashboard_url,
        "iso_week": _iso_week_tag(now),
    }


def _format_seo_weekly_digest_html(stats: dict) -> str:
    """Render the digest payload as a Resend-compatible HTML email body."""
    sc = stats.get("status_counts") or {}
    uptime = stats.get("uptime_pct", 0.0)
    uptime_color = "#16a34a" if uptime >= 95 else ("#d97706" if uptime >= 80 else "#c0392b")
    latest = (stats.get("latest_status") or "unknown").upper()
    latest_color = {"OK": "#16a34a", "DEGRADED": "#d97706", "CRITICAL": "#c0392b"}.get(latest, "#475569")
    dashboard = stats.get("dashboard_url") or _SEO_WEEKLY_DIGEST_DASHBOARD_URL

    return (
        "<div style='font-family:sans-serif;max-width:560px;margin:auto;padding:24px;color:#0f172a'>"
        "<h2 style='color:#7c3aed;margin:0 0 4px'>Syrabit.ai · SEO weekly digest</h2>"
        f"<p style='color:#64748b;margin:0 0 18px;font-size:13px'>"
        f"Window: {stats.get('window_start','')[:10]} → {stats.get('window_end','')[:10]} "
        f"(ISO week {stats.get('iso_week','')})"
        "</p>"
        "<table style='border-collapse:collapse;width:100%;font-size:14px;margin-bottom:18px'>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Snapshots collected</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{stats.get('total_snapshots', 0)}</b></td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Healthy uptime</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right;color:{uptime_color};font-weight:bold'>{uptime}%</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Latest status</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right;color:{latest_color};font-weight:bold'>{latest}</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Status breakdown</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'>"
        f"OK: {sc.get('ok',0)} · DEGRADED: {sc.get('degraded',0)} · CRITICAL: {sc.get('critical',0)}"
        f"{' · UNKNOWN: ' + str(sc.get('unknown',0)) if sc.get('unknown',0) else ''}"
        "</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Avg URL spot-check success</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{stats.get('avg_url_success_rate',0)}%</b> "
        f"({stats.get('ok_url_checks',0)}/{stats.get('total_url_checks',0)} sampled)</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Avg valid sitemaps</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'>"
        f"{stats.get('avg_valid_sitemaps',0)} / {stats.get('avg_total_sitemaps',0)}</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Valid sitemaps trend</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'>"
        f"{stats.get('valid_sitemaps_first',0)} → {stats.get('valid_sitemaps_latest',0)} "
        f"<b style='color:{'#16a34a' if stats.get('valid_sitemaps_trend')=='up' else ('#c0392b' if stats.get('valid_sitemaps_trend')=='down' else '#475569')}'>"
        f"({'▲' if stats.get('valid_sitemaps_trend')=='up' else ('▼' if stats.get('valid_sitemaps_trend')=='down' else '▬')} "
        f"{'+' if stats.get('valid_sitemaps_delta',0)>0 else ''}{stats.get('valid_sitemaps_delta',0)})"
        f"</b></td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Alerts fired this week</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{stats.get('recent_alerts',0)}</b></td></tr>"
        "</table>"
        f"<p style='margin:18px 0'><a href='{dashboard}' style='display:inline-block;background:#7c3aed;"
        "color:white;text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600;font-size:14px'>"
        "Open SEO Manager dashboard</a></p>"
        "<p style='color:#94a3b8;font-size:12px;margin-top:24px'>"
        "You're getting this because you're listed as the Syrabit.ai SEO admin contact. "
        "To stop these weekly summaries, clear the email channel in /admin notifications."
        "</p></div>"
    )


async def _gather_weekly_digest_inputs(now: Optional[datetime] = None) -> dict:
    """Pull the past-7-days history and alert count from Mongo, then compose
    the digest stats. Returns ``{}`` when Mongo is unavailable."""
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        return {}
    _now = now or datetime.now(timezone.utc)
    cutoff = _now - timedelta(days=7)
    try:
        history = await db.seo_health_history.find(
            {"recorded_at": {"$gte": cutoff}}, {"_id": 0}
        ).sort("recorded_at", 1).to_list(length=200)
    except Exception as exc:
        logger.debug(f"[SEO digest] history fetch failed: {exc}")
        history = []
    try:
        # Only SEO-related alert types so the digest's "alerts fired this
        # week" reflects actual SEO incidents rather than every system alert
        # (endpoint_down, billing, etc.) that happened to fire in the window.
        recent_alerts = await db.alerts.count_documents({
            "fired_at": {"$gte": cutoff.isoformat()},
            "type": {"$in": _SEO_DIGEST_ALERT_TYPES},
        })
    except Exception:
        recent_alerts = 0
    return _compose_seo_weekly_digest(history, recent_alerts=recent_alerts)


async def _send_seo_weekly_digest_email(stats: dict, *, to: Optional[str] = None) -> dict:
    """Send the rendered digest via Resend. Returns ``{sent, to, reason?}``."""
    if not stats:
        return {"sent": False, "to": "", "reason": "no_stats"}
    try:
        from metrics import _notification_channels, _load_alert_settings
        try:
            await _load_alert_settings()
        except Exception:
            pass
        admin_email = (to or _notification_channels.get("email")
                       or os.environ.get("ALERT_EMAIL", "")).strip()
    except Exception:
        admin_email = (to or os.environ.get("ALERT_EMAIL", "")).strip()
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not admin_email:
        return {"sent": False, "to": "", "reason": "no_admin_email"}
    if not resend_key:
        return {"sent": False, "to": admin_email, "reason": "no_resend_key"}
    try:
        from email_templates import EMAIL_FROM
    except Exception:
        EMAIL_FROM = os.environ.get("EMAIL_FROM", "Syrabit.ai <noreply@syrabit.ai>").strip()
    html = _format_seo_weekly_digest_html(stats)
    subject = (
        f"Syrabit SEO weekly digest · "
        f"{stats.get('uptime_pct', 0)}% uptime · "
        f"{stats.get('iso_week', '')}"
    )
    try:
        import resend as _resend_sdk
        _resend_sdk.api_key = resend_key
        _resend_sdk.Emails.send({
            "from": EMAIL_FROM,
            "to": [admin_email],
            "subject": subject,
            "html": html,
        })
        logger.info(f"[SEO digest] sent weekly digest → {admin_email} ({stats.get('iso_week','')})")
        return {"sent": True, "to": admin_email, "subject": subject}
    except Exception as exc:
        logger.warning(f"[SEO digest] Resend send failed: {exc}")
        return {"sent": False, "to": admin_email, "reason": f"send_error:{type(exc).__name__}"}


async def _seo_weekly_digest_loop():
    """Background loop for the weekly SEO digest.

    Polls every ``_SEO_WEEKLY_DIGEST_LOOP_SLEEP_S`` (5 min) and only fires
    inside a ±``_SEO_WEEKLY_DIGEST_TOLERANCE_MINUTES`` (15 min) window
    around Monday 03:30 UTC (= 09:00 IST), as enforced by
    ``_should_send_weekly_digest_now``.

    Dedup is atomic across replicas: we issue a conditional
    ``find_one_and_update`` (with an ``insert_one`` bootstrap fallback) on a
    dedicated singleton lock document inside ``db.job_locks`` (``_id`` =
    ``_SEO_WEEKLY_DIGEST_LOCK_ID``). Only the worker whose write touches a
    row actually sends the email; all other replicas observe the marker has
    already advanced to the current ISO week and skip.
    """
    from deps import db, is_mongo_available
    await asyncio.sleep(600)  # let the app warm up
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if await is_mongo_available():
                await _try_send_weekly_digest_once(db, now_utc)
        except Exception as exc:
            logger.debug(f"[SEO digest] loop iteration error: {exc}")
        await asyncio.sleep(_SEO_WEEKLY_DIGEST_LOOP_SLEEP_S)


async def _claim_weekly_digest_slot(db, cur_iso_week: str) -> bool:
    """Atomic compare-and-set on a dedicated lock document inside the
    ``job_locks`` collection (``_id`` = ``_SEO_WEEKLY_DIGEST_LOCK_ID``).

    We use a separate collection — not ``api_config`` — because the rest of
    the codebase reads ``api_config`` as a singleton via ``find_one({})``
    with no ``_id`` filter. Adding a second document there would make those
    reads nondeterministic and silently break alert settings, GA4 tokens,
    notification channel config, etc.

    Returns True iff this caller successfully advanced the marker from
    ``!= cur_iso_week`` to ``cur_iso_week``. Concurrent callers race on the
    unique ``_id`` so at most one wins per ISO week — no duplicate emails
    even with multiple Railway replicas."""
    from pymongo.errors import DuplicateKeyError

    # Path A: doc already exists for an older week — atomic compare-and-set.
    try:
        res = await db.job_locks.find_one_and_update(
            {
                "_id": _SEO_WEEKLY_DIGEST_LOCK_ID,
                _SEO_WEEKLY_DIGEST_API_CONFIG_KEY: {"$ne": cur_iso_week},
            },
            {"$set": {_SEO_WEEKLY_DIGEST_API_CONFIG_KEY: cur_iso_week}},
            upsert=False,
        )
        if res is not None:
            return True  # we flipped a stale marker → we own the claim
    except Exception as exc:
        logger.debug(f"[SEO digest] CAS update failed: {exc}")
        return False

    # Path B: doc may not exist yet — try a one-shot insert. The unique
    # `_id` constraint guarantees only one worker's insert succeeds; the
    # rest get DuplicateKeyError and bail out as losers.
    try:
        await db.job_locks.insert_one({
            "_id": _SEO_WEEKLY_DIGEST_LOCK_ID,
            _SEO_WEEKLY_DIGEST_API_CONFIG_KEY: cur_iso_week,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[SEO digest] bootstrap insert failed: {exc}")
        return False


async def _try_send_weekly_digest_once(db, now_utc: datetime) -> dict:
    """One iteration of the digest loop, factored out for testability."""
    cur_iso_week = _iso_week_tag(now_utc)
    # Cheap pre-gate read so we don't hammer the lock collection with CAS
    # calls outside the Monday window.
    try:
        cfg = await db.job_locks.find_one(
            {"_id": _SEO_WEEKLY_DIGEST_LOCK_ID},
            {"_id": 0, _SEO_WEEKLY_DIGEST_API_CONFIG_KEY: 1},
        ) or {}
    except Exception:
        cfg = {}
    last_sent = cfg.get(_SEO_WEEKLY_DIGEST_API_CONFIG_KEY, "")
    if not _should_send_weekly_digest_now(now_utc, last_sent):
        return {"claimed": False, "sent": False, "reason": "outside_window_or_dedup"}

    if not await _claim_weekly_digest_slot(db, cur_iso_week):
        return {"claimed": False, "sent": False, "reason": "lost_race"}

    stats = await _gather_weekly_digest_inputs(now_utc)
    result = await _send_seo_weekly_digest_email(stats)
    if not result.get("sent"):
        # Roll the marker back so a subsequent poll inside the same window
        # can retry (transient Resend outage, etc.).
        logger.info(
            f"[SEO digest] send failed for {cur_iso_week} "
            f"(reason={result.get('reason','unknown')}); rolling back claim"
        )
        try:
            await db.job_locks.update_one(
                {
                    "_id": _SEO_WEEKLY_DIGEST_LOCK_ID,
                    _SEO_WEEKLY_DIGEST_API_CONFIG_KEY: cur_iso_week,
                },
                {"$set": {_SEO_WEEKLY_DIGEST_API_CONFIG_KEY: last_sent or ""}},
            )
        except Exception:
            pass
    return {"claimed": True, "sent": result.get("sent", False), "reason": result.get("reason")}


async def _seo_health_alert_loop():
    """Hourly: snapshot /seo/health. Fires two independent admin alerts via
    metrics._dispatch_alert (Resend email + persisted to db.alerts):

      1. ``seo_health_degraded`` — when the two most recent snapshots both
         have aggregate status of ``degraded`` or ``critical``.
      2. ``seo_url_spike`` — when the URL spot-check success rate falls
         below ``100 - url_404_spike_pct`` for two consecutive snapshots.
         The alert email includes a per-page-type breakdown so admins can
         see which sitemap is failing (e.g. only ``/learn/*`` URLs).
    """
    global _seo_health_alert_last_fired, _seo_url_spike_alert_last_fired

    await asyncio.sleep(180)
    while True:
        try:
            snapshot = await _record_seo_health_snapshot()
            status = (snapshot.get("status") or "unknown").lower()

            # ── (2) seo_url_spike — checked first because it can fire even
            # when aggregate status is still "ok".
            try:
                from metrics import _ALERT_THRESHOLDS, _load_alert_settings, _dispatch_alert as _md
                from metrics import _alert_last_fired as _ml
                # Refresh thresholds so admin tweaks apply within an hour.
                try:
                    await _load_alert_settings()
                except Exception:
                    pass
                threshold_pct = float(_ALERT_THRESHOLDS.get("url_404_spike_pct", 20.0))
                bad_floor = 100.0 - threshold_pct
                latest_rate = float((snapshot.get("summary") or {}).get("url_check_success_rate", 100))
                latest_total = int((snapshot.get("summary") or {}).get("total_url_checks", 0))
                if latest_total > 0 and latest_rate < bad_floor:
                    from deps import db as _db, is_mongo_available as _ma
                    spike_consecutive = 1
                    if await _ma():
                        try:
                            recent = await _db.seo_health_history.find(
                                {}, {"_id": 0, "summary": 1, "recorded_at": 1}
                            ).sort("recorded_at", -1).limit(2).to_list(2)
                            if len(recent) >= 2:
                                prev_summary = recent[1].get("summary") or {}
                                prev_rate = float(prev_summary.get("url_check_success_rate", 100))
                                prev_total = int(prev_summary.get("total_url_checks", 0))
                                if prev_total > 0 and prev_rate < bad_floor:
                                    spike_consecutive = 2
                        except Exception:
                            pass

                    now_ts = time.time()
                    if spike_consecutive >= 2 and (now_ts - _seo_url_spike_alert_last_fired) >= _SEO_URL_SPIKE_ALERT_COOLDOWN_S:
                        _ml.pop("seo_url_spike", None)
                        s = snapshot.get("summary") or {}
                        by_sm = snapshot.get("by_sitemap") or []
                        body_text = (
                            f"URL spot-check success rate has been at {latest_rate}% for two "
                            f"consecutive hourly checks (alert fires below {bad_floor}%). "
                            f"OK: {s.get('ok_url_checks', 0)}/{s.get('total_url_checks', 0)} "
                            f"sampled URLs. Inspect /api/seo/health and the SEO Manager dashboard."
                            f"{_format_by_sitemap_text(by_sm)}"
                        )
                        try:
                            await _md(
                                "seo_url_spike",
                                f"SEO: URL 404 spike ({latest_rate}% OK)",
                                body_text,
                                threshold_snapshot={
                                    "metric": "url_404_spike_pct",
                                    "value": threshold_pct,
                                    "actual": round(100.0 - latest_rate, 1),
                                    "ok_url_checks": s.get("ok_url_checks", 0),
                                    "total_url_checks": s.get("total_url_checks", 0),
                                    "by_sitemap_html": _format_by_sitemap_html(by_sm, threshold_pct),
                                },
                            )
                            _seo_url_spike_alert_last_fired = now_ts
                        except Exception as exc:
                            logger.debug(f"Failed to dispatch seo_url_spike alert: {exc}")
            except Exception as exc:
                logger.debug(f"seo_url_spike check skipped: {exc}")

            if status in ("degraded", "critical"):
                from deps import db, is_mongo_available
                consecutive_bad = 1
                if await is_mongo_available():
                    try:
                        recent = await db.seo_health_history.find(
                            {}, {"_id": 0, "status": 1, "recorded_at": 1}
                        ).sort("recorded_at", -1).limit(2).to_list(2)
                        if len(recent) >= 2 and (recent[1].get("status") or "").lower() in ("degraded", "critical"):
                            consecutive_bad = 2
                    except Exception:
                        pass

                now = time.time()
                if consecutive_bad >= 2 and (now - _seo_health_alert_last_fired) >= _SEO_HEALTH_ALERT_COOLDOWN_S:
                    try:
                        from metrics import _dispatch_alert, _alert_last_fired as _ml
                        _ml.pop("seo_health_degraded", None)
                        s = snapshot.get("summary") or {}
                        await _dispatch_alert(
                            "seo_health_degraded",
                            f"SEO health: {status.upper()}",
                            (
                                f"/api/seo/health reported {status.upper()} for two consecutive hourly checks. "
                                f"Sitemaps valid: {s.get('valid_sitemaps', 0)}/{s.get('total_sitemaps', 0)} · "
                                f"URL spot-checks OK: {s.get('ok_url_checks', 0)}/{s.get('total_url_checks', 0)} "
                                f"({s.get('url_check_success_rate', 0)}%). "
                                f"Inspect /api/seo/health and the SEO Manager dashboard."
                            ),
                            threshold_snapshot={
                                "metric": "seo_health_status",
                                "value": "ok",
                                "actual": status,
                                "valid_sitemaps": s.get("valid_sitemaps", 0),
                                "total_sitemaps": s.get("total_sitemaps", 0),
                                "url_check_success_rate": s.get("url_check_success_rate", 0),
                            },
                        )
                        _seo_health_alert_last_fired = now
                    except Exception as exc:
                        logger.debug(f"Failed to dispatch seo_health_degraded alert: {exc}")
        except Exception as exc:
            logger.debug(f"SEO health alert loop iteration error: {exc}")

        await asyncio.sleep(3600)


@router.get("/admin/seo/fanout-recent")
async def admin_seo_fanout_recent(
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_admin_user),
):
    """Return the most recent SEO Phase A content-time fan-out events for
    debugging — what URL was generated, when, and whether IndexNow / cache
    purge / bot prewarm each fired or were skipped. Newest last.

    Also reports whether the killswitch (`SEO_FANOUT_ENABLED`) is on so the
    admin UI can show "fan-out disabled" vs "no recent activity".
    """
    try:
        from seo_fanout import recent_fanout_events, is_enabled
    except Exception as e:
        return {"enabled": False, "events": [], "error": str(e)}
    return {
        "enabled": is_enabled(),
        "events": recent_fanout_events(limit=limit),
    }


@router.get("/admin/seo/google-indexing-stats")
async def admin_seo_google_indexing_stats(
    admin: dict = Depends(get_admin_user),
):
    """SEO Phase C — return today's Google Indexing API counters
    (submissions, 2xx/4xx/5xx, quota remaining) plus sitemap-ping stats
    and service-account-load status. Since Task #327 it also returns
    yesterday's totals (hydrated from Mongo `google_indexing_daily`) for
    the admin dashboard history panel, and hydrates today's in-memory
    counters on first call per process so the 200/day cap survives a
    restart."""
    try:
        from google_indexing_client import get_stats_with_history
    except Exception as e:
        return {"enabled": False, "error": str(e)}
    return await get_stats_with_history()


@router.post("/admin/seo/google-sitemap-ping")
async def admin_seo_google_sitemap_ping(
    admin: dict = Depends(get_admin_user),
):
    """Manual trigger for the free Google sitemap-ping endpoint. Useful
    when an operator wants to nudge Google after a bulk content push
    without waiting for the nightly sitemap-diff loop."""
    return await _ping_google_sitemap()


@router.get("/admin/seo/health-history")
async def admin_seo_health_history(
    limit: int = Query(168, ge=1, le=720),
    admin: dict = Depends(get_admin_user),
):
    """Return recent SEO health snapshots for trend analysis (default last 7 days
    of hourly snapshots). Also returns latest status and a flag indicating whether
    the dashboard should display a degraded banner."""
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        return {"history": [], "latest": None, "banner": None}

    try:
        docs = await db.seo_health_history.find(
            {}, {"_id": 0}
        ).sort("recorded_at", -1).limit(limit).to_list(limit)
    except Exception as exc:
        logger.debug(f"seo health history fetch failed: {exc}")
        docs = []

    latest = docs[0] if docs else None
    banner = None
    if latest:
        latest_status = (latest.get("status") or "").lower()
        if latest_status in ("degraded", "critical"):
            consecutive = 1
            for d in docs[1:]:
                if (d.get("status") or "").lower() in ("degraded", "critical"):
                    consecutive += 1
                else:
                    break
            # Per task spec: banner only appears after two consecutive bad
            # checks (same gate as the alert email) to avoid flapping noise.
            if consecutive >= 2:
                banner = {
                    "severity": latest_status,
                    "consecutive": consecutive,
                    "checked_at": latest.get("checked_at"),
                    "summary": latest.get("summary", {}),
                }

    history_asc = list(reversed(docs))
    for d in history_asc:
        ra = d.get("recorded_at")
        if isinstance(ra, datetime):
            d["recorded_at"] = ra.isoformat()

    return {
        "history": history_asc,
        "latest": latest,
        "banner": banner,
        "count": len(docs),
    }


@router.post("/admin/seo/weekly-digest/send")
async def admin_seo_weekly_digest_send(
    preview_only: bool = Query(False, description="If true, return the rendered stats/HTML without sending the email."),
    admin: dict = Depends(get_admin_user),
):
    """Manually trigger (or preview) the weekly SEO digest. Useful for QA and
    for catching up after an outage. Does not advance the ISO-week dedup
    marker so the regular Monday send still happens."""
    stats = await _gather_weekly_digest_inputs()
    html = _format_seo_weekly_digest_html(stats) if stats else ""
    if preview_only:
        return {"sent": False, "preview": True, "stats": stats, "html": html}
    result = await _send_seo_weekly_digest_email(stats)
    return {"sent": result.get("sent", False), "to": result.get("to", ""),
            "reason": result.get("reason"), "stats": stats}


@router.post("/admin/seo/health-snapshot")
async def admin_seo_health_snapshot_now(admin: dict = Depends(get_admin_user)):
    """Manually trigger an SEO health snapshot (does not bypass the alert
    cooldown). Useful for verifying the system after fixing a regression."""
    snapshot = await _record_seo_health_snapshot()
    if isinstance(snapshot.get("recorded_at"), datetime):
        snapshot["recorded_at"] = snapshot["recorded_at"].isoformat()
    return snapshot


# Task #345: when a sitemap shows ≥10 failing URLs in the regular health
# probe (which only samples 10 random URLs per sitemap) admins lose
# visibility into the true blast radius of an outage. This endpoint
# fetches a single named sitemap and HEAD-probes every URL inside it
# (capped at SEO_DEEP_SCAN_MAX_URLS for safety) so the admin dashboard
# can show the full failing list on demand.
SEO_DEEP_SCAN_MAX_URLS = 500
SEO_DEEP_SCAN_CONCURRENCY = 20


async def _deep_scan_sitemap(sitemap_name: str) -> dict:
    """Fetch every URL in `sitemap_name` and return the list of failing
    URLs (status != 200, or network error → status 0). Caller is
    responsible for whitelisting `sitemap_name` against
    SEO_SITEMAP_FILENAMES — this helper does not re-validate."""
    import httpx
    import xml.etree.ElementTree as ET

    sitemap_url = f"{BASE_URL}/api/seo/{sitemap_name}"
    result: dict = {
        "sitemap": sitemap_name,
        "sitemap_url": sitemap_url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_urls": 0,
        "checked": 0,
        "truncated": False,
        "failing": [],
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(sitemap_url)
        except Exception as fetch_err:
            result["error"] = f"sitemap fetch failed: {str(fetch_err)[:200]}"
            return result
        if resp.status_code != 200:
            result["error"] = f"sitemap returned HTTP {resp.status_code}"
            return result
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as pe:
            result["error"] = f"sitemap XML parse error: {str(pe)[:200]}"
            return result

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls: List[str] = [loc.text for loc in root.findall(".//sm:loc", ns) if loc.text]
        result["total_urls"] = len(urls)
        if len(urls) > SEO_DEEP_SCAN_MAX_URLS:
            urls = urls[:SEO_DEEP_SCAN_MAX_URLS]
            result["truncated"] = True
        result["checked"] = len(urls)

        sem = asyncio.Semaphore(SEO_DEEP_SCAN_CONCURRENCY)
        failing: List[Dict] = []
        failing_lock = asyncio.Lock()

        async def _probe(u: str):
            async with sem:
                try:
                    r = await client.head(u, follow_redirects=True, timeout=10.0)
                    if r.status_code in (405, 403):
                        r = await client.get(u, follow_redirects=True, timeout=10.0)
                    if r.status_code != 200:
                        async with failing_lock:
                            failing.append({"url": u, "status": r.status_code})
                except Exception as exc:
                    async with failing_lock:
                        failing.append({
                            "url": u, "status": 0, "error": str(exc)[:120],
                        })

        await asyncio.gather(*[_probe(u) for u in urls])
        # Stable order — match original sitemap order so admins see URLs
        # in a predictable sequence rather than completion-time order.
        order_index = {u: i for i, u in enumerate(urls)}
        failing.sort(key=lambda f: order_index.get(f["url"], 1 << 31))
        result["failing"] = failing

    return result


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


@router.post("/admin/indexnow/resubmit-recent")
async def admin_indexnow_resubmit_recent(admin: dict = Depends(get_admin_user)):
    """Force a full re-submission cycle: push the most recently updated
    pages immediately, run a sitemap diff to capture any URLs that have
    never been submitted, and flush the batcher queue."""
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    pages = await db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1,
         "topic_slug": 1, "page_type": 1}
    ).sort("updated_at", -1).limit(500).to_list(500)
    recent_urls = []
    for p in pages:
        u = _page_doc_to_url(p)
        if u:
            recent_urls.append(u)
    if recent_urls:
        await push_indexnow(recent_urls, source="admin_resubmit_recent")

    diff_summary = await diff_sitemap_against_submitted(source="admin_resubmit_recent")
    flushed = await indexnow_batcher.flush_force(source="admin_resubmit_recent")

    return {
        "status": "ok",
        "recent_urls_pushed": len(recent_urls),
        "sitemap_diff": diff_summary,
        "batcher_flushed": flushed,
    }


# ---------------------------------------------------------------------------
# IndexNow full URL backfill — Task #334
#
# One-time admin operation that pushes EVERY public URL on syrabit.ai to
# Bing/Yandex/IndexNow, not just the 500-most-recent slice the existing
# `admin_indexnow_push` ships. Used to bring older content into Bing's
# index when it has never been submitted.
#
# Idempotent: re-running submits the full catalog again. Concurrent runs
# are blocked at the state level (returns 409). Progress is exposed via
# `GET /admin/indexnow/backfill-progress` so the admin UI can poll.
# ---------------------------------------------------------------------------

_BACKFILL_CHUNK_SIZE = 10000
_BACKFILL_LOCK_ID = "indexnow_full_backfill"
_BACKFILL_RUNS_COLLECTION = "indexnow_backfill_runs"
# A run is considered stale (and stealable) after this much wall-clock time
# without finishing — large enough to let a real ~50k-URL backfill finish
# (a few minutes), small enough to recover from a worker crash quickly.
_BACKFILL_STALE_AFTER = timedelta(hours=2)

_backfill_state: Dict[str, object] = {
    "status": "idle",  # idle | running | done | error
    "discovered": 0,
    "submitted": 0,
    "succeeded": 0,
    "failed": 0,
    "skipped": 0,
    "skip_reasons": {},
    "chunks_total": 0,
    "chunks_done": 0,
    "endpoint_status": {},   # endpoint -> {success_chunks, failed_chunks}
    "started_at": None,
    "finished_at": None,
    "source": "admin_full_backfill",
    "error": None,
    "run_id": None,
}
_backfill_lock = asyncio.Lock()


def _reset_backfill_state(run_id: str) -> None:
    _backfill_state.update({
        "status": "running",
        "discovered": 0,
        "submitted": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "skip_reasons": {},
        "chunks_total": 0,
        "chunks_done": 0,
        "endpoint_status": {ep: {"success_chunks": 0, "failed_chunks": 0}
                             for ep in INDEXNOW_ENDPOINTS},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "source": "admin_full_backfill",
        "error": None,
        "run_id": run_id,
    })


def _validate_backfill_url(url: str) -> Optional[str]:
    """Return None if `url` is acceptable, else a short skip reason. Rules:
    - must be a non-empty string
    - must be absolute http(s)
    - host must equal `syrabit.ai` (sub-domains, www, http→https mismatches
      are rejected — IndexNow's host claim is exact)
    - must not contain whitespace / control chars (RFC-3986 fail-safe)
    - max length 2048 (Bing's documented per-URL cap)
    """
    if not url or not isinstance(url, str):
        return "empty"
    s = url.strip()
    if not s:
        return "empty"
    if any(ch.isspace() or ord(ch) < 0x20 for ch in s):
        return "invalid_chars"
    if len(s) > 2048:
        return "too_long"
    try:
        from urllib.parse import urlparse
        p = urlparse(s)
    except Exception:
        return "unparseable"
    if p.scheme not in ("http", "https"):
        return "not_absolute"
    if p.netloc.lower() != "syrabit.ai":
        return "wrong_host"
    return None


async def _collect_all_backfill_urls() -> tuple[List[str], Dict[str, int]]:
    """Discover every public URL that should be in Bing's index.

    Starts from `_collect_current_sitemap_urls()` (STATIC_PAGES + subjects
    + chapters + learn docs + the legacy 5 seo_page types the daily
    sitemap exposes) and then **explicitly enumerates every published
    seo_page across ALL page_types** (no allowlist) so the catalog push
    is genuinely complete — any future / non-legacy page_type ships too.
    The homepage `/` is also appended explicitly (STATIC_PAGES emits
    `/home`; Cloudflare Pages serves `/` as a separate canonical URL).
    """
    raw = await _collect_current_sitemap_urls()
    raw.append(f"{BASE_URL}/")

    # Supplementary pass: pick up published seo_pages whose page_type sits
    # outside the daily-sitemap allowlist. We do not filter by page_type
    # at all here — the only requirement is that the page is published
    # and that we can construct a usable URL.
    try:
        from deps import db, is_mongo_available
        if await is_mongo_available():
            try:
                from seo_engine import _build_valid_slug_chains
                valid_chains: Optional[set] = None
                try:
                    valid_chains = await _build_valid_slug_chains()
                except Exception as e:  # pragma: no cover — diagnostic only
                    logger.debug(f"backfill: valid_chains load failed: {e}")
                pages = await db.seo_pages.find(
                    {"status": "published"},
                    {"_id": 0, "board_slug": 1, "class_slug": 1,
                     "subject_slug": 1, "topic_slug": 1, "page_type": 1},
                ).to_list(200000)
                for p in pages:
                    if valid_chains is not None and (
                        p.get("board_slug"), p.get("class_slug"), p.get("subject_slug")
                    ) not in valid_chains:
                        continue
                    u = _page_doc_to_url(p)
                    if u:
                        raw.append(u)
            except Exception as e:
                logger.warning(f"backfill: seo_pages full-type fetch failed: {e}")
    except Exception as e:  # pragma: no cover — defensive
        logger.debug(f"backfill: seo_pages supplementary pass skipped: {e}")

    seen: set = set()
    valid: List[str] = []
    skip_reasons: Dict[str, int] = {}
    for u in raw:
        norm = u.strip() if isinstance(u, str) else ""
        if norm in seen:
            continue
        seen.add(norm)
        reason = _validate_backfill_url(norm)
        if reason is not None:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        valid.append(norm)
    return valid, skip_reasons


def _state_with_queued(state: dict) -> dict:
    """Return a shallow copy of `state` with an explicit `queued` field
    derived from `discovered - submitted` (clamped at 0).

    Note: `discovered` is the count of *valid* URLs that the worker
    actually intends to push (the validator strips invalid ones into
    `skipped` before we record `discovered = len(valid_urls)`). So the
    queued backlog is simply discovered minus the URLs already shipped
    to IndexNow — subtracting `skipped` here would double-count.
    """
    snap = dict(state)
    try:
        discovered = int(snap.get("discovered", 0) or 0)
        submitted = int(snap.get("submitted", 0) or 0)
    except (TypeError, ValueError):
        discovered = submitted = 0
    snap["queued"] = max(discovered - submitted, 0)
    return snap


async def _persist_backfill_progress() -> None:
    """Best-effort write of the in-memory backfill state to Mongo so a
    sibling worker / replica polling `GET /admin/indexnow/backfill-progress`
    sees the same numbers as the worker actually doing the push.

    Keyed by `_id = run_id`, so each run gets its own durable record
    (useful for post-mortem too — `db.indexnow_backfill_runs.find().sort({updated_at:-1})`).
    Swallows DB errors so we never crash the push loop on a write failure.
    """
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
        run_id = _backfill_state.get("run_id")
        if not run_id:
            return
        snap = dict(_backfill_state)
        snap["updated_at"] = datetime.now(timezone.utc)
        await db[_BACKFILL_RUNS_COLLECTION].update_one(
            {"_id": run_id},
            {"$set": snap},
            upsert=True,
        )
    except Exception as e:  # pragma: no cover — diagnostic only
        logger.debug("backfill progress persist failed: %s", e)


async def _load_latest_backfill_run() -> Optional[dict]:
    """Read the most recent run document from Mongo so the GET endpoint
    can return cross-worker progress. Returns None if Mongo is down or
    no runs have ever been recorded. The `_id` and `updated_at` storage
    fields are stripped so the payload shape matches `_backfill_state`."""
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return None
        doc = await db[_BACKFILL_RUNS_COLLECTION].find_one(
            {}, sort=[("updated_at", -1)],
        )
        if not doc:
            return None
        doc.pop("_id", None)
        doc.pop("updated_at", None)
        return doc
    except Exception as e:  # pragma: no cover — diagnostic only
        logger.debug("backfill progress load failed: %s", e)
        return None


async def _claim_backfill_lock(run_id: str) -> bool:
    """Atomic, DB-backed single-flight guard for the full backfill, so
    concurrent admin clicks against multiple gunicorn workers / Railway
    replicas can't start two simultaneous catalog pushes.

    Strategy:
      1. Try ``insert_one`` of a fresh lock doc — wins if no doc exists.
      2. On ``DuplicateKeyError`` (a doc already exists) attempt to *steal*
         it with a single ``find_one_and_update`` whose filter matches only
         non-running OR stale (>``_BACKFILL_STALE_AFTER``) holders. If the
         CAS matches we win; otherwise a live run already owns the lock
         and we lose (caller must 409).

    Returns True iff this caller acquired the lock.
    """
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        return False
    from pymongo.errors import DuplicateKeyError
    now = datetime.now(timezone.utc)
    try:
        await db.job_locks.insert_one({
            "_id": _BACKFILL_LOCK_ID,
            "owner_run_id": run_id,
            "claimed_at": now,
            "status": "running",
        })
        return True
    except DuplicateKeyError:
        pass
    stale_cutoff = now - _BACKFILL_STALE_AFTER
    res = await db.job_locks.find_one_and_update(
        {
            "_id": _BACKFILL_LOCK_ID,
            "$or": [
                {"status": {"$ne": "running"}},
                {"claimed_at": {"$lt": stale_cutoff}},
            ],
        },
        {"$set": {
            "owner_run_id": run_id,
            "claimed_at": now,
            "status": "running",
        }},
    )
    return res is not None


async def _release_backfill_lock(run_id: str, status: str) -> None:
    """Release our claim if (and only if) we still own it. Best-effort —
    swallows DB errors so we never crash the worker on cleanup."""
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
        await db.job_locks.update_one(
            {"_id": _BACKFILL_LOCK_ID, "owner_run_id": run_id},
            {"$set": {
                "status": status,
                "released_at": datetime.now(timezone.utc),
            }},
        )
    except Exception as e:  # pragma: no cover — diagnostic only
        logger.debug("backfill lock release failed run_id=%s: %s", run_id, e)


async def _run_indexnow_backfill(run_id: str) -> None:
    """Background worker: enumerate, chunk ≤10k, push, update progress."""
    final_status = "error"
    try:
        # Fail fast when Mongo is unavailable, instead of silently
        # short-circuiting via _collect_current_sitemap_urls' empty-list
        # fallback (which would mark the run as "done" with discovered=0
        # and mislead operators into thinking a successful push happened).
        from deps import is_mongo_available
        if not await is_mongo_available():
            if _backfill_state.get("run_id") == run_id:
                _backfill_state["status"] = "error"
                _backfill_state["error"] = (
                    "MongoDB is unavailable — cannot enumerate URL catalog"
                )
                _backfill_state["finished_at"] = datetime.now(timezone.utc).isoformat()
            return

        urls, skip_reasons = await _collect_all_backfill_urls()
        # Guard: if a fresh run replaced us in the in-memory state, abort
        # silently rather than clobbering the new run's counters.
        if _backfill_state.get("run_id") != run_id:
            return
        _backfill_state["discovered"] = len(urls)
        _backfill_state["skipped"] = sum(skip_reasons.values())
        _backfill_state["skip_reasons"] = skip_reasons

        chunks = [urls[i:i + _BACKFILL_CHUNK_SIZE]
                  for i in range(0, len(urls), _BACKFILL_CHUNK_SIZE)]
        _backfill_state["chunks_total"] = len(chunks)
        await _persist_backfill_progress()
        if not chunks:
            _backfill_state["status"] = "done"
            _backfill_state["finished_at"] = datetime.now(timezone.utc).isoformat()
            final_status = "done"
            await _persist_backfill_progress()
            logger.info(
                "IndexNow backfill run_id=%s discovered=0 — nothing to send", run_id
            )
            return

        logger.info(
            "IndexNow backfill run_id=%s starting: %d URLs in %d chunks",
            run_id, len(urls), len(chunks),
        )

        for idx, chunk in enumerate(chunks):
            try:
                ep_results = await push_indexnow(
                    chunk, source="admin_full_backfill"
                )
            except Exception as e:
                logger.warning(
                    "IndexNow backfill chunk %d/%d failed: %s",
                    idx + 1, len(chunks), e,
                )
                ep_results = {ep: False for ep in INDEXNOW_ENDPOINTS}

            chunk_succeeded = any(ep_results.values())
            for ep, ok in ep_results.items():
                slot = _backfill_state["endpoint_status"].setdefault(  # type: ignore[union-attr]
                    ep, {"success_chunks": 0, "failed_chunks": 0}
                )
                if ok:
                    slot["success_chunks"] += 1
                else:
                    slot["failed_chunks"] += 1

            _backfill_state["submitted"] = int(_backfill_state["submitted"]) + len(chunk)  # type: ignore[arg-type]
            if chunk_succeeded:
                _backfill_state["succeeded"] = int(_backfill_state["succeeded"]) + len(chunk)  # type: ignore[arg-type]
            else:
                _backfill_state["failed"] = int(_backfill_state["failed"]) + len(chunk)  # type: ignore[arg-type]
            _backfill_state["chunks_done"] = idx + 1
            await _persist_backfill_progress()

        _backfill_state["status"] = "done"
        _backfill_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        final_status = "done"
        await _persist_backfill_progress()
        logger.info(
            "IndexNow backfill run_id=%s complete: discovered=%d submitted=%d "
            "succeeded=%d failed=%d skipped=%d",
            run_id,
            _backfill_state["discovered"], _backfill_state["submitted"],
            _backfill_state["succeeded"], _backfill_state["failed"],
            _backfill_state["skipped"],
        )
    except Exception as e:
        logger.exception("IndexNow backfill run_id=%s crashed: %s", run_id, e)
        if _backfill_state.get("run_id") == run_id:
            _backfill_state["status"] = "error"
            _backfill_state["error"] = str(e)
            _backfill_state["finished_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_backfill_progress()
        final_status = "error"
    finally:
        await _release_backfill_lock(run_id, final_status)


@router.post("/admin/indexnow/backfill-all")
async def admin_indexnow_backfill_all(
    background_tasks: BackgroundTasks,
    admin: dict = Depends(get_admin_user),
):
    """Kick off a full IndexNow backfill in the background. Returns 409 if
    a run is already in progress (claimed atomically via the DB-backed
    lock so concurrent admins on different gunicorn workers / Railway
    replicas can't double-fire), 503 if Mongo is unavailable; otherwise
    resets state and returns the initial progress payload."""
    from deps import is_mongo_available
    if not await is_mongo_available():
        raise HTTPException(
            status_code=503,
            detail="MongoDB is unavailable — cannot run IndexNow backfill",
        )
    async with _backfill_lock:
        if _backfill_state.get("status") == "running":
            raise HTTPException(
                status_code=409,
                detail="A backfill run is already in progress",
            )
        run_id = uuid.uuid4().hex[:12]
        claimed = await _claim_backfill_lock(run_id)
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail="A backfill run is already in progress on another worker",
            )
        _reset_backfill_state(run_id)

    background_tasks.add_task(_run_indexnow_backfill, run_id)
    return {"status": "started", "run_id": run_id, "progress": dict(_backfill_state)}


@router.get("/admin/indexnow/backfill-progress")
async def admin_indexnow_backfill_progress(
    admin: dict = Depends(get_admin_user),
):
    """Live progress snapshot for the most recent / running backfill.

    Reads from Mongo (`indexnow_backfill_runs`) so polls hitting any
    gunicorn worker / Railway replica see the same numbers as the worker
    actually doing the push. Falls back to in-memory state when Mongo is
    unavailable or no run has ever been recorded. Includes an explicit
    `queued = max(discovered - submitted, 0)` field for the UI (`discovered`
    already excludes validator-skipped URLs, so `skipped` is NOT subtracted
    again).
    """
    db_snap = await _load_latest_backfill_run()
    local = dict(_backfill_state)

    if db_snap is None:
        snap = local
    else:
        local_run = local.get("run_id")
        db_run = db_snap.get("run_id")
        if local_run and local_run == db_run:
            # Same run on this worker — local memory is at least as fresh
            # as the last persist (the persist happens after each chunk
            # but the in-memory mutation happens first). Prefer whichever
            # has more chunks_done so we never go backwards on a poll.
            local_done = int(local.get("chunks_done", 0) or 0)
            db_done = int(db_snap.get("chunks_done", 0) or 0)
            snap = local if local_done >= db_done else db_snap
        else:
            # Run was driven by another worker (or this worker booted after
            # a restart). DB is the authoritative source.
            snap = db_snap

    return {"progress": _state_with_queued(snap)}


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

        sitemap_diff_latest = None
        sitemap_diff_history: list = []
        try:
            diff_docs = await db.indexnow_sitemap_diff_log.find(
                {},
                {"_id": 0, "ran_at": 1, "sitemap_total": 1, "already_submitted": 1,
                 "new_queued": 1, "skipped_capacity": 1},
            ).sort("ran_at", -1).limit(10).to_list(10)
            for doc in diff_docs:
                ts = doc.get("ran_at")
                if isinstance(ts, datetime):
                    doc["ran_at"] = ts.isoformat()
            if diff_docs:
                sitemap_diff_latest = diff_docs[0]
                sitemap_diff_history = diff_docs
        except Exception as diff_err:
            logger.debug("Sitemap diff log fetch failed: %s", diff_err)

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
            "sitemap_diff_latest": sitemap_diff_latest,
            "sitemap_diff_history": sitemap_diff_history,
        }
    except Exception as e:
        logger.error(f"IndexNow stats fetch failed: {e}")
        return {"total_pushes": 0, "total_urls_pushed": 0, "last_push": None, "by_source": [], "pending": 0, "endpoint_health": []}


# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare per-UA crawler report (Task #315)
# Weekly job that snapshots verified-search-bot traffic per crawler and
# stores the markdown + raw aggregates in `db.cf_bot_reports` (one doc per
# ISO week). Mirrors the same Mon 03:30 UTC ±15min window pattern as the
# SEO weekly digest, offset by 30 minutes (04:00 UTC) so the two jobs
# don't pile onto the same five-minute poll tick.
# ─────────────────────────────────────────────────────────────────────────────

_CF_BOT_REPORT_LOCK_ID = "cf_bot_report_lock"
_CF_BOT_REPORT_API_CONFIG_KEY = "cf_bot_report_last_iso_week"
_CF_BOT_REPORT_COLLECTION = "cf_bot_reports"
_CF_BOT_REPORT_TARGET_WEEKDAY = 0       # Monday
_CF_BOT_REPORT_TARGET_HOUR_UTC = 4      # 04:00 UTC ≈ 09:30 IST
_CF_BOT_REPORT_TARGET_MINUTE_UTC = 0
_CF_BOT_REPORT_TOLERANCE_MINUTES = 15
_CF_BOT_REPORT_LOOP_SLEEP_S = 300       # 5 min poll
_CF_BOT_REPORT_WARMUP_S = 900           # 15 min after boot before first tick
# Where the loop drops the dated markdown file (matches the existing
# hand-run report layout in `.local/reports/`). Overridable via
# CF_BOT_REPORT_DIR for tests / non-Replit environments. We resolve the
# default lazily so production deployments without a writable `.local/`
# don't fail the whole loop — `_write_cf_report_to_disk` swallows IOErrors.
_CF_BOT_REPORT_FILE_PREFIX = "cloudflare-search-bots-per-ua-"


def _cf_bot_report_dir() -> str:
    """Resolve the target dir for the dated markdown drop.

    Resolution order:
      1. ``CF_BOT_REPORT_DIR`` env var (explicit override).
      2. Walk up from this file looking for a ``.local`` sibling — robust
         to deploy layouts that don't preserve the `routes/` →
         `syrabit-backend/` → `artifacts/` → repo nesting.
      3. Fall back to ``$PWD/.local/reports`` so the path resolution
         itself never raises (any actual write failure is then caught
         by ``_write_cf_report_to_disk``).
    """
    import pathlib
    override = os.getenv("CF_BOT_REPORT_DIR", "").strip()
    if override:
        return override
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".local").is_dir():
            return str(parent / ".local" / "reports")
    return str(pathlib.Path.cwd() / ".local" / "reports")


def _write_cf_report_to_disk(markdown: str, raw_data: dict, now_utc: datetime) -> Optional[str]:
    """Write the markdown + JSON sidecar to `.local/reports/`. Returns the
    absolute path on success, None on any IOError (so the loop never
    crashes when running on a read-only deploy)."""
    import pathlib
    try:
        target_dir = pathlib.Path(_cf_bot_report_dir())
        target_dir.mkdir(parents=True, exist_ok=True)
        date_tag = now_utc.strftime("%Y-%m-%d")
        md_path = target_dir / f"{_CF_BOT_REPORT_FILE_PREFIX}{date_tag}.md"
        md_path.write_text(markdown, encoding="utf-8")
        sidecar = md_path.with_suffix(".json")
        sidecar.write_text(json.dumps(raw_data, indent=2), encoding="utf-8")
        return str(md_path)
    except OSError as exc:
        logger.info(f"[CF bot report] disk write skipped ({exc.__class__.__name__}: {exc})")
        return None
    except Exception as exc:
        logger.warning(f"[CF bot report] unexpected disk-write error: {exc}")
        return None


def _should_run_cf_bot_report_now(now_utc: datetime, last_iso_week: str) -> bool:
    """Pure gate predicate (mirror of `_should_send_weekly_digest_now`).

    Returns True iff `now_utc` is inside Monday 04:00 UTC ±15 min and we
    have not already produced a report for the current ISO week.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if now_utc.weekday() != _CF_BOT_REPORT_TARGET_WEEKDAY:
        return False
    target = now_utc.replace(
        hour=_CF_BOT_REPORT_TARGET_HOUR_UTC,
        minute=_CF_BOT_REPORT_TARGET_MINUTE_UTC,
        second=0, microsecond=0,
    )
    delta_minutes = abs((now_utc - target).total_seconds()) / 60.0
    if delta_minutes > _CF_BOT_REPORT_TOLERANCE_MINUTES:
        return False
    return _iso_week_tag(now_utc) != (last_iso_week or "")


async def _claim_cf_bot_report_slot(db, cur_iso_week: str) -> bool:
    """Atomic compare-and-set on `db.job_locks[_CF_BOT_REPORT_LOCK_ID]`.

    Identical pattern to `_claim_weekly_digest_slot` — separate doc id so
    the two weekly jobs don't collide.
    """
    from pymongo.errors import DuplicateKeyError

    try:
        res = await db.job_locks.find_one_and_update(
            {
                "_id": _CF_BOT_REPORT_LOCK_ID,
                _CF_BOT_REPORT_API_CONFIG_KEY: {"$ne": cur_iso_week},
            },
            {"$set": {_CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week}},
            upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[CF bot report] CAS update failed: {exc}")
        return False

    try:
        await db.job_locks.insert_one({
            "_id": _CF_BOT_REPORT_LOCK_ID,
            _CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[CF bot report] bootstrap insert failed: {exc}")
        return False


async def _load_prior_cf_bot_report(db) -> Optional[dict]:
    """Fetch the most recent stored report's `data` block so the next run
    can compute a week-over-week diff against it. Returns None on miss."""
    try:
        doc = await db[_CF_BOT_REPORT_COLLECTION].find_one(
            {}, sort=[("generated_at", -1)],
        )
    except Exception as exc:
        logger.debug(f"[CF bot report] prior load failed: {exc}")
        return None
    if not doc:
        return None
    return doc.get("data") or None


async def _try_run_cf_bot_report_once(db, now_utc: datetime) -> dict:
    """One iteration of the report loop, factored out for testability.

    Returns a small status dict so tests can assert on the outcome
    without inspecting Mongo state.
    """
    cur_iso_week = _iso_week_tag(now_utc)
    try:
        cfg = await db.job_locks.find_one(
            {"_id": _CF_BOT_REPORT_LOCK_ID},
            {"_id": 0, _CF_BOT_REPORT_API_CONFIG_KEY: 1},
        ) or {}
    except Exception:
        cfg = {}
    last_run = cfg.get(_CF_BOT_REPORT_API_CONFIG_KEY, "")
    if not _should_run_cf_bot_report_now(now_utc, last_run):
        return {"claimed": False, "stored": False, "reason": "outside_window_or_dedup"}

    if not await _claim_cf_bot_report_slot(db, cur_iso_week):
        return {"claimed": False, "stored": False, "reason": "lost_race"}

    from cf_bot_report import generate_per_ua_report

    prior = await _load_prior_cf_bot_report(db)
    try:
        result = await generate_per_ua_report(prior=prior, now=now_utc)
    except Exception as exc:
        logger.warning(f"[CF bot report] generation crashed: {exc}")
        result = None

    if not result:
        # Roll the marker back so a later poll inside the same window can
        # retry (Cloudflare API blip, missing creds being added, etc.).
        try:
            await db.job_locks.update_one(
                {
                    "_id": _CF_BOT_REPORT_LOCK_ID,
                    _CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week,
                },
                {"$set": {_CF_BOT_REPORT_API_CONFIG_KEY: last_run or ""}},
            )
        except Exception:
            pass
        return {"claimed": True, "stored": False, "reason": "generate_failed"}

    doc = {
        "iso_week": cur_iso_week,
        "generated_at": now_utc,
        "since": result["since"],
        "until": result["until"],
        "zone_id": result["zone_id"],
        "data": result["data"],
        "wow": result["wow"],
        "crosscheck": result.get("crosscheck"),
        "markdown": result["markdown"],
    }
    try:
        await db[_CF_BOT_REPORT_COLLECTION].update_one(
            {"iso_week": cur_iso_week},
            {"$set": doc},
            upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[CF bot report] store failed: {exc}")
        # Mirror the generate-failure rollback: roll the lock marker
        # back so a later poll inside the same Monday window can retry
        # the store after a transient Mongo blip.
        try:
            await db.job_locks.update_one(
                {
                    "_id": _CF_BOT_REPORT_LOCK_ID,
                    _CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week,
                },
                {"$set": {_CF_BOT_REPORT_API_CONFIG_KEY: last_run or ""}},
            )
        except Exception:
            pass
        return {"claimed": True, "stored": False, "reason": f"store_error:{type(exc).__name__}"}

    # Also drop a dated markdown + JSON sidecar into `.local/reports/` so
    # the SEO/crawl-budget review workflow can keep using the file-based
    # artifact path. No-op (logged at INFO) on read-only deploys.
    disk_path = _write_cf_report_to_disk(result["markdown"], result["data"], now_utc)

    logger.info(
        f"[CF bot report] stored weekly report for {cur_iso_week} "
        f"({result['data']['totals']['requests']} req, "
        f"{result['data']['totals']['bots']} crawlers)"
        + (f" → {disk_path}" if disk_path else "")
    )
    return {"claimed": True, "stored": True, "iso_week": cur_iso_week,
            "totals": result["data"]["totals"], "file_path": disk_path}


async def _cf_bot_report_catchup_if_missed(db, now_utc: datetime) -> dict:
    """One-shot recovery: if we missed the Monday 04:00 window for the
    current ISO week (e.g. service was down then), run the report once
    on boot so the week isn't silently skipped.

    Bypasses `_should_run_cf_bot_report_now`'s window check, but still
    requires the dedup lock — so multiple replicas booting concurrently
    can't double-fire. Only runs if no report exists for this ISO week.
    """
    cur_iso_week = _iso_week_tag(now_utc)
    try:
        existing = await db[_CF_BOT_REPORT_COLLECTION].find_one(
            {"iso_week": cur_iso_week}, {"_id": 1},
        )
    except Exception as exc:
        logger.debug(f"[CF bot report] catch-up lookup failed: {exc}")
        return {"ran": False, "reason": "lookup_failed"}
    if existing:
        return {"ran": False, "reason": "already_have_week"}

    if not await _claim_cf_bot_report_slot(db, cur_iso_week):
        return {"ran": False, "reason": "lost_race"}

    from cf_bot_report import generate_per_ua_report

    prior = await _load_prior_cf_bot_report(db)
    try:
        result = await generate_per_ua_report(prior=prior, now=now_utc)
    except Exception as exc:
        logger.warning(f"[CF bot report] catch-up generate crashed: {exc}")
        result = None
    if not result:
        # Roll back so a normal Monday-window poll can still run later.
        try:
            await db.job_locks.update_one(
                {"_id": _CF_BOT_REPORT_LOCK_ID,
                 _CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week},
                {"$set": {_CF_BOT_REPORT_API_CONFIG_KEY: ""}},
            )
        except Exception:
            pass
        return {"ran": False, "reason": "generate_failed"}

    doc = {
        "iso_week": cur_iso_week, "generated_at": now_utc,
        "since": result["since"], "until": result["until"],
        "zone_id": result["zone_id"], "data": result["data"],
        "wow": result["wow"],
        "crosscheck": result.get("crosscheck"),
        "markdown": result["markdown"],
        "catch_up": True,
    }
    try:
        await db[_CF_BOT_REPORT_COLLECTION].update_one(
            {"iso_week": cur_iso_week}, {"$set": doc}, upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[CF bot report] catch-up store failed: {exc}")
        # Roll the lock marker back so a later poll (or next boot) can
        # retry the catch-up after a transient Mongo write blip — same
        # rollback policy used in `_try_run_cf_bot_report_once`.
        try:
            await db.job_locks.update_one(
                {"_id": _CF_BOT_REPORT_LOCK_ID,
                 _CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week},
                {"$set": {_CF_BOT_REPORT_API_CONFIG_KEY: ""}},
            )
        except Exception:
            pass
        return {"ran": False, "reason": "store_failed"}
    _write_cf_report_to_disk(result["markdown"], result["data"], now_utc)
    logger.info(f"[CF bot report] catch-up ran for missed week {cur_iso_week}")
    return {"ran": True, "iso_week": cur_iso_week}


async def _cf_bot_report_loop():
    """Background loop for the weekly Cloudflare per-UA crawler report.

    On boot (after a 15-min warmup) runs `_cf_bot_report_catchup_if_missed`
    once so a service outage during the Monday window doesn't silently
    skip a week. Then polls every 5 min and fires inside Mon 04:00 UTC
    ±15 min, dedup'd via `_claim_cf_bot_report_slot`.
    """
    from deps import db, is_mongo_available
    await asyncio.sleep(_CF_BOT_REPORT_WARMUP_S)
    # Boot-time catch-up: heal any missed Monday window.
    try:
        if await is_mongo_available():
            await _cf_bot_report_catchup_if_missed(db, datetime.now(timezone.utc))
    except Exception as exc:
        logger.debug(f"[CF bot report] catch-up error: {exc}")
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if await is_mongo_available():
                await _try_run_cf_bot_report_once(db, now_utc)
        except Exception as exc:
            logger.debug(f"[CF bot report] loop iteration error: {exc}")
        await asyncio.sleep(_CF_BOT_REPORT_LOOP_SLEEP_S)


@router.post("/admin/cf-bot-report/external-totals")
async def admin_cf_bot_report_set_externals(
    payload: dict,
    admin: dict = Depends(get_admin_user),
):
    """Persist the week's Googlebot/Bingbot totals from Google Search
    Console and Bing Webmaster Tools into the JSON sidecar. The next
    weekly run (or manual trigger) will then render the comparison
    table with divergence flags.

    Expected payload:
    ```json
    {
      "iso_week": "2026-W16",  // optional, defaults to current
      "googlebot": {"requests": 4200, "source": "GSC Crawl stats"},
      "bingbot":   {"requests":  900, "source": "BWT Crawl information"}
    }
    ```
    Either `googlebot` or `bingbot` may be omitted; existing values for
    the other bot are preserved.
    """
    import json as _json
    from cf_bot_crosscheck import _default_external_totals_path

    now_utc = datetime.now(timezone.utc)
    iso_week = (payload.get("iso_week") or "").strip() or _iso_week_tag(now_utc)

    path = _default_external_totals_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(f"[CF crosscheck] cannot create dir {path.parent}: {exc}")
        raise HTTPException(status_code=500, detail="report_dir_unwritable")

    raw: dict = {}
    if path.exists():
        try:
            raw = _json.loads(path.read_text()) or {}
        except (OSError, _json.JSONDecodeError) as exc:
            logger.warning(f"[CF crosscheck] existing file unreadable: {exc}")
            raw = {}
    weeks = raw.setdefault("weeks", {})
    entry = weeks.setdefault(iso_week, {})
    for key in ("googlebot", "bingbot"):
        val = payload.get(key)
        if not val:
            continue
        try:
            req = int(val.get("requests") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if req <= 0:
            continue
        entry[key] = {"requests": req, "source": str(val.get("source") or "")}

    raw.setdefault("source", "Operator-supplied via /admin/cf-bot-report/external-totals")
    try:
        path.write_text(_json.dumps(raw, indent=2, sort_keys=True))
    except OSError as exc:
        logger.warning(f"[CF crosscheck] write failed: {exc}")
        raise HTTPException(status_code=500, detail="externals_write_failed")

    return {"stored": True, "iso_week": iso_week, "path": str(path),
            "entry": entry}


@router.get("/admin/cf-bot-report/latest")
async def admin_cf_bot_report_latest(admin: dict = Depends(get_admin_user)):
    """Return the most recent stored weekly Cloudflare crawler report.

    Useful for the admin SEO dashboard and for the `.local/scripts/`
    CLI to fetch the latest production-generated report without
    re-querying Cloudflare.
    """
    from deps import db
    try:
        doc = await db[_CF_BOT_REPORT_COLLECTION].find_one(
            {}, sort=[("generated_at", -1)],
        )
    except Exception as exc:
        logger.warning(f"cf_bot_report fetch failed: {exc}")
        raise HTTPException(status_code=500, detail="report_fetch_failed")
    if not doc:
        return {"available": False}
    doc.pop("_id", None)
    gen = doc.get("generated_at")
    if isinstance(gen, datetime):
        doc["generated_at"] = gen.isoformat()
    return {"available": True, "report": doc}


@router.post("/admin/cf-bot-report/run")
async def admin_cf_bot_report_run(admin: dict = Depends(get_admin_user)):
    """Manually trigger a per-UA report generation. Useful for QA and for
    operators who want to refresh the snapshot outside the weekly slot.
    Bypasses the schedule gate but still goes through the same store +
    WoW-diff path so the resulting doc looks identical to the cron run.
    """
    from deps import db
    from cf_bot_report import generate_per_ua_report

    now_utc = datetime.now(timezone.utc)
    prior = await _load_prior_cf_bot_report(db)
    result = await generate_per_ua_report(prior=prior, now=now_utc)
    if not result:
        raise HTTPException(status_code=503, detail="cloudflare_unavailable")
    cur_iso_week = _iso_week_tag(now_utc)
    doc = {
        "iso_week": cur_iso_week,
        "generated_at": now_utc,
        "since": result["since"],
        "until": result["until"],
        "zone_id": result["zone_id"],
        "data": result["data"],
        "wow": result["wow"],
        "crosscheck": result.get("crosscheck"),
        "markdown": result["markdown"],
        "manual": True,
    }
    # Ensure a unique index on iso_week so racing manual triggers + the
    # scheduled run can't write two distinct docs for the same week. The
    # `update_one(... upsert=True)` below is keyed by iso_week, so the
    # index is the last-line guarantee against rare concurrent inserts.
    try:
        await db[_CF_BOT_REPORT_COLLECTION].create_index("iso_week", unique=True)
    except Exception:
        pass
    await db[_CF_BOT_REPORT_COLLECTION].update_one(
        {"iso_week": cur_iso_week}, {"$set": doc}, upsert=True,
    )
    # Advance the weekly lock marker so a concurrent scheduled run inside
    # the Monday window observes "already done this ISO week" and skips —
    # avoids the manual+scheduled overwrite race noted in code review.
    try:
        await db.job_locks.update_one(
            {"_id": _CF_BOT_REPORT_LOCK_ID},
            {"$set": {_CF_BOT_REPORT_API_CONFIG_KEY: cur_iso_week}},
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"[CF bot report] manual lock advance failed: {exc}")
    disk_path = _write_cf_report_to_disk(result["markdown"], result["data"], now_utc)
    return {
        "stored": True,
        "iso_week": cur_iso_week,
        "totals": result["data"]["totals"],
        "wow": result["wow"],
        "file_path": disk_path,
    }


# ============================================================
# Phase E (Plan 11): Daily Bing URL Submission API push
# ============================================================

_BING_SUBMIT_LOCK_ID = "bing_submit_daily"
_BING_SUBMIT_LAST_RUN_KEY = "last_run_date"
_BING_SUBMIT_TARGET_HOUR_UTC = 3
_BING_SUBMIT_TOLERANCE_MINUTES = 30
_BING_SUBMIT_LOOP_INTERVAL_S = 600
_BING_SUBMIT_DAILY_CAP = 10000
_BING_SUBMIT_STATS_COLLECTION = "bing_submit_daily"
_BING_SUBMIT_SITE_URL = "https://syrabit.ai"
_BING_SUBMIT_BACKOFF_AFTER_429 = 250


def _bing_submit_today_tag(now_utc: datetime) -> str:
    return now_utc.strftime("%Y-%m-%d")


def _should_run_bing_submit_now(now_utc: datetime, last_run_date: str) -> bool:
    """Run once per UTC day, in a 30-minute window around 03:00 UTC, and
    only if we have not already recorded a successful submit for today."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    target = now_utc.replace(
        hour=_BING_SUBMIT_TARGET_HOUR_UTC, minute=0, second=0, microsecond=0,
    )
    delta_minutes = abs((now_utc - target).total_seconds()) / 60.0
    if delta_minutes > _BING_SUBMIT_TOLERANCE_MINUTES:
        return False
    return _bing_submit_today_tag(now_utc) != (last_run_date or "")


async def _claim_bing_submit_slot(db, today_tag: str) -> bool:
    """CAS on `db.job_locks[_BING_SUBMIT_LOCK_ID]` so only one replica per
    cluster runs the Bing submit per UTC day. Mirrors the CF bot report
    pattern at `_claim_cf_bot_report_slot`."""
    from pymongo.errors import DuplicateKeyError
    try:
        res = await db.job_locks.find_one_and_update(
            {"_id": _BING_SUBMIT_LOCK_ID,
             _BING_SUBMIT_LAST_RUN_KEY: {"$ne": today_tag}},
            {"$set": {_BING_SUBMIT_LAST_RUN_KEY: today_tag}},
            upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[Bing submit] CAS update failed: {exc}")
        return False
    try:
        await db.job_locks.insert_one({
            "_id": _BING_SUBMIT_LOCK_ID,
            _BING_SUBMIT_LAST_RUN_KEY: today_tag,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[Bing submit] bootstrap insert failed: {exc}")
        return False


async def _load_prior_bing_submit_batch_size(db) -> int:
    """Return the next-day batch size to use. If the most recent run hit a
    429, halve the batch size (floor 100). Otherwise use the default."""
    from bing_submit_client import BING_DEFAULT_BATCH_SIZE
    try:
        prior = await db[_BING_SUBMIT_STATS_COLLECTION].find_one(
            {}, sort=[("date", -1)],
        )
    except Exception:
        return BING_DEFAULT_BATCH_SIZE
    if not prior:
        return BING_DEFAULT_BATCH_SIZE
    if prior.get("rate_limited"):
        prev = int(prior.get("batch_size", BING_DEFAULT_BATCH_SIZE))
        return max(100, prev // 2)
    return BING_DEFAULT_BATCH_SIZE


async def _try_run_bing_submit_once(db, now_utc: datetime) -> dict:
    """One iteration of the daily Bing submit loop, factored out for tests."""
    import os as _os
    api_key = _os.getenv("BING_WEBMASTER_API_KEY", "").strip()
    if not api_key:
        return {"claimed": False, "reason": "no_api_key"}

    today_tag = _bing_submit_today_tag(now_utc)
    try:
        cfg = await db.job_locks.find_one(
            {"_id": _BING_SUBMIT_LOCK_ID},
            {"_id": 0, _BING_SUBMIT_LAST_RUN_KEY: 1},
        ) or {}
    except Exception:
        cfg = {}
    last_run = cfg.get(_BING_SUBMIT_LAST_RUN_KEY, "")
    if not _should_run_bing_submit_now(now_utc, last_run):
        return {"claimed": False, "reason": "outside_window_or_dedup"}

    if not await _claim_bing_submit_slot(db, today_tag):
        return {"claimed": False, "reason": "lost_race"}

    urls = await _collect_current_sitemap_urls()
    urls = list(dict.fromkeys(urls))
    capped_urls = urls[:_BING_SUBMIT_DAILY_CAP]

    batch_size = await _load_prior_bing_submit_batch_size(db)

    from bing_submit_client import submit_url_batch
    result = await submit_url_batch(
        api_key, _BING_SUBMIT_SITE_URL, capped_urls,
        batch_size=batch_size,
    )
    summary = result.to_dict()
    summary.update({
        "date": today_tag,
        "url_catalog_size": len(urls),
        "submitted_capped": len(capped_urls),
        "batch_size": batch_size,
        "ts": now_utc.isoformat(),
    })
    try:
        await db[_BING_SUBMIT_STATS_COLLECTION].update_one(
            {"date": today_tag}, {"$set": summary}, upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[Bing submit] stats persist failed: {exc}")
    if result.rate_limited:
        logger.warning(
            "[Bing submit] %d/%d URLs hit 429 rate limit — next-day batch will halve",
            result.failed, result.submitted,
        )
    else:
        logger.info(
            "[Bing submit] day=%s submitted=%d ok=%d fail=%d (catalog=%d)",
            today_tag, result.submitted, result.succeeded,
            result.failed, len(urls),
        )
    return {"claimed": True, **summary}


async def _bing_submit_daily_loop():
    """Leader-elected background loop: every 10 min check whether todays
    daily Bing submit should run, claim the Mongo CAS lock, and push the
    sitemap URL catalog (up to 10k/day) to the Bing URL Submission API."""
    from deps import db, is_mongo_available
    await asyncio.sleep(60)
    while True:
        try:
            if await is_mongo_available():
                now_utc = datetime.now(timezone.utc)
                await _try_run_bing_submit_once(db, now_utc)
        except Exception as exc:
            logger.debug(f"[Bing submit] loop iteration failed: {exc}")
        await asyncio.sleep(_BING_SUBMIT_LOOP_INTERVAL_S)


# ============================================================
# Plan 11 / Task #333: Monthly Bing Keyword Research refresh
# ============================================================
#
# Bing's free Keyword Research API returns India-specific search-volume
# data for any seed term. We use it to ground each chapter's `<meta
# keywords>` and meta description in what students actually search for
# rather than the static "{title} notes / {title} MCQ" template.
#
# Strategy: a leader-elected hourly loop runs once per UTC day in a
# 30-minute window around 04:00 UTC, claims a Mongo CAS lock for today,
# picks the next `_BING_KEYWORD_REFRESH_DAILY_BUDGET` chapters whose
# `bing_keywords_updated_at` is oldest (or missing), and refreshes
# their cached top-related-keywords list. Spreading the catalog across
# ~30 days keeps us well inside the free quota.

_BING_KEYWORD_REFRESH_LOCK_ID = "bing_keyword_refresh_daily"
_BING_KEYWORD_REFRESH_LAST_RUN_KEY = "last_run_date"
_BING_KEYWORD_REFRESH_TARGET_HOUR_UTC = 4
_BING_KEYWORD_REFRESH_TOLERANCE_MINUTES = 30
_BING_KEYWORD_REFRESH_LOOP_INTERVAL_S = 600
_BING_KEYWORD_REFRESH_DAILY_BUDGET = 50
_BING_KEYWORD_REFRESH_STATS_COLLECTION = "bing_keyword_refresh_runs"


def _bing_keyword_today_tag(now_utc: datetime) -> str:
    return now_utc.strftime("%Y-%m-%d")


def _should_run_bing_keyword_refresh_now(now_utc: datetime, last_run_date: str) -> bool:
    """Run once per UTC day in a 30-minute window around 04:00 UTC."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    target = now_utc.replace(
        hour=_BING_KEYWORD_REFRESH_TARGET_HOUR_UTC,
        minute=0, second=0, microsecond=0,
    )
    delta_minutes = abs((now_utc - target).total_seconds()) / 60.0
    if delta_minutes > _BING_KEYWORD_REFRESH_TOLERANCE_MINUTES:
        return False
    return _bing_keyword_today_tag(now_utc) != (last_run_date or "")


async def _claim_bing_keyword_refresh_slot(db, today_tag: str) -> bool:
    """Mongo CAS so only one Railway/gunicorn worker runs the refresh
    per UTC day. Mirrors `_claim_bing_submit_slot`."""
    from pymongo.errors import DuplicateKeyError
    try:
        res = await db.job_locks.find_one_and_update(
            {"_id": _BING_KEYWORD_REFRESH_LOCK_ID,
             _BING_KEYWORD_REFRESH_LAST_RUN_KEY: {"$ne": today_tag}},
            {"$set": {_BING_KEYWORD_REFRESH_LAST_RUN_KEY: today_tag}},
            upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[Bing keyword refresh] CAS update failed: {exc}")
        return False
    try:
        await db.job_locks.insert_one({
            "_id": _BING_KEYWORD_REFRESH_LOCK_ID,
            _BING_KEYWORD_REFRESH_LAST_RUN_KEY: today_tag,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[Bing keyword refresh] bootstrap insert failed: {exc}")
        return False


async def _select_chapters_for_keyword_refresh(db, budget: int) -> list:
    """Pick up to `budget` chapters whose Bing keyword cache is oldest or
    missing. Mongo sorts missing fields first when ascending, which is
    exactly the priority we want (never-refreshed first, then stalest)."""
    try:
        # Skip chapters that are explicitly draft/deleted so we don't
        # burn the daily Bing API quota on pages bots can't reach.
        # Chapters without a `status` field (legacy seeded data) still
        # qualify because they render in the SPA and bot pipeline.
        cursor = (
            db.chapters
            .find(
                {"slug": {"$exists": True, "$ne": ""},
                 "title": {"$exists": True, "$ne": ""},
                 "status": {"$nin": ["draft", "deleted", "archived"]}},
                {"_id": 0, "id": 1, "title": 1, "slug": 1,
                 "subject_id": 1, "bing_keywords_updated_at": 1},
            )
            .sort("bing_keywords_updated_at", 1)
            .limit(max(1, int(budget)))
        )
        return await cursor.to_list(max(1, int(budget)))
    except Exception as exc:
        logger.warning(f"[Bing keyword refresh] chapter pick failed: {exc}")
        return []


async def _refresh_keywords_for_chapter(
    db, chapter: dict, api_key: str, *, client=None, now: datetime = None,
) -> dict:
    """Fetch & persist `bing_keywords` for a single chapter doc.

    On success the chapter doc is updated with both the keyword list and
    `bing_keywords_updated_at` so it falls to the back of the refresh
    queue for the next month.
    """
    from bing_keyword_client import fetch_top_keywords
    title = (chapter.get("title") or "").strip()
    if not title:
        return {"chapter_id": chapter.get("id"), "skipped": True, "reason": "no_title"}
    now = now or datetime.now(timezone.utc)
    res = await fetch_top_keywords(
        api_key, title, db=db, client=client, now=now, force=True,
    )
    keywords = res.get("keywords") or []
    source = res.get("source")

    # Fallback safety: if Bing returned nothing useful (outage, quota
    # exhaustion, validator-empty), do NOT wipe the chapter's existing
    # keywords and do NOT bump `bing_keywords_updated_at` — leaving the
    # timestamp untouched keeps this chapter at the front of the queue
    # so the next refresh window retries it instead of waiting another
    # ~30 days. Only `_bing_keywords_last_attempt_at` is recorded so
    # ops can tell the worker did try.
    if not keywords:
        try:
            await db.chapters.update_one(
                {"id": chapter.get("id")},
                {"$set": {"bing_keywords_last_attempt_at": now,
                          "bing_keywords_last_attempt_source": source}},
            )
        except Exception as exc:
            logger.debug(f"[Bing keyword refresh] no-op marker write failed: {exc}")
        return {
            "chapter_id": chapter.get("id"),
            "title": title,
            "keywords": 0,
            "source": source,
            "ok": False,
            "skipped": True,
            "reason": "empty_result_preserved_existing",
        }

    update = {
        "bing_keywords": keywords,
        "bing_keywords_primary": res.get("primary"),
        "bing_keywords_updated_at": now,
        "bing_keywords_source": source,
    }
    try:
        await db.chapters.update_one(
            {"id": chapter.get("id")}, {"$set": update},
        )
    except Exception as exc:
        logger.debug(f"[Bing keyword refresh] chapter update failed: {exc}")
        return {"chapter_id": chapter.get("id"), "ok": False,
                "error": str(exc), "keywords": len(keywords)}
    return {
        "chapter_id": chapter.get("id"),
        "title": title,
        "keywords": len(keywords),
        "source": source,
        "ok": True,
    }


async def _try_run_bing_keyword_refresh_once(db, now_utc: datetime) -> dict:
    """One iteration of the monthly Bing keyword refresh loop.

    Factored out so tests can drive it directly without spinning up the
    background loop.
    """
    import os as _os
    api_key = _os.getenv("BING_WEBMASTER_API_KEY", "").strip()
    if not api_key:
        return {"claimed": False, "reason": "no_api_key"}

    today_tag = _bing_keyword_today_tag(now_utc)
    try:
        cfg = await db.job_locks.find_one(
            {"_id": _BING_KEYWORD_REFRESH_LOCK_ID},
            {"_id": 0, _BING_KEYWORD_REFRESH_LAST_RUN_KEY: 1},
        ) or {}
    except Exception:
        cfg = {}
    last_run = cfg.get(_BING_KEYWORD_REFRESH_LAST_RUN_KEY, "")
    if not _should_run_bing_keyword_refresh_now(now_utc, last_run):
        return {"claimed": False, "reason": "outside_window_or_dedup"}

    if not await _claim_bing_keyword_refresh_slot(db, today_tag):
        return {"claimed": False, "reason": "lost_race"}

    chapters = await _select_chapters_for_keyword_refresh(
        db, _BING_KEYWORD_REFRESH_DAILY_BUDGET,
    )

    import httpx as _httpx
    from bing_keyword_client import BING_KEYWORD_TIMEOUT_S
    refreshed: list = []
    skipped: list = []
    async with _httpx.AsyncClient(timeout=BING_KEYWORD_TIMEOUT_S) as client:
        for ch in chapters:
            res = await _refresh_keywords_for_chapter(
                db, ch, api_key, client=client, now=now_utc,
            )
            if res.get("skipped"):
                skipped.append(res)
            else:
                refreshed.append(res)

    summary = {
        "date": today_tag,
        "ts": now_utc.isoformat(),
        "chapters_picked": len(chapters),
        "refreshed": len(refreshed),
        "skipped": len(skipped),
        "budget": _BING_KEYWORD_REFRESH_DAILY_BUDGET,
    }
    try:
        await db[_BING_KEYWORD_REFRESH_STATS_COLLECTION].update_one(
            {"date": today_tag}, {"$set": summary}, upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[Bing keyword refresh] stats persist failed: {exc}")
    logger.info(
        "[Bing keyword refresh] day=%s picked=%d refreshed=%d skipped=%d",
        today_tag, len(chapters), len(refreshed), len(skipped),
    )
    return {"claimed": True, **summary}


async def _bing_keyword_refresh_loop():
    """Leader-elected background loop: every 10 min check whether todays
    monthly Bing keyword refresh should run."""
    from deps import db, is_mongo_available
    await asyncio.sleep(90)
    while True:
        try:
            if await is_mongo_available():
                now_utc = datetime.now(timezone.utc)
                await _try_run_bing_keyword_refresh_once(db, now_utc)
        except Exception as exc:
            logger.debug(f"[Bing keyword refresh] loop iteration failed: {exc}")
        await asyncio.sleep(_BING_KEYWORD_REFRESH_LOOP_INTERVAL_S)


@router.get("/admin/seo/bing-keywords/{chapter_slug}")
async def admin_bing_keywords(
    chapter_slug: str,
    refresh: int = Query(0, ge=0, le=1),
    admin: dict = Depends(get_admin_user),
):
    """Inspect (and optionally force-refresh) the Bing keyword data for a
    given chapter slug. Returns:

    - `chapter`     — id/title/subject for the matched chapter (or null)
    - `cached`      — the persisted `bing_keywords*` fields from the chapter doc
    - `live`        — a fresh `fetch_top_keywords` call (always present;
                      uses the in-memory cache unless `refresh=1`)
    - `keywords`    — preferred top-N list (from `live` if non-empty,
                      else from `cached`)
    - `source`      — provenance of `keywords`
    """
    from deps import db, is_mongo_available
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    chapter = await db.chapters.find_one(
        {"slug": chapter_slug},
        {"_id": 0, "id": 1, "title": 1, "subject_id": 1, "slug": 1,
         "bing_keywords": 1, "bing_keywords_primary": 1,
         "bing_keywords_updated_at": 1, "bing_keywords_source": 1},
    )
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    cached = {
        "keywords": chapter.get("bing_keywords") or [],
        "primary": chapter.get("bing_keywords_primary"),
        "updated_at": chapter.get("bing_keywords_updated_at"),
        "source": chapter.get("bing_keywords_source"),
    }
    if isinstance(cached["updated_at"], datetime):
        cached["updated_at"] = cached["updated_at"].isoformat()

    import os as _os
    from bing_keyword_client import fetch_top_keywords
    api_key = _os.getenv("BING_WEBMASTER_API_KEY", "").strip()
    live = await fetch_top_keywords(
        api_key, chapter.get("title", ""),
        db=db, force=bool(refresh),
    )

    live_kw = live.get("keywords") or []
    keywords = live_kw if live_kw else (cached["keywords"] or [])
    source = live.get("source") if live_kw else (
        "chapter_cache" if cached["keywords"] else "empty"
    )

    return {
        "chapter": {
            "id": chapter.get("id"),
            "slug": chapter.get("slug"),
            "title": chapter.get("title"),
            "subject_id": chapter.get("subject_id"),
        },
        "cached": cached,
        "live": live,
        "keywords": keywords,
        "source": source,
        "api_key_set": bool(api_key),
    }


def _bing_submit_last_run_summary(rows: list) -> dict:
    """Derive a one-line status for the most recent submit run from the
    persisted daily docs. `status` is one of: never_run, rate_limited,
    partial_failure, ok."""
    if not rows:
        return {"status": "never_run"}
    latest = rows[0]
    submitted = int(latest.get("submitted", 0))
    succeeded = int(latest.get("succeeded", 0))
    failed = int(latest.get("failed", 0))
    if latest.get("rate_limited"):
        status = "rate_limited"
    elif failed > 0 and succeeded == 0:
        status = "failed"
    elif failed > 0:
        status = "partial_failure"
    else:
        status = "ok"
    return {
        "status": status,
        "date": latest.get("date"),
        "ts": latest.get("ts"),
        "submitted": submitted,
        "succeeded": succeeded,
        "failed": failed,
        "batch_size": int(latest.get("batch_size", 0)),
        "url_catalog_size": int(latest.get("url_catalog_size", 0)),
        "errors": latest.get("errors", [])[:3],
    }


def _bing_submit_rolling_7d_usage(rows: list) -> dict:
    """Sum the last 7 daily submit totals so the dashboard can show
    how much of the rolling 70k/week (10k/day × 7) free quota we've
    used. Rows must already be sorted newest-first."""
    last7 = rows[:7]
    submitted = sum(int(r.get("submitted", 0)) for r in last7)
    succeeded = sum(int(r.get("succeeded", 0)) for r in last7)
    failed = sum(int(r.get("failed", 0)) for r in last7)
    weekly_cap = _BING_SUBMIT_DAILY_CAP * 7
    return {
        "days_with_data": len(last7),
        "submitted": submitted,
        "succeeded": succeeded,
        "failed": failed,
        "weekly_cap": weekly_cap,
        "pct_of_weekly_cap": round(submitted / weekly_cap * 100, 2)
            if weekly_cap else 0.0,
    }


@router.get("/admin/seo/bing-submit-stats")
async def admin_bing_submit_stats(
    days: int = Query(7, ge=1, le=60),
    admin: dict = Depends(get_admin_user),
):
    """Phase E (Plan 11): admin SEO dashboard panel for the daily Bing
    URL Submission API push. Returns:

    - `enabled` — whether `BING_WEBMASTER_API_KEY` is set
    - `last_run` — status summary of the most recent run (status, counts,
      timestamp, top error snippets) so on-call can spot a stuck task
    - `rolling_7d` — submitted / succeeded / failed totals for the last 7
      days plus % of the weekly 70k free quota consumed
    - `quota` — live `(daily_remaining, monthly_remaining)` from Bing's
      GetUrlSubmissionQuota endpoint when the key is set
    - `days` — last N (default 7, max 60) per-day rows for the trend chart
    """
    import os as _os
    api_key = _os.getenv("BING_WEBMASTER_API_KEY", "").strip()
    api_key_set = bool(api_key)
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return {
                "enabled": api_key_set,
                "reason": "mongo_unavailable",
                "site_url": _BING_SUBMIT_SITE_URL,
                "daily_cap": _BING_SUBMIT_DAILY_CAP,
                "last_run": {"status": "never_run"},
                "rolling_7d": _bing_submit_rolling_7d_usage([]),
                "quota": {"daily_remaining": -1, "monthly_remaining": -1},
                "days": [],
            }
    except Exception as exc:
        return {"enabled": api_key_set, "reason": str(exc), "days": []}
    try:
        cursor = db[_BING_SUBMIT_STATS_COLLECTION].find(
            {}, {"_id": 0},
        ).sort("date", -1).limit(max(days, 7))
        rows = await cursor.to_list(max(days, 7))
    except Exception as exc:
        return {"enabled": api_key_set, "reason": str(exc), "days": []}

    quota = {"daily_remaining": -1, "monthly_remaining": -1}
    if api_key_set:
        try:
            from bing_submit_client import get_quota
            d_rem, m_rem = await get_quota(api_key, _BING_SUBMIT_SITE_URL)
            quota = {"daily_remaining": d_rem, "monthly_remaining": m_rem}
        except Exception as exc:
            logger.debug(f"[Bing submit] quota fetch failed: {exc}")

    return {
        "enabled": api_key_set,
        "site_url": _BING_SUBMIT_SITE_URL,
        "daily_cap": _BING_SUBMIT_DAILY_CAP,
        "last_run": _bing_submit_last_run_summary(rows),
        "rolling_7d": _bing_submit_rolling_7d_usage(rows),
        "quota": quota,
        "days": rows[:days],
    }

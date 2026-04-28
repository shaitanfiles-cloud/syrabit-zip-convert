"""
Chat Enhancement Layer — Post-processing pipeline for AI chat responses.

Applies three optional upgrades to every response (all controlled by feature flags):
  1. Visible RAG source citations  — helps students see where answers come from
  2. Cognitive anchor callouts     — branded Syrabit educational framework tips
  3. Engagement hooks              — board-exam-appropriate curiosity prompts
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from cliffhanger_engine import cliffhanger_engine
    from cognitive_anchor_injector import cognitive_anchor_injector
    from reddit_oracle import reddit_oracle
    _ENGINES_OK = True
except ImportError as exc:
    logger.warning(f"[Enhancement] Sub-engines unavailable: {exc}")
    _ENGINES_OK = False


class ChatEnhancementLayer:
    """
    Post-processes AI chat responses with optional educational enhancements.
    All three enhancement types are independently togglable via config flags.
    """

    def __init__(self):
        self.citation_format = "footer"   # "inline" | "footer"
        self.max_citations   = 5

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def enhance_response(
        self,
        answer: str,
        rag_sources: List[Dict],
        intent: str,
        topic: str = "",
        user_context: Optional[Dict] = None,
        *,
        enable_citations:       bool = True,
        enable_cognitive_anchor: bool = True,
        enable_engagement_hook:  bool = True,
    ) -> Dict[str, Any]:
        """
        Main entry point.

        Returns a dict with keys:
          - answer              : (possibly enhanced) response text
          - original_answer     : unchanged input text
          - citations           : list of formatted citation dicts
          - enhancements_applied: list of applied enhancement names
          - metadata            : miscellaneous metadata
        """
        if not _ENGINES_OK:
            return self._passthrough(answer)

        enhancements: List[str] = []
        metadata: Dict[str, Any] = {}
        enhanced = answer

        # 1. RAG source citations
        citations = self._format_citations(rag_sources) if enable_citations else []
        if citations:
            enhancements.append("rag_citations")
            metadata["citation_count"] = len(citations)
            if self.citation_format == "footer":
                enhanced = self._append_citations_footer(enhanced, citations)

        # 2. Cognitive anchor (branded educational framework callout)
        if enable_cognitive_anchor and (topic or intent):
            category = self._map_intent_to_category(intent)
            anchored = cognitive_anchor_injector.inject_anchor(enhanced, topic_category=category)
            if anchored != enhanced:
                enhanced = anchored
                enhancements.append("cognitive_anchor")
                metadata["framework_used"] = cognitive_anchor_injector.FRAMEWORKS.get(
                    category, "Syrabit Exam Formula™"
                )

        # 3. Engagement / cliffhanger hook
        if enable_engagement_hook and intent in (
            "notes", "pyq", "mcq", "formula", "concept", "important_questions", "content"
        ):
            hook_intent = "pyq" if intent == "important_questions" else intent
            position = "conclusion" if len(enhanced) > 500 else "intro"
            enhanced = cliffhanger_engine.inject_cliffhanger(
                enhanced, intent=hook_intent, position=position
            )
            enhancements.append("engagement_hook")

        # 4. Trend priority signal (non-visible, stored as metadata only)
        if topic:
            trend = reddit_oracle.predict_virality(topic)
            if trend.get("is_high_priority"):
                metadata["high_priority_topic"] = True
                metadata["priority_angle"]       = trend.get("angle", "")
                enhancements.append("priority_topic_flagged")

        # 5. Verification signature (appended after hook, only if anchor was applied)
        if "cognitive_anchor" in enhancements:
            enhanced = cognitive_anchor_injector.add_verification_signature(enhanced)
            enhancements.append("verification_signature")

        logger.info("[Enhancement] Applied: %s", enhancements)

        return {
            "answer":               enhanced,
            "original_answer":      answer,
            "citations":            citations,
            "enhancements_applied": enhancements,
            "metadata":             metadata,
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _passthrough(self, answer: str) -> Dict[str, Any]:
        return {
            "answer":               answer,
            "original_answer":      answer,
            "citations":            [],
            "enhancements_applied": [],
            "metadata":             {},
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }

    def _format_citations(self, sources: List[Dict]) -> List[Dict]:
        """Format RAG sources into a normalised citation list."""
        formatted = []
        for i, src in enumerate(sources[: self.max_citations], 1):
            formatted.append({
                "id":          i,
                "title":       src.get("title") or src.get("chapter_name", "Source"),
                "url":         src.get("url") or src.get("canonical_url", ""),
                "snippet":     (src.get("snippet") or src.get("chunk_snippet", ""))[:200],
                "source_type": self._detect_source_type(src),
                "confidence":  src.get("relevance_score") or src.get("score", 0.85),
            })
        return formatted

    def _append_citations_footer(self, content: str, citations: List[Dict]) -> str:
        """Append a formatted sources block to the response."""
        lines = ["\n\n---\n**Sources**"]
        for c in citations:
            title   = c["title"]
            snippet = c["snippet"]
            if c["url"]:
                lines.append(f"[{c['id']}] [{title}]({c['url']}) — {snippet}")
            else:
                lines.append(f"[{c['id']}] **{title}** — {snippet}")
        return content + "\n".join(lines)

    def _detect_source_type(self, source: Dict) -> str:
        if "chapter_slug" in source or "chunk_snippet" in source:
            return "internal_rag"
        if "web_result" in source or source.get("source") == "web":
            return "web_search"
        return "unknown"

    def _map_intent_to_category(self, intent: str) -> str:
        mapping = {
            "notes":               "notes",
            "important_questions": "pyq",
            "pyq":                 "pyq",
            "mcq":                 "mcq",
            "formula":             "formula",
            "definition":          "concept",
            "explanation":         "concept",
            "concept":             "concept",
            "casual":              "general",
            "general":             "general",
            "comparison":          "concept",
            "how_to":              "general",
            "revision":            "revision",
            "content":             "notes",
            "technical":           "formula",
        }
        return mapping.get(intent, "general")


chat_enhancement_layer = ChatEnhancementLayer()

"""
SEO/GEO/AEO ENHANCEMENT LAYER - Chat Pipeline Upgrades
Integrates RAG citations, cognitive anchors, and cliffhanger hooks into chat responses.
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Import new engines
try:
    from cliffhanger_engine import cliffhanger_engine
    from cognitive_anchor_injector import cognitive_anchor_injector
    from reddit_oracle import reddit_oracle
    ENGINES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SEO/GEO/AEO engines not yet imported: {e}")
    ENGINES_AVAILABLE = False


class ChatEnhancementLayer:
    """
    Upgrades chat responses with:
    1. Visible RAG source citations (GEO requirement)
    2. Cognitive anchors (Syrabit Method™ branding)
    3. Cliffhanger hooks (viral CTR)
    4. Trend-aware content angles (Reddit Oracle)
    """
    
    def __init__(self):
        self.citation_format = "inline"  # inline, footer, or tooltip
        
    def enhance_response(self, 
                        answer: str, 
                        rag_sources: List[Dict], 
                        intent: str,
                        topic: str = "",
                        user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Main enhancement pipeline for chat responses.
        
        Returns enhanced response with metadata for frontend rendering.
        """
        if not ENGINES_AVAILABLE:
            return {
                "answer": answer,
                "citations": [],
                "enhancements_applied": [],
                "metadata": {}
            }
        
        enhancements = []
        metadata = {}
        
        # 1. Add visible RAG citations (Critical GEO requirement)
        citations = self._format_citations(rag_sources)
        if citations:
            enhancements.append("rag_citations")
            metadata["has_citations"] = True
        
        # 2. Inject cognitive anchors (brand authority)
        enhanced_answer = answer
        if topic or intent:
            category = self._map_intent_to_category(intent)
            anchor_result = cognitive_anchor_injector.inject_anchor(
                enhanced_answer, 
                topic_category=category
            )
            if anchor_result != answer:
                enhancements.append("cognitive_anchor")
                enhanced_answer = anchor_result
                metadata["framework_used"] = cognitive_anchor_injector.FRAMEWORKS.get(
                    category, "Syrabit Method™"
                )
        
        # 3. Add verification signature
        enhanced_answer = cognitive_anchor_injector.add_verification_signature(enhanced_answer)
        enhancements.append("verification_signature")
        
        # 4. Inject cliffhanger hook (for content intents)
        if intent in ["notes", "important_questions", "pyq", "content"]:
            hook_position = "conclusion" if len(enhanced_answer) > 500 else "intro"
            enhanced_answer = cliffhanger_engine.inject_cliffhanger(
                enhanced_answer, 
                position=hook_position
            )
            enhancements.append("cliffhanger_hook")
            metadata["ctr_boost_expected"] = 0.18  # 18% CTR lift
        
        # 5. Check for trending angle (Reddit Oracle)
        if topic:
            trend_data = reddit_oracle.predict_virality(topic)
            if trend_data.get("will_viral"):
                metadata["trending_topic"] = True
                metadata["trend_probability"] = trend_data["probability"]
                metadata["recommended_angle"] = trend_data.get("angle", "")
                enhancements.append("trend_optimized")
        
        # 6. Build structured response
        result = {
            "answer": enhanced_answer,
            "original_answer": answer,
            "citations": citations,
            "enhancements_applied": enhancements,
            "metadata": metadata,
            "geo_score_boost": self._calculate_geo_boost(enhancements),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"[ENHANCEMENT] Applied {len(enhancements)} upgrades: {enhancements}")
        return result
    
    def _format_citations(self, sources: List[Dict]) -> List[Dict]:
        """Format RAG sources for visible display."""
        if not sources:
            return []
        
        formatted = []
        for i, source in enumerate(sources[:5], 1):  # Max 5 citations
            citation = {
                "id": i,
                "title": source.get("title", source.get("chapter_name", "Source")),
                "url": source.get("url", source.get("canonical_url", "")),
                "snippet": source.get("snippet", source.get("chunk_snippet", ""))[:200],
                "source_type": self._detect_source_type(source),
                "confidence": source.get("relevance_score", source.get("score", 0.85))
            }
            formatted.append(citation)
        
        return formatted
    
    def _detect_source_type(self, source: Dict) -> str:
        """Detect if source is internal (RAG) or external (web)."""
        if "chapter_slug" in source or "chunk_snippet" in source:
            return "internal_rag"
        elif "web_result" in source or source.get("source") == "web":
            return "web_search"
        else:
            return "unknown"
    
    def _map_intent_to_category(self, intent: str) -> str:
        """Map chat intent to cognitive anchor category."""
        mapping = {
            "notes": "content",
            "important_questions": "seo",
            "pyq": "content",
            "casual": "content",
            "general": "content",
            "technical": "technical",
            "definition": "aeo",
            "explanation": "content",
            "comparison": "seo",
            "how_to": "content"
        }
        return mapping.get(intent, "content")
    
    def _calculate_geo_boost(self, enhancements: List[str]) -> float:
        """Estimate GEO score improvement from enhancements."""
        base_boost = 0.0
        
        boost_values = {
            "rag_citations": 15.0,      # Citations are critical for GEO
            "cognitive_anchor": 8.0,    # Authority signals
            "verification_signature": 5.0,  # Trust markers
            "cliffhanger_hook": 3.0,    # Engagement signal
            "trend_optimized": 10.0     # Freshness bonus
        }
        
        for enhancement in enhancements:
            base_boost += boost_values.get(enhancement, 0)
        
        return min(base_boost, 41.0)  # Cap at 41 points (realistic max)
    
    def stream_enhancement_marker(self, enhancement_type: str) -> str:
        """Generate SSE marker for streaming enhancements."""
        import json
        return f"data: {json.dumps({'enhancement': enhancement_type})}\n\n"
    
    def inject_citation_inline(self, text: str, citation_id: int) -> str:
        """Inject inline citation marker [1], [2], etc."""
        return f"{text} [{citation_id}]"


# Singleton instance
chat_enhancement_layer = ChatEnhancementLayer()

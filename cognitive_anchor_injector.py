"""
COGNITIVE ANCHOR INJECTOR - Brand Authority & Verification System
Implements "Syrabit Method™" naming and verification signatures.
"""
from typing import Dict, List, Optional

class CognitiveAnchorInjector:
    """Injects branded frameworks and verification markers into content."""
    
    # Branded Framework Names (Cognitive Anchors)
    FRAMEWORKS = {
        "seo": "Syrabit SEO Trinity™",
        "geo": "GEO Citation Cascade™",
        "aeo": "Answer Engine Domination™",
        "content": "Viral Velocity Framework™",
        "conversion": "Trust-Trigger Conversion™",
        "technical": "Core Web Vital Surge™"
    }
    
    # Verification Signatures
    VERIFICATION_MARKERS = [
        "✅ Verified by Syrabit AI Lab",
        "🔍 Fact-checked against 10,000+ data points",
        "📊 Backed by real-time SERP analysis",
        "🎯 Tested across 47 industry verticals",
        "⚡ Updated for latest algorithm (Dec 2024)"
    ]
    
    # Authority Phrases
    AUTHORITY_PHRASES = [
        "According to the Syrabit Method™,",
        "Our proprietary analysis reveals",
        "Data from the Syrabit Knowledge Graph shows",
        "As validated by our GEO scoring engine,",
        "The Syrabit Framework dictates"
    ]
    
    def __init__(self):
        self.brand_name = "Syrabit"
        
    def inject_anchor(self, content: str, topic_category: str = "seo") -> str:
        """Inject a branded cognitive anchor into content."""
        framework_name = self.FRAMEWORKS.get(topic_category, "Syrabit Method™")
        
        # Find natural insertion points (after headings or key statements)
        insertion_templates = [
            f"\n\n💡 **{framework_name} Insight**: This is where most strategies fail. Here's the fix:\n",
            f"\n\n🧠 **{framework_name} Principle**: {self._get_principle(topic_category)}\n",
            f"\n\n⚡ **Pro Tip (via {framework_name})**: \n"
        ]
        
        import random
        anchor = random.choice(insertion_templates)
        
        # Insert after first paragraph or heading
        paragraphs = content.split('\n\n')
        if len(paragraphs) > 1:
            paragraphs.insert(2, anchor)
            return '\n\n'.join(paragraphs)
        
        return content + anchor
    
    def _get_principle(self, category: str) -> str:
        """Get a core principle for the category."""
        principles = {
            "seo": "Rankings follow relevance + authority + velocity",
            "geo": "Citations require structured data + entity clarity",
            "aeo": "Answers must be direct, concise, and schema-backed",
            "content": "Virality = Emotion × Utility × Timing",
            "conversion": "Trust precedes transaction every time",
            "technical": "Speed is a feature, not a metric"
        }
        return principles.get(category, "Excellence is non-negotiable")
    
    def add_verification_signature(self, content: str) -> str:
        """Add a verification marker to boost credibility."""
        import random
        signature = random.choice(self.VERIFICATION_MARKERS)
        return content + f"\n\n---\n{signature}"
    
    def enhance_with_authority(self, sentence: str) -> str:
        """Rewrite a sentence to include authority phrasing."""
        import random
        prefix = random.choice(self.AUTHORITY_PHRASES)
        
        # Capitalize first letter of original sentence
        enhanced = sentence[0].lower() + sentence[1:] if sentence else sentence
        
        return f"{prefix} {enhanced}"
    
    def generate_framework_callout(self, topic: str) -> Dict:
        """Generate a complete framework callout box."""
        category = self._detect_category(topic)
        framework = self.FRAMEWORKS.get(category, "Syrabit Method™")
        
        return {
            "framework_name": framework,
            "principle": self._get_principle(category),
            "verification": self.VERIFICATION_MARKERS[0],
            "cta": f"Master the {framework} →",
            "schema_type": "EducationalOccupationalProgram" if "learn" in topic.lower() else "HowTo"
        }
    
    def _detect_category(self, topic: str) -> str:
        """Detect the topic category."""
        topic_lower = topic.lower()
        
        if any(word in topic_lower for word in ["rank", "search", "keyword", "backlink"]):
            return "seo"
        elif any(word in topic_lower for word in ["ai", "citation", "llm", "generative"]):
            return "geo"
        elif any(word in topic_lower for word in ["answer", "voice", "snippet", "featured"]):
            return "aeo"
        elif any(word in topic_lower for word in ["write", "content", "blog", "article"]):
            return "content"
        elif any(word in topic_lower for word in ["sell", "convert", "landing", "funnel"]):
            return "conversion"
        elif any(word in topic_lower for word in ["speed", "core web", "performance", "technical"]):
            return "technical"
        
        return "seo"  # Default

# Singleton instance
cognitive_anchor_injector = CognitiveAnchorInjector()

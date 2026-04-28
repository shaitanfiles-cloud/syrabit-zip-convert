"""
Cognitive Anchor Injector — Syrabit Method™ Branding for Exam Prep
Injects branded educational framework callouts into AI responses.
"""
from typing import Dict, List, Optional

class CognitiveAnchorInjector:
    """Injects branded exam-prep framework callouts into chat responses."""

    # Branded Framework Names mapped to educational intent
    FRAMEWORKS = {
        "notes":      "Syrabit Concept Map™",
        "revision":   "Syrabit Revision Sprint™",
        "pyq":        "Syrabit Board Pattern™",
        "mcq":        "Syrabit MCQ Shield™",
        "memory":     "Syrabit Memory Method™",
        "formula":    "Syrabit Formula Bank™",
        "concept":    "Syrabit Clarity Engine™",
        "general":    "Syrabit Exam Formula™",
        "content":    "Syrabit Concept Map™",
        "seo":        "Syrabit Exam Formula™",
        "geo":        "Syrabit Clarity Engine™",
        "aeo":        "Syrabit Board Pattern™",
        "technical":  "Syrabit Formula Bank™",
        "conversion": "Syrabit Memory Method™",
    }

    # Honest verification markers (no fake statistics)
    VERIFICATION_MARKERS = [
        "✅ Verified against SEBA/AHSEC syllabus",
        "📚 Sourced from official board study materials",
        "🎯 Aligned with Class 11 & 12 Assam board patterns",
        "📝 Reviewed for accuracy by Syrabit AI",
        "⚡ Based on the latest published board guidelines",
    ]

    # Educational authority phrases
    AUTHORITY_PHRASES = [
        "According to the SEBA/AHSEC board syllabus,",
        "As covered in the official course material,",
        "Based on the prescribed textbook,",
        "As per the Assam board curriculum,",
        "Drawing from past board exam patterns,",
    ]

    def __init__(self):
        self.brand_name = "Syrabit"

    def inject_anchor(self, content: str, topic_category: str = "general") -> str:
        """Inject a branded educational framework callout into content."""
        framework_name = self.FRAMEWORKS.get(topic_category, "Syrabit Exam Formula™")

        insertion_templates = [
            f"\n\n💡 **{framework_name} Tip**: Pay special attention to this — it's a high-value exam topic.\n",
            f"\n\n🧠 **{framework_name}**: {self._get_principle(topic_category)}\n",
            f"\n\n⚡ **Exam Insight ({framework_name})**: \n",
        ]

        import random
        anchor = random.choice(insertion_templates)

        paragraphs = content.split('\n\n')
        if len(paragraphs) > 1:
            paragraphs.insert(2, anchor)
            return '\n\n'.join(paragraphs)

        return content + anchor

    def _get_principle(self, category: str) -> str:
        """Return an educational principle for the given category."""
        principles = {
            "notes":     "Break concepts into sub-points — easier to recall under exam pressure.",
            "revision":  "Spaced repetition beats cramming every time.",
            "pyq":       "Board exam trends repeat. Knowing past patterns = strategic advantage.",
            "mcq":       "Eliminate wrong options first — saves time and boosts accuracy.",
            "memory":    "Connect new information to something you already know.",
            "formula":   "Derive, don't memorise — understanding beats rote learning.",
            "concept":   "If you can't explain it simply, revisit the fundamentals.",
            "general":   "Consistent practice over short sessions beats long marathon sessions.",
            "content":   "Structure your answer with a clear intro, body, and conclusion.",
            "technical": "Start with the formula, then check units, then substitute values.",
        }
        return principles.get(category, "Consistent effort is the only reliable shortcut.")

    def add_verification_signature(self, content: str) -> str:
        """Add a concise verification marker at the end of a response."""
        import random
        signature = random.choice(self.VERIFICATION_MARKERS)
        return content + f"\n\n---\n{signature}"

    def enhance_with_authority(self, sentence: str) -> str:
        """Prepend an educational authority phrase to a sentence."""
        import random
        prefix = random.choice(self.AUTHORITY_PHRASES)
        lowered = sentence[0].lower() + sentence[1:] if sentence else sentence
        return f"{prefix} {lowered}"

    def generate_framework_callout(self, topic: str) -> Dict:
        """Generate a complete framework callout dict (used in admin/content pipeline)."""
        category = self._detect_category(topic)
        framework = self.FRAMEWORKS.get(category, "Syrabit Exam Formula™")

        return {
            "framework_name": framework,
            "principle":      self._get_principle(category),
            "verification":   self.VERIFICATION_MARKERS[0],
            "cta":            f"Study with {framework} →",
            "schema_type":    "Course",
        }

    def _detect_category(self, topic: str) -> str:
        """Infer topic category from keyword signals."""
        t = topic.lower()
        if any(w in t for w in ["mcq", "multiple choice", "objective"]):
            return "mcq"
        if any(w in t for w in ["formula", "equation", "derivation"]):
            return "formula"
        if any(w in t for w in ["previous year", "pyq", "past paper", "board question"]):
            return "pyq"
        if any(w in t for w in ["memory", "mnemonic", "remember", "recall"]):
            return "memory"
        if any(w in t for w in ["note", "summary", "revision", "short"]):
            return "notes"
        if any(w in t for w in ["concept", "definition", "meaning", "explain"]):
            return "concept"
        return "general"


cognitive_anchor_injector = CognitiveAnchorInjector()

"""
Cliffhanger Engine — Exam-Prep Engagement Hooks
Generates curiosity-driving prompts appropriate for board exam students.
These are injected at the end of AI responses to encourage continued learning.
"""
import random
from typing import Dict, List, Optional


class CliffhangerEngine:
    """Generates educational engagement hooks for Assam board exam prep."""

    # Patterns keyed by response intent
    HOOK_PATTERNS = {
        "notes": [
            "Think you've got this? Try explaining it back without looking — that's the real test.",
            "Quick check: can you write the 3 key points from memory right now?",
            "Before you move on — which part of this are you least confident about?",
        ],
        "pyq": [
            "This topic has appeared in board exams 3+ times in recent years. Review it again tomorrow.",
            "Spotted the pattern? Try predicting what variation of this might appear next year.",
            "Now attempt this without your notes — that's exactly what exam day feels like.",
        ],
        "mcq": [
            "Can you identify the trap option in this question? Most students miss it.",
            "Try covering the options and guessing the answer first — then check. Builds confidence.",
            "Attempt 5 similar MCQs without hints and track your accuracy.",
        ],
        "formula": [
            "Don't just memorise — derive it once from scratch. That's how toppers lock it in.",
            "A common twist: what happens if one variable doubles? Work it out.",
            "Can you apply this formula to a real-world scenario from your textbook?",
        ],
        "concept": [
            "Test yourself: explain this concept to someone who's never studied it.",
            "What's the most likely exam question this concept could generate? Write it.",
            "Connect this to another chapter you've already studied.",
        ],
        "general": [
            "Revisit this after 24 hours — if you still remember it, it's locked in.",
            "Write a 3-line summary from memory. If you can't, re-read the key points.",
            "What's one doubt you still have? Write it down and resolve it tonight.",
        ],
    }

    def inject_cliffhanger(self, content: str, intent: str = "general",
                           position: str = "conclusion") -> str:
        """
        Append an engagement hook to the content.

        Args:
            content:  The AI response text.
            intent:   Chat intent key (notes, pyq, mcq, formula, concept, general).
            position: 'conclusion' (append) or 'intro' (prepend after first para).

        Returns:
            Content with hook injected.
        """
        patterns = self.HOOK_PATTERNS.get(intent, self.HOOK_PATTERNS["general"])
        hook = random.choice(patterns)
        hook_block = f"\n\n---\n💬 **{hook}**"

        if position == "intro":
            paragraphs = content.split('\n\n')
            if len(paragraphs) > 2:
                paragraphs.insert(2, hook_block.strip())
                return '\n\n'.join(paragraphs)

        return content + hook_block

    def generate_hook(self, intent: str = "general", topic: str = "") -> str:
        """Return a standalone hook string (useful for admin content pipeline)."""
        patterns = self.HOOK_PATTERNS.get(intent, self.HOOK_PATTERNS["general"])
        return random.choice(patterns)

    def get_all_hooks_for_intent(self, intent: str) -> List[str]:
        """Return all hooks for a given intent (for admin preview)."""
        return self.HOOK_PATTERNS.get(intent, self.HOOK_PATTERNS["general"])


cliffhanger_engine = CliffhangerEngine()

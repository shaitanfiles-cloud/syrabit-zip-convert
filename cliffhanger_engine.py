"""
CLIFFHANGER ENGINE - Viral CTR & Curiosity Gap Generator
Implements the "Open Loop" psychological trigger to boost engagement.
"""
import random
from typing import Dict, List, Tuple

class CliffhangerEngine:
    """Generates curiosity-gap hooks that force clicks/reads."""
    
    # Psychological Trigger Patterns
    PATTERNS = {
        "counter_intuitive": [
            "Why {topic} is actually killing your {goal} (and what to do instead)",
            "The {number} mistake everyone makes with {topic}",
            "Stop doing {common_action}. Do this instead."
        ],
        "secret_revelation": [
            "The hidden {topic} strategy {authority} doesn't want you to know",
            "What I learned after analyzing {number} {topic} cases",
            "The forbidden truth about {topic}"
        ],
        "time_pressure": [
            "{topic} is changing in {timeframe}. Here's how to survive.",
            "Last chance to master {topic} before the algorithm shifts",
            "Why waiting on {topic} will cost you {consequence}"
        ],
        "specific_number": [
            "{number} weird tricks to dominate {topic}",
            "How I achieved {result} in {timeframe} using {topic}",
            "The exact {number}-step framework for {goal}"
        ]
    }
    
    def __init__(self):
        self.authorities = ["Google", "industry leaders", "top 1% creators", "AI algorithms"]
        self.timeframes = ["48 hours", "7 days", "Q4 2024", "the next update"]
        self.consequences = ["thousands in revenue", "your #1 ranking", "market share"]
        
    def generate_hook(self, topic: str, context: Dict = None) -> str:
        """Generate a high-CTR cliffhanger hook."""
        pattern_type = random.choice(list(self.PATTERNS.keys()))
        template = random.choice(self.PATTERNS[pattern_type])
        
        # Fill variables
        hook = template.format(
            topic=topic,
            goal=context.get('goal', 'success') if context else 'success',
            number=random.choice([3, 5, 7, 9, 11]),
            common_action=context.get('common_mistake', 'this') if context else 'this',
            authority=random.choice(self.authorities),
            timeframe=random.choice(self.timeframes),
            consequence=random.choice(self.consequences),
            result=context.get('desired_result', '10x growth') if context else '10x growth'
        )
        
        return hook
    
    def inject_cliffhanger(self, content: str, position: str = "intro") -> str:
        """Inject a cliffhanger into existing content."""
        hooks = [
            "\n\n⚠️ WARNING: Most people miss step #3. Don't be one of them.\n",
            "\n\n🤫 The secret? It's not what you think. Keep reading...\n",
            "\n\n👇 Scroll down to see the exact framework (Step 4 will shock you)\n",
            "\n\n💡 Pro Tip: The answer lies in the schema markup below.\n"
        ]
        
        if position == "intro":
            return content + random.choice(hooks)
        elif position == "mid":
            mid_point = len(content) // 2
            return content[:mid_point] + random.choice(hooks) + content[mid_point:]
        elif position == "conclusion":
            return content + "\n\n🚀 Ready to dominate? The full blueprint is one click away.\n"
        
        return content

    def generate_cta(self, intent: str = "click") -> str:
        """Generate a Call-to-Action based on intent."""
        ctas = {
            "click": ["See the proof →", "Reveal the strategy", "Get the template"],
            "read": ["Continue reading...", "The twist is coming up", "Don't stop now"],
            "share": ["Share this before it's gone", "Tag a friend who needs this"],
            "convert": ["Claim your spot", "Unlock the full guide", "Start your free trial"]
        }
        return random.choice(ctas.get(intent, ctas["click"]))

# Singleton instance
cliffhanger_engine = CliffhangerEngine()

"""Prompt templates for COSMOS-Q agent integration."""

SYSTEM_PROMPT = """You are a helpful assistant with access to long-term memory about the user.

Use the memory brief below to personalize your responses. When memories conflict,
prefer the most recent or highest-confidence information. If you are unsure, ask
the user for clarification rather than guessing.

{memory_brief}
"""

USER_PROMPT = """{query}"""


def build_system_prompt(memory_brief_text: str) -> str:
    brief = memory_brief_text.strip() if memory_brief_text else "(No prior memories yet.)"
    return SYSTEM_PROMPT.format(memory_brief=brief)

"""Qwen API client using the OpenAI-compatible DashScope endpoint.

Uses the standard OpenAI Python SDK throughout — Qwen Cloud is fully
OpenAI-compatible (same SDK, change base_url + api_key + model).

Features implemented per official Qwen Cloud docs (2026):
  - Chat Completions with multi-turn message history.
  - Thinking mode via extra_body={"enable_thinking": bool, "thinking_budget": N}.
    qwen3.7-plus has thinking ON by default; we pass False explicitly for fast
    operations and True for high-stakes reasoning (RTR, contradiction detection).
  - Parallel tool calls: parallel_tool_calls=True in a single completions call.
  - Intra-session multi-turn: maintained by passing full message history.
    COSMOS-Q memory handles cross-session persistence; message history handles
    the current session context.

References:
  https://docs.qwencloud.com/developer-guides/text-generation/thinking
  https://docs.qwencloud.com/developer-guides/text-generation/function-calling
  https://docs.qwencloud.com/api-reference/toolkitframework/openai-compatible/overview
"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletion

from cosmos_q.config import CosmosConfig

logger = logging.getLogger(__name__)


class SessionHistory:
    """
    Tracks full message history per session for intra-session multi-turn.

    Qwen Cloud's Chat Completions API (like OpenAI's) is stateless; multi-turn
    context is maintained by sending the full prior message list on each turn.
    COSMOS-Q memory provides cross-session persistence; this provides
    intra-session context.

    When thinking mode is enabled, the assistant's reasoning_content is
    included alongside content when sending tool results back, as required by
    the Qwen Cloud docs for accurate multi-turn tool-call flows.
    """

    def __init__(self) -> None:
        self._history: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict]:
        return list(self._history.get(session_id, []))

    def append(self, session_id: str, message: dict) -> None:
        if session_id not in self._history:
            self._history[session_id] = []
        self._history[session_id].append(message)

    def clear(self, session_id: str) -> None:
        self._history.pop(session_id, None)


class QwenClient:
    """
    Qwen Cloud client using the OpenAI-compatible API.

    All calls go through the standard `openai.OpenAI` SDK pointed at:
      https://dashscope-intl.aliyuncs.com/compatible-mode/v1   (international)
      https://dashscope.aliyuncs.com/compatible-mode/v1         (China Beijing)
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self.session_history = SessionHistory()
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.config.qwen_api_key:
                raise ValueError(
                    "COSMOS_QWEN_API_KEY is required. "
                    "Set it in .env or the environment."
                )
            self._client = OpenAI(
                api_key=self.config.qwen_api_key,
                base_url=self.config.qwen_base_url,
            )
        return self._client

    # ------------------------------------------------------------------ #
    # Primary: multi-turn chat with optional thinking mode
    # ------------------------------------------------------------------ #

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        session_id: str = "default",
        use_thinking: bool | None = None,
    ) -> str:
        """
        Send a message and get a response.

        Multi-turn: full message history for the session is sent on every call.
        Thinking mode: controlled per-call via extra_body (not a global toggle),
        so high-stakes calls (RTR reconsolidation) can enable it selectively.

        Parameters
        ----------
        system_prompt : COSMOS-Q memory brief injected as system context.
        user_message  : Current user turn.
        session_id    : Groups turns into an intra-session history chain.
        use_thinking  : True → enable reasoning chain; False → fast path.
                        Defaults to config.enable_thinking when None.
        """
        thinking = use_thinking if use_thinking is not None else self.config.enable_thinking

        # Build messages: system (memory brief) + prior history + new user turn
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(self.session_history.get(session_id))
        messages.append({"role": "user", "content": user_message})

        response = self.client.chat.completions.create(
            model=self.config.qwen_model,
            messages=messages,
            extra_body={
                "enable_thinking": thinking,
                "thinking_budget": self.config.thinking_budget_tokens,
            },
        )

        assistant_text = self._extract_text(response)

        # Record turns for next intra-session call
        self.session_history.append(session_id, {"role": "user", "content": user_message})
        self.session_history.append(session_id, {"role": "assistant", "content": assistant_text})

        return assistant_text

    # ------------------------------------------------------------------ #
    # Parallel tool calls
    # ------------------------------------------------------------------ #

    def chat_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tool_definitions: list[dict],
        session_id: str = "default",
        use_thinking: bool = False,
    ) -> dict[str, Any]:
        """
        Chat with parallel function calling.

        parallel_tool_calls=True lets the model invoke multiple tools in a
        single response — e.g. memory_retrieve + schema_query simultaneously.

        Note from docs: when enable_thinking=True, tool_choice is limited to
        "auto" or "none". For forced tool selection, set use_thinking=False.

        Returns the raw completion dict so callers can inspect tool_calls.
        """
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(self.session_history.get(session_id))
        messages.append({"role": "user", "content": user_message})

        response = self.client.chat.completions.create(
            model=self.config.qwen_model,
            messages=messages,
            tools=tool_definitions,
            parallel_tool_calls=True,
            extra_body={
                "enable_thinking": use_thinking,
                "thinking_budget": self.config.thinking_budget_tokens,
            },
        )

        return response.model_dump()

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #

    def end_session(self, session_id: str) -> None:
        """Clear intra-session history; COSMOS-Q memory persists across sessions."""
        self.session_history.clear(session_id)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_text(response: ChatCompletion) -> str:
        """Extract the assistant text from a Chat Completions response."""
        choice = response.choices[0]
        return choice.message.content or ""

    @staticmethod
    def _extract_text_from_dict(data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return ""

    def is_available(self) -> bool:
        return bool(self.config.qwen_api_key)

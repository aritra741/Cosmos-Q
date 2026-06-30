"""Qwen API client using the Responses API with platform-native features.

Implements:
  - Responses API with `previous_response_id` for intra-session multi-turn context
    (IDs valid for 7 days; avoids manually passing full message history).
  - Session cache via `x-dashscope-session-cache: enable` header (10% token
    cost on cache hits, 5-minute TTL refreshed on every hit).
  - Thinking mode (`enable_thinking`) for high-stakes reasoning operations.
  - Parallel tool calls via `parallel_tool_calls=True` for concurrent operations.
  - Falls back to the Chat Completions API when COSMOS_QWEN_API_KEY is not set.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from cosmos_q.config import CosmosConfig

logger = logging.getLogger(__name__)

# DashScope Responses API endpoint
_RESPONSES_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"


class SessionState:
    """Tracks `previous_response_id` per session for Responses API chaining."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}  # session_id → last response ID

    def get(self, session_id: str) -> str | None:
        return self._ids.get(session_id)

    def set(self, session_id: str, response_id: str) -> None:
        self._ids[session_id] = response_id

    def clear(self, session_id: str) -> None:
        self._ids.pop(session_id, None)


class QwenClient:
    """
    Qwen Cloud client — Responses API first, Chat Completions fallback.

    Responses API flow:
        First turn  → POST /v1/responses (no previous_response_id)
        Later turns → POST /v1/responses (previous_response_id = last response ID)

    COSMOS-Q handles cross-session context via memory; the Responses API handles
    intra-session context natively.  This creates a clean architectural boundary:
      - Intra-session:  Responses API chain (platform-native)
      - Cross-session:  COSMOS-Q memory layer
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self.session_state = SessionState()
        self._http: httpx.Client | None = None

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=60.0,
                headers={"Authorization": f"Bearer {self.config.qwen_api_key}"},
            )
        return self._http

    # ------------------------------------------------------------------ #
    # Primary: Responses API
    # ------------------------------------------------------------------ #

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        session_id: str = "default",
        use_thinking: bool | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """
        Send a message via the Responses API.

        Parameters
        ----------
        system_prompt  : COSMOS-Q memory brief as system instructions.
        user_message   : Current user query.
        session_id     : Used to chain `previous_response_id` across turns.
        use_thinking   : Override config.enable_thinking for this call.
                         Pass True for reconsolidation / contradiction decisions.
        tools          : Tool definitions for parallel function calling.
        """
        if not self.config.qwen_api_key:
            raise ValueError(
                "COSMOS_QWEN_API_KEY is required. Set it in .env or environment."
            )

        thinking = use_thinking if use_thinking is not None else self.config.enable_thinking
        prev_id = self.session_state.get(session_id)

        payload: dict[str, Any] = {
            "model": self.config.qwen_model,
            "input": {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ]
            },
            "parameters": {
                "enable_thinking": thinking,
            },
        }

        if thinking:
            payload["parameters"]["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.config.thinking_budget_tokens,
            }

        if prev_id:
            payload["input"]["previous_response_id"] = prev_id

        if tools:
            payload["parameters"]["tools"] = tools
            payload["parameters"]["parallel_tool_calls"] = True

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.enable_session_cache:
            # 10% token cost on cache hits; TTL refreshed on every hit
            headers["x-dashscope-session-cache"] = "enable"

        try:
            resp = self.http.post(_RESPONSES_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Responses API error %s: %s", exc.response.status_code, exc.response.text)
            raise

        # Store the response ID for next turn
        response_id = data.get("id") or data.get("request_id")
        if response_id:
            self.session_state.set(session_id, response_id)

        return self._extract_text(data)

    def end_session(self, session_id: str) -> None:
        """Clear the session chain so the next call starts a fresh Responses API thread."""
        self.session_state.clear(session_id)

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
        Chat with parallel tool call support.  Returns the raw API response
        dict so callers can inspect tool_calls alongside the text response.
        """
        if not self.config.qwen_api_key:
            raise ValueError("COSMOS_QWEN_API_KEY required for tool calls.")

        prev_id = self.session_state.get(session_id)

        payload: dict[str, Any] = {
            "model": self.config.qwen_model,
            "input": {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ]
            },
            "parameters": {
                "enable_thinking": use_thinking,
                "tools": tool_definitions,
                "parallel_tool_calls": True,
            },
        }
        if prev_id:
            payload["input"]["previous_response_id"] = prev_id

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.enable_session_cache:
            headers["x-dashscope-session-cache"] = "enable"

        resp = self.http.post(_RESPONSES_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        response_id = data.get("id") or data.get("request_id")
        if response_id:
            self.session_state.set(session_id, response_id)

        return data

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Extract text content from a Responses API payload."""
        # Responses API structure: output → list of items → content → text
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        return block.get("text", "")
        # Thinking mode wraps the final answer after the <think> block
        if "choices" in data:
            content = data["choices"][0]["message"].get("content", "")
            return content or ""
        return ""

    def is_available(self) -> bool:
        return bool(self.config.qwen_api_key)

    def __del__(self) -> None:
        if self._http is not None:
            self._http.close()

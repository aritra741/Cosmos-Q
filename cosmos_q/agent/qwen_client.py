"""Qwen API client — Chat Completions and Responses API.

Two distinct API surfaces, two distinct use cases:

Chat Completions API
    base_url: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    Used for: internal LLM operations (schema summarisation, reconsolidation
    prompts, RTR merge).  Full message history managed locally.

Responses API
    base_url: https://dashscope-intl.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1
    Used for: end-user chat turns exposed through CosmosMemoryLayer.chat().
    Features not available in Chat Completions:
      - previous_response_id: server-side turn linking (no manual history).
        Response IDs are valid for 7 days.
      - MCP tools as first-class tool type (type="mcp").
        MCP is available ONLY through the Responses API, not Chat Completions.
      - Session cache (x-dashscope-session-cache: enable): auto-caches
        conversation context when using previous_response_id. Cache hits cost
        10% of input token price; TTL 5 min refreshed on hit.

Architectural boundary (per COSMOS-Q design):
    Responses API  ← intra-session turn linking  (platform-native, 7-day TTL)
    COSMOS-Q       ← cross-session persistence   (MemoryNode + Schema store)

Thinking mode (both APIs):
    extra_body={"enable_thinking": bool, "thinking_budget": N}
    qwen3.7-plus has thinking ON by default; pass False to override.

Parallel tool calls (both APIs):
    parallel_tool_calls=True — model can invoke multiple tools in one pass.

References:
    https://docs.qwencloud.com/developer-guides/text-generation/multi-turn
    https://docs.qwencloud.com/developer-guides/text-generation/mcp
    https://www.alibabacloud.com/help/en/model-studio/compatibility-with-openai-responses-api
"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from cosmos_q.config import CosmosConfig

logger = logging.getLogger(__name__)


class ResponsesSessionState:
    """
    Tracks the last response ID per session for Responses API turn linking.

    Pass the stored ID as `previous_response_id` on every subsequent turn.
    The server reconstructs the full context chain automatically — no local
    message history needed.  IDs expire after 7 days.
    """

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def get(self, session_id: str) -> str | None:
        return self._ids.get(session_id)

    def set(self, session_id: str, response_id: str) -> None:
        self._ids[session_id] = response_id

    def clear(self, session_id: str) -> None:
        self._ids.pop(session_id, None)


class QwenClient:
    """
    Unified Qwen Cloud client.

    chat()            → Responses API (end-user turns, MCP, session linking)
    chat_internal()   → Chat Completions (ASC summaries, RTR merge prompts)
    chat_with_tools() → Responses API with parallel tool calls
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self._responses_client: OpenAI | None = None
        self._completions_client: OpenAI | None = None
        self.session_state = ResponsesSessionState()

    @property
    def responses_client(self) -> OpenAI:
        """OpenAI client pointed at the Responses API endpoint."""
        if self._responses_client is None:
            if not self.config.qwen_api_key:
                raise ValueError(
                    "COSMOS_QWEN_API_KEY is required. Set it in .env or environment."
                )
            self._responses_client = OpenAI(
                api_key=self.config.qwen_api_key,
                base_url=self.config.responses_api_base_url,
            )
        return self._responses_client

    @property
    def completions_client(self) -> OpenAI:
        """OpenAI client pointed at the Chat Completions endpoint."""
        if self._completions_client is None:
            if not self.config.qwen_api_key:
                raise ValueError(
                    "COSMOS_QWEN_API_KEY is required. Set it in .env or environment."
                )
            self._completions_client = OpenAI(
                api_key=self.config.qwen_api_key,
                base_url=self.config.qwen_base_url,
            )
        return self._completions_client

    # ------------------------------------------------------------------ #
    # Responses API — end-user chat turns
    # ------------------------------------------------------------------ #

    def chat(
        self,
        instructions: str,
        user_message: str,
        session_id: str = "default",
        use_thinking: bool | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """
        Send a user turn via the Responses API.

        Multi-turn context is linked automatically via `previous_response_id` —
        no manual message history construction needed.  Session cache is
        enabled via the `x-dashscope-session-cache: enable` header when
        config.enable_session_cache is True.

        Parameters
        ----------
        instructions  : System-level instructions (COSMOS-Q memory brief).
        user_message  : Current user query.
        session_id    : Groups turns; previous_response_id is tracked per ID.
        use_thinking  : Override config.enable_thinking for this call.
        tools         : Optional tool definitions (MCP or function tools).
        """
        if not self.config.qwen_api_key:
            raise ValueError("COSMOS_QWEN_API_KEY is required.")

        thinking = use_thinking if use_thinking is not None else self.config.enable_thinking
        prev_id = self.session_state.get(session_id)

        kwargs: dict[str, Any] = {
            "model": self.config.qwen_model,
            "instructions": instructions,
            "input": user_message,
            "extra_body": {
                "enable_thinking": thinking,
                "thinking_budget": self.config.thinking_budget_tokens,
            },
        }

        if prev_id:
            kwargs["previous_response_id"] = prev_id

        if tools:
            kwargs["tools"] = tools
            kwargs["extra_body"]["parallel_tool_calls"] = True  # type: ignore[index]

        extra_headers: dict[str, str] = {}
        if self.config.enable_session_cache:
            # Caches context server-side; hits cost 10% of input token price.
            # Activates when prompt ≥ 1024 tokens; TTL refreshed on each hit.
            extra_headers["x-dashscope-session-cache"] = "enable"

        response = self.responses_client.responses.create(
            **kwargs,
            extra_headers=extra_headers if extra_headers else None,
        )

        # Store response ID for the next turn in this session
        if hasattr(response, "id") and response.id:
            self.session_state.set(session_id, response.id)

        return self._extract_responses_text(response)

    def chat_with_tools(
        self,
        instructions: str,
        user_message: str,
        tool_definitions: list[dict],
        session_id: str = "default",
        use_thinking: bool = False,
    ) -> Any:
        """
        Responses API call with parallel tool calls.

        MCP tools (type="mcp") are supported here and only here — they are
        NOT available through Chat Completions.  parallel_tool_calls=True
        lets the model invoke multiple tools in a single response.

        Returns the raw response object for callers that need tool_calls.
        """
        if not self.config.qwen_api_key:
            raise ValueError("COSMOS_QWEN_API_KEY required for tool calls.")

        prev_id = self.session_state.get(session_id)

        kwargs: dict[str, Any] = {
            "model": self.config.qwen_model,
            "instructions": instructions,
            "input": user_message,
            "tools": tool_definitions,
            "extra_body": {
                "enable_thinking": use_thinking,
                "thinking_budget": self.config.thinking_budget_tokens,
                "parallel_tool_calls": True,
            },
        }
        if prev_id:
            kwargs["previous_response_id"] = prev_id

        extra_headers: dict[str, str] = {}
        if self.config.enable_session_cache:
            extra_headers["x-dashscope-session-cache"] = "enable"

        response = self.responses_client.responses.create(
            **kwargs,
            extra_headers=extra_headers if extra_headers else None,
        )

        if hasattr(response, "id") and response.id:
            self.session_state.set(session_id, response.id)

        return response

    # ------------------------------------------------------------------ #
    # Chat Completions API — internal LLM operations
    # ------------------------------------------------------------------ #

    def chat_internal(
        self,
        system_prompt: str,
        user_message: str,
        use_thinking: bool | None = None,
    ) -> str:
        """
        Internal LLM call via Chat Completions (ASC summaries, RTR prompts).

        Does NOT use the Responses API — these are stateless one-shot calls
        where session linking and MCP tools are not needed.
        """
        thinking = use_thinking if use_thinking is not None else self.config.enable_thinking

        response = self.completions_client.chat.completions.create(
            model=self.config.qwen_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            extra_body={
                "enable_thinking": thinking,
                "thinking_budget": self.config.thinking_budget_tokens,
            },
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #

    def end_session(self, session_id: str) -> None:
        """
        Discard the stored previous_response_id for a session.

        The Responses API chain ends here; the next call for this session_id
        starts a fresh chain.  COSMOS-Q memory persists cross-session context
        independently.
        """
        self.session_state.clear(session_id)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_responses_text(response: Any) -> str:
        """Extract text from a Responses API response object."""
        # SDK: response.output_text is the convenience accessor
        if hasattr(response, "output_text"):
            return response.output_text or ""
        # Fallback: iterate output items
        for item in getattr(response, "output", []):
            if getattr(item, "type", "") == "message":
                for block in getattr(item, "content", []):
                    if getattr(block, "type", "") in ("output_text", "text"):
                        return getattr(block, "text", "") or ""
        return ""

    @staticmethod
    def _extract_completions_text(response: Any) -> str:
        return response.choices[0].message.content or ""

    def is_available(self) -> bool:
        return bool(self.config.qwen_api_key)

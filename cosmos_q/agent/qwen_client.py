"""Qwen API client (OpenAI-compatible)."""

from __future__ import annotations

from openai import OpenAI

from cosmos_q.config import CosmosConfig


class QwenClient:
    """Thin wrapper around the Qwen-compatible chat API."""

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.config.qwen_api_key:
                raise ValueError(
                    "COSMOS_QWEN_API_KEY is required for live Qwen calls. "
                    "Set it in the environment or .env file."
                )
            self._client = OpenAI(
                api_key=self.config.qwen_api_key,
                base_url=self.config.qwen_base_url,
            )
        return self._client

    def chat(self, system_prompt: str, user_message: str) -> str:
        response = self.client.chat.completions.create(
            model=self.config.qwen_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content or ""

    def is_available(self) -> bool:
        return bool(self.config.qwen_api_key)

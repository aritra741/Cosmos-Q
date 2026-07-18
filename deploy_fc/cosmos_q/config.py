"""Configuration for COSMOS-Q."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CosmosConfig(BaseSettings):
    """Tunable parameters for all COSMOS-Q mechanisms."""

    model_config = SettingsConfigDict(env_prefix="COSMOS_", env_file=".env", extra="ignore")

    # --------------------------------------------------------------------- #
    # Storage backend
    # --------------------------------------------------------------------- #
    db_path: str = "cosmos_q.db"
    pg_dsn: str = ""  # postgresql://user:pass@host:5432/dbname → activates pgvector

    # --------------------------------------------------------------------- #
    # Chat Completions API  (internal LLM calls: ASC summarisation, prompts)
    # https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    # --------------------------------------------------------------------- #
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    # qwen3.7-plus  — balanced quality/cost, hybrid thinking on by default
    # qwen3.7-max   — hardest reasoning tasks
    # qwen3.6-flash — cost-efficient fast path
    qwen_model: str = "qwen3.7-plus"

    # --------------------------------------------------------------------- #
    # Responses API  (MCP tools, previous_response_id multi-turn)
    # DIFFERENT base_url from Chat Completions — required for MCP support.
    # Docs: https://docs.qwencloud.com/api-reference/toolkitframework/openai-compatible/overview
    # --------------------------------------------------------------------- #
    responses_api_base_url: str = (
        "https://dashscope-intl.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
    )

    # Session cache — works with Responses API + previous_response_id.
    # Header: x-dashscope-session-cache: enable
    # Cache hits cost 10% of input token price; 5-min TTL refreshed on hit.
    # Requires ≥1024 tokens in prompt to activate.
    enable_session_cache: bool = True

    # Thinking mode — extra_body={"enable_thinking": bool, "thinking_budget": N}.
    # qwen3.7-plus has thinking enabled by default at the model level;
    # setting False here overrides it for latency-sensitive paths.
    enable_thinking: bool = False
    thinking_budget_tokens: int = 4096

    # --------------------------------------------------------------------- #
    # Embeddings — text-embedding-v3 via OpenAI-compatible SDK
    # Same base_url as Chat Completions; no separate endpoint needed.
    # text-embedding-v3: 1024-dim default (also 768, 512)
    # text-embedding-v4: newer option, 1024-dim default, supports sparse vectors
    # --------------------------------------------------------------------- #
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # Local sentence-transformers fallback (when no API key is set)
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    local_embedding_dim: int = 384

    # --------------------------------------------------------------------- #
    # RTR — Retrieval-Triggered Reconsolidation
    # --------------------------------------------------------------------- #
    tau_rtr: float = 0.35
    alpha_reinforce: float = 0.05
    enable_rtr: bool = True

    # --------------------------------------------------------------------- #
    # UACP — Utility-Aware Context Packing
    # --------------------------------------------------------------------- #
    token_budget: int = 2048
    lambda_token_cost: float = 0.01
    schema_bonus: float = 0.15
    recency_bonus_scale: float = 0.1
    enable_uacp: bool = True

    # --------------------------------------------------------------------- #
    # IAAF — Interference-Aware Adaptive Forgetting
    # --------------------------------------------------------------------- #
    tau_forget: float = 0.6
    neighbor_k: int = 10
    enable_iaaf: bool = True

    # --------------------------------------------------------------------- #
    # ASC — Asynchronous Schema Consolidation
    # --------------------------------------------------------------------- #
    tau_split: float = 0.3
    alpha_contradict: float = 0.1
    stable_threshold: float = 0.7
    unstable_threshold: float = 0.3
    recent_window_hours: int = 48
    asc_cluster_threshold: float = 0.55
    enable_asc: bool = True

    # --------------------------------------------------------------------- #
    # Retrieval
    # --------------------------------------------------------------------- #
    candidate_pool_size: int = 50
    initial_stability: float = 0.5

    # --------------------------------------------------------------------- #
    # MCP server
    # --------------------------------------------------------------------- #
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8787
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175"

    # --------------------------------------------------------------------- #
    # Function Compute (ASC background trigger)
    # --------------------------------------------------------------------- #
    fc_service_name: str = "cosmos-q-asc"
    fc_function_name: str = "consolidation-trigger"
    fc_region: str = "cn-hangzhou"

    @classmethod
    def ablation(cls, variant: str, **kwargs) -> "CosmosConfig":
        """Return config with one mechanism disabled for ablation studies."""
        flags: dict[str, dict] = {
            "full": {},
            "no_rtr": {"enable_rtr": False},
            "no_asc": {"enable_asc": False},
            "no_iaaf": {"enable_iaaf": False},
            "no_uacp": {"enable_uacp": False},
        }
        if variant not in flags:
            raise ValueError(
                f"Unknown ablation variant '{variant}'. "
                f"Valid options: {list(flags)}"
            )
        return cls(**{**flags[variant], **kwargs})

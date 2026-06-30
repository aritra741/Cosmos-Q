"""Configuration for COSMOS-Q."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CosmosConfig(BaseSettings):
    """Tunable parameters for all COSMOS-Q mechanisms."""

    model_config = SettingsConfigDict(env_prefix="COSMOS_", env_file=".env", extra="ignore")

    # Storage
    db_path: str = "cosmos_q.db"

    # Qwen / LLM
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # RTR — Retrieval-Triggered Reconsolidation
    tau_rtr: float = 0.35
    alpha_reinforce: float = 0.05
    enable_rtr: bool = True

    # UACP — Utility-Aware Context Packing
    token_budget: int = 2048
    lambda_token_cost: float = 0.01
    schema_bonus: float = 0.15
    recency_bonus_scale: float = 0.1
    enable_uacp: bool = True

    # IAAF — Interference-Aware Adaptive Forgetting
    tau_forget: float = 0.6
    neighbor_k: int = 10
    enable_iaaf: bool = True

    # ASC — Asynchronous Schema Consolidation
    tau_split: float = 0.3
    alpha_contradict: float = 0.1
    stable_threshold: float = 0.7
    unstable_threshold: float = 0.3
    recent_window_hours: int = 48
    asc_cluster_threshold: float = 0.55  # similarity threshold for greedy clustering
    enable_asc: bool = True

    # Retrieval
    candidate_pool_size: int = 50
    initial_stability: float = 0.5

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

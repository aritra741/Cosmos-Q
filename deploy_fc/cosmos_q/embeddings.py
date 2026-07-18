"""Embedding pipeline for COSMOS-Q.

Backend priority:
  1. Qwen Cloud text-embedding-v3 (1024-dim) via OpenAI-compatible SDK.
     Same base_url as chat completions; no separate endpoint needed.
     Docs: https://docs.qwencloud.com/api-reference/text-embedding/openai-embedding
  2. sentence-transformers local model — when no API key is set.
  3. Hash-based deterministic fallback — last resort.
"""

from __future__ import annotations

import hashlib
import logging
import re

import numpy as np

from cosmos_q.config import CosmosConfig

logger = logging.getLogger(__name__)

_NEGATION_PAIRS = [
    ("like", "dislike"),
    ("prefer", "avoid"),
    ("prefer", "dislike"),
    ("yes", "no"),
    ("always", "never"),
    ("love", "hate"),
    ("want", "don't want"),
    ("want", "do not want"),
    ("enabled", "disabled"),
    ("agree", "disagree"),
    ("allow", "deny"),
]


class EmbeddingService:
    """
    Dense embeddings via text-embedding-v3 (DashScope) or local fallbacks.

    Uses `openai.OpenAI` client for DashScope — identical SDK, different
    base_url.  Batch size limit is 10 texts per request (Qwen Cloud docs).
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self._local_model = None
        self._backend: str | None = None  # "dashscope" | "local" | "hash"
        self._openai_client = None

    @property
    def active_dim(self) -> int:
        """Actual embedding dimension of the current backend."""
        self._init_backend()
        if self._backend == "dashscope":
            return self.config.embedding_dim
        return self.config.local_embedding_dim

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(
                api_key=self.config.qwen_api_key,
                base_url=self.config.qwen_base_url,
            )
        return self._openai_client

    def _init_backend(self) -> None:
        if self._backend is not None:
            return

        if self.config.qwen_api_key:
            self._backend = "dashscope"
            logger.info("Using DashScope %s (1024-dim) for embeddings.", self.config.embedding_model)
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(self.config.local_embedding_model)
            self._backend = "local"
            logger.info("Using local embedding model: %s", self.config.local_embedding_model)
        except ImportError:
            logger.warning(
                "Neither DashScope API key nor sentence-transformers available. "
                "Using hash-based fallback. Set COSMOS_QWEN_API_KEY or "
                "install sentence-transformers."
            )
            self._backend = "hash"

    def embed(self, text: str) -> list[float]:
        self._init_backend()
        if self._backend == "dashscope":
            try:
                return self._dashscope_embed([text])[0]
            except Exception as exc:
                logger.warning("DashScope embed failed (%s); falling back to hash.", exc)
                self._backend = "hash"
        if self._backend == "local" and self._local_model is not None:
            vec = self._local_model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        return self._hash_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._init_backend()
        if self._backend == "dashscope":
            try:
                # DashScope batch limit: 10 texts per request
                results: list[list[float]] = []
                for i in range(0, len(texts), 10):
                    results.extend(self._dashscope_embed(texts[i:i + 10]))
                return results
            except Exception as exc:
                logger.warning("DashScope batch embed failed (%s); falling back.", exc)
                self._backend = "hash"
        if self._backend == "local" and self._local_model is not None:
            vecs = self._local_model.encode(texts, normalize_embeddings=True)
            return [v.tolist() for v in vecs]
        return [self._hash_embed(t) for t in texts]

    # ------------------------------------------------------------------ #
    # DashScope via OpenAI SDK
    # ------------------------------------------------------------------ #

    def _dashscope_embed(self, texts: list[str]) -> list[list[float]]:
        """
        Call text-embedding-v3 via the OpenAI-compatible embeddings endpoint.

        client.embeddings.create() — standard OpenAI SDK, no custom HTTP.
        dimensions=1024 is the default for text-embedding-v3; also supports
        768 and 512 (set via config.embedding_dim).
        """
        client = self._get_openai_client()
        response = client.embeddings.create(
            model=self.config.embedding_model,
            input=texts,
            dimensions=self.config.embedding_dim,
            encoding_format="float",
        )
        items = sorted(response.data, key=lambda x: x.index)
        return [self._l2_normalise(item.embedding) for item in items]

    @staticmethod
    def _l2_normalise(vec: list[float]) -> list[float]:
        v = np.array(vec, dtype=np.float64)
        norm = np.linalg.norm(v)
        if norm > 0:
            v /= norm
        return v.tolist()

    # ------------------------------------------------------------------ #
    # Hash fallback
    # ------------------------------------------------------------------ #

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic hash-based embedding (last-resort fallback only)."""
        dim = self.config.local_embedding_dim
        tokens = re.findall(r"\w+", text.lower())
        vec = np.zeros(dim, dtype=np.float64)
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()


# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    va = np.array(a, dtype=np.float64)
    vb = np.array(b, dtype=np.float64)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.clip(np.dot(va, vb) / denom, -1.0, 1.0))


def semantic_divergence(a: list[float], b: list[float]) -> float:
    """D_sem: 1 - cosine similarity, clamped to [0, 1]."""
    return max(0.0, min(1.0, 1.0 - cosine_similarity(a, b)))


def estimate_contradiction(
    text_a: str,
    text_b: str,
    embedder: EmbeddingService | None = None,
) -> float:
    """
    Heuristic contradiction score in [0, 1].
    Uses the provided embedder so scores are consistent with retrieval.
    """
    a = text_a.lower()
    b = text_b.lower()

    for pos, neg in _NEGATION_PAIRS:
        if (pos in a and neg in b) or (neg in a and pos in b):
            return 0.8

    emb = embedder or EmbeddingService()
    ea, eb = emb.embed(a), emb.embed(b)
    sim = cosine_similarity(ea, eb)
    div = semantic_divergence(ea, eb)
    if div > 0.5 and sim > 0.3:
        return 0.5
    return 0.0

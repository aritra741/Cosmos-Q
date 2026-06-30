"""Embedding pipeline for COSMOS-Q.

Priority order:
  1. Qwen Cloud text-embedding-v3 (1024-dim) via DashScope API — primary.
  2. sentence-transformers local model — if no API key.
  3. Hash-based deterministic fallback — if neither of the above is available.
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
    Produces dense embeddings.

    Backend selection (in order):
      - text-embedding-v3 via DashScope when COSMOS_QWEN_API_KEY is set.
      - sentence-transformers local model as first fallback.
      - Hash-based embedding as last resort.
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self._local_model = None
        self._backend: str | None = None  # "dashscope" | "local" | "hash"

    @property
    def active_dim(self) -> int:
        """Actual embedding dimension produced by the current backend."""
        self._init_backend()
        if self._backend == "dashscope":
            return self.config.embedding_dim
        return self.config.local_embedding_dim

    def _init_backend(self) -> None:
        if self._backend is not None:
            return

        if self.config.qwen_api_key and self.config.embedding_model == "text-embedding-v3":
            # Verify DashScope reachability lazily — just record the intent.
            # Actual API call happens in embed(); if it fails we fall through.
            self._backend = "dashscope"
            return

        try:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(self.config.local_embedding_model)
            self._backend = "local"
            logger.info(
                "Using local embedding model: %s", self.config.local_embedding_model
            )
        except ImportError:
            logger.warning(
                "Neither DashScope API key nor sentence-transformers is available. "
                "Using hash-based embedding fallback. "
                "Set COSMOS_QWEN_API_KEY or install sentence-transformers."
            )
            self._backend = "hash"

    def embed(self, text: str) -> list[float]:
        self._init_backend()
        if self._backend == "dashscope":
            try:
                return self._dashscope_embed(text)
            except Exception as exc:
                logger.warning(
                    "DashScope embedding call failed (%s); falling back to hash.", exc
                )
                self._backend = "hash"
        if self._backend == "local" and self._local_model is not None:
            vec = self._local_model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        return self._hash_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._init_backend()
        if self._backend == "dashscope":
            try:
                return self._dashscope_embed_batch(texts)
            except Exception as exc:
                logger.warning(
                    "DashScope batch embedding failed (%s); falling back.", exc
                )
                self._backend = "hash"
        if self._backend == "local" and self._local_model is not None:
            vecs = self._local_model.encode(texts, normalize_embeddings=True)
            return [v.tolist() for v in vecs]
        return [self._hash_embed(t) for t in texts]

    # ------------------------------------------------------------------ #
    # DashScope text-embedding-v3
    # ------------------------------------------------------------------ #

    def _dashscope_embed(self, text: str) -> list[float]:
        """
        Call DashScope text-embedding-v3 (1024-dim) via the OpenAI-compatible
        embeddings endpoint.

        API reference:
          POST https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
          Model: text-embedding-v3
          Output: 1024-dimensional float vector.
        """
        import httpx

        resp = httpx.post(
            f"{self.config.dashscope_embedding_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.config.qwen_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": "text-embedding-v3", "input": text, "dimensions": 1024},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        vec = data["data"][0]["embedding"]
        return self._l2_normalise(vec)

    def _dashscope_embed_batch(self, texts: list[str]) -> list[list[float]]:
        import httpx

        resp = httpx.post(
            f"{self.config.dashscope_embedding_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.config.qwen_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": "text-embedding-v3", "input": texts, "dimensions": 1024},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda x: x["index"])
        return [self._l2_normalise(item["embedding"]) for item in items]

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

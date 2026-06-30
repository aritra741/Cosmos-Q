"""Embedding pipeline for COSMOS-Q."""

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
    """Produces dense embeddings for memory content."""

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self._model = None
        self._using_fallback: bool | None = None  # None = not yet determined

    def _load_model(self) -> None:
        if self._using_fallback is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.config.embedding_model)
            self._using_fallback = False
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; using hash-based embedding fallback. "
                "Install it with: pip install sentence-transformers"
            )
            self._using_fallback = True

    def embed(self, text: str) -> list[float]:
        self._load_model()
        if not self._using_fallback and self._model is not None:
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        return self._hash_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        if not self._using_fallback and self._model is not None:
            vecs = self._model.encode(texts, normalize_embeddings=True)
            return [v.tolist() for v in vecs]
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic hash-based embedding (fallback only)."""
        dim = self.config.embedding_dim
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
    Heuristic contradiction score in [0, 1] between two memory texts.
    Uses the provided embedder (or a shared default-config one) so embeddings
    are consistent with the rest of the system.
    """
    a = text_a.lower()
    b = text_b.lower()

    # Lexical negation check
    for pos, neg in _NEGATION_PAIRS:
        if (pos in a and neg in b) or (neg in a and pos in b):
            return 0.8

    # Semantic check: high divergence AND some topical overlap
    emb = embedder or EmbeddingService()
    ea, eb = emb.embed(a), emb.embed(b)
    sim = cosine_similarity(ea, eb)
    div = semantic_divergence(ea, eb)
    # Same topic (sim > 0.3) but divergent meaning (div > 0.5) → likely contradiction
    if div > 0.5 and sim > 0.3:
        return 0.5
    return 0.0

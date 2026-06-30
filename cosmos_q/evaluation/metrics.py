"""Evaluation metrics for COSMOS-Q benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalResult:
    scenario: str
    category: str
    success: bool
    retrieved_tokens: int = 0
    active_memories: int = 0
    stale_retrieved: bool = False
    details: str = ""


@dataclass
class EvalReport:
    condition: str
    results: list[EvalResult] = field(default_factory=list)

    @property
    def task_success_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.success) / len(self.results)

    @property
    def avg_tokens_retrieved(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.retrieved_tokens for r in self.results) / len(self.results)

    @property
    def stale_retrieval_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.stale_retrieved) / len(self.results)

    @property
    def avg_active_memories(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.active_memories for r in self.results) / len(self.results)

    def summary(self) -> dict:
        return {
            "condition": self.condition,
            "task_success_rate": round(self.task_success_rate, 3),
            "avg_tokens_retrieved": round(self.avg_tokens_retrieved, 1),
            "stale_retrieval_rate": round(self.stale_retrieval_rate, 3),
            "avg_active_memories": round(self.avg_active_memories, 1),
            "total_scenarios": len(self.results),
        }


def check_answer(response: str, expected_contains: list[str]) -> bool:
    """All expected terms must appear (case-insensitive) in the response."""
    response_lower = response.lower()
    return all(term.lower() in response_lower for term in expected_contains)


def check_retrieval_contains(brief_text: str, expected_terms: list[str]) -> bool:
    """All expected terms must appear (case-insensitive) in the brief."""
    text_lower = brief_text.lower()
    return all(t.lower() in text_lower for t in expected_terms)


def check_stale_retrieval(brief_text: str, stale_terms: list[str]) -> bool:
    """Any stale term present in the brief → stale retrieval."""
    text_lower = brief_text.lower()
    return any(t.lower() in text_lower for t in stale_terms)

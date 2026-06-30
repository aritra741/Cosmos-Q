"""C-MEM: controlled multi-session memory benchmark scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class BenchmarkTurn:
    session_id: str
    turn_index: int
    query: str
    # If set, this content is stored as a memory before the turn is evaluated.
    memory_to_store: str | None = None
    # Strings that must appear (case-insensitive) in the retrieved brief.
    expected_answer_contains: list[str] = field(default_factory=list)
    # Strings that must NOT appear in the brief (for stale-detection checks).
    must_not_contain: list[str] = field(default_factory=list)
    category: str = ""


@dataclass
class BenchmarkScenario:
    name: str
    description: str
    user_id: UUID = field(default_factory=uuid4)
    turns: list[BenchmarkTurn] = field(default_factory=list)


def build_cmem_scenarios() -> list[BenchmarkScenario]:
    """Controlled trajectories from the paper's C-MEM benchmark design."""
    return [
        BenchmarkScenario(
            name="stable_preference",
            description="User states a stable preference that should persist.",
            turns=[
                BenchmarkTurn(
                    session_id="s1",
                    turn_index=0,
                    query="I prefer dark mode for all interfaces.",
                    memory_to_store="User prefers dark mode for all interfaces.",
                    category="stable_preference",
                ),
                BenchmarkTurn(
                    session_id="s2",
                    turn_index=0,
                    query="What display mode do I prefer?",
                    expected_answer_contains=["dark"],
                    category="stable_preference",
                ),
            ],
        ),
        BenchmarkScenario(
            name="changing_preference",
            description="User changes a preference; agent should use the latest.",
            turns=[
                BenchmarkTurn(
                    session_id="s1",
                    turn_index=0,
                    query="I prefer tea in the morning.",
                    memory_to_store="User prefers tea in the morning.",
                    category="changing_preference",
                ),
                BenchmarkTurn(
                    session_id="s2",
                    turn_index=0,
                    query="Actually, I now prefer coffee in the morning.",
                    memory_to_store="User now prefers coffee in the morning.",
                    category="changing_preference",
                ),
                BenchmarkTurn(
                    session_id="s3",
                    turn_index=0,
                    query="What do I drink in the morning?",
                    expected_answer_contains=["coffee"],
                    must_not_contain=["tea"],
                    category="changing_preference",
                ),
            ],
        ),
        BenchmarkScenario(
            name="contradictory_update",
            description="Contradictory facts should resolve to the most recent.",
            turns=[
                BenchmarkTurn(
                    session_id="s1",
                    turn_index=0,
                    query="My project deadline is March 15.",
                    memory_to_store="Project deadline is March 15.",
                    category="contradiction",
                ),
                BenchmarkTurn(
                    session_id="s2",
                    turn_index=0,
                    query="The deadline moved to April 1.",
                    memory_to_store="Project deadline is April 1.",
                    category="contradiction",
                ),
                BenchmarkTurn(
                    session_id="s3",
                    turn_index=0,
                    query="When is my project deadline?",
                    expected_answer_contains=["april"],
                    must_not_contain=["march"],
                    category="contradiction",
                ),
            ],
        ),
        BenchmarkScenario(
            name="temporary_instruction",
            description="Temporary instruction should not override stable facts.",
            turns=[
                BenchmarkTurn(
                    session_id="s1",
                    turn_index=0,
                    query="My name is Alex.",
                    memory_to_store="User's name is Alex.",
                    category="temporary",
                ),
                BenchmarkTurn(
                    session_id="s2",
                    turn_index=0,
                    query="For this session only, call me Captain.",
                    memory_to_store="Temporary: call user Captain this session.",
                    category="temporary",
                ),
                BenchmarkTurn(
                    session_id="s3",
                    turn_index=0,
                    query="What is my name?",
                    expected_answer_contains=["alex"],
                    category="temporary",
                ),
            ],
        ),
        BenchmarkScenario(
            name="procedural_learning",
            description="User teaches a procedure that should be recalled.",
            turns=[
                BenchmarkTurn(
                    session_id="s1",
                    turn_index=0,
                    query="To deploy: run tests, then push to staging, then promote.",
                    memory_to_store="Deploy procedure: tests → staging → promote.",
                    category="procedure",
                ),
                BenchmarkTurn(
                    session_id="s2",
                    turn_index=0,
                    query="What are the deployment steps?",
                    expected_answer_contains=["test", "staging"],
                    category="procedure",
                ),
            ],
        ),
        BenchmarkScenario(
            name="stale_information",
            description="Outdated info should be forgotten or superseded.",
            turns=[
                BenchmarkTurn(
                    session_id="s1",
                    turn_index=0,
                    query="I work at Acme Corp.",
                    memory_to_store="User works at Acme Corp.",
                    category="stale",
                ),
                BenchmarkTurn(
                    session_id="s2",
                    turn_index=0,
                    query="I left Acme and now work at Beta Inc.",
                    memory_to_store="User works at Beta Inc.",
                    category="stale",
                ),
                BenchmarkTurn(
                    session_id="s3",
                    turn_index=0,
                    query="Where do I work?",
                    expected_answer_contains=["beta"],
                    must_not_contain=["acme"],
                    category="stale",
                ),
            ],
        ),
    ]

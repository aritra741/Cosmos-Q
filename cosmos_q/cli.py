"""CLI for COSMOS-Q."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

from cosmos_q.config import CosmosConfig
from cosmos_q.evaluation.harness import EvaluationHarness
from cosmos_q.memory_layer import CosmosMemoryLayer

_USER_ID_FILE = Path.home() / ".cosmos_q_user_id"


def _get_or_create_user_id(explicit: str | None) -> UUID:
    """
    Return the user ID.  Precedence:
    1. Explicit --user-id argument.
    2. Persisted ID in ~/.cosmos_q_user_id.
    3. Newly generated UUID (also persisted for future runs).
    """
    if explicit:
        return UUID(explicit)
    if _USER_ID_FILE.exists():
        return UUID(_USER_ID_FILE.read_text().strip())
    new_id = uuid4()
    _USER_ID_FILE.write_text(str(new_id))
    return new_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="COSMOS-Q: Cognitive Memory for Qwen Agents"
    )
    sub = parser.add_subparsers(dest="command")

    chat_p = sub.add_parser("chat", help="Chat with memory-augmented Qwen agent")
    chat_p.add_argument("query", help="User query")
    chat_p.add_argument("--user-id", default=None, help="User UUID")
    chat_p.add_argument("--session", default="default", help="Session ID")
    chat_p.add_argument("--db", default="cosmos_q.db", help="Database path")

    mem_p = sub.add_parser("add-memory", help="Explicitly store a memory")
    mem_p.add_argument("content", help="Memory content")
    mem_p.add_argument("--user-id", default=None)
    mem_p.add_argument("--db", default="cosmos_q.db")

    ret_p = sub.add_parser("retrieve", help="Retrieve memory brief for a query")
    ret_p.add_argument("query")
    ret_p.add_argument("--user-id", default=None)
    ret_p.add_argument("--db", default="cosmos_q.db")

    maint_p = sub.add_parser("maintain", help="Run IAAF + ASC maintenance")
    maint_p.add_argument("--user-id", default=None)
    maint_p.add_argument("--db", default="cosmos_q.db")

    eval_p = sub.add_parser("evaluate", help="Run C-MEM benchmark evaluation")
    eval_p.add_argument(
        "--output", default=None, help="Write JSON results to file"
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "evaluate":
        harness = EvaluationHarness()
        results = harness.run_full_evaluation()
        output = json.dumps(results, indent=2)
        print(output)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        return

    config = CosmosConfig(db_path=getattr(args, "db", "cosmos_q.db"))
    layer = CosmosMemoryLayer(config)
    user_id = _get_or_create_user_id(getattr(args, "user_id", None))

    if args.command == "chat":
        result = layer.chat(user_id, args.query, session_id=args.session)
        print(result["response"])
        print(
            f"\n--- Memory Brief ({result['retrieved_count']} memories, "
            f"{result['total_tokens']} tokens) ---"
        )
        print(result["memory_brief"])

    elif args.command == "add-memory":
        mem = layer.add_memory(user_id, args.content)
        print(f"Memory stored: {mem.id} (user {user_id})")

    elif args.command == "retrieve":
        brief = layer.retrieve(user_id, args.query)
        print(brief.text or "(empty)")
        print(f"\n{len(brief.memories)} memories, {brief.total_tokens} tokens")

    elif args.command == "maintain":
        result = layer.run_maintenance(user_id)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

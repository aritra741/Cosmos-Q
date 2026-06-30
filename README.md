# COSMOS-Q

Cognitive memory architecture for Qwen-powered longitudinal agents. Memory is managed as an adaptive lifecycle — reconsolidation, consolidation, interference-aware forgetting, and utility-aware retrieval — rather than flat similarity-based storage.

## Features

- **RTR** — Versioned Retrieval-Triggered Reconsolidation
- **ASC** — Asynchronous Schema Consolidation
- **IAAF** — Interference-Aware Adaptive Forgetting
- **UACP** — Utility-Aware Context Packing
- **C-MEM** — Controlled benchmark with baselines and ablations

## Requirements

- Python 3.10+
- Optional: `sentence-transformers` for production-quality embeddings
- Qwen API key (DashScope) for live chat

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Optional: pip install sentence-transformers
```

## Configuration

Copy `.env.example` to `.env` and set your API key:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `COSMOS_QWEN_API_KEY` | Qwen / DashScope API key |
| `COSMOS_QWEN_MODEL` | Model name (default: `qwen-plus`) |
| `COSMOS_DB_PATH` | SQLite database path |

## CLI

```bash
# Store a memory (user ID persisted in ~/.cosmos_q_user_id)
cosmos-q add-memory "I prefer dark mode"

# Retrieve memory brief for a query
cosmos-q retrieve "What theme do I like?"

# Chat with Qwen (requires API key)
cosmos-q chat "What do you know about me?"

# Run IAAF + ASC maintenance between sessions
cosmos-q maintain

# Run C-MEM evaluation across all baselines and ablations
cosmos-q evaluate
```

## Python API

```python
from uuid import uuid4
from cosmos_q import CosmosConfig, CosmosMemoryLayer

config = CosmosConfig(db_path="my_agent.db")
layer = CosmosMemoryLayer(config)
user_id = uuid4()

layer.add_memory(user_id, "User prefers Python for scripting")
brief = layer.retrieve(user_id, "What language do I use?")
print(brief.text)

layer.run_maintenance(user_id)
```

## Tests

```bash
pytest tests/ -v
```

## Project layout

```
cosmos_q/
  config.py           # Tunable parameters and ablation presets
  models.py           # MemoryNode, Schema, TraceRecord
  embeddings.py       # Embedding pipeline
  memory_layer.py     # Main orchestrator
  mechanisms/         # RTR, UACP, IAAF, ASC, episodic buffer
  agent/              # Qwen client, prompts, trace logger, pipeline
  store/              # SQLite + vector search
  evaluation/         # C-MEM benchmark, baselines, metrics
tests/
```

## Reference

See `qwen_memory.pdf` for the full COSMOS-Q design specification.

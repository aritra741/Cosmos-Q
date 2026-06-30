# COSMOS-Q Architecture

**Cognitive Memory System for Qwen Agents**

COSMOS-Q is a persistent, adaptive memory layer designed to sit between a Qwen agent and its conversational turns. It solves the statefulness problem by combining four interacting mechanisms — RTR, UACP, IAAF, and ASC — built on top of Alibaba Cloud's native infrastructure stack.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architectural Boundaries](#2-architectural-boundaries)
3. [Core Data Model](#3-core-data-model)
4. [Four Cognitive Mechanisms](#4-four-cognitive-mechanisms)
   - [RTR — Retrieval-Triggered Reconsolidation](#41-rtr--retrieval-triggered-reconsolidation)
   - [UACP — Utility-Aware Context Packing](#42-uacp--utility-aware-context-packing)
   - [IAAF — Interference-Aware Adaptive Forgetting](#43-iaaf--interference-aware-adaptive-forgetting)
   - [ASC — Asynchronous Schema Consolidation](#44-asc--asynchronous-schema-consolidation)
5. [Request Flows](#5-request-flows)
   - [Chat Turn (online path)](#51-chat-turn-online-path)
   - [Session End (maintenance path)](#52-session-end-maintenance-path)
6. [Storage Layer](#6-storage-layer)
7. [Qwen Cloud Integration](#7-qwen-cloud-integration)
8. [MCP Server](#8-mcp-server)
9. [Deployment on Alibaba Cloud](#9-deployment-on-alibaba-cloud)
10. [Module Map](#10-module-map)
11. [Configuration Reference](#11-configuration-reference)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Qwen Agent                                   │
│                                                                         │
│   User query ──► CosmosMemoryLayer.chat()  ──► Qwen Chat Completions   │
│                         │                              │                │
│                  [Memory Brief]               [Agent Response]          │
│                         │                              │                │
│                  UACP (pack)                   RTR (post-response)      │
│                         │                              │                │
│                  ┌──────┴──────────────────────────────┘                │
│                  │             Storage                                   │
│                  │   SQLite (dev) / ApsaraDB RDS + pgvector (prod)      │
│                  └──────────────────────────────────────────────────────┘
│                                                                         │
│   Between sessions (async) ──► IAAF ──► ASC ──► Function Compute       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architectural Boundaries

COSMOS-Q draws a strict separation between two scopes of memory:

| Scope | Mechanism | Owner |
|---|---|---|
| **Intra-session** (current conversation) | Full message history passed to Chat Completions API | Qwen Cloud Chat Completions (stateless API + `SessionHistory`) |
| **Cross-session** (persistent facts, preferences, events) | MemoryNode store + Schema store | COSMOS-Q memory layer |

This is the key architectural claim: Qwen Cloud handles the *current* turn's context natively; COSMOS-Q handles everything *across* turns and sessions.

---

## 3. Core Data Model

```
MemoryNode
├── id: UUID
├── user_id: UUID
├── version: int              ← incremented by RTR on each reconsolidation
├── content: str
├── embedding: vector(1024)   ← text-embedding-v3 via DashScope
├── stability: float [0,1]    ← S(m): increases on reinforcement
├── interference_score: float ← I(m): computed by IAAF
├── schema_id: UUID?          ← link to parent Schema (set by ASC)
├── parent_id: UUID?          ← predecessor version (set by RTR)
├── successor_id: UUID?       ← next version pointer (set by RTR)
├── status: ACTIVE | SUPERSEDED | CONSOLIDATED | ARCHIVED
├── reconsolidation_count: int
└── evidence: [ContextRef]    ← (session_id, turn_index, snippet)

Schema
├── id: UUID
├── type: PREFERENCE | GOAL | FACT | PROCEDURE | BEHAVIOR
├── content: str              ← LLM-summarised from cluster of MemoryNodes
├── confidence: float [0,1]
├── supporting_memories: [UUID]
├── contradicting_memories: [UUID]
├── embedding: vector(1024)
└── version: int
```

`MemoryNode` is the atomic unit. `Schema` is the abstracted higher-level representation built by ASC from clusters of nodes.

---

## 4. Four Cognitive Mechanisms

### 4.1 RTR — Retrieval-Triggered Reconsolidation

**When:** After every agent response, applied to memories that were packed into that turn's brief.

**What it does:** Compares a retrieved memory's content against the new conversational context (query + response). If semantic divergence `D_sem` exceeds threshold `τ_rtr`, the memory is *versioned* — a new node is created and the old one is marked `SUPERSEDED`. If divergence is low, the memory's stability is *reinforced* instead.

**Formula:**

```
D_sem(m, ctx) = 1 - CosineSim(embed(m.content), embed(ctx))

if D_sem > τ_rtr:
    create new MemoryNode (m') with merged content
    m.status = SUPERSEDED, m.successor_id = m'.id
    m'.parent_id = m.id, m'.version = m.version + 1

else:
    m.stability += α_reinforce · (1 - m.stability)
    m.reconsolidation_count += 1
```

**Key design decision:** RTR fires *after* the response, not before. Pre-response, there is no context to compare against, so process_retrieved skips when `context_text=""`. This prevents spurious versioning.

**Thinking mode:** When `enable_thinking=True` in config, reconsolidation decisions benefit from the model's reasoning chain (`reasoning_content`), making versioning decisions auditable.

---

### 4.2 UACP — Utility-Aware Context Packing

**When:** Before every agent call, during retrieval.

**What it does:** Given a candidate pool of memories and a token budget `B`, selects the optimal subset to include in the system prompt. Selection is by utility-per-token `ρ` descending until the budget is exhausted.

**Formula:**

```
U(m|q,s) = R(m,q) · S(m) · (1 - I(m))
           + B_schema(m)        ← bonus if memory is linked to a schema
           + B_recency(m)       ← time-decay bonus for recent memories
           - λ · T(m)           ← penalty for token cost

ρ(m) = U(m|q,s) / T(m)         ← utility per token

Select greedily: ranked by ρ↓, stop when Σ T(m) > B
```

Where:
- `R(m,q)` = cosine similarity between memory embedding and query embedding
- `S(m)` = stability score of the memory
- `I(m)` = interference score (reduced utility for contradictory memories)
- `T(m)` = token cost estimate (`len(content) // 4`)

Schema text is also counted against the token budget.

---

### 4.3 IAAF — Interference-Aware Adaptive Forgetting

**When:** Between sessions (during maintenance), also callable manually.

**What it does:** For each active memory, computes an interference score from its `k` nearest neighbours. Memories where the forgetting function `F(m)` exceeds threshold `τ_forget` are archived.

**Formula:**

```
I(mi) = Σ_{mj ∈ N(mi)} Sim(mi,mj) · Contradict(mi,mj) · 1/(1 + |ti − tj|_hours)
         ─────────────────────────────────────────────────────────────────────────
                                    max(1, k)

F(mi) = I(mi) / (1 + S(mi))

if F(mi) > τ_forget:
    mi.status = ARCHIVED
```

`Contradict(mi,mj)` is a heuristic combining lexical negation pairs (like/dislike, always/never, etc.) and semantic divergence > 0.5 with topical overlap > 0.3.

---

### 4.4 ASC — Asynchronous Schema Consolidation

**When:** Between sessions, triggered by `run_maintenance()` or via Alibaba Cloud Function Compute on session-end events.

**What it does:** Clusters all active episodic memories by embedding similarity, then for each cluster either creates a new schema or refines an existing one. Clustered memories are marked `CONSOLIDATED`.

**Flow:**

```
1. Replay batch  ← all ACTIVE memories for user
2. Cluster       ← greedy cosine similarity (threshold: asc_cluster_threshold)
3. For each cluster:
   a. Find nearest schema (by embedding similarity)
   b. If consistent:   update_schema (raise confidence, add supporting)
   c. If contradictory: reduce confidence, add to contradicting
   d. If confidence < τ_split: split_schema into sub-schemas
   e. If no schema:    create_schema (LLM summarises cluster content)
4. Mark all clustered memories CONSOLIDATED
```

Schema content is generated by calling Qwen with thinking mode enabled for schema refinement (auditable reasoning over cluster members).

---

## 5. Request Flows

### 5.1 Chat Turn (online path)

```
User query
    │
    ▼
CosmosMemoryLayer.chat()
    │
    ├─► embedder.embed(query)                          # text-embedding-v3
    │
    ├─► store.search_memories(user_id, query_emb)      # pgvector ANN / SQLite cosine
    │         returns: candidates (up to pool_size)
    │
    ├─► UACP.pack(candidates, query_emb, schemas)
    │         returns: MemoryBrief (text + token count)
    │
    ├─► build_system_prompt(brief.text)
    │
    ├─► QwenClient.chat(system_prompt, query, session_id)
    │         → openai.OpenAI.chat.completions.create(
    │               model="qwen3.7-plus",
    │               messages=[system, ...history, user],
    │               extra_body={"enable_thinking": False}  # fast path
    │           )
    │         returns: response_text
    │
    ├─► _post_response_rtr(brief.memories, query, response_text)
    │         → RTR.process_retrieved() for each packed memory
    │         → thinking mode optionally enabled here
    │
    ├─► TraceLogger.log(TraceRecord)
    │
    └─► EpisodicBuffer.ingest_trace(trace)             # write new MemoryNode
            → embedder.embed(response_text)
            → store.save_memory(new_node)

Return: {response, memory_brief, retrieved_count, total_tokens, session_id}
```

### 5.2 Session End (maintenance path)

```
CosmosMemoryLayer.end_session(user_id, session_id)
    │
    ├─► SessionHistory.clear(session_id)    # drop intra-session message list
    │
    └─► run_maintenance(user_id)
            │
            ├─► IAAF.update_interference_scores(user_id)
            ├─► IAAF.run_forgetting(user_id)          # archive high-interference
            └─► ASC.run_consolidation(user_id)        # build/update schemas

# Or triggered serverlessly via:
# Alibaba Cloud Function Compute → asc_handler.handler(event)
```

---

## 6. Storage Layer

Two backends, selected automatically from `COSMOS_PG_DSN`:

### SQLite (`MemoryStore`) — local development

```
cosmos_q.db
├── memories     (id, user_id, version, content, embedding JSON, ...)
├── schemas      (id, user_id, type, content, confidence, embedding JSON, ...)
└── traces       (user_id, session_id, turn_index, query, response, ...)
```

Vector similarity computed in Python (cosine over full candidate set).

### ApsaraDB RDS + pgvector (`PgMemoryStore`) — production

```
PostgreSQL 15 + pgvector extension
├── memories     embedding column: vector(1024), ivfflat index (cosine_ops)
├── schemas      embedding column: vector(1024)
└── traces
```

Vector similarity via `<=>` operator (native ANN):

```sql
SELECT *, 1 - (embedding <=> $1::vector) AS cosine_sim
FROM memories
WHERE user_id=$2 AND status='ACTIVE'
ORDER BY embedding <=> $1::vector
LIMIT 50;
```

**Switch between backends:**
```bash
# SQLite (default)
COSMOS_DB_PATH=cosmos_q.db

# PostgreSQL + pgvector
COSMOS_PG_DSN=postgresql://user:pass@host:5432/cosmos_q
```

---

## 7. Qwen Cloud Integration

All Qwen Cloud calls use the **standard OpenAI Python SDK** pointed at the DashScope endpoint — no custom HTTP clients.

### Chat Completions

```python
from openai import OpenAI

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

# Standard call (fast path, thinking off)
response = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=[{"role": "system", "content": brief}, {"role": "user", "content": query}],
    extra_body={"enable_thinking": False},
)

# High-stakes call (thinking on — RTR reconsolidation, schema refinement)
response = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=messages,
    extra_body={"enable_thinking": True, "thinking_budget": 4096},
)
```

### Parallel Tool Calls

```python
response = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=messages,
    tools=tool_definitions,       # memory_retrieve + schema_query
    parallel_tool_calls=True,     # both called in one model pass
    extra_body={"enable_thinking": False},
)
```

### Embeddings (text-embedding-v3, 1024-dim)

```python
response = client.embeddings.create(
    model="text-embedding-v3",
    input=texts,              # up to 10 per request
    dimensions=1024,
    encoding_format="float",
)
```

### Model Tiers

| Model | Use case in COSMOS-Q |
|---|---|
| `qwen3.7-plus` | Default chat, episodic ingestion |
| `qwen3.7-max` | Complex schema refinement, contradiction analysis |
| `qwen3.6-flash` | High-throughput evaluation / ablation runs |

### Thinking Mode Per Operation

| Operation | Thinking | Reason |
|---|---|---|
| `QwenClient.chat()` | Off (default) | Latency-sensitive user path |
| `QwenClient.chat()` with RTR | Configurable | Auditable reconsolidation decisions |
| Schema summarisation (ASC) | Recommended | Better schema quality |
| Contradiction detection | Recommended | Reduces false positives |
| Simple retrieval | Off | No LLM call needed |

---

## 8. MCP Server

COSMOS-Q exposes its memory operations as **Model Context Protocol (MCP)** tool endpoints, transforming it from a standalone library into infrastructure any Qwen agent can call.

### Endpoints

```
GET  /health           → service liveness
GET  /tools            → tool schema discovery
GET  /sse              → SSE stream (MCP protocol handshake)
POST /invoke           → tool invocation
```

### Available Tools

| Tool | Description |
|---|---|
| `memory_store` | Embed and persist a new episodic memory |
| `memory_retrieve` | UACP-packed retrieval for a query → returns memory brief |
| `memory_reconsolidate` | Apply RTR to a specific memory with new context |
| `memory_forget` | Run IAAF forgetting pass for a user |
| `schema_query` | Query schemas by type and minimum confidence |

### Registration with a Qwen Agent

```python
tools = [
    {
        "type": "mcp",
        "server_url": "http://localhost:8765/sse",
        "name": "cosmos-q"
    }
]
response = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=messages,
    tools=tools,
    parallel_tool_calls=True,
)
```

Start the server:
```bash
cosmos-q mcp-server --port 8765
# or
cosmos-q-mcp
```

---

## 9. Deployment on Alibaba Cloud

### Local development

```bash
docker compose up          # starts postgres+pgvector + MCP server
```

### Production topology

```
                        ┌──────────────────────┐
                        │  Alibaba Cloud ECS   │
                        │                      │
User ──► Application ──►│  COSMOS-Q MCP Server │──► Qwen Cloud API
                        │  (Docker, ACR image) │    (Chat + Embeddings)
                        └──────────┬───────────┘
                                   │
                        ┌──────────▼───────────┐
                        │  ApsaraDB RDS        │
                        │  PostgreSQL + pgvector│
                        └──────────────────────┘
                                   │
                    Session end event
                                   │
                        ┌──────────▼───────────┐
                        │  Function Compute     │
                        │  asc_handler.handler  │
                        │  (IAAF + ASC async)   │
                        └──────────────────────┘
```

### Container Registry (ACR)

```bash
export ACR_NAMESPACE=your-namespace
bash scripts/acr_push.sh latest
# → pushes to registry.cn-hangzhou.aliyuncs.com/<namespace>/cosmos-q:latest
```

### Function Compute (ASC)

Triggered on session-end events; daily scheduled at 03:00 UTC.

```bash
fun deploy -t function_compute_template.yml
```

Event payload:
```json
{"user_id": "<UUID>", "trigger": "session_end"}
```

---

## 10. Module Map

```
cosmos_q/
├── config.py                  CosmosConfig (pydantic-settings, env-driven)
├── models.py                  MemoryNode, Schema, AgentState, TraceRecord, MemoryBrief
├── embeddings.py              EmbeddingService (text-embedding-v3 → local → hash)
├── memory_layer.py            CosmosMemoryLayer (main entry point)
│
├── agent/
│   ├── qwen_client.py         QwenClient — OpenAI SDK wrapper, thinking, tools
│   ├── trace_logger.py        TraceLogger — logs turns to store
│   ├── pipeline.py            MemoryUpdatePipeline — orchestrates trace→buffer
│   └── prompts.py             build_system_prompt(brief_text)
│
├── mechanisms/
│   ├── rtr.py                 ReconsolidationEngine (RTR)
│   ├── uacp.py                ContextPacker (UACP)
│   ├── iaaf.py                ForgettingEngine (IAAF)
│   ├── episodic_buffer.py     EpisodicBuffer — ingest traces and explicit adds
│   └── asc.py                 ConsolidationEngine (ASC)
│
├── store/
│   ├── __init__.py            make_store() factory (SQLite or pgvector)
│   ├── memory_store.py        SQLite backend
│   └── pg_store.py            ApsaraDB RDS + pgvector backend
│
├── mcp_server.py              FastAPI SSE server (5 MCP tool endpoints)
├── cli.py                     cosmos-q CLI (chat, retrieve, add-memory, ...)
│
├── function_compute/
│   └── asc_handler.py         Alibaba Cloud FC entry point (IAAF + ASC)
│
└── evaluation/
    ├── cmem.py                C-MEM benchmark scenarios
    ├── metrics.py             EvalResult, check_answer, check_retrieval_contains
    ├── baselines.py           No Memory, Full Transcript, Rolling Summary, Naive RAG
    └── harness.py             EvaluationHarness — runs full C-MEM benchmark
```

---

## 11. Configuration Reference

All settings are prefixed `COSMOS_` and can be set in `.env` or the environment.

| Variable | Default | Description |
|---|---|---|
| `COSMOS_QWEN_API_KEY` | `""` | DashScope API key |
| `COSMOS_QWEN_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | Chat + embedding endpoint |
| `COSMOS_QWEN_MODEL` | `qwen3.7-plus` | LLM model |
| `COSMOS_ENABLE_THINKING` | `false` | Global thinking mode default |
| `COSMOS_THINKING_BUDGET_TOKENS` | `4096` | Max reasoning tokens |
| `COSMOS_EMBEDDING_MODEL` | `text-embedding-v3` | DashScope embedding model |
| `COSMOS_EMBEDDING_DIM` | `1024` | Vector dimension |
| `COSMOS_DB_PATH` | `cosmos_q.db` | SQLite path (dev) |
| `COSMOS_PG_DSN` | `""` | PostgreSQL DSN (prod; activates pgvector backend) |
| `COSMOS_TOKEN_BUDGET` | `2048` | UACP token budget per turn |
| `COSMOS_TAU_RTR` | `0.35` | RTR divergence threshold |
| `COSMOS_TAU_FORGET` | `0.6` | IAAF forgetting threshold |
| `COSMOS_ASC_CLUSTER_THRESHOLD` | `0.55` | ASC cluster similarity |
| `COSMOS_MCP_PORT` | `8765` | MCP server port |
| `COSMOS_FC_REGION` | `cn-hangzhou` | Function Compute region |

Full reference: `.env.example`

# COSMOS-Q

COSMOS-Q is a local memory system for persistent user state.

It stores user memories, retrieves relevant context for new requests, groups related memories into schemas, and maintains the memory graph over time. The repository includes a Python API server, MCP-style tool endpoints, and a React interface for inspecting and exercising the system locally.

## Core Capabilities

COSMOS-Q provides:

- Persistent memory storage for a user across sessions
- Retrieval of relevant memories for a new query
- Schema creation and updates from related memories
- Session-end maintenance for memory cleanup and consolidation
- Local REST and SSE interfaces for integrating the memory layer into other systems

If `COSMOS_QWEN_API_KEY` is set, the system uses Qwen for live response generation and some internal operations. If it is not set, the local app still runs and uses mock chat responses where needed.

## Project Structure

```text
cosmos_q/     Python backend, API routes, memory logic, and server entrypoints
frontend/     React + Vite interface for local inspection and interaction
tests/        Test suite
```

## Prerequisites

- Python 3.10 or newer
- Node.js 18 or newer
- npm

## Environment Setup

Copy the example environment file:

```bash
cp .env.example .env
```

The most important variables are:

- `COSMOS_QWEN_API_KEY`: Optional. Enables live Qwen-backed responses.
- `COSMOS_QWEN_MODEL`: Optional. Overrides the default Qwen model.
- `COSMOS_DB_PATH`: Optional. Overrides the local SQLite database path.

## Install

### Backend

Create a virtual environment and install the backend with server dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"
```

### Frontend

Install the frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

## Run Locally

Start the backend in one terminal:

```bash
source .venv/bin/activate
cosmos-q-mcp
```

The backend listens on `http://127.0.0.1:8787` by default.

Start the frontend in a second terminal:

```bash
cd frontend
npm run dev
```

Vite will print the local URL, usually `http://127.0.0.1:5173` or `http://localhost:5173`.

Open that URL in your browser to inspect memory state and exercise the local system.

## API Endpoints

The backend includes these main routes:

- `GET /health`: Health check
- `GET /api/user`: Get or create a user ID
- `GET /api/state`: Read memory graph and state for a user
- `POST /api/chat`: Run a turn through the memory-backed flow
- `POST /api/session/end`: End a session and run maintenance
- `GET /tools`: List available MCP-style tools
- `GET /sse`: SSE endpoint for tool discovery
- `POST /invoke`: Invoke a tool by name

## Tool Endpoints

The MCP-style tool layer exposes operations such as:

- `memory_store`
- `memory_retrieve`
- `memory_reconsolidate`
- `memory_forget`
- `schema_query`

Example health check:

```bash
curl http://127.0.0.1:8787/health
```

## Frontend Configuration

The frontend proxies:

- `/api` to `http://localhost:8787`
- `/health` to `http://localhost:8787`

If you need a different backend URL, set `VITE_API_URL`.

## Development Notes

- The default database file is `cosmos_q.db` in the repo root.
- The backend allows local frontend origins on common Vite ports.
- A persistent user ID may be stored in `~/.cosmos_q_demo_user_id`.

## Tests

Run the backend test suite with:

```bash
pytest tests/ -v
```

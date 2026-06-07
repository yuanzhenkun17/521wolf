# 521wolf

Python rules engine for a 12-player Werewolf game. The engine owns the hardcoded game rules and calls each player through one async interface:

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

The `engine/` package intentionally does not depend on LangChain or LangGraph. LLM players and orchestration live in `app/` and still satisfy the same `act(request)` contract.

## Current Rule Set

- 12 players: 3 werewolves, 1 white wolf king, 4 villagers, seer, witch, hunter, guard.
- Sheriff election, sheriff vote weight, and badge transfer/destroy.
- Night actions: guard, wolves, seer, witch.
- Witch: first-night self-save is supported by the action model, antidote and poison are one-use, and same guard plus save still dies.
- Day actions: ordered speeches, white wolf king explosion, exile vote, immediate exile last words, PK vote on tie.
- Win condition: villagers win when all wolves die; wolves win by slaughtering all villagers, slaughtering all gods, or reaching parity with the good players.

## Project Layout

- `engine/`: rules engine. It owns phases, role rules, role state, voting, death chains, victory checks, logs, snapshots, and the `ActionRequest` / `ActionResponse` contract.
- `app/`: active runtime. It owns LangGraph orchestration, agent decision nodes, memory, Markdown skill routing, LLM services, review, evaluation, self-play, evidence extraction, and role skill evolution.
- `storage/`: SQLite persistence and replay helpers for games, events, decisions, experience candidates, evolution runs, patterns, and leaderboards. Two databases: `wolf.db` (games + battle evaluation) and `evolution.db` (learning pipeline).
- `ui/`: FastAPI backend plus Vue 3 frontend. It starts games, streams SSE events, handles human actions, reads persisted artifacts, and manages role evolution.
- `scripts/`: maintenance scripts, including `seed_skills.py` for rebuilding the local skill registry under `data/registry/`.
- `docs/`: design notes, current feature inventory, implementation plan, and architecture documents.

Current top-level structure:

```text
521wolf/
├── app/                # Active LangGraph runtime, services, business logic, entrypoints
├── engine/             # Rule engine, phases, role rules, role_state, logging
├── storage/            # SQLite schema, stores, replay
├── ui/
│   ├── backend/        # FastAPI app and runners
│   └── frontend/       # Vue 3 UI
├── tests/              # Unit, integration, backend, storage, and structure tests
├── docs/               # Current docs and design specs
├── scripts/            # Utility scripts
├── data/               # Local runtime data, gitignored except examples
└── runs/               # Local selfplay/evolution/game artifacts, gitignored
```

## Agent Boundary

The rules engine only depends on the `PlayerAgent` protocol:

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

LLM prompting, model calls, structured memory, belief, skill routing, output parsing, and fallback behavior live under `app/services` and `app/graphs/subgraphs/agent`. Game, evaluation, and evolution orchestration enter through `app.run`, which dispatches into LangGraph subgraphs behind the same `act(request)` contract. There is no root-level `agent/` package; active runtime code must use `app.*` entrypoints.

## Test

```bash
uv run pytest
```

## Seed Local Skills

Versioned Markdown skills live under local gitignored `data/registry/`. On a fresh checkout, rebuild the seed baselines before running UI games or role evolution:

```bash
uv run python scripts/seed_skills.py
```

## Run With LLM Agents

LLM players use an OpenAI-compatible chat completions endpoint. Configure it with a local ignored `.env` file:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
WEREWOLF_LLM_API_KEY=your-api-key
WEREWOLF_LLM_BASE_URL=https://router.shengsuanyun.com/api/v1
WEREWOLF_LLM_MODEL=ali/qwen3.5-flash
WEREWOLF_LLM_TIMEOUT=45
WEREWOLF_LLM_TEMPERATURE=0.4
```

Langfuse tracing is optional. It stays disabled unless `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are both configured.

Shell environment variables override values loaded from `.env`:

```bash
export WEREWOLF_LLM_API_KEY="your-api-key"
export WEREWOLF_LLM_BASE_URL="https://router.shengsuanyun.com/api/v1"
export WEREWOLF_LLM_MODEL="ali/qwen3.5-flash"
```

The UI backend calls `app.run.run_game()`, `app.run.run_evaluation()`, and `app.run.run_evolution()`. Game setup uses `app.lib.game.create_agents()` / `create_engine()`, while the LLM client comes from `app.services.llm`. Each player receives a seat/role prompt plus the current `ActionRequest`, then returns an `ActionResponse`.
Game logs are written under the configured runtime paths, typically:

```text
runs/games/game1/game_events.jsonl
runs/games/game1/archive.json
data/wolf.db
```

# 521wolf

Python rules engine for a 12-player Werewolf game. The engine owns the hardcoded game rules and calls each player through one async interface:

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

The core package intentionally does not depend on LangChain. A LangChain player can be added later by wrapping a runnable/agent behind the same `act(request)` contract.

## Current Rule Set

- 12 players: 3 werewolves, 1 white wolf king, 4 villagers, seer, witch, hunter, guard.
- Sheriff election, sheriff vote weight, and badge transfer/destroy.
- Night actions: guard, wolves, seer, witch.
- Witch: first-night self-save is supported by the action model, antidote and poison are one-use, and same guard plus save still dies.
- Day actions: ordered speeches, white wolf king explosion, exile vote, immediate exile last words, PK vote on tie.
- Win condition: villagers win when all wolves die; wolves win by slaughtering all villagers, slaughtering all gods, or reaching parity with the good players.

## Project Layout

- `engine/`: rules engine. It owns phases, role rules, voting, death chains, victory checks, logs, and the `ActionRequest` / `ActionResponse` contract.
- `agent/`: main Agent implementation. It owns the runtime pipeline, memory, belief, Markdown skills, ToT/GoT reasoning, LLM calls, parsing, policy repair, archive logs, review, self-play, evaluation, and skill evolution.
- `ui/`: observer UI. It starts or reads games through the backend, consumes logs/snapshots, and renders the game experience.
- `docs/`: design notes, ideas, review records, and architecture documents.

## Agent Boundary

The rules engine only depends on the `PlayerAgent` protocol:

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

LLM prompting, model calls, structured memory, belief, skill routing, output parsing, and fallback behavior live in root-level `agent/`. This keeps the rules system independent from player reasoning. A future LangGraph implementation should be added behind the same `act(request)` contract, not inside the rules engine.

## Test

```bash
uv run python -m unittest discover -s tests -v
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

The UI backend uses `agent.api.factory.load_llm_client()` and `agent.api.factory.create_agents()` to create one Agent per player. Each player receives a seat/role prompt plus the current `ActionRequest`, then returns an `ActionResponse`.
Game logs are written to numbered files such as:

```text
logs/game1/events.jsonl
logs/game1/agent_decisions.jsonl
logs/game1/archive.json
```

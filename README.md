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

- `src/werewolf/`: first-layer rules engine. It owns phases, role rules, voting, death chains, victory checks, logs, and the `ActionRequest` / `ActionResponse` contract.
- `playeragent/`: second-layer player brain. It owns memory, belief, role strategy, prompt construction, model calls, parsing, fallback policy, and LLM player implementations.
- `ui/`: third-layer UI. It starts or reads games through the backend, consumes logs/snapshots, and renders the game experience.
- `src/werewolf/agent_runtime/` and `src/werewolf/llm_agents.py`: backward-compatible import shims that forward to `playeragent/`.

## Agent Boundary

The rules engine only depends on the `PlayerAgent` protocol:

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

LLM prompting, model calls, structured memory, belief, role strategy, output parsing, and fallback behavior live in root-level `playeragent/`. This keeps the first layer rules system independent from the second layer player reasoning system. A future LangChain implementation should be added as another model adapter behind the same runtime contract, not inside the rules engine.

## Test

```bash
uv run python -m unittest discover -s tests -v
```

## Run LLM Agents Demo

LLM players use an OpenAI-compatible chat completions endpoint. You can configure it with a local ignored config file:

```bash
cp config/llm.example.json config/llm.local.json
```

Then edit `config/llm.local.json`:

```json
{
  "api_key": "your-api-key",
  "base_url": "https://router.shengsuanyun.com/api/v1",
  "model": "ali/qwen3.5-flash",
  "timeout": 45
}
```

Run:

```bash
uv run python -m werewolf.demo_llm
# or
uv run werewolf-demo-llm
```

Environment variables can also override the local config:

```bash
export WEREWOLF_LLM_API_KEY="your-api-key"
export WEREWOLF_LLM_BASE_URL="https://router.shengsuanyun.com/api/v1"
export WEREWOLF_LLM_MODEL="ali/qwen3.5-flash"
uv run python -m werewolf.demo_llm
```

The LLM demo creates 12 `LLMPlayerAgent` objects in one Python process. Each player receives a seat/role/persona prompt plus the current `ActionRequest`, then returns JSON that is parsed into `ActionResponse`.
It writes full god-view logs to numbered files such as:

```text
logs/game1.jsonl
logs/game1.txt
```

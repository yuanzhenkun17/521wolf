"""Shared concurrent game-batch runner.

Used by the eval and evolve pipelines to run many games through the reusable
game subgraph with bounded concurrency, per-game persistence dirs, and a
fail-fast guard against systemic failures.

Replaces the three near-duplicate serial loops that previously lived in
eval/nodes.py and evolve/nodes.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from app.util.winner import has_valid_winner, normalize_winner

_log = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 3
# Abort a batch if this many games error in a row — signals a systemic problem
# (bad model, bad skill path) rather than the occasional unlucky game.
CONSECUTIVE_FAILURE_LIMIT = 5

_GAME_RESULT_METADATA_KEYS: tuple[str, ...] = (
    "source_run_id",
    "source_game_id",
    "evaluation_set_id",
    "seed_set_id",
    "benchmark_id",
    "benchmark_version",
    "benchmark_config_hash",
    "target_role",
    "target_version_id",
    "model_id",
    "model_config_hash",
    "langfuse_trace_id",
    "langfuse_trace_url",
    "langfuse_dataset_name",
    "langfuse_dataset_item_id",
    "langfuse_experiment_name",
    "langfuse_run_name",
    "langfuse_dataset_run_id",
    "langfuse_dataset_run_item_id",
    "langfuse_experiment_url",
)


class BatchAbortedError(RuntimeError):
    """Raised when a batch hits too many consecutive game failures."""


def normalize_game_result(*, game_id: str, seed: int, result: dict[str, Any]) -> dict[str, Any]:
    """Reduce a game subgraph result to the compact per-game record.

    Single source of truth — both eval and evolve consume this shape.
    """
    events = result.get("game_events", [])
    days = [int(e.get("day", 0) or 0) for e in events if isinstance(e, dict)]
    record = {
        "game_id": game_id,
        "seed": seed,
        "winner": result.get("winner"),
        "outcome": result.get("outcome"),
        "terminal_reason": result.get("terminal_reason"),
        "days": max(days) if days else 0,
        "player_roles": dict(result.get("roles", {})),
        "events": events,
        "decisions": list(result.get("decisions", [])),
        "error": result.get("error"),
    }
    for key in _GAME_RESULT_METADATA_KEYS:
        if key in result:
            record[key] = result.get(key)
    return record


def winner_counts(games: list[dict[str, Any]]) -> dict[str, int]:
    """Tally winners across a list of normalized game records."""
    counts: dict[str, int] = {}
    for game in games:
        winner = normalize_winner(game.get("winner")) or "unknown"
        counts[winner] = counts.get(winner, 0) + 1
    return counts


def valid_completed_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return games that ended normally with a rankable winning side."""
    return [game for game in games if has_valid_winner(game)]


def resolve_game_subgraph(state: dict[str, Any]) -> Any:
    """Return the injected game subgraph, building a default if absent."""
    game_subgraph = state.get("game_subgraph")
    if game_subgraph is not None:
        return game_subgraph
    from app.graphs.subgraphs.agent.builder import build_agent_subgraph
    from app.graphs.subgraphs.game.builder import build_game_subgraph

    return build_game_subgraph(agent_subgraph=build_agent_subgraph())


async def run_game_batch(
    game_subgraph: Any,
    count: int,
    build_game_state: Callable[[int], dict[str, Any]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    label: str = "batch",
    fail_fast: bool = True,
    game_timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Run ``count`` games concurrently, preserving input order in the output.

    Args:
        game_subgraph: compiled game subgraph (``.ainvoke(state)``).
        count: number of games to run.
        build_game_state: ``index -> game_state dict`` (must include game_id/seed).
        concurrency: max games in flight at once.
        label: log label.
        fail_fast: abort with BatchAbortedError after too many consecutive errors.
        game_timeout: optional wall-clock timeout per game, in seconds.

    Returns a list of normalized game records, ordered by index. A game whose
    subgraph raises (or returns an error) becomes an ``error`` record rather
    than aborting the whole batch — unless ``fail_fast`` trips on a run of them.
    """
    if count <= 0:
        return []
    effective = max(1, min(concurrency, count))
    semaphore = asyncio.Semaphore(effective)
    results: list[dict[str, Any] | None] = [None] * count

    # Track consecutive failures by completion order for the fail-fast guard.
    consecutive = 0
    consecutive_lock = asyncio.Lock()
    aborted = asyncio.Event()

    async def _run_one(index: int) -> None:
        if aborted.is_set():
            return
        game_id = f"{label}_{index + 1:03d}"
        seed = index
        game_state: dict[str, Any] | None = None
        timeout: float | None = None
        async with semaphore:
            if aborted.is_set():
                return
            try:
                game_state = build_game_state(index)
                game_id = str(game_state.get("game_id", game_id))
                seed = int(game_state.get("seed", seed) or 0)
                timeout = _game_timeout_for_state(game_state, explicit=game_timeout)
                call = game_subgraph.ainvoke(game_state)
                raw = await call if timeout is None else await asyncio.wait_for(call, timeout=timeout)
                record = normalize_game_result(game_id=game_id, seed=seed, result=raw)
            except Exception as exc:  # noqa: BLE001 — isolate one game's failure
                error = _game_error_message(exc, timeout)
                _log.warning("%s game %s failed: %s", label, game_id, error)
                _cleanup_failed_game_state(game_state, game_id)
                record = {
                    "game_id": game_id, "seed": seed, "winner": "error",
                    "days": 0, "player_roles": {}, "events": [], "decisions": [],
                    "error": error,
                }
        results[index] = record

        async with consecutive_lock:
            nonlocal consecutive
            if record.get("error"):
                consecutive += 1
                if fail_fast and consecutive >= CONSECUTIVE_FAILURE_LIMIT:
                    aborted.set()
            else:
                consecutive = 0

    await asyncio.gather(*(_run_one(i) for i in range(count)))

    if aborted.is_set():
        first_error = next((r.get("error") for r in results if r and r.get("error")), "unknown")
        raise BatchAbortedError(
            f"{label}: aborted after {CONSECUTIVE_FAILURE_LIMIT} consecutive failures "
            f"(first error: {first_error})"
        )
    return [r for r in results if r is not None]


def per_game_dir(base: Path | str | None, label: str, index: int) -> str | None:
    """Build a per-game output dir under ``base`` for persistence, or None."""
    if base is None:
        return None
    return str(Path(base) / f"{label}_{index + 1:03d}")


def _game_timeout_for_state(game_state: dict[str, Any], *, explicit: float | None) -> float | None:
    raw_value: Any = explicit
    if raw_value is None:
        raw_value = game_state.get("batch_game_timeout") or game_state.get("runner_batch_game_timeout")
    if raw_value is None:
        raw_value = (
            os.environ.get("WEREWOLF_BATCH_GAME_TIMEOUT")
            or os.environ.get("WEREWOLF_RUNNER_BATCH_GAME_TIMEOUT")
        )
    if raw_value in {None, ""}:
        return None
    try:
        timeout = float(raw_value)
    except (TypeError, ValueError):
        return None
    return timeout if timeout > 0 else None


def _game_error_message(exc: Exception, timeout: float | None) -> str:
    if isinstance(exc, TimeoutError):
        return f"game timed out after {timeout:g}s" if timeout is not None else "game timed out"
    text = str(exc)
    return text or type(exc).__name__


def _cleanup_failed_game_state(game_state: dict[str, Any] | None, game_id: str) -> None:
    """Remove partially streamed rows for a game that never reached final persistence."""
    if not game_state or not game_id:
        return
    persistence = game_state.get("game_persistence") or game_state.get("persistence")
    close = getattr(persistence, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:  # noqa: BLE001 — cleanup must not mask the game failure
            _log.warning("failed to close partial persistence for game %s: %s", game_id, exc)

    provider = game_state.get("storage_provider")
    if provider is None:
        return

    try:
        from storage.game_store import delete_game_from_provider

        delete_game_from_provider(provider, game_id)
    except Exception as exc:  # noqa: BLE001
        _log.warning("failed to clean partial rows for game %s: %s", game_id, exc)

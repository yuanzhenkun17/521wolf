"""Benchmark report batch result, game, and Langfuse helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ui.backend.services.benchmark_payload_utils import (
    dict_items as _dict_items,
    json_clone as _json_clone,
    optional_text as _optional_text,
    sanitize_public_payload,
    text_items as _text_items,
    unique_texts as _unique_texts,
)
from ui.backend.task_state import _match_filter


def _benchmark_results(batch: dict[str, Any]) -> list[dict[str, Any]]:
    results = batch.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, dict)]
    result = batch.get("result")
    return [dict(result)] if isinstance(result, dict) else []


def _benchmark_result_batch_id(result: dict[str, Any]) -> str:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    return str(result.get("batch_id") or config.get("batch_id") or "")


def _benchmark_result_role(result: dict[str, Any]) -> str | None:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    role = result.get("target_role") or config.get("target_role")
    return str(role) if role else None


def _benchmark_result_game_count(result: dict[str, Any]) -> int:
    for key in ("game_count", "completed", "attempted_game_count"):
        try:
            if result.get(key) is not None:
                return max(0, int(result.get(key) or 0))
        except (TypeError, ValueError):
            continue
    games = result.get("games")
    return len([item for item in games if isinstance(item, dict)]) if isinstance(games, list) else 0


def _benchmark_games_for_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    parent_batch_id = str(batch.get("batch_id") or "")
    games_out: list[dict[str, Any]] = []
    for result in _benchmark_results(batch):
        result_batch_id = _benchmark_result_batch_id(result)
        target_role = _benchmark_result_role(result)
        games = result.get("games")
        if not isinstance(games, list):
            continue
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            games_out.append(
                _benchmark_game_item(
                    parent_batch_id=parent_batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    target_type=str(batch.get("target_type") or ""),
                    result=result,
                    game=game,
                    index=index,
                )
            )
    return games_out


def _benchmark_game_item(
    *,
    parent_batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    target_type: str,
    result: dict[str, Any],
    game: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    game_id = str(game.get("game_id") or game.get("id") or game.get("source_game_id") or "")
    history_game_id = str(game.get("history_game_id") or game_id or "")
    events = game.get("events") if isinstance(game.get("events"), list) else []
    decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
    diagnostics = _dict_items(game.get("diagnostics"))
    item = {
        "batch_id": parent_batch_id,
        "result_batch_id": result_batch_id,
        "target_type": target_type,
        "target_role": target_role,
        "index": index,
        "game_id": game_id,
        "id": str(game.get("id") or game_id),
        "history_game_id": history_game_id or None,
        "replay_available": bool(history_game_id),
        "replay_unavailable_reason": None if history_game_id else "missing game id for replay",
        "status": _benchmark_game_status(game),
        "seed": game.get("seed"),
        "winner": game.get("winner"),
        "phase": game.get("phase") or "benchmark",
        "side": game.get("side"),
        "event_count": int(game.get("event_count") or len(events)),
        "decision_count": int(game.get("decision_count") or len(decisions)),
        "day": game.get("day", game.get("days", 0)),
        "days": game.get("days", game.get("day", 0)),
        "in_progress": bool(game.get("in_progress", False)),
        "source_run_id": game.get("source_run_id") or result_batch_id,
        "source_game_id": game.get("source_game_id") or game_id,
        "diagnostic_count": len(diagnostics),
    }
    errors = _text_items(game.get("errors"))
    if errors and "error_count" not in item:
        item["error_count"] = len(errors)
    fallbacks = _dict_items(game.get("fallbacks"))
    if fallbacks and "fallback_count" not in item:
        item["fallback_count"] = len(fallbacks)
    llm_errors = _text_items(game.get("llm_errors"))
    if llm_errors and "llm_error_count" not in item:
        item["llm_error_count"] = len(llm_errors)
    policy_adjustments = _dict_items(game.get("policy_adjustments"))
    if policy_adjustments and "policy_adjusted_count" not in item:
        item["policy_adjusted_count"] = len(policy_adjustments)
    for key in (
        "error",
        "rankable",
        "rankable_reason",
        "timeout",
        "abnormal",
        "fallback",
        "fallback_count",
        "llm_error",
        "llm_error_count",
        "policy_adjusted",
        "policy_adjusted_count",
    ):
        if key in game:
            item[key] = game.get(key)
    langfuse = _benchmark_game_langfuse_block(
        game=game,
        result=result,
        result_batch_id=result_batch_id,
        index=index,
    )
    if langfuse:
        item["langfuse"] = langfuse
        item["observability"] = {"langfuse": _json_clone(langfuse)}
    return sanitize_public_payload(item)


def _benchmark_game_langfuse_block(
    *,
    game: dict[str, Any],
    result: dict[str, Any],
    result_batch_id: str,
    index: int,
) -> dict[str, Any]:
    result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
    score_summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    game_sources = _langfuse_sources(game)
    batch_sources = [result_config, result, score_summary]
    seed = game.get("seed")
    dataset_item_id = (
        _langfuse_text(game_sources, "dataset_item_id")
        or _benchmark_langfuse_dataset_item_id_from_config(result_config, seed=seed, index=index)
        or _langfuse_text(batch_sources, "dataset_item_id")
    )
    dataset_run_url = _langfuse_text(game_sources, "dataset_run_url")
    experiment_url = _langfuse_text(game_sources, "experiment_url")
    if dataset_run_url is None:
        dataset_run_url = experiment_url
    if experiment_url is None:
        experiment_url = dataset_run_url

    block = {
        "trace_id": _langfuse_text(game_sources, "trace_id"),
        "trace_url": _langfuse_text(game_sources, "trace_url"),
        "dataset_name": _langfuse_text(game_sources, "dataset_name")
        or _langfuse_text(batch_sources, "dataset_name")
        or _optional_text(result_config.get("evaluation_set_id")),
        "dataset_id": _langfuse_text(game_sources, "dataset_id"),
        "dataset_item_id": dataset_item_id,
        "dataset_item_url": _langfuse_text(game_sources, "dataset_item_url"),
        "dataset_run_id": _langfuse_text(game_sources, "dataset_run_id")
        or _langfuse_text(batch_sources, "dataset_run_id"),
        "dataset_run_item_id": _langfuse_text(game_sources, "dataset_run_item_id"),
        "dataset_run_url": dataset_run_url,
        "experiment_name": _langfuse_text(game_sources, "experiment_name")
        or _langfuse_text(batch_sources, "experiment_name")
        or _optional_text(result_config.get("benchmark_id"))
        or _optional_text(result_config.get("evaluation_set_id")),
        "run_name": _langfuse_text(game_sources, "run_name")
        or _langfuse_text(batch_sources, "run_name")
        or _optional_text(result_config.get("batch_id"))
        or _optional_text(result_batch_id),
        "experiment_url": experiment_url,
    }
    return {key: value for key, value in block.items() if value is not None}


_LANGFUSE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "trace_id": ("trace_id", "langfuse_trace_id"),
    "trace_url": ("trace_url", "langfuse_trace_url"),
    "dataset_name": ("dataset_name", "langfuse_dataset_name"),
    "dataset_id": ("dataset_id", "langfuse_dataset_id"),
    "dataset_item_id": ("dataset_item_id", "langfuse_dataset_item_id"),
    "dataset_item_url": ("dataset_item_url", "langfuse_dataset_item_url"),
    "dataset_run_id": ("dataset_run_id", "langfuse_dataset_run_id"),
    "dataset_run_item_id": ("dataset_run_item_id", "langfuse_dataset_run_item_id"),
    "dataset_run_url": ("dataset_run_url", "langfuse_dataset_run_url"),
    "experiment_name": ("experiment_name", "langfuse_experiment_name"),
    "run_name": ("run_name", "langfuse_run_name"),
    "experiment_url": ("experiment_url", "langfuse_experiment_url"),
}


def _langfuse_sources(value: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    langfuse = value.get("langfuse")
    if isinstance(langfuse, dict):
        sources.append(langfuse)
    observability = value.get("observability")
    if isinstance(observability, dict):
        observed_langfuse = observability.get("langfuse")
        if isinstance(observed_langfuse, dict):
            sources.append(observed_langfuse)
    sources.append(value)
    return sources


def _langfuse_text(sources: list[dict[str, Any]], field: str) -> str | None:
    for source in sources:
        for key in _LANGFUSE_FIELD_ALIASES.get(field, (field,)):
            text = _optional_text(source.get(key))
            if text is not None:
                return text
    return None


def _benchmark_langfuse_dataset_item_id_from_config(
    cfg: dict[str, Any],
    *,
    seed: Any,
    index: int,
) -> str | None:
    configured = cfg.get("langfuse_dataset_item_id")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    zero_index = max(0, int(index or 1) - 1)
    if isinstance(configured, list):
        for candidate_index in (zero_index, index):
            if 0 <= candidate_index < len(configured):
                value = _optional_text(configured[candidate_index])
                if value is not None:
                    return value
    if isinstance(configured, dict):
        for key in (seed, str(seed) if seed is not None else None, zero_index, str(zero_index), index, str(index)):
            if key is not None and key in configured:
                value = _optional_text(configured[key])
                if value is not None:
                    return value

    evaluation_set_id = _optional_text(cfg.get("evaluation_set_id"))
    seed_set_id = _optional_text(cfg.get("seed_set_id"))
    seed_text = _optional_text(seed)
    if evaluation_set_id is None or seed_set_id is None or seed_text is None:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed_text}"


def _benchmark_batch_langfuse_summary(batch: dict[str, Any], *, games: list[dict[str, Any]]) -> dict[str, Any]:
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)
    result_configs = [
        result.get("config")
        for result in results
        if isinstance(result.get("config"), dict)
    ]
    config_sources = [source for source in [config, *result_configs] if isinstance(source, dict)]
    game_blocks = [game.get("langfuse") for game in games if isinstance(game.get("langfuse"), dict)]
    return {
        "dataset_names": _unique_texts(
            *[_langfuse_text(config_sources, "dataset_name")],
            *[block.get("dataset_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "experiment_names": _unique_texts(
            *[_langfuse_text(config_sources, "experiment_name")],
            *[block.get("experiment_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "run_names": _unique_texts(
            *[_langfuse_text(config_sources, "run_name")],
            *[block.get("run_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "trace_count": len(_unique_texts(*[block.get("trace_id") for block in game_blocks if isinstance(block, dict)])),
        "dataset_run_count": len(
            _unique_texts(*[block.get("dataset_run_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "dataset_run_item_count": len(
            _unique_texts(*[block.get("dataset_run_item_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "dataset_item_count": len(
            _unique_texts(*[block.get("dataset_item_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "links": {
            "trace_urls": _unique_texts(*[block.get("trace_url") for block in game_blocks if isinstance(block, dict)]),
            "dataset_run_urls": _unique_texts(
                *[block.get("dataset_run_url") for block in game_blocks if isinstance(block, dict)]
            ),
            "experiment_urls": _unique_texts(
                *[block.get("experiment_url") for block in game_blocks if isinstance(block, dict)]
            ),
        },
    }


def _benchmark_game_matches_status_filter(game: dict[str, Any], statuses: set[str]) -> bool:
    if "problem" in statuses and _benchmark_game_is_problem(game):
        return True
    explicit = {status for status in statuses if status != "problem"}
    if not explicit:
        return False
    return _match_filter(game.get("status", "completed"), explicit)


def _benchmark_game_is_problem(game: dict[str, Any]) -> bool:
    status = str(game.get("status") or "").strip().lower()
    if status in {"failed", "timeout", "abnormal", "cancelled", "interrupted"}:
        return True
    if int(game.get("diagnostic_count") or 0) > 0:
        return True
    if game.get("error") or game.get("timeout") or game.get("abnormal"):
        return True
    for key in ("fallback", "llm_error", "policy_adjusted", "errors", "fallbacks", "llm_errors", "policy_adjustments"):
        if game.get(key):
            return True
    for key in ("error_count", "fallback_count", "llm_error_count", "policy_adjusted_count"):
        try:
            if int(game.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _benchmark_game_status(game: dict[str, Any]) -> str:
    status = str(game.get("status") or "").strip().lower()
    if status:
        return status
    if game.get("error") or game.get("failed"):
        return "failed"
    if game.get("timeout"):
        return "timeout"
    if game.get("abnormal"):
        return "abnormal"
    return "completed"


def _benchmark_game_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(game.get("status") or "unknown") for game in games)
    return {
        "total": len(games),
        "by_status": dict(sorted(counts.items())),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "timeout": counts.get("timeout", 0),
        "abnormal": counts.get("abnormal", 0),
    }

"""Run a real-LLM full-game smoke check.

This command is intentionally stricter than import or fake-model smoke tests:
it requires a configured real model, PostgreSQL connectivity, and a completed
game with a winner before reporting ``passed``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from typing import Any, Sequence

from dotenv import load_dotenv

from app.config import LLM_ENV_PATH, load_llm_config
from app.run import run_game
from app.services.llm import create_llm
from app.util.redaction import redact_text
from storage.provider import PostgresStorageProvider

DEFAULT_OUTER_TIMEOUT_SECONDS = 900.0
DEFAULT_OUTER_TIMEOUT_BUFFER_SECONDS = 30.0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one full Werewolf game through the real LLM runtime.",
    )
    parser.add_argument("--game-id", default="", help="Stable smoke game id.")
    parser.add_argument("--seed", type=int, default=20260608, help="Engine seed.")
    parser.add_argument("--max-days", type=int, default=5, help="Maximum game days.")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help=(
            "Outer smoke timeout. Defaults to WEREWOLF_GAME_TIMEOUT plus "
            "a small buffer, or 900s when no game timeout is configured."
        ),
    )
    parser.add_argument(
        "--timeout-buffer-seconds",
        type=float,
        default=DEFAULT_OUTER_TIMEOUT_BUFFER_SECONDS,
        help="Buffer added when --timeout-seconds is omitted and a game timeout env var is configured.",
    )
    parser.add_argument("--agent-fast-smoke", action="store_true", help="Skip low-value LLM actions.")
    parser.add_argument("--no-agent-fast-smoke", action="store_true", help="Disable fast-smoke skips.")
    parser.add_argument("--enable-sheriff", action="store_true", default=True)
    parser.add_argument("--disable-sheriff", action="store_true")
    parser.add_argument("--judge-max-decisions", type=int, default=1)
    parser.add_argument("--judge-timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--allow-missing-env",
        action="store_true",
        help="Return skipped instead of nonzero when LLM/PostgreSQL config is missing.",
    )
    parser.add_argument("--preflight-only", action="store_true", help="Only validate real LLM and PostgreSQL preflight.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def _json_result(status: str, **fields: Any) -> dict[str, Any]:
    result = {
        "kind": "real_llm_full_game_smoke",
        "schema_version": 1,
        "status": status,
    }
    result.update(fields)
    return result


def _print_result(result: dict[str, Any], *, pretty: bool) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2 if pretty else None, default=str))


def _preflight(args: argparse.Namespace) -> tuple[bool, dict[str, Any]]:
    load_dotenv(LLM_ENV_PATH, override=False)
    if os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}:
        return False, _json_result(
            "skipped",
            reason="fake_llm_enabled",
            message="Unset UI_BACKEND_USE_FAKE_LLM before running the real LLM smoke.",
        )

    try:
        llm_config = load_llm_config(env_path=None)
    except Exception as exc:  # noqa: BLE001 - command should return structured diagnostics
        return False, _json_result(
            "skipped" if args.allow_missing_env else "failed",
            reason="llm_config_missing",
            diagnostics=[_diagnostic("llm_config", exc)],
        )

    conninfo = os.environ.get("POSTGRES_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not conninfo:
        return False, _json_result(
            "skipped" if args.allow_missing_env else "failed",
            reason="postgres_config_missing",
            diagnostics=[{"stage": "postgres_config", "message": "POSTGRES_DATABASE_URL/DATABASE_URL is not set."}],
        )

    conn = None
    try:
        conn = PostgresStorageProvider(conninfo, connect_kwargs={"connect_timeout": 5}).open_wolf_connection()
        conn.execute("SELECT 1").fetchone()
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - command should return structured diagnostics
        return False, _json_result(
            "skipped" if args.allow_missing_env else "failed",
            reason="postgres_unavailable",
            diagnostics=[_diagnostic("postgres_connect", exc)],
        )
    finally:
        if conn is not None:
            conn.close()

    return True, _json_result(
        "preflight_ok",
        model=str(llm_config.get("model") or ""),
        base_url=redact_text(str(llm_config.get("base_url") or ""), context="public"),
        timeout=llm_config.get("timeout"),
        runtime_timeout=llm_config.get("runtime_timeout"),
    )


def _diagnostic(stage: str, exc: Exception) -> dict[str, str]:
    return {
        "stage": stage,
        "exception_type": type(exc).__name__,
        "message": redact_text(str(exc) or type(exc).__name__, context="diagnostic"),
    }


def _positive_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _env_positive_float(*names: str) -> float | None:
    for name in names:
        value = _positive_float(os.environ.get(name))
        if value is not None:
            return value
    return None


def _resolve_outer_timeout(args: argparse.Namespace) -> dict[str, float | str | None]:
    explicit = _positive_float(args.timeout_seconds)
    if explicit is not None:
        return {
            "outer_timeout_seconds": max(1.0, explicit),
            "outer_timeout_source": "argument",
            "game_timeout_seconds": _env_positive_float("WEREWOLF_GAME_TIMEOUT", "WEREWOLF_RUNNER_GAME_TIMEOUT"),
        }

    game_timeout = _env_positive_float("WEREWOLF_GAME_TIMEOUT", "WEREWOLF_RUNNER_GAME_TIMEOUT")
    if game_timeout is not None:
        buffer_seconds = _positive_float(args.timeout_buffer_seconds)
        if buffer_seconds is None:
            buffer_seconds = DEFAULT_OUTER_TIMEOUT_BUFFER_SECONDS
        return {
            "outer_timeout_seconds": max(1.0, game_timeout + buffer_seconds),
            "outer_timeout_source": "game_timeout_env",
            "game_timeout_seconds": game_timeout,
        }

    return {
        "outer_timeout_seconds": DEFAULT_OUTER_TIMEOUT_SECONDS,
        "outer_timeout_source": "default",
        "game_timeout_seconds": None,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ok, preflight = _preflight(args)
    if not ok:
        return preflight
    if args.preflight_only:
        preflight["status"] = "passed"
        preflight["reason"] = "preflight_ok"
        return preflight

    started = time.monotonic()
    game_id = args.game_id or f"real_llm_smoke_{uuid.uuid4().hex[:10]}"
    fast_smoke = args.agent_fast_smoke and not args.no_agent_fast_smoke
    enable_sheriff = bool(args.enable_sheriff and not args.disable_sheriff)
    timeout_info = _resolve_outer_timeout(args)
    outer_timeout = float(timeout_info["outer_timeout_seconds"] or DEFAULT_OUTER_TIMEOUT_SECONDS)
    try:
        game = await asyncio.wait_for(
            run_game(
                game_id=game_id,
                seed=args.seed,
                max_days=max(1, int(args.max_days)),
                model=create_llm(),
                enable_sheriff=enable_sheriff,
                agent_fast_smoke=fast_smoke,
                enable_decision_judge=True,
                review_decision_judge=True,
                review_judge_max_decisions=max(0, int(args.judge_max_decisions)),
                review_judge_timeout_seconds=max(1.0, float(args.judge_timeout_seconds)),
                judge_timeout_seconds=max(1.0, float(args.judge_timeout_seconds)),
            ),
            timeout=outer_timeout,
        )
    except TimeoutError as exc:
        return _json_result(
            "failed",
            reason="outer_timeout",
            game_id=game_id,
            elapsed_seconds=round(time.monotonic() - started, 3),
            **timeout_info,
            diagnostics=[_diagnostic("run_game", exc)],
        )
    except Exception as exc:  # noqa: BLE001 - command should return structured diagnostics
        return _json_result(
            "failed",
            reason="run_game_error",
            game_id=game_id,
            elapsed_seconds=round(time.monotonic() - started, 3),
            **timeout_info,
            diagnostics=[_diagnostic("run_game", exc)],
        )

    events = game.get("events") or game.get("game_events") or []
    decisions = game.get("decisions") or []
    winner = game.get("winner")
    terminal_reason = game.get("terminal_reason")
    game_status = str(game.get("status") or "")
    passed = (
        game_status == "completed"
        and winner in {"villagers", "werewolves"}
        and len(events) > 0
        and len(decisions) > 0
    )
    return _json_result(
        "passed" if passed else "failed",
        reason="completed_with_winner" if passed else "completion_contract_failed",
        game_id=game_id,
        game_status=game_status,
        winner=winner,
        terminal_reason=terminal_reason,
        event_count=len(events),
        decision_count=len(decisions),
        max_days=max(1, int(args.max_days)),
        seed=args.seed,
        agent_fast_smoke=fast_smoke,
        enable_sheriff=enable_sheriff,
        elapsed_seconds=round(time.monotonic() - started, 3),
        **timeout_info,
        review_status=(game.get("review") or {}).get("status") if isinstance(game.get("review"), dict) else None,
        decision_judge_status=(
            (game.get("decision_judge") or {}).get("status")
            if isinstance(game.get("decision_judge"), dict)
            else None
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = asyncio.run(_run(args))
    _print_result(result, pretty=bool(args.pretty))
    if result.get("status") == "passed":
        return 0
    if result.get("status") == "skipped":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

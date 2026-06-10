"""Run full local benchmark and self-evolution samples.

The command is an orchestration wrapper around existing app/UI flows. It keeps a
fixed manifest and a fixed issues/fixes report under runs/full_local_samples so
long local runs can be audited and resumed between phases.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

from app.config import DEFAULT_GAME_CONCURRENCY, DEFAULT_PATHS, LLM_ENV_PATH, load_llm_config
from app.lib.benchmark_spec import load_benchmark_spec, materialize_benchmark_spec
from app.run import run_evolution
from app.services.chain import LLMCallError
from app.services.llm import create_llm, get_runtime_policy
from app.util.json import to_jsonable, write_json
from app.util.redaction import redact, redact_text
from app.util.time import beijing_now_iso
from storage.provider import storage_provider_from_env
from ui.backend.constants import ROLE_ORDER
from ui.backend.evolution_serializers import _evolution_run_summary
from ui.backend.schemas import BenchmarkRequest, EvolutionStartRequest
from ui.backend.store import BackendStore
from ui.backend.task_state import _set_task_contract

DEFAULT_OUTPUT_DIR = Path("runs/full_local_samples")
DEFAULT_BENCHMARK_ID = "role-baseline-standard-v1"
DEFAULT_TRAINING_GAMES = 20
DEFAULT_BATTLE_GAMES = 10
DEFAULT_MAX_DAYS = 5
DEFAULT_LLM_CONCURRENCY = 0
DEFAULT_JUDGE_CONCURRENCY = 4
DEFAULT_JUDGE_MAX_DECISIONS = 20
DEFAULT_JUDGE_TIMEOUT_SECONDS = 60.0
DEFAULT_GAME_TIMEOUT_SECONDS = 900.0
DEFAULT_EVOLUTION_SEED_START = 371000
DEFAULT_EVOLUTION_BATTLE_SEED_START = 381000
DEFAULT_ROLE_SEED_STRIDE = 1000
SUCCESS_EVOLUTION_STATUSES = {"completed", "reviewing", "promoted", "rejected"}


@dataclass(frozen=True)
class RuntimeSettings:
    game_concurrency: int
    llm_concurrency: int
    judge_concurrency: int
    judge_max_decisions: int
    judge_timeout_seconds: float
    game_timeout_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_concurrency": self.game_concurrency,
            "llm_concurrency": self.llm_concurrency,
            "judge_concurrency": self.judge_concurrency,
            "judge_max_decisions": self.judge_max_decisions,
            "judge_timeout_seconds": self.judge_timeout_seconds,
            "game_timeout_seconds": self.game_timeout_seconds,
        }


class RunContext:
    def __init__(self, output_dir: Path, manifest_path: Path) -> None:
        self.output_dir = output_dir
        self.manifest_path = manifest_path
        self.issue_report_path = output_dir / "ISSUES_AND_FIXES.md"
        self.run_report_path = output_dir / "RUN_REPORT.md"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_manifest()
        self._ensure_issue_report()

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    return value
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "kind": "full_local_samples_manifest",
            "schema_version": 1,
            "created_at": beijing_now_iso(),
            "updated_at": None,
            "status": "created",
            "artifacts": {},
            "preflight": {},
            "benchmark": {},
            "evolution": {"roles": {}},
            "tuning": [],
        }

    def reset_manifest_for_fresh_run(self) -> None:
        self.manifest = {
            "kind": "full_local_samples_manifest",
            "schema_version": 1,
            "created_at": beijing_now_iso(),
            "updated_at": None,
            "status": "created",
            "artifacts": {
                "manifest": str(self.manifest_path),
                "issues_and_fixes": str(self.issue_report_path),
                "run_report": str(self.run_report_path),
            },
            "preflight": {},
            "benchmark": {},
            "evolution": {"roles": {}},
            "tuning": [],
        }

    def _ensure_issue_report(self) -> None:
        if self.issue_report_path.exists():
            return
        self.issue_report_path.write_text(
            "\n".join(
                [
                    "# Full Local Samples Issues And Fixes",
                    "",
                    f"- Created at: {beijing_now_iso()}",
                    f"- Manifest: `{self.manifest_path.as_posix()}`",
                    "- Scope: full standard benchmark plus full per-role self-evolution samples.",
                    "",
                    "## Entries",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def save_manifest(self, status: str | None = None) -> None:
        if status is not None:
            self.manifest["status"] = status
        self.manifest["updated_at"] = beijing_now_iso()
        artifacts = self.manifest.setdefault("artifacts", {})
        artifacts["manifest"] = str(self.manifest_path)
        artifacts["issues_and_fixes"] = str(self.issue_report_path)
        artifacts["run_report"] = str(self.run_report_path)
        write_json(self.manifest_path, redact(to_jsonable(self.manifest), context="diagnostic"))

    def log(self, message: str) -> None:
        print(f"[{beijing_now_iso()}] {message}", flush=True)

    def record_issue(
        self,
        *,
        stage: str,
        symptom: str,
        action: str,
        outcome: str = "",
        root_cause: str = "",
        command: str = "",
        details: Any = None,
    ) -> None:
        lines = [
            f"### {beijing_now_iso()} - {stage}",
            "",
            f"- Symptom: {redact_text(symptom, context='diagnostic')}",
        ]
        if command:
            lines.append(f"- Command: `{redact_text(command, context='diagnostic')}`")
        if root_cause:
            lines.append(f"- Root cause: {redact_text(root_cause, context='diagnostic')}")
        lines.append(f"- Action: {redact_text(action, context='diagnostic')}")
        if outcome:
            lines.append(f"- Outcome: {redact_text(outcome, context='diagnostic')}")
        if details not in (None, "", [], {}):
            safe_details = json.dumps(redact(to_jsonable(details), context="diagnostic"), ensure_ascii=False, indent=2, default=str)
            lines.extend(["- Details:", "```json", safe_details, "```"])
        lines.append("")
        with self.issue_report_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def write_run_report(self) -> None:
        benchmark = self.manifest.get("benchmark") if isinstance(self.manifest.get("benchmark"), dict) else {}
        evolution = self.manifest.get("evolution") if isinstance(self.manifest.get("evolution"), dict) else {}
        roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
        lines = [
            "# Full Local Samples Run Report",
            "",
            f"- Updated at: {beijing_now_iso()}",
            f"- Status: {self.manifest.get('status')}",
            f"- Manifest: `{self.manifest_path.as_posix()}`",
            f"- Issues/fixes: `{self.issue_report_path.as_posix()}`",
            "",
            "## Benchmark",
            "",
            f"- Status: {benchmark.get('status') or 'not_run'}",
            f"- Benchmark id: {benchmark.get('benchmark_id') or ''}",
            f"- Batch id: {benchmark.get('batch_id') or ''}",
            f"- Roles completed: {benchmark.get('completed_roles', 0)}/{benchmark.get('role_count', 0)}",
            f"- Games completed: {benchmark.get('completed_games', 0)}/{benchmark.get('expected_games', 0)}",
            "",
            "## Evolution",
            "",
        ]
        if roles:
            for role, item in sorted(roles.items()):
                if isinstance(item, dict):
                    lines.append(
                        "- "
                        f"{role}: {item.get('status') or 'unknown'}; "
                        f"run={item.get('run_id') or ''}; "
                        f"training={item.get('training_completed', 0)}/{item.get('training_game_count', 0)}; "
                        f"battle={item.get('battle_completed', 0)}/{item.get('battle_game_count', 0)}; "
                        f"proposals={item.get('proposal_count', 0)}; "
                        f"gate={item.get('gate_decision') or ''}"
                    )
        else:
            lines.append("- Not run.")
        lines.extend(["", "## Artifacts", ""])
        artifacts = self.manifest.get("artifacts") if isinstance(self.manifest.get("artifacts"), dict) else {}
        for key, value in sorted(artifacts.items()):
            lines.append(f"- {key}: `{value}`")
        lines.append("")
        self.run_report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full local benchmark and self-evolution samples.")
    parser.add_argument("--output-dir", default="", help="Defaults to runs/full_local_samples.")
    parser.add_argument("--manifest", default="", help="Defaults to <output-dir>/manifest.json.")
    parser.add_argument("--benchmark-id", default=DEFAULT_BENCHMARK_ID)
    parser.add_argument("--skip-benchmark", action="store_true")
    parser.add_argument("--skip-evolution", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-migrations", action="store_true")
    parser.add_argument("--skip-baseline-dry-run", action="store_true")
    parser.add_argument("--skip-llm-smoke", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--adaptive-retry", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--allow-fake-llm", action="store_true")
    parser.add_argument("--roles", default="", help="Comma-separated roles. Defaults to benchmark spec roles.")
    parser.add_argument(
        "--benchmark-games",
        type=int,
        default=0,
        help="Override benchmark games per eval batch while keeping benchmark metadata/seeds. Use 0 for spec default.",
    )
    parser.add_argument("--evolution-training-games", type=int, default=DEFAULT_TRAINING_GAMES)
    parser.add_argument("--evolution-battle-games", type=int, default=DEFAULT_BATTLE_GAMES)
    parser.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    parser.add_argument("--game-concurrency", type=int, default=DEFAULT_GAME_CONCURRENCY)
    parser.add_argument(
        "--llm-concurrency",
        type=int,
        default=DEFAULT_LLM_CONCURRENCY,
        help="Process-wide async LLM request limit. Use 0 to disable.",
    )
    parser.add_argument("--judge-concurrency", type=int, default=DEFAULT_JUDGE_CONCURRENCY)
    parser.add_argument("--judge-max-decisions", type=int, default=DEFAULT_JUDGE_MAX_DECISIONS)
    parser.add_argument("--judge-timeout-seconds", type=float, default=DEFAULT_JUDGE_TIMEOUT_SECONDS)
    parser.add_argument(
        "--game-timeout-seconds",
        type=float,
        default=DEFAULT_GAME_TIMEOUT_SECONDS,
        help="Per-game wall-clock timeout. Use 0 to disable.",
    )
    parser.add_argument(
        "--agent-fast-smoke",
        action="store_true",
        help=(
            "Enable the existing fast agent profile: skip low-value speech/sheriff LLM calls, "
            "trim prompts, and keep protected actions on LLM. Game counts are unchanged."
        ),
    )
    parser.add_argument(
        "--agent-policy-skip-llm",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Explicitly enable/disable configured non-protected agent LLM skips.",
    )
    parser.add_argument("--agent-policy-skip-llm-preset", default="", help="Example: smoke_fast.")
    parser.add_argument("--agent-policy-skip-llm-actions", default="", help="Comma-separated action_type values.")
    parser.add_argument("--auto-promote", action="store_true")
    parser.add_argument("--evolution-seed-start", type=int, default=DEFAULT_EVOLUTION_SEED_START)
    parser.add_argument("--evolution-battle-seed-start", type=int, default=DEFAULT_EVOLUTION_BATTLE_SEED_START)
    parser.add_argument("--role-seed-stride", type=int, default=DEFAULT_ROLE_SEED_STRIDE)
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    load_dotenv(LLM_ENV_PATH, override=False)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    manifest_path = Path(args.manifest) if args.manifest else output_dir / "manifest.json"
    ctx = RunContext(output_dir=output_dir, manifest_path=manifest_path)
    if not args.resume:
        ctx.reset_manifest_for_fresh_run()
    settings = RuntimeSettings(
        game_concurrency=max(1, int(args.game_concurrency)),
        llm_concurrency=max(0, int(args.llm_concurrency)),
        judge_concurrency=max(1, int(args.judge_concurrency)),
        judge_max_decisions=max(0, int(args.judge_max_decisions)),
        judge_timeout_seconds=max(1.0, float(args.judge_timeout_seconds)),
        game_timeout_seconds=_positive_float(args.game_timeout_seconds),
    )
    agent_runtime = _agent_runtime_config_from_args(args)
    ctx.manifest["command"] = " ".join([Path(sys.executable).name, "-m", "tools.research.run_full_local_samples", *sys.argv[1:]])
    ctx.manifest["settings"] = settings.to_dict()
    ctx.manifest["agent_runtime"] = agent_runtime
    ctx.manifest["parameters"] = {
        "benchmark_id": args.benchmark_id,
        "benchmark_games": max(0, int(args.benchmark_games)),
        "roles": _requested_roles(args),
        "skip_benchmark": bool(args.skip_benchmark),
        "skip_evolution": bool(args.skip_evolution),
        "evolution_training_games": int(args.evolution_training_games),
        "evolution_battle_games": int(args.evolution_battle_games),
        "max_days": int(args.max_days),
        "auto_promote": bool(args.auto_promote),
        "resume": bool(args.resume),
        "adaptive_retry": bool(args.adaptive_retry),
        "max_retries": max(0, int(args.max_retries)),
        "agent_fast_smoke": bool(args.agent_fast_smoke),
        "agent_policy_skip_llm": args.agent_policy_skip_llm,
        "agent_policy_skip_llm_preset": str(args.agent_policy_skip_llm_preset or ""),
        "agent_policy_skip_llm_actions": str(args.agent_policy_skip_llm_actions or ""),
    }
    ctx.save_manifest("preparing")
    ctx.log(f"prepared full local samples runner with settings={settings.to_dict()} agent_runtime={agent_runtime}")

    if not args.skip_preflight:
        preflight = run_preflight(ctx, args)
        ctx.manifest["preflight"] = preflight
        ctx.save_manifest("preflight_ok" if preflight.get("status") == "passed" else "preflight_failed")
        ctx.log(f"preflight status={preflight.get('status')}")
        if preflight.get("status") != "passed":
            ctx.write_run_report()
            return 1
    if args.preflight_only:
        ctx.write_run_report()
        return 0

    roles = resolve_roles(args, ctx)
    ctx.manifest.setdefault("evolution", {})["selected_roles"] = roles
    ctx.save_manifest("running")
    effective_settings = settings
    if not args.skip_benchmark:
        effective_settings = await run_benchmark_with_retries(ctx, args, settings)
        if not _benchmark_completed(ctx.manifest):
            ctx.save_manifest(_overall_status(ctx.manifest))
            ctx.write_run_report()
            return 1
    if not args.skip_evolution:
        await run_evolution_roles(ctx, args, effective_settings, roles)
    ctx.save_manifest(_overall_status(ctx.manifest))
    ctx.write_run_report()
    return 0 if ctx.manifest.get("status") in {"completed", "completed_with_failures"} else 1


def run_preflight(ctx: RunContext, args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "passed", "started_at": beijing_now_iso(), "checks": []}

    def fail(check: str, exc: Exception | str, action: str) -> None:
        result["status"] = "failed"
        message = str(exc)
        result["checks"].append({"check": check, "status": "failed", "message": redact_text(message, context="diagnostic")})
        ctx.record_issue(stage=f"preflight.{check}", symptom=message, action=action, details=_exception_detail(exc) if isinstance(exc, Exception) else None)

    fake_enabled = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}
    if fake_enabled and not args.allow_fake_llm:
        fail("llm_runtime", "UI_BACKEND_USE_FAKE_LLM is enabled.", "Unset fake LLM or pass --allow-fake-llm explicitly.")
    else:
        try:
            llm_config = load_llm_config(env_path=None)
            result["checks"].append(
                {
                    "check": "llm_config",
                    "status": "passed",
                    "model": str(llm_config.get("model") or ""),
                    "base_url": redact_text(str(llm_config.get("base_url") or ""), context="public"),
                    "timeout": llm_config.get("timeout"),
                    "runtime_timeout": llm_config.get("runtime_timeout"),
                    "runtime_concurrency": max(0, int(args.llm_concurrency)),
                }
            )
            if not args.skip_llm_smoke:
                smoke = _run_llm_smoke_check(
                    timeout_seconds=min(30.0, float(llm_config.get("runtime_timeout") or 30.0)),
                    llm_concurrency=max(0, int(args.llm_concurrency)),
                )
                result["checks"].append(smoke)
                if smoke.get("status") != "passed":
                    result["status"] = "failed"
                    ctx.record_issue(
                        stage="preflight.llm_smoke",
                        symptom=str(smoke.get("message") or smoke.get("reason") or "LLM smoke check failed."),
                        root_cause="Configured LLM failed an authenticated minimal chat call.",
                        action="Fix LLM credential/endpoint/model before benchmark/evolution.",
                        outcome="Preflight failed before creating benchmark or evolution runs.",
                        details=smoke,
                    )
        except Exception as exc:  # noqa: BLE001
            fail("llm_config", exc, "Configure WEREWOLF_LLM_API_KEY and model settings in .env.")

    for check, opener in (
        ("postgres_wolf", lambda: storage_provider_from_env(paths=DEFAULT_PATHS).open_wolf_connection()),
        ("postgres_registry", lambda: storage_provider_from_env(paths=DEFAULT_PATHS).open_registry_connection()),
        ("postgres_evolution", lambda: storage_provider_from_env(paths=DEFAULT_PATHS).open_evolution_connection()),
    ):
        conn = None
        try:
            conn = opener()
            conn.execute("SELECT 1").fetchone()
            conn.commit()
            result["checks"].append({"check": check, "status": "passed"})
        except Exception as exc:  # noqa: BLE001
            fail(check, exc, "Start PostgreSQL and verify POSTGRES_DATABASE_URL or DATABASE_URL.")
        finally:
            if conn is not None:
                conn.close()

    if not args.skip_migrations:
        proc = run_command([sys.executable, "-m", "alembic", "upgrade", "head"], timeout_seconds=300)
        result["checks"].append(proc)
        if proc.get("status") != "passed":
            fallback = _unknown_revision_schema_fallback(proc)
            if fallback is not None:
                result["checks"].append(fallback)
                if fallback.get("status") == "passed":
                    proc["status"] = "warning"
                    proc["warning"] = "database alembic_version points at a revision absent from this checkout; core schema is present"
                    ctx.record_issue(
                        stage="preflight.alembic_unknown_revision",
                        symptom=str(proc.get("stderr") or proc.get("stdout") or proc.get("returncode")),
                        command=str(proc.get("command") or ""),
                        root_cause=(
                            "The local database was migrated by another checkout and stores an Alembic "
                            "revision that latest origin/main does not contain."
                        ),
                        action=(
                            "Did not stamp or rewrite the database. Verified required wolf/registry/evolution "
                            "tables exist and downgraded migration status to a warning for this runner."
                        ),
                        outcome="Schema health check passed; preflight can continue.",
                        details={"alembic": proc, "schema_check": fallback},
                    )
                else:
                    result["status"] = "failed"
                    ctx.record_issue(
                        stage="preflight.alembic",
                        symptom=str(proc.get("stderr") or proc.get("stdout") or proc.get("returncode")),
                        command=str(proc.get("command") or ""),
                        action="Fix Alembic revision history or restore the required database schema before long samples.",
                        outcome="Preflight failed; fallback schema check did not pass.",
                        details={"alembic": proc, "schema_check": fallback},
                    )
            else:
                result["status"] = "failed"
                ctx.record_issue(
                    stage="preflight.alembic",
                    symptom=str(proc.get("stderr") or proc.get("stdout") or proc.get("returncode")),
                    command=str(proc.get("command") or ""),
                    action="Run migrations before long samples.",
                    outcome="Preflight failed.",
                    details=proc,
                )

    if not args.skip_baseline_dry_run:
        proc = run_command([sys.executable, "-m", "app.tools.seed_default_baseline", "--dry-run"], timeout_seconds=300)
        result["checks"].append(proc)
        if proc.get("status") != "passed":
            result["status"] = "failed"
            ctx.record_issue(
                stage="preflight.baseline_registry",
                symptom=str(proc.get("stderr") or proc.get("stdout") or proc.get("returncode")),
                command=str(proc.get("command") or ""),
                action="Fix baseline registry before benchmark/evolution.",
                outcome="Preflight failed.",
                details=proc,
            )

    try:
        spec, seed_set = materialize_benchmark_spec(load_benchmark_spec(args.benchmark_id, paths=DEFAULT_PATHS), paths=DEFAULT_PATHS)
        effective_game_count = spec.game_count
        if int(getattr(args, "benchmark_games", 0) or 0) > 0:
            effective_game_count = min(spec.game_count, max(0, int(args.benchmark_games)))
        result["checks"].append(
            {
                "check": "benchmark_spec",
                "status": "passed",
                "benchmark_id": spec.id,
                "roles": list(spec.roles),
                "game_count": spec.game_count,
                "effective_game_count": effective_game_count,
                "game_count_override": max(0, int(getattr(args, "benchmark_games", 0) or 0)),
                "max_days": spec.max_days,
                "seed_set_id": spec.seed_set_id,
                "seed_count": len(seed_set.seeds) if seed_set is not None else spec.game_count,
            }
        )
    except Exception as exc:  # noqa: BLE001
        fail("benchmark_spec", exc, "Fix benchmark resources before running the full benchmark.")
    result["finished_at"] = beijing_now_iso()
    return result


def _run_llm_smoke_check(*, timeout_seconds: float, llm_concurrency: int = 0) -> dict[str, Any]:
    started = time.monotonic()

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = create_llm(
            timeout=timeout_seconds,
            runtime_timeout=timeout_seconds,
            runtime_concurrency=max(0, int(llm_concurrency)),
            max_retries=0,
        )
        result = llm.invoke(
            [
                SystemMessage(content="Reply with exactly: ok"),
                HumanMessage(content="ok"),
            ]
        )
        content = getattr(result, "content", "")
        return {
            "check": "llm_smoke",
            "status": "passed",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "runtime_concurrency": get_runtime_policy(llm).concurrency,
            "response_preview": redact_text(str(content or "")[:80], context="diagnostic"),
        }
    except LLMCallError as exc:
        return {
            "check": "llm_smoke",
            "status": "failed",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "runtime_concurrency": max(0, int(llm_concurrency)),
            "reason": "llm_call_error",
            "exception_type": type(exc.__cause__ or exc).__name__,
            "message": redact_text(str(exc), context="diagnostic"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "check": "llm_smoke",
            "status": "failed",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "runtime_concurrency": max(0, int(llm_concurrency)),
            "reason": "exception",
            "exception_type": type(exc).__name__,
            "message": redact_text(str(exc), context="diagnostic"),
        }


def _create_runtime_store(settings: RuntimeSettings) -> tuple[Any, BackendStore]:
    model = create_llm(runtime_concurrency=settings.llm_concurrency)
    store = BackendStore(paths=DEFAULT_PATHS, model=model)
    store._persist_background_tasks = lambda: None  # type: ignore[method-assign]
    return model, store


async def run_benchmark_with_retries(ctx: RunContext, args: argparse.Namespace, initial_settings: RuntimeSettings) -> RuntimeSettings:
    settings = initial_settings
    attempts = 1 + max(0, int(args.max_retries))
    for attempt in range(1, attempts + 1):
        _model, store = _create_runtime_store(settings)
        ctx.log(
            "created isolated backend store for benchmark "
            f"attempt={attempt}; disabled UI task-index writes for this long runner"
        )
        try:
            await run_benchmark_once(ctx, store, args, settings, attempt=attempt)
            return settings
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or type(exc).__name__
            ctx.record_issue(
                stage="benchmark",
                symptom=message,
                root_cause="Benchmark attempt failed.",
                action="Evaluate adaptive retry.",
                outcome=f"Attempt {attempt}/{attempts} failed.",
                details=_exception_detail(exc),
            )
            _update_benchmark_manifest(ctx, {"status": "failed", "error": message})
            if not args.adaptive_retry or attempt >= attempts or not _looks_retryable(message):
                return settings
            next_settings = _reduced_settings(settings)
            ctx.manifest.setdefault("tuning", []).append({"at": beijing_now_iso(), "stage": "benchmark", "reason": message, "from": settings.to_dict(), "to": next_settings.to_dict()})
            ctx.record_issue(stage="benchmark.tuning", symptom=message, action="Retry benchmark with adjusted concurrency/timeout.", outcome=f"{settings.to_dict()} -> {next_settings.to_dict()}")
            settings = next_settings
            ctx.save_manifest("running")
        finally:
            store.close()
    return settings


async def run_benchmark_once(ctx: RunContext, store: BackendStore, args: argparse.Namespace, settings: RuntimeSettings, *, attempt: int) -> None:
    benchmark_state = ctx.manifest.setdefault("benchmark", {})
    if args.resume and benchmark_state.get("status") == "completed":
        return
    request = _benchmark_request_from_args(args)
    benchmark_service = store.benchmark_service
    batch = benchmark_service.queue_benchmark(request)
    batch_id = str(batch["batch_id"])
    config = batch.setdefault("config", {})
    config["game_concurrency"] = settings.game_concurrency
    config["llm_concurrency"] = settings.llm_concurrency
    config["eval_judge_concurrency"] = settings.judge_concurrency
    config["judge_concurrency"] = settings.judge_concurrency
    config["eval_judge_timeout_seconds"] = settings.judge_timeout_seconds
    config["judge_timeout_seconds"] = settings.judge_timeout_seconds
    config.update(_agent_runtime_config_from_args(args))
    if settings.game_timeout_seconds is not None:
        config["runner_game_timeout"] = settings.game_timeout_seconds
        config["game_timeout"] = settings.game_timeout_seconds
        config["runner_batch_game_timeout"] = settings.game_timeout_seconds
        config["batch_game_timeout"] = settings.game_timeout_seconds
    _update_benchmark_manifest(
        ctx,
        {
            "status": "running",
            "attempt": attempt,
            "batch_id": batch_id,
            "benchmark_id": args.benchmark_id,
            "settings": settings.to_dict(),
            "agent_runtime": _agent_runtime_config_from_args(args),
            "started_at": beijing_now_iso(),
            "role_count": len(batch.get("roles", []) or []),
            "completed_roles": 0,
        },
    )
    ctx.log(f"benchmark batch started batch_id={batch_id} attempt={attempt}")
    await _await_with_partial_game_heartbeat(
        ctx,
        benchmark_service.run_queued_benchmark(batch_id, request),
        stage="benchmark",
        game_prefix=batch_id,
        interval_seconds=60.0,
    )
    batch = store.evolution_batches.get(batch_id, batch)
    detail = benchmark_service.benchmark_batch_detail(batch_id)
    report = benchmark_service.benchmark_batch_report(batch_id)
    markdown = benchmark_service.benchmark_batch_report(batch_id, format="markdown")
    diagnostics = benchmark_service.benchmark_batch_diagnostics(batch_id)
    aggregate_diagnostics = benchmark_service.benchmark_diagnostics(benchmark_id=args.benchmark_id)
    benchmark_dir = ctx.output_dir / "benchmark" / batch_id
    write_json(benchmark_dir / "batch.json", batch)
    write_json(benchmark_dir / "detail.json", detail)
    write_json(benchmark_dir / "report.json", report)
    write_json(benchmark_dir / "diagnostics.json", diagnostics)
    write_json(benchmark_dir / "aggregate_diagnostics.json", aggregate_diagnostics)
    (benchmark_dir / "report.md").write_text(str(markdown.get("content") or ""), encoding="utf-8")
    expected_games = _expected_benchmark_games(detail)
    completed_games = _completed_benchmark_games(detail)
    status = str(batch.get("status") or "unknown")
    ctx.log(f"benchmark batch finished batch_id={batch_id} status={status}")
    artifacts = ctx.manifest.setdefault("artifacts", {})
    artifacts["benchmark_batch"] = str(benchmark_dir / "batch.json")
    artifacts["benchmark_detail"] = str(benchmark_dir / "detail.json")
    artifacts["benchmark_report"] = str(benchmark_dir / "report.json")
    artifacts["benchmark_report_markdown"] = str(benchmark_dir / "report.md")
    artifacts["benchmark_diagnostics"] = str(benchmark_dir / "diagnostics.json")
    _update_benchmark_manifest(
        ctx,
        {
            "status": status,
            "finished_at": batch.get("finished_at") or beijing_now_iso(),
            "role_count": len(batch.get("roles", []) or []),
            "completed_roles": (batch.get("progress") or {}).get("completed_roles", 0),
            "expected_games": expected_games,
            "completed_games": completed_games,
            "report_id": report.get("report_id"),
            "content_hash": report.get("content_hash"),
            "artifact_dir": str(benchmark_dir),
        },
    )
    if status != "completed":
        raise RuntimeError(str(batch.get("error") or f"benchmark ended with status={status}"))


async def run_evolution_roles(ctx: RunContext, args: argparse.Namespace, settings: RuntimeSettings, roles: list[str]) -> None:
    current_settings = settings
    for index, role in enumerate(roles):
        current_settings = await run_evolution_role_with_retries(ctx, args, current_settings, role, role_index=index)


async def run_evolution_role_with_retries(
    ctx: RunContext,
    args: argparse.Namespace,
    initial_settings: RuntimeSettings,
    role: str,
    *,
    role_index: int,
) -> RuntimeSettings:
    role_state = ctx.manifest.setdefault("evolution", {}).setdefault("roles", {}).get(role, {})
    if args.resume and isinstance(role_state, dict) and role_state.get("status") in SUCCESS_EVOLUTION_STATUSES:
        return initial_settings
    settings = initial_settings
    attempts = 1 + max(0, int(args.max_retries))
    for attempt in range(1, attempts + 1):
        model, store = _create_runtime_store(settings)
        ctx.log(
            f"created isolated backend store for evolution role={role} "
            f"attempt={attempt}; disabled UI task-index writes for this long runner"
        )
        try:
            await run_evolution_role_once(ctx, store, model, args, settings, role, role_index=role_index, attempt=attempt)
            return settings
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or type(exc).__name__
            ctx.record_issue(
                stage=f"evolution.{role}",
                symptom=message,
                root_cause=f"Evolution attempt failed for role={role}.",
                action="Evaluate adaptive retry.",
                outcome=f"Attempt {attempt}/{attempts} failed.",
                details=_exception_detail(exc),
            )
            _update_evolution_role_manifest(ctx, role, {"status": "failed", "error": message, "attempt": attempt})
            if not args.adaptive_retry or attempt >= attempts or not _looks_retryable(message):
                return settings
            next_settings = _reduced_settings(settings)
            ctx.manifest.setdefault("tuning", []).append({"at": beijing_now_iso(), "stage": f"evolution.{role}", "reason": message, "from": settings.to_dict(), "to": next_settings.to_dict()})
            ctx.record_issue(stage=f"evolution.{role}.tuning", symptom=message, action="Retry role evolution with adjusted concurrency/timeout.", outcome=f"{settings.to_dict()} -> {next_settings.to_dict()}")
            settings = next_settings
            ctx.save_manifest("running")
        finally:
            store.close()
    return settings


async def run_evolution_role_once(
    ctx: RunContext,
    store: BackendStore,
    model: Any,
    args: argparse.Namespace,
    settings: RuntimeSettings,
    role: str,
    *,
    role_index: int,
    attempt: int,
) -> None:
    request = EvolutionStartRequest(
        roles=[role],
        training_games=max(0, int(args.evolution_training_games)),
        battle_games=max(0, int(args.evolution_battle_games)),
        max_days=max(1, int(args.max_days)),
        auto_promote=bool(args.auto_promote),
    )
    run = store._create_evolution_run(role, request)
    run_id = str(run["run_id"])
    seed_start = int(args.evolution_seed_start) + role_index * int(args.role_seed_stride)
    battle_seed_start = int(args.evolution_battle_seed_start) + role_index * int(args.role_seed_stride)
    config = {
        "role": role,
        "training_games": request.training_games,
        "battle_games": request.battle_games,
        "max_days": request.max_days,
        "seed_start": seed_start,
        "battle_seed_start": battle_seed_start,
        "auto_promote": request.auto_promote,
        "game_concurrency": settings.game_concurrency,
        "llm_concurrency": settings.llm_concurrency,
        "enable_decision_judge": True,
        "training_decision_judge": True,
        "evolve_decision_judge": True,
        "training_judge_max_decisions": settings.judge_max_decisions,
        "evolve_judge_max_decisions": settings.judge_max_decisions,
        "training_judge_concurrency": settings.judge_concurrency,
        "evolve_judge_concurrency": settings.judge_concurrency,
        "training_judge_timeout_seconds": settings.judge_timeout_seconds,
        "evolve_judge_timeout_seconds": settings.judge_timeout_seconds,
    }
    config.update(_agent_runtime_config_from_args(args))
    if settings.game_timeout_seconds is not None:
        config["runner_game_timeout"] = settings.game_timeout_seconds
        config["game_timeout"] = settings.game_timeout_seconds
        config["runner_batch_game_timeout"] = settings.game_timeout_seconds
        config["batch_game_timeout"] = settings.game_timeout_seconds
    _update_evolution_role_manifest(
        ctx,
        role,
        {
            "status": "running",
            "attempt": attempt,
            "run_id": run_id,
            "settings": settings.to_dict(),
            "agent_runtime": _agent_runtime_config_from_args(args),
            "training_game_count": request.training_games,
            "battle_game_count": request.battle_games * 2,
            "seed_start": seed_start,
            "battle_seed_start": battle_seed_start,
            "started_at": beijing_now_iso(),
        },
    )
    ctx.log(f"evolution role started role={role} run_id={run_id} attempt={attempt}")

    def progress_sink(snapshot: dict[str, Any]) -> None:
        store._sync_evolution_progress(run_id, snapshot)
        _update_evolution_role_manifest(ctx, role, _compact_evolution_snapshot(snapshot), save=False)
        ctx.save_manifest("running")

    result = await _await_with_partial_game_heartbeat(
        ctx,
        run_evolution(
            role=role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            max_days=request.max_days,
            auto_promote=request.auto_promote,
            run_id=run_id,
            config=config,
            model=model,
            paths=DEFAULT_PATHS,
            progress_sink=progress_sink,
        ),
        stage=f"evolution.{role}",
        role=role,
        game_prefix=run_id,
        interval_seconds=60.0,
    )
    run.update(result)
    run["run_id"] = result.get("run_id") or run_id
    run["role"] = role
    run["status"] = result.get("status", "reviewing")
    _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
    run["started_at"] = run.get("started_at") or result.get("started_at") or beijing_now_iso()
    run["finished_at"] = result.get("finished_at") or beijing_now_iso()
    store._touch_background_task(run)
    run["training_completed"] = store._count_evolution_games(run.get("training_games"))
    run["battle_completed"] = store._count_evolution_games(run.get("battle_games"))
    run["overall_progress"] = store._evolution_overall_progress(run)
    store._persist_background_tasks()
    summary = _evolution_run_summary(run)
    role_dir = ctx.output_dir / "evolution" / role / run_id
    write_json(role_dir / "run.json", run)
    write_json(role_dir / "summary.json", summary)
    artifacts = ctx.manifest.setdefault("artifacts", {})
    artifacts[f"evolution_{role}_run"] = str(role_dir / "run.json")
    artifacts[f"evolution_{role}_summary"] = str(role_dir / "summary.json")
    gate = summary.get("gate_report") if isinstance(summary.get("gate_report"), dict) else {}
    _update_evolution_role_manifest(
        ctx,
        role,
        {
            **_compact_evolution_snapshot(summary),
            "status": summary.get("status") or run.get("status"),
            "run_id": run_id,
            "finished_at": run.get("finished_at"),
            "proposal_count": summary.get("proposal_count"),
            "diff_count": summary.get("diff_count"),
            "gate_decision": gate.get("decision") or gate.get("release_decision") or summary.get("recommendation"),
            "artifact_dir": str(role_dir),
        },
    )
    ctx.log(f"evolution role finished role={role} run_id={run_id} status={run.get('status')}")
    if str(run.get("status") or "").lower() == "failed":
        raise RuntimeError(str(run.get("error") or "evolution status=failed"))


def resolve_roles(args: argparse.Namespace, ctx: RunContext) -> list[str]:
    requested = _requested_roles(args)
    if requested:
        return _dedupe_valid_roles(requested)
    try:
        spec, _seed_set = materialize_benchmark_spec(load_benchmark_spec(args.benchmark_id, paths=DEFAULT_PATHS), paths=DEFAULT_PATHS)
        return list(spec.roles)
    except Exception as exc:  # noqa: BLE001
        ctx.record_issue(
            stage="roles.resolve",
            symptom=str(exc),
            action="Fallback to UI ROLE_ORDER because benchmark spec roles could not be resolved.",
            outcome="Continuing.",
            details=_exception_detail(exc),
        )
        return list(ROLE_ORDER)


def _requested_roles(args: argparse.Namespace) -> list[str]:
    return [item.strip().lower() for item in str(args.roles or "").split(",") if item.strip()]


def _benchmark_request_from_args(args: argparse.Namespace) -> BenchmarkRequest:
    benchmark_games = max(0, int(getattr(args, "benchmark_games", 0) or 0))
    return BenchmarkRequest(
        benchmark_id=args.benchmark_id,
        target_type="role_version",
        roles=_requested_roles(args),
        battle_games=benchmark_games if benchmark_games > 0 else None,
    )


def run_command(command: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=str(DEFAULT_PATHS.root), capture_output=True, text=True, timeout=timeout_seconds, check=False)
        return {
            "check": command[2] if len(command) > 2 else command[0],
            "status": "passed" if proc.returncode == 0 else "failed",
            "command": " ".join(command),
            "returncode": proc.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": redact_text((proc.stdout or "")[-2000:], context="diagnostic"),
            "stderr": redact_text((proc.stderr or "")[-2000:], context="diagnostic"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "check": command[2] if len(command) > 2 else command[0],
            "status": "failed",
            "command": " ".join(command),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": redact_text(str(exc), context="diagnostic"),
            "exception_type": type(exc).__name__,
        }


def _unknown_revision_schema_fallback(proc: dict[str, Any]) -> dict[str, Any] | None:
    text = f"{proc.get('stdout') or ''}\n{proc.get('stderr') or ''}"
    if "Can't locate revision identified by" not in text:
        return None
    required = {
        "wolf": {
            "games",
            "players",
            "decisions",
            "game_events",
            "reports",
            "evaluation_batches",
            "benchmark_leaderboard",
            "benchmark_leaderboard_snapshots",
            "ui_background_tasks",
            "ui_task_events",
        },
        "registry": {
            "role_versions",
            "role_current_baseline",
            "role_baseline_history",
            "skill_files",
            "rejected_proposals",
        },
        "evolution": {
            "evolution_runs",
            "trust_bundles",
            "skill_proposals",
            "experience_candidates",
            "patterns",
            "rejected_proposals",
            "situational_records",
            "decision_outcomes",
            "evolution_rounds",
            "candidate_packages",
            "promotion_decisions",
            "ab_comparison_groups",
        },
    }
    conn = None
    try:
        conn = storage_provider_from_env(paths=DEFAULT_PATHS).open_wolf_connection()
        missing: list[str] = []
        present: list[str] = []
        for schema, tables in sorted(required.items()):
            for table in sorted(tables):
                row = conn.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_name = ? LIMIT 1",
                    (schema, table),
                ).fetchone()
                name = f"{schema}.{table}"
                if row is None:
                    missing.append(name)
                else:
                    present.append(name)
        return {
            "check": "core_schema_after_unknown_alembic_revision",
            "status": "passed" if not missing else "failed",
            "present_count": len(present),
            "missing_count": len(missing),
            "missing": missing,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "check": "core_schema_after_unknown_alembic_revision",
            "status": "failed",
            "error": redact_text(str(exc), context="diagnostic"),
            "exception_type": type(exc).__name__,
        }
    finally:
        if conn is not None:
            conn.close()


def _update_benchmark_manifest(ctx: RunContext, updates: dict[str, Any]) -> None:
    benchmark = ctx.manifest.setdefault("benchmark", {})
    status = str(updates.get("status") or "").lower()
    if status in {"running", "completed"} and "error" not in updates:
        benchmark.pop("error", None)
    benchmark.update(redact(to_jsonable(updates), context="diagnostic"))
    ctx.save_manifest()


def _update_evolution_role_manifest(ctx: RunContext, role: str, updates: dict[str, Any], *, save: bool = True) -> None:
    roles = ctx.manifest.setdefault("evolution", {}).setdefault("roles", {})
    role_state = roles.setdefault(role, {})
    status = str(updates.get("status") or "").lower()
    if status in {"running", "completed", "reviewing", "promoted", "rejected"} and "error" not in updates:
        role_state.pop("error", None)
    role_state.update(redact(to_jsonable(updates), context="diagnostic"))
    if save:
        ctx.save_manifest()


async def _await_with_partial_game_heartbeat(
    ctx: RunContext,
    awaitable: Any,
    *,
    stage: str,
    game_prefix: str,
    role: str | None = None,
    interval_seconds: float = 60.0,
) -> Any:
    task = asyncio.create_task(awaitable)
    while not task.done():
        await asyncio.sleep(max(1.0, float(interval_seconds)))
        progress = _partial_game_progress(game_prefix)
        updates = {
            "last_heartbeat_at": beijing_now_iso(),
            "partial_game_progress": progress,
        }
        if role:
            _update_evolution_role_manifest(ctx, role, updates)
        else:
            _update_benchmark_manifest(ctx, updates)
        ctx.log(
            f"{stage} heartbeat prefix={game_prefix} "
            f"games={progress.get('game_rows', 0)} "
            f"event_games={progress.get('event_game_count', 0)} "
            f"events={progress.get('event_count', 0)} "
            f"decisions={progress.get('decision_count', 0)} "
            f"last_event={progress.get('last_event_at') or ''}"
        )
    return await task


def _partial_game_progress(game_prefix: str) -> dict[str, Any]:
    prefix = str(game_prefix or "").strip()
    if not prefix:
        return {}
    conn = None
    try:
        conn = storage_provider_from_env(paths=DEFAULT_PATHS).open_wolf_connection()
        like = f"{prefix}%"
        game_row = conn.execute(
            "SELECT count(*) AS n, max(finished_at) AS last_finished_at "
            "FROM games WHERE id LIKE ? OR source_run_id LIKE ?",
            (like, like),
        ).fetchone()
        event_row = conn.execute(
            "SELECT count(*) AS n, count(DISTINCT game_id) AS game_count, max(created_at) AS last_event_at "
            "FROM game_events WHERE game_id LIKE ?",
            (like,),
        ).fetchone()
        decision_row = conn.execute(
            "SELECT count(*) AS n, count(DISTINCT game_id) AS game_count, max(created_at) AS last_decision_at "
            "FROM decisions WHERE game_id LIKE ?",
            (like,),
        ).fetchone()
        return {
            "game_prefix": prefix,
            "game_rows": int(game_row["n"] or 0) if game_row is not None else 0,
            "last_finished_at": str(game_row["last_finished_at"]) if game_row is not None and game_row["last_finished_at"] is not None else None,
            "event_count": int(event_row["n"] or 0) if event_row is not None else 0,
            "event_game_count": int(event_row["game_count"] or 0) if event_row is not None else 0,
            "last_event_at": str(event_row["last_event_at"]) if event_row is not None and event_row["last_event_at"] is not None else None,
            "decision_count": int(decision_row["n"] or 0) if decision_row is not None else 0,
            "decision_game_count": int(decision_row["game_count"] or 0) if decision_row is not None else 0,
            "last_decision_at": str(decision_row["last_decision_at"]) if decision_row is not None and decision_row["last_decision_at"] is not None else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "game_prefix": prefix,
            "error": redact_text(str(exc), context="diagnostic"),
            "exception_type": type(exc).__name__,
        }
    finally:
        if conn is not None:
            conn.close()


def _compact_evolution_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    battle = snapshot.get("battle_result") if isinstance(snapshot.get("battle_result"), dict) else {}
    gate = snapshot.get("gate_report") if isinstance(snapshot.get("gate_report"), dict) else {}
    if not gate and isinstance(snapshot.get("promotion_gate"), dict):
        gate = snapshot["promotion_gate"]
    return {
        "status": snapshot.get("status"),
        "current_stage": snapshot.get("current_stage") or progress.get("stage"),
        "progress_percent": progress.get("percent"),
        "training_completed": _count_dicts(snapshot.get("training_games")) or snapshot.get("training_completed"),
        "training_game_count": snapshot.get("training_game_count"),
        "battle_completed": _count_dicts(snapshot.get("battle_games")) or snapshot.get("battle_completed"),
        "battle_game_count": snapshot.get("battle_game_count"),
        "candidate_hash": snapshot.get("candidate_hash"),
        "parent_hash": snapshot.get("parent_hash"),
        "recommendation": snapshot.get("recommendation"),
        "gate_decision": gate.get("decision") or gate.get("recommendation") or battle.get("recommendation"),
        "diagnostic_count": _count_dicts(snapshot.get("diagnostics")),
        "warning_count": len(snapshot.get("warnings", []) or []) if isinstance(snapshot.get("warnings"), list) else None,
        "error_count": len(snapshot.get("errors", []) or []) if isinstance(snapshot.get("errors"), list) else None,
        "proposal_count": _count_dicts(snapshot.get("proposals")),
        "diff_count": _count_dicts(snapshot.get("diff")),
        "last_heartbeat_at": snapshot.get("last_heartbeat_at"),
    }


def _expected_benchmark_games(detail: dict[str, Any]) -> int:
    results = detail.get("results") if isinstance(detail.get("results"), list) else []
    total = sum(int(item.get("game_count") or 0) for item in results if isinstance(item, dict))
    if total:
        return total
    roles = detail.get("roles") if isinstance(detail.get("roles"), list) else []
    benchmark = detail.get("benchmark") if isinstance(detail.get("benchmark"), dict) else {}
    spec = benchmark.get("spec_snapshot") if isinstance(benchmark.get("spec_snapshot"), dict) else {}
    return len(roles) * int(spec.get("game_count") or 0)


def _completed_benchmark_games(detail: dict[str, Any]) -> int:
    summary = detail.get("game_summary") if isinstance(detail.get("game_summary"), dict) else {}
    by_status = summary.get("by_status") if isinstance(summary.get("by_status"), dict) else {}
    completed = int(by_status.get("completed") or 0) + int(by_status.get("reviewing") or 0)
    return completed or int(summary.get("total") or 0)


def _overall_status(manifest: dict[str, Any]) -> str:
    benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
    evolution = manifest.get("evolution") if isinstance(manifest.get("evolution"), dict) else {}
    roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
    failures: list[str] = []
    if benchmark and benchmark.get("status") not in {None, "completed", "completed_selected_scope"}:
        failures.append("benchmark")
    for role, item in roles.items():
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed":
            failures.append(str(role))
    return "completed_with_failures" if failures else "completed"


def _benchmark_completed(manifest: dict[str, Any]) -> bool:
    benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
    if not benchmark:
        return False
    return str(benchmark.get("status") or "").lower() in {"completed", "completed_selected_scope"}


def _reduced_settings(settings: RuntimeSettings) -> RuntimeSettings:
    timeout = settings.game_timeout_seconds
    timeout = 900.0 if timeout is None else max(timeout * 1.5, timeout + 120.0)
    return replace(
        settings,
        game_concurrency=max(1, settings.game_concurrency // 2),
        llm_concurrency=max(1, settings.llm_concurrency // 2) if settings.llm_concurrency > 0 else 0,
        judge_concurrency=max(1, settings.judge_concurrency // 2),
        game_timeout_seconds=timeout,
    )


def _agent_runtime_config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if bool(getattr(args, "agent_fast_smoke", False)):
        config["agent_fast_smoke"] = True

    preset = str(getattr(args, "agent_policy_skip_llm_preset", "") or "").strip()
    actions = str(getattr(args, "agent_policy_skip_llm_actions", "") or "").strip()
    explicit_skip = getattr(args, "agent_policy_skip_llm", None)
    if explicit_skip is not None:
        config["agent_policy_skip_llm_enabled"] = bool(explicit_skip)
    elif preset or actions:
        config["agent_policy_skip_llm_enabled"] = True
    if preset:
        config["agent_policy_skip_llm_preset"] = preset
    if actions:
        config["agent_policy_skip_llm_actions"] = actions
    return config


def _looks_retryable(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in ("timeout", "timed out", "rate", "limit", "connection", "temporary", "circuit", "server"))


def _dedupe_valid_roles(roles: list[str]) -> list[str]:
    valid = set(ROLE_ORDER)
    result: list[str] = []
    for role in roles:
        if role not in valid:
            raise ValueError(f"unsupported role: {role}")
        if role not in result:
            result.append(role)
    return result


def _count_dicts(value: Any) -> int:
    return len([item for item in value if isinstance(item, dict)]) if isinstance(value, list) else 0


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _exception_detail(exc: Exception | str) -> dict[str, Any]:
    if isinstance(exc, str):
        return {"message": redact_text(exc, context="diagnostic")}
    return {
        "exception_type": type(exc).__name__,
        "message": redact_text(str(exc), context="diagnostic"),
        "traceback": redact_text("".join(traceback.format_exception_only(type(exc), exc)), context="diagnostic"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())

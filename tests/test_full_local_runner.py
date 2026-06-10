import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

from tools.research import run_full_local_samples as runner
from tools.research.run_full_local_samples import (
    RuntimeSettings,
    _agent_runtime_config_from_args,
    _benchmark_completed,
    _benchmark_request_from_args,
    parse_args,
)


def test_agent_fast_smoke_runner_config() -> None:
    args = parse_args(["--agent-fast-smoke"])

    assert _agent_runtime_config_from_args(args) == {"agent_fast_smoke": True}


def test_agent_policy_skip_runner_config() -> None:
    args = parse_args(
        [
            "--agent-policy-skip-llm-preset",
            "smoke_fast",
            "--agent-policy-skip-llm-actions",
            "speak,sheriff_speak",
        ]
    )

    assert _agent_runtime_config_from_args(args) == {
        "agent_policy_skip_llm_enabled": True,
        "agent_policy_skip_llm_preset": "smoke_fast",
        "agent_policy_skip_llm_actions": "speak,sheriff_speak",
    }


def test_agent_policy_skip_can_be_explicitly_disabled() -> None:
    args = parse_args(["--no-agent-policy-skip-llm", "--agent-policy-skip-llm-preset", "smoke_fast"])

    assert _agent_runtime_config_from_args(args) == {
        "agent_policy_skip_llm_enabled": False,
        "agent_policy_skip_llm_preset": "smoke_fast",
    }


def test_benchmark_completed_requires_completed_status() -> None:
    assert _benchmark_completed({"benchmark": {"status": "completed"}}) is True
    assert _benchmark_completed({"benchmark": {"status": "completed_selected_scope"}}) is True
    assert _benchmark_completed({"benchmark": {"status": "failed"}}) is False
    assert _benchmark_completed({"benchmark": {"status": "running"}}) is False
    assert _benchmark_completed({}) is False


def test_benchmark_request_honors_roles_argument() -> None:
    args = parse_args(["--roles", "villager, seer"])

    request = _benchmark_request_from_args(args)

    assert request.roles == ["villager", "seer"]


def test_benchmark_request_honors_benchmark_games_override() -> None:
    args = parse_args(["--benchmark-id", "model-baseline-standard-v1", "--benchmark-games", "20"])

    request = _benchmark_request_from_args(args)

    assert request.benchmark_id == "model-baseline-standard-v1"
    assert request.battle_games == 20


def test_benchmark_retry_recreates_runtime_store(monkeypatch: Any) -> None:
    args = parse_args(["--max-retries", "1"])
    initial = RuntimeSettings(
        game_concurrency=32,
        llm_concurrency=40,
        judge_concurrency=8,
        judge_max_decisions=20,
        judge_timeout_seconds=60.0,
        game_timeout_seconds=7200.0,
    )
    created_settings: list[RuntimeSettings] = []
    closed: list[int] = []
    attempts: list[tuple[int, int, int]] = []

    class DummyStore:
        def __init__(self, index: int) -> None:
            self.index = index

        def close(self) -> None:
            closed.append(self.index)

    class DummyCtx:
        def __init__(self) -> None:
            self.manifest: dict[str, Any] = {}
            self.issues: list[dict[str, Any]] = []

        def log(self, _message: str) -> None:
            return None

        def record_issue(self, **kwargs: Any) -> None:
            self.issues.append(kwargs)

        def save_manifest(self, _status: str | None = None) -> None:
            return None

    def fake_create_runtime_store(settings: RuntimeSettings) -> tuple[object, DummyStore]:
        created_settings.append(settings)
        return object(), DummyStore(index=len(created_settings))

    async def fake_run_benchmark_once(
        ctx: DummyCtx,
        store: DummyStore,
        _args: Any,
        settings: RuntimeSettings,
        *,
        attempt: int,
    ) -> None:
        attempts.append((attempt, store.index, settings.game_concurrency))
        if attempt == 1:
            raise RuntimeError("server closed the connection unexpectedly")
        ctx.manifest["benchmark"] = {"status": "completed"}

    monkeypatch.setattr(runner, "_create_runtime_store", fake_create_runtime_store)
    monkeypatch.setattr(runner, "run_benchmark_once", fake_run_benchmark_once)

    ctx = DummyCtx()
    result = asyncio.run(runner.run_benchmark_with_retries(ctx, args, initial))

    assert attempts == [(1, 1, 32), (2, 2, 16)]
    assert closed == [1, 2]
    assert [item.game_concurrency for item in created_settings] == [32, 16]
    assert result == replace(initial, game_concurrency=16, llm_concurrency=20, judge_concurrency=4, game_timeout_seconds=10800.0)


def test_fresh_run_reset_clears_stale_manifest_state(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        """
{
  "kind": "full_local_samples_manifest",
  "schema_version": 1,
  "created_at": "old",
  "status": "running",
  "artifacts": {
    "manifest": "old-manifest",
    "issues_and_fixes": "old-issues",
    "run_report": "old-report",
    "benchmark_report": "old-benchmark-report"
  },
  "benchmark": {
    "status": "failed",
    "batch_id": "bench_old",
    "finished_at": "old"
  },
  "evolution": {
    "roles": {
      "villager": {
        "status": "running",
        "run_id": "evolve_old"
      }
    }
  },
  "tuning": [{"stage": "old"}]
}
""",
        encoding="utf-8",
    )

    ctx = runner.RunContext(output_dir=tmp_path, manifest_path=manifest_path)
    ctx.reset_manifest_for_fresh_run()

    assert ctx.manifest["benchmark"] == {}
    assert ctx.manifest["evolution"] == {"roles": {}}
    assert ctx.manifest["tuning"] == []
    assert "benchmark_report" not in ctx.manifest["artifacts"]
    assert ctx.manifest["artifacts"]["issues_and_fixes"] == str(tmp_path / "ISSUES_AND_FIXES.md")

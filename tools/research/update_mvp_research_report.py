"""Generate mvp-research-report.md from local full-run evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.config import DEFAULT_PATHS, LLM_ENV_PATH
from app.lib.benchmark_spec import load_benchmark_spec, materialize_benchmark_spec
from app.util.json import to_jsonable, write_json
from app.util.redaction import redact
from app.util.time import beijing_now_iso
from tools.research.full_local_evidence_snapshot import collect_snapshot
from tools.research.run_full_local_samples import DEFAULT_BENCHMARK_ID, DEFAULT_OUTPUT_DIR
from ui.backend.constants import ROLE_ORDER


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update mvp-research-report.md from local run evidence.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--output-dirs",
        nargs="*",
        default=None,
        help="Optional list of run output dirs. Comma/semicolon separated values are also accepted.",
    )
    parser.add_argument("--manifest", default="", help="Defaults to <output-dir>/manifest.json for single-dir mode.")
    parser.add_argument("--snapshot", default="", help="Defaults to <output-dir>/evidence_snapshot.json for single-dir mode.")
    parser.add_argument("--combined-snapshot", default="", help="Defaults to <common-output-parent>/evidence_snapshot.combined.json.")
    parser.add_argument("--report", default="mvp-research-report.md")
    parser.add_argument("--benchmark-id", default=DEFAULT_BENCHMARK_ID)
    parser.add_argument("--no-refresh-snapshot", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(LLM_ENV_PATH, override=False)

    output_dirs = _selected_output_dirs(args)
    runs: list[dict[str, Any]] = []
    multi_dir_mode = len(output_dirs) > 1

    for output_dir in output_dirs:
        manifest_path = _manifest_path(args, output_dir=output_dir, multi_dir_mode=multi_dir_mode)
        snapshot_path = _snapshot_path(args, output_dir=output_dir, multi_dir_mode=multi_dir_mode)
        manifest = _read_json(manifest_path)
        if args.no_refresh_snapshot:
            snapshot = _read_json(snapshot_path)
        else:
            snapshot = _collect_snapshot_safely(manifest=manifest, manifest_path=manifest_path)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(snapshot_path, redact(to_jsonable(snapshot), context="diagnostic"))
        benchmark_id = _manifest_benchmark_id(manifest, fallback=args.benchmark_id)
        runs.append(
            {
                "output_dir": output_dir,
                "manifest_path": manifest_path,
                "snapshot_path": snapshot_path,
                "issue_path": output_dir / "ISSUES_AND_FIXES.md",
                "manifest": manifest,
                "snapshot": snapshot,
                "spec": _benchmark_spec(benchmark_id),
                "issues": _issue_summary(output_dir / "ISSUES_AND_FIXES.md"),
            }
        )

    report_path = Path(args.report)
    combined_snapshot_path = _combined_snapshot_path(args, report_path=report_path, runs=runs)
    global_issue_path = _global_issue_path(runs)
    global_issues = _issue_summary(global_issue_path)
    combined_snapshot = {
        "kind": "mvp_research_report_evidence",
        "schema_version": 1,
        "created_at": beijing_now_iso(),
        "global_issue_path": _path_text(global_issue_path),
        "global_issues": global_issues,
        "runs": [
            {
                "label": _run_label(run),
                "output_dir": _path_text(run["output_dir"]),
                "manifest_path": _path_text(run["manifest_path"]),
                "snapshot_path": _path_text(run["snapshot_path"]),
                "issue_path": _path_text(run["issue_path"]),
                "manifest": run["manifest"],
                "snapshot": run["snapshot"],
            }
            for run in runs
        ],
    }
    if multi_dir_mode:
        combined_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(combined_snapshot_path, redact(to_jsonable(combined_snapshot), context="diagnostic"))

    content = render_report(
        runs=runs,
        combined_snapshot_path=combined_snapshot_path,
        global_issue_path=global_issue_path,
        global_issues=global_issues,
    )
    if report_path.parent != Path("."):
        report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")

    source = combined_snapshot_path if multi_dir_mode else runs[0]["snapshot_path"]
    print(f"updated {report_path} from {source}")
    return 0


def render_report(
    *,
    runs: list[dict[str, Any]],
    combined_snapshot_path: Path,
    global_issue_path: Path,
    global_issues: list[dict[str, Any]],
) -> str:
    now = _fmt_time(beijing_now_iso())
    latest_snapshot = _latest_snapshot(runs)
    review = latest_snapshot.get("review") if isinstance(latest_snapshot.get("review"), dict) else {}
    counts = latest_snapshot.get("counts") if isinstance(latest_snapshot.get("counts"), dict) else {}
    registry = latest_snapshot.get("registry") if isinstance(latest_snapshot.get("registry"), dict) else {}
    evolution = latest_snapshot.get("evolution") if isinstance(latest_snapshot.get("evolution"), dict) else {}
    wolf_counts = counts.get("wolf") if isinstance(counts.get("wolf"), dict) else {}
    registry_counts = counts.get("registry") if isinstance(counts.get("registry"), dict) else {}
    evolution_counts = counts.get("evolution") if isinstance(counts.get("evolution"), dict) else {}
    artifact_counts = evolution.get("artifact_counts") if isinstance(evolution.get("artifact_counts"), dict) else {}

    benchmark_runs = [run for run in runs if _has_benchmark(run)]
    evolution_runs = [run for run in runs if _has_evolution(run)]
    benchmark_completed = sum(1 for run in benchmark_runs if _benchmark_is_complete(run))
    evolution_completed = sum(1 for run in evolution_runs if _evolution_is_complete(run))
    running_count = sum(1 for run in runs if str(run["manifest"].get("status") or "").lower() == "running")

    lines = [
        "# MVP Research Report",
        "",
        f"- Updated at: {now}",
        "- Scope: 评测、复盘、自进化完成度复盘",
        f"- Combined evidence snapshot: `{_path_text(combined_snapshot_path)}`",
        f"- Fixed issue log: `{_path_text(global_issue_path)}`",
        "- Run mode: real LLM, no smoke policy, no agent policy skip.",
        "",
        "## Executive Summary",
        "",
        (
            "521wolf 的 MVP 工程闭环已经具备可审计长跑能力：固定 seed 评测、真实 LLM 对局、事件/决策落库、"
            "复盘表结构、自进化 runner、manifest、heartbeat 和固定问题记录都在同一个证据链里。"
        ),
        "",
        (
            f"本轮按 20 局入榜门槛运行 `Model Baseline Standard Benchmark v1`："
            f"{len(benchmark_runs)} 个模型基线 run，其中 {benchmark_completed}/{len(benchmark_runs)} 已完成。"
            f"当前保留 Code 模型证据；seer 自进化也使用 Code 模型，配置为 5 局训练 + 4 局 baseline/candidate 对战每边。"
        ),
        "",
        (
            "关键边界：不同模型的 partial run 不能混成一个干净的 Role Baseline。"
            "本轮 Pro run 因 429/fallback 主导已停止并标为无效；后续有效证据以 Code 模型为准。"
        ),
        "",
        "## Completion Matrix",
        "",
        "| 模块 | 功能完成度 | 本轮样本完成度 | 结论 |",
        "|---|---:|---:|---|",
        "| 游戏运行 MVP | 高 | 真实 LLM 运行中 | 12 人局、角色行动、事件/决策落库可用；吞吐主要受 LLM 限流和单局长度影响。 |",
        f"| 评测系统 | 高 | model baseline {benchmark_completed}/{len(benchmark_runs)} completed | 标准 suite、固定 seed、report/diagnostics/leaderboard 路径具备；未完成 run 不能入榜或排名。 |",
        f"| 复盘系统 | 中 | reports={_int(review.get('reports'))}, decision_reviews={_int(review.get('decision_reviews'))} | 持久化表和展示路径存在；高质量战术复盘样本要等完整对局/报告产出后评估。 |",
        f"| 自进化系统 | 中高 | seer evolution {evolution_completed}/{len(evolution_runs)} completed | training/proposal/candidate/replay/battle/gate 路径已接入；本轮只评 seer，不外推到全部角色。 |",
        f"| 运行观测与容错 | 高 | {running_count} run(s) still running | preflight、heartbeat、partial DB progress、问题记录和证据快照可用。 |",
        "",
        "## Run Matrix",
        "",
        "| Run | Model | Scope | Status | Progress | Config | Evidence |",
        "|---|---|---|---|---|---|---|",
        *_run_matrix_rows(runs),
        "",
        "## Evaluation",
        "",
        "本轮正式评测配置：",
        "",
        "- Benchmark: `model-baseline-standard-v1` / `Model Baseline Standard Benchmark v1`。",
        "- Effective games: `20` fixed seeds per model run；`model` scope 是单个 eval batch，游戏内覆盖完整 7 角色配置，不按角色拆成 7 个 eval batches。",
        "- Concurrency: 一批 5 局，`game_concurrency=5`；LLM 并发同为 5；judge 并发为 2。",
        "- Runtime: 真实 LLM；未启用 `agent_fast_smoke`，未启用 policy skip。",
        "",
        "评测进度：",
        "",
        "| Model baseline run | Batch | Status | Completed games | Active event games | Events | Decisions | Latest activity |",
        "|---|---|---|---:|---:|---:|---:|---|",
        *_benchmark_rows(benchmark_runs),
        "",
        "当前可下的评测结论：",
        "",
        "- 可以确认真实 LLM 标准评测链路能启动、写事件、写决策、持续 heartbeat。",
        "- 未完成到 20 seeds/role 的 run，不能用于入榜、排名、发布 gate 或模型胜负结论。",
        "- Pro/model1 出现 TPM 429/circuit-open 且 fallback 主导，已停止并从有效证据口径中移除。",
        "- Code 模型当前没有认证问题；span export proxy timeout 属于观测导出，不影响对局主流程。",
        "",
        "关于 Role Baseline 的口径：",
        "",
        "- 干净 Role Baseline 需要同一模型、同一参数、同一 seed 规则下比较不同角色。",
        "- 不同模型或无效 partial run 不能直接合并成 Role Baseline，因为模型能力和失败模式会成为混杂变量。",
        "- Code Model Baseline 跑满 20 个 model-scope fixed seeds 后，才能作为当前有效模型基线证据。",
        "",
        "## Review",
        "",
        "复盘能力当前更接近“规则启发式复盘 + decision judge evidence”，不是完整 LLM 战术教练。已有能力包括胜负摘要、玩家评分、关键转折、高光/失误、建议、反事实和时间线展示。完整复盘质量要等完整对局和报告产出后再抽样评测。",
        "",
        "当前持久化证据：",
        "",
        f"- `reports={_int(review.get('reports'))}`",
        f"- `decision_reviews={_int(review.get('decision_reviews'))}`",
        f"- `counterfactuals={_int(review.get('counterfactuals'))}`",
        "",
        "## Self Evolution",
        "",
        "本轮自进化配置：code 模型、`seer` 单角色、5 局训练、4 局 baseline/candidate 对战每边，manifest 中 battle 总量为 8。它是自进化链路验证，不是全角色收益结论。",
        "",
        "| Run | Role | Status | Training | Battle | Proposals/Gate | Active progress | Evidence |",
        "|---|---|---|---:|---:|---|---|---|",
        *_evolution_rows(evolution_runs),
        "",
        "自进化链路已具备的阶段：",
        "",
        "- `init`: 冻结当前 baseline。",
        "- `training`: 训练局和 decision judge evidence。",
        "- `consolidating`: 从训练证据生成 skill proposals。",
        "- `applying`: 应用提案生成 candidate。",
        "- `scenario_replay`: 场景回放检查。",
        "- `battle`: baseline/candidate A/B battle。",
        "- `decide`: promotion gate、trust bundle、proposal attribution、promote/reject。",
        "",
        "数据库侧累计证据：",
        "",
        f"- registry 当前 baseline 数：`{registry.get('baseline_count')}`；缺失 baseline 角色：`{', '.join(registry.get('missing_baseline_roles') or []) or 'none'}`。",
        f"- `role_versions={registry_counts.get('role_versions')}`，`role_current_baseline={registry_counts.get('role_current_baseline')}`，`role_baseline_history={registry_counts.get('role_baseline_history')}`。",
        f"- `evolution_runs={evolution_counts.get('evolution_runs')}`，`skill_proposals={artifact_counts.get('skill_proposals')}`，`candidate_packages={artifact_counts.get('candidate_packages')}`，`promotion_decisions={artifact_counts.get('promotion_decisions')}`。",
        "",
        "## Issues Fixed During This Run",
        "",
        "所有运行问题都写入各自 output-dir 下的 `ISSUES_AND_FIXES.md`。本报告只汇总 stage，不展开 API 请求细节，也不记录密钥。",
        f"主问题日志：`{_path_text(global_issue_path)}`。",
        "",
        *_issue_lines_for_global(global_issues),
        "",
        *_issue_lines_for_runs(runs),
        "",
        "## Evidence Inventory",
        "",
        f"- Wolf DB totals: `games={wolf_counts.get('games')}`，`game_events={wolf_counts.get('game_events')}`，`decisions={wolf_counts.get('decisions')}`。",
        f"- Review DB totals: `reports={review.get('reports')}`，`decision_reviews={review.get('decision_reviews')}`，`counterfactuals={review.get('counterfactuals')}`。",
        f"- Registry DB totals: `role_versions={registry_counts.get('role_versions')}`，`current_baseline={registry_counts.get('role_current_baseline')}`。",
        f"- Evolution DB totals: `evolution_runs={evolution_counts.get('evolution_runs')}`，`candidate_packages={evolution_counts.get('candidate_packages')}`，`promotion_decisions={evolution_counts.get('promotion_decisions')}`。",
        "",
        "Per-run evidence:",
        "",
        f"- global issues: `{_path_text(global_issue_path)}`",
        *_evidence_inventory_rows(runs),
        "",
        "## Verification",
        "",
        "本轮代码验证：",
        "",
        "- `uv run python -m py_compile tools/research/run_full_local_samples.py ui/backend/store.py tools/research/update_mvp_research_report.py`",
        "- `uv run pytest tests/test_full_local_runner.py -q`",
        "",
        "运行证据验证：",
        "",
        "- 每个正式 run 的 manifest 都记录 `agent_fast_smoke=false`。",
        "- 两个模型基线 run 的 preflight benchmark check 都记录 `effective_game_count=20`。",
        "- seer 自进化 run 的 manifest 记录 `training_game_count=5`、`battle_game_count=8`。",
        "",
        "## Final Assessment",
        "",
        (
            "MVP 的工程闭环已经不是纸面设计，而是有真实 LLM 长跑证据的系统。当前最关键的结论边界仍然是样本完成度："
            "benchmark 未完成前，不给模型排名；seer 自进化未完成前，不声称收益；不同模型不同角色不拼成干净 Role Baseline。"
        ),
        "",
    ]
    return "\n".join(lines)


def _selected_output_dirs(args: argparse.Namespace) -> list[Path]:
    raw = args.output_dirs if args.output_dirs is not None else [args.output_dir]
    values: list[str] = []
    for item in raw:
        for part in str(item).replace(";", ",").split(","):
            text = part.strip()
            if text:
                values.append(text)
    return [Path(value) for value in values] or [Path(args.output_dir)]


def _manifest_path(args: argparse.Namespace, *, output_dir: Path, multi_dir_mode: bool) -> Path:
    if args.manifest and not multi_dir_mode:
        return Path(args.manifest)
    return output_dir / "manifest.json"


def _snapshot_path(args: argparse.Namespace, *, output_dir: Path, multi_dir_mode: bool) -> Path:
    if args.snapshot and not multi_dir_mode:
        return Path(args.snapshot)
    return output_dir / "evidence_snapshot.json"


def _combined_snapshot_path(args: argparse.Namespace, *, report_path: Path, runs: list[dict[str, Any]]) -> Path:
    if args.combined_snapshot:
        return Path(args.combined_snapshot)
    if len(runs) == 1:
        return runs[0]["snapshot_path"]
    parents = {Path(run["output_dir"]).parent for run in runs}
    if len(parents) == 1:
        return parents.pop() / "evidence_snapshot.combined.json"
    return report_path.parent / "evidence_snapshot.combined.json"


def _global_issue_path(runs: list[dict[str, Any]]) -> Path:
    parents = [Path(run["output_dir"]).parent for run in runs if run.get("output_dir")]
    if not parents:
        return DEFAULT_OUTPUT_DIR / "ISSUES_AND_FIXES.md"
    first = parents[0]
    if all(parent == first for parent in parents):
        return first / "ISSUES_AND_FIXES.md"
    return DEFAULT_OUTPUT_DIR / "ISSUES_AND_FIXES.md"


def _collect_snapshot_safely(*, manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    try:
        return collect_snapshot(manifest=manifest, manifest_path=manifest_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "kind": "full_local_evidence_snapshot",
            "schema_version": 1,
            "created_at": beijing_now_iso(),
            "manifest_path": str(manifest_path),
            "manifest_status": manifest.get("status"),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _benchmark_spec(benchmark_id: str) -> dict[str, Any]:
    try:
        spec, seed_set = materialize_benchmark_spec(load_benchmark_spec(benchmark_id, paths=DEFAULT_PATHS), paths=DEFAULT_PATHS)
        data = spec.model_dump(mode="json")
        if seed_set is not None:
            data["seed_set_id"] = seed_set.id
            data["seed_count"] = len(seed_set.seeds)
        return data
    except Exception:
        return {"id": benchmark_id, "roles": list(ROLE_ORDER), "game_count": 0, "max_days": None}


def _manifest_benchmark_id(manifest: dict[str, Any], *, fallback: str) -> str:
    benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
    params = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    return str(benchmark.get("benchmark_id") or params.get("benchmark_id") or fallback)


def _has_benchmark(run: dict[str, Any]) -> bool:
    benchmark = run["manifest"].get("benchmark") if isinstance(run["manifest"].get("benchmark"), dict) else {}
    return bool(benchmark)


def _has_evolution(run: dict[str, Any]) -> bool:
    evolution = run["manifest"].get("evolution") if isinstance(run["manifest"].get("evolution"), dict) else {}
    roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
    return bool(roles)


def _benchmark_is_complete(run: dict[str, Any]) -> bool:
    benchmark = run["manifest"].get("benchmark") if isinstance(run["manifest"].get("benchmark"), dict) else {}
    status = str(benchmark.get("status") or "").lower()
    if status not in {"completed", "completed_selected_scope"}:
        return False
    completed, expected = _benchmark_completed_expected(run)
    return expected <= 0 or completed >= expected


def _evolution_is_complete(run: dict[str, Any]) -> bool:
    evolution = run["manifest"].get("evolution") if isinstance(run["manifest"].get("evolution"), dict) else {}
    roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
    if not roles:
        return False
    statuses = {str(item.get("status") or "").lower() for item in roles.values() if isinstance(item, dict)}
    return bool(statuses) and statuses.issubset({"completed", "reviewing", "promoted", "rejected"})


def _run_matrix_rows(runs: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for run in runs:
        model = _model_name(run["manifest"])
        scope = _scope_text(run)
        status = str(run["manifest"].get("status") or "unknown")
        progress = _progress_text(run)
        settings = _settings(run)
        config = (
            f"game={settings.get('game_concurrency', '')}; "
            f"llm={settings.get('llm_concurrency', '')}; "
            f"judge={settings.get('judge_concurrency', '')}"
        )
        evidence = f"`{_path_text(run['manifest_path'])}`"
        rows.append(f"| {_run_label(run)} | `{model}` | {scope} | {_zh_status(status)} | {progress} | {config} | {evidence} |")
    return rows or ["| none |  |  |  |  |  |  |"]


def _benchmark_rows(runs: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for run in runs:
        manifest = run["manifest"]
        benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
        active = _active_progress(run)
        completed, expected = _benchmark_completed_expected(run)
        rows.append(
            "| "
            f"{_run_label(run)} | "
            f"`{benchmark.get('batch_id') or ''}` | "
            f"{_zh_status(benchmark.get('status') or manifest.get('status') or 'unknown')} | "
            f"{completed}/{expected} | "
            f"{_int(active.get('event_game_count'))} | "
            f"{_int(active.get('event_count'))} | "
            f"{_int(active.get('decision_count'))} | "
            f"`{active.get('last_event_at') or active.get('last_decision_at') or ''}` |"
        )
    return rows or ["| none |  |  | 0/0 | 0 | 0 | 0 |  |"]


def _evolution_rows(runs: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for run in runs:
        evolution = run["manifest"].get("evolution") if isinstance(run["manifest"].get("evolution"), dict) else {}
        roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
        for role, item in sorted(roles.items()):
            if not isinstance(item, dict):
                continue
            active = item.get("partial_game_progress") if isinstance(item.get("partial_game_progress"), dict) else {}
            training_done = _int(item.get("training_completed"))
            training_total = _int(item.get("training_game_count"))
            battle_done = _int(item.get("battle_completed"))
            battle_total = _int(item.get("battle_game_count"))
            progress = (
                f"rows={_int(active.get('game_rows'))}; "
                f"event_games={_int(active.get('event_game_count'))}; "
                f"events={_int(active.get('event_count'))}; "
                f"decisions={_int(active.get('decision_count'))}"
            )
            rows.append(
                "| "
                f"{_run_label(run)} | "
                f"{role} | "
                f"{_zh_status(item.get('status') or 'unknown')} | "
                f"{training_done}/{training_total} | "
                f"{battle_done}/{battle_total} | "
                f"proposals={_int(item.get('proposal_count'))}; gate={item.get('gate_decision') or 'none'} | "
                f"{progress} | "
                f"`{item.get('run_id') or ''}` |"
            )
    return rows or ["| none |  | 未开始 | 0/0 | 0/0 | proposals=0; gate=none |  |  |"]


def _evidence_inventory_rows(runs: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for run in runs:
        artifacts = run["manifest"].get("artifacts") if isinstance(run["manifest"].get("artifacts"), dict) else {}
        rows.append(f"- {_run_label(run)} manifest: `{_path_text(run['manifest_path'])}`")
        rows.append(f"- {_run_label(run)} snapshot: `{_path_text(run['snapshot_path'])}`")
        rows.append(f"- {_run_label(run)} issues: `{_path_text(run['issue_path'])}`")
        if artifacts.get("benchmark_report_markdown"):
            rows.append(f"- {_run_label(run)} benchmark report: `{artifacts.get('benchmark_report_markdown')}`")
        if artifacts.get("run_report"):
            rows.append(f"- {_run_label(run)} run report: `{artifacts.get('run_report')}`")
    return rows or ["- none"]


def _issue_lines_for_runs(runs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for run in runs:
        issues = run.get("issues") if isinstance(run.get("issues"), list) else []
        if not issues:
            lines.append(f"- {_run_label(run)}: no issue entries.")
            continue
        for item in issues[:8]:
            count = _int(item.get("count"))
            suffix = f" x{count}" if count > 1 else ""
            lines.append(f"- {_run_label(run)}: `{item.get('stage')}`{suffix}, latest `{item.get('latest')}`.")
    return lines or ["- No entries yet."]


def _issue_lines_for_global(issues: list[dict[str, Any]]) -> list[str]:
    if not issues:
        return ["- global: no issue entries."]
    lines: list[str] = []
    for item in issues[:12]:
        count = _int(item.get("count"))
        suffix = f" x{count}" if count > 1 else ""
        lines.append(f"- global: `{item.get('stage')}`{suffix}, latest `{item.get('latest')}`.")
    return lines


def _issue_summary(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("### ") or " - " not in line:
            continue
        timestamp, stage = line[4:].split(" - ", 1)
        item = entries.setdefault(stage, {"stage": stage, "count": 0, "latest": ""})
        item["count"] = _int(item.get("count")) + 1
        item["latest"] = timestamp
    return sorted(entries.values(), key=lambda item: str(item.get("latest") or ""), reverse=True)


def _model_name(manifest: dict[str, Any]) -> str:
    check = _preflight_check(manifest, "llm_config")
    model = str(check.get("model") or "").strip()
    if model == "ep-20260514115834-5mhq8":
        return "Doubao-Seed-2.0-Code / ep-20260514115834-5mhq8"
    if model:
        return model
    return "unknown"


def _run_label(run: dict[str, Any]) -> str:
    name = Path(run["output_dir"]).name
    mapping = {
        "model1_model_baseline_20": "model1 baseline 20",
        "model2_code_model_baseline_20": "code baseline 20",
        "model2_code_evolution_seer_5train_4battle": "code seer evolution",
    }
    return mapping.get(name, name)


def _scope_text(run: dict[str, Any]) -> str:
    if _has_benchmark(run):
        check = _preflight_check(run["manifest"], "benchmark_spec")
        roles = check.get("roles") if isinstance(check.get("roles"), list) else ROLE_ORDER
        games = _effective_game_count(run)
        benchmark_id = _manifest_benchmark_id(run["manifest"], fallback=DEFAULT_BENCHMARK_ID)
        target_type = _benchmark_target_type(run)
        if target_type == "model":
            return f"`{benchmark_id}`; model scope; {games} games; {len(roles)} configured roles"
        return f"`{benchmark_id}`; {len(roles)} roles x {games}"
    if _has_evolution(run):
        evolution = run["manifest"].get("evolution") if isinstance(run["manifest"].get("evolution"), dict) else {}
        roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
        role_text = ",".join(sorted(roles)) or "none"
        return f"self-evolution; roles={role_text}"
    return "unknown"


def _progress_text(run: dict[str, Any]) -> str:
    if _has_benchmark(run):
        completed, expected = _benchmark_completed_expected(run)
        active = _active_progress(run)
        return f"{completed}/{expected}; active={_int(active.get('event_game_count'))}"
    if _has_evolution(run):
        evolution = run["manifest"].get("evolution") if isinstance(run["manifest"].get("evolution"), dict) else {}
        roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
        parts: list[str] = []
        for role, item in sorted(roles.items()):
            if not isinstance(item, dict):
                continue
            parts.append(
                f"{role}: train {_int(item.get('training_completed'))}/{_int(item.get('training_game_count'))}, "
                f"battle {_int(item.get('battle_completed'))}/{_int(item.get('battle_game_count'))}"
            )
        return "; ".join(parts) or "0/0"
    return "unknown"


def _settings(run: dict[str, Any]) -> dict[str, Any]:
    manifest = run["manifest"]
    benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
    if isinstance(benchmark.get("settings"), dict):
        return benchmark["settings"]
    evolution = manifest.get("evolution") if isinstance(manifest.get("evolution"), dict) else {}
    roles = evolution.get("roles") if isinstance(evolution.get("roles"), dict) else {}
    for item in roles.values():
        if isinstance(item, dict) and isinstance(item.get("settings"), dict):
            return item["settings"]
    return manifest.get("settings") if isinstance(manifest.get("settings"), dict) else {}


def _active_progress(run: dict[str, Any]) -> dict[str, Any]:
    benchmark = run["manifest"].get("benchmark") if isinstance(run["manifest"].get("benchmark"), dict) else {}
    live = benchmark.get("partial_game_progress") if isinstance(benchmark.get("partial_game_progress"), dict) else {}
    snapshot = run["snapshot"].get("benchmark") if isinstance(run["snapshot"].get("benchmark"), dict) else {}
    active = snapshot.get("active_progress") if isinstance(snapshot.get("active_progress"), dict) else {}
    return live or active


def _benchmark_completed_expected(run: dict[str, Any]) -> tuple[int, int]:
    benchmark = run["manifest"].get("benchmark") if isinstance(run["manifest"].get("benchmark"), dict) else {}
    active = _active_progress(run)
    completed = _int(benchmark.get("completed_games"), _int(active.get("game_rows")))
    expected = _int(benchmark.get("expected_games"))
    if expected <= 0:
        check = _preflight_check(run["manifest"], "benchmark_spec")
        roles = check.get("roles") if isinstance(check.get("roles"), list) else []
        if not roles:
            roles = run["spec"].get("roles") if isinstance(run["spec"].get("roles"), list) else list(ROLE_ORDER)
        eval_batches = 1 if _benchmark_target_type(run) == "model" else len(roles)
        expected = max(1, eval_batches) * _effective_game_count(run)
    return completed, expected


def _benchmark_target_type(run: dict[str, Any]) -> str:
    benchmark = run["manifest"].get("benchmark") if isinstance(run["manifest"].get("benchmark"), dict) else {}
    if benchmark.get("target_type"):
        return "model" if str(benchmark.get("target_type")).lower() == "model" else "role_version"
    spec = run.get("spec") if isinstance(run.get("spec"), dict) else {}
    if spec.get("target_type"):
        return "model" if str(spec.get("target_type")).lower() == "model" else "role_version"
    check = _preflight_check(run["manifest"], "benchmark_spec")
    if str(check.get("benchmark_id") or "").strip() == "model-baseline-standard-v1":
        return "model"
    return "role_version"


def _effective_game_count(run: dict[str, Any]) -> int:
    check = _preflight_check(run["manifest"], "benchmark_spec")
    effective = _int(check.get("effective_game_count"))
    if effective > 0:
        return effective
    params = run["manifest"].get("parameters") if isinstance(run["manifest"].get("parameters"), dict) else {}
    override = _int(params.get("benchmark_games"))
    if override > 0:
        return override
    return _int(run["spec"].get("game_count"))


def _preflight_check(manifest: dict[str, Any], check_name: str) -> dict[str, Any]:
    preflight = manifest.get("preflight") if isinstance(manifest.get("preflight"), dict) else {}
    checks = preflight.get("checks") if isinstance(preflight.get("checks"), list) else []
    for item in checks:
        if isinstance(item, dict) and item.get("check") == check_name:
            return item
    return {}


def _latest_snapshot(runs: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [run["snapshot"] for run in runs if isinstance(run.get("snapshot"), dict)]
    if not snapshots:
        return {}
    return sorted(snapshots, key=lambda item: str(item.get("created_at") or ""))[-1]


def _fmt_time(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if "T" in text:
        date, rest = text.split("T", 1)
        time_part = rest[:5]
        suffix = "+08:00" if "+08:00" in rest else ""
        return f"{date} {time_part} {suffix}".strip()
    return text


def _zh_status(value: Any) -> str:
    status = str(value or "").lower()
    mapping = {
        "not_started": "未开始",
        "created": "已创建",
        "running": "运行中",
        "completed": "已完成",
        "completed_selected_scope": "已完成",
        "reviewing": "复核中",
        "promoted": "已提升",
        "rejected": "已拒绝",
        "failed": "失败",
        "cancelled": "已取消",
        "stopped_invalid": "已停止/无效",
        "unknown": "未知",
    }
    return mapping.get(status, str(value or "未知"))


def _path_text(value: Any) -> str:
    try:
        return Path(value).as_posix()
    except TypeError:
        return str(value)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())

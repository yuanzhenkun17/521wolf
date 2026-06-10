"""Benchmark snapshot export helpers."""

from __future__ import annotations

import json
from typing import Any

from ui.backend.services.benchmark_payload_utils import json_clone as _json_clone
from ui.backend.services.benchmark_snapshot_common import (
    _benchmark_snapshot_int,
    _leaderboard_metric,
    _leaderboard_score,
)


def _benchmark_snapshot_release_gate_export_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    release_gate = snapshot.get("release_gate") if isinstance(snapshot.get("release_gate"), dict) else {}
    if not release_gate and isinstance(summary.get("release_gate"), dict):
        release_gate = summary["release_gate"]
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    manifest_gate = manifest.get("release_gate") if isinstance(manifest.get("release_gate"), dict) else {}
    gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
    ok_value = release_gate.get("ok")
    if not isinstance(ok_value, bool):
        ok_value = manifest_gate.get("ok") if isinstance(manifest_gate.get("ok"), bool) else None
    blocker_count = _benchmark_snapshot_int(
        summary.get("release_gate_blocker_count"),
        gate_summary.get("blocker_count"),
        manifest_gate.get("blocker_count"),
        len(release_gate.get("blockers") or []),
    )
    warning_count = _benchmark_snapshot_int(
        summary.get("release_gate_warning_count"),
        gate_summary.get("warning_count"),
        manifest_gate.get("warning_count"),
        len(release_gate.get("warnings") or []),
    )
    return {
        "ok": ok_value,
        "label": "通过" if ok_value is True else ("阻断" if ok_value is False else "未上报"),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "thresholds": _json_clone(gate_summary.get("thresholds") or manifest_gate.get("thresholds") or {}),
        "suite_lifecycle": _json_clone(
            gate_summary.get("suite_lifecycle") or manifest_gate.get("suite_lifecycle") or {}
        ),
    }


def _benchmark_snapshot_markdown(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    release_gate = _benchmark_snapshot_release_gate_export_summary(snapshot)
    thresholds = release_gate["thresholds"]
    lifecycle = release_gate["suite_lifecycle"]
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    lines = [
        f"# 榜单快照：{_markdown_value(snapshot.get('title'))}",
        "",
        "## 快照头",
        f"- 快照 ID: {_markdown_value(snapshot.get('snapshot_id'))}",
        f"- 范围: {_markdown_value(snapshot.get('scope'))}",
        f"- 套件: {_markdown_value(snapshot.get('benchmark_id'))} v{_markdown_value(snapshot.get('benchmark_version'))}",
        f"- 评测集: {_markdown_value(snapshot.get('evaluation_set_id'))}",
        f"- 种子集: {_markdown_value(snapshot.get('seed_set_id'))}",
        f"- Config Hash: {_markdown_value(snapshot.get('benchmark_config_hash'))}",
        f"- 目标角色: {_markdown_value(snapshot.get('target_role'))}",
        f"- 内容 Hash: {_markdown_value(snapshot.get('content_hash'))}",
        f"- 创建时间: {_markdown_value(snapshot.get('created_at'))}",
        f"- 发布门禁: {release_gate['label']} / 阻断 {release_gate['blocker_count']} / 警告 {release_gate['warning_count']}",
        f"- 套件状态: {_markdown_value(lifecycle.get('status') or '未上报')} / launchable={_markdown_value(lifecycle.get('launchable'))}",
        f"- 门禁阈值: sample={_markdown_value(thresholds.get('min_sample_size'))}, completed={_markdown_value(thresholds.get('min_completed_games'))}, paired={_markdown_value(thresholds.get('min_paired_overlap'))}",
        "",
        "## 发布说明",
        _markdown_value(snapshot.get("release_notes") or "未填写"),
        "",
        "## 摘要",
        f"- 行数: {summary.get('row_count', snapshot.get('row_count', 0))}",
        f"- 可入榜: {summary.get('rankable_count', snapshot.get('rankable_count', 0))}",
        f"- 未入榜: {summary.get('unrankable_count', snapshot.get('unrankable_count', 0))}",
        f"- 来源运行: {summary.get('source_run_count', snapshot.get('source_run_count', 0))}",
        f"- 来源报告: {summary.get('source_report_count', snapshot.get('source_report_count', 0))}",
        f"- 来源过滤: {_markdown_value(source.get('source_filter_applied') or summary.get('source_filter_applied') or {})}",
        "",
        "## 冻结行",
    ]
    for index, row in enumerate(rows[:100], start=1):
        if not isinstance(row, dict):
            continue
        score = _leaderboard_score(row, scope=str(snapshot.get("scope") or "role_version"))
        win_rate = _leaderboard_metric(row, "target_side_win_rate")
        lines.append(
            f"- {index}. {_markdown_value(row.get('subject_id') or row.get('hash'))}: "
            f"分数 {score:.4f} / 胜率 {win_rate:.4f} / "
            f"{'可入榜' if row.get('rankable') is not False else '未入榜'} / "
            f"运行 {_markdown_value(row.get('source_run_id') or row.get('batch_id'))} / "
            f"报告 {_markdown_value(row.get('report_id'))}"
        )
    if len(rows) > 100:
        lines.append(f"- 另有 {len(rows) - 100} 行未在 Markdown 预览中展开。")
    if not rows:
        lines.append("- 无冻结行")
    return "\n".join(lines)


def _benchmark_snapshot_csv(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    release_gate = _benchmark_snapshot_release_gate_export_summary(snapshot)
    thresholds = release_gate["thresholds"]
    lifecycle = release_gate["suite_lifecycle"]
    rows: list[list[Any]] = [
        ["区段", "标签", "值", "详情"],
        ["快照头", "快照 ID", snapshot.get("snapshot_id"), ""],
        ["快照头", "标题", snapshot.get("title"), ""],
        ["快照头", "范围", snapshot.get("scope"), ""],
        ["快照头", "套件", snapshot.get("benchmark_id"), snapshot.get("benchmark_version")],
        ["快照头", "评测集", snapshot.get("evaluation_set_id"), ""],
        ["快照头", "种子集", snapshot.get("seed_set_id"), ""],
        ["快照头", "Config Hash", snapshot.get("benchmark_config_hash"), ""],
        ["快照头", "内容 Hash", snapshot.get("content_hash"), ""],
        ["发布门禁", "状态", release_gate["label"], f"阻断 {release_gate['blocker_count']} / 警告 {release_gate['warning_count']}"],
        ["发布门禁", "套件状态", lifecycle.get("status") or "未上报", f"launchable={lifecycle.get('launchable')}"],
        [
            "发布门禁",
            "阈值",
            json.dumps(thresholds, ensure_ascii=False),
            "min_sample_size / min_completed_games / min_paired_overlap",
        ],
        ["发布说明", "说明", snapshot.get("release_notes"), ""],
        ["摘要", "行数", summary.get("row_count", snapshot.get("row_count", 0)), ""],
        ["摘要", "可入榜", summary.get("rankable_count", snapshot.get("rankable_count", 0)), ""],
        ["摘要", "未入榜", summary.get("unrankable_count", snapshot.get("unrankable_count", 0)), ""],
        ["摘要", "来源运行", summary.get("source_run_count", snapshot.get("source_run_count", 0)), ""],
        ["摘要", "来源报告", summary.get("source_report_count", snapshot.get("source_report_count", 0)), ""],
        ["摘要", "来源过滤", json.dumps(source.get("source_filter_applied") or summary.get("source_filter_applied") or {}, ensure_ascii=False), ""],
    ]
    scope = str(snapshot.get("scope") or "role_version")
    for row in snapshot.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        subject = row.get("subject_id") or row.get("hash") or row.get("model_config_hash") or row.get("model_id")
        rows.append([
            "冻结行",
            subject,
            _leaderboard_score(row, scope=scope),
            (
                f"胜率 {row.get('target_side_win_rate', '')} / "
                f"入榜 {row.get('rankable') is not False} / "
                f"运行 {row.get('source_run_id') or row.get('batch_id') or ''} / "
                f"报告 {row.get('report_id') or ''}"
            ),
        ])
    return "\n".join(",".join(_csv_value(value) for value in row) for row in rows)


def _markdown_value(value: Any) -> str:
    return str(value if value is not None else "--").replace("\n", " ").replace("|", "\\|")


def _csv_value(value: Any) -> str:
    text = str(value if value is not None else "")
    if any(char in text for char in [",", "\"", "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text

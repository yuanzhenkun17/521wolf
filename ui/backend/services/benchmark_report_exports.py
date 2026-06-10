"""Benchmark report export helpers."""

from __future__ import annotations

import hashlib
from typing import Any


def _benchmark_run_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 评测运行报告：{_markdown_value(report.get('run_id'))}",
        "",
        "## 报告头",
        f"- 报告 ID: {_markdown_value(report.get('report_id'))}",
        f"- 运行 ID: {_markdown_value(report.get('run_id'))}",
        f"- 套件: {_markdown_value(report.get('suite', {}).get('label'))}",
        f"- 状态: {_markdown_value(report.get('status'))}",
        f"- 对象类型: {_markdown_value(report.get('suite', {}).get('target_type'))}",
        f"- 评测集: {_markdown_value(report.get('suite', {}).get('evaluation_set_id'))}",
        f"- 种子集: {_markdown_value(report.get('suite', {}).get('seed_set_id'))}",
        f"- 评测对象: {_markdown_value(report.get('subject', {}).get('label'))}",
        f"- 内容 Hash: {_markdown_value(report.get('content_hash'))}",
        "",
        "## 摘要",
    ]
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    game_summary = summary.get("game_summary") if isinstance(summary.get("game_summary"), dict) else {}
    diagnostic_summary = summary.get("diagnostic_summary") if isinstance(summary.get("diagnostic_summary"), dict) else {}
    lines.extend(
        [
            f"- 可入榜: {summary.get('rankable_count', 0)}/{summary.get('result_count', 0)}",
            f"- 结果数: {summary.get('result_count', 0)}",
            f"- 对局数: {game_summary.get('total', 0)}（{summary.get('problem_game_count', 0)} 个问题样本）",
            f"- 诊断数: {diagnostic_summary.get('total', 0)}",
            "",
            "## 门禁摘要",
        ]
    )
    gates = report.get("gates") if isinstance(report.get("gates"), list) else []
    lines.extend(
        [
            f"- {_markdown_value(row.get('title'))}: {_markdown_value(row.get('status'))} - {_markdown_value(row.get('reason'))}"
            for row in gates[:16]
            if isinstance(row, dict)
        ]
        or ["- 未加载门禁行"]
    )
    lines.extend(["", "## 问题对局"])
    problem_games = report.get("problem_games") if isinstance(report.get("problem_games"), list) else []
    lines.extend(
        [
            f"- {_markdown_value(game.get('game_id'))}: {_markdown_value(game.get('status'))} / 种子 {_markdown_value(game.get('seed'))} / 诊断 {game.get('diagnostic_count', 0)} / 回放 {_markdown_value(game.get('history_game_id') or game.get('replay_unavailable_reason') or '不可用')}"
            for game in problem_games[:8]
            if isinstance(game, dict)
        ]
        or ["- 未加载对局样本"]
    )
    lines.extend(["", "## 诊断与标签"])
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), list) else []
    tags = report.get("tags") if isinstance(report.get("tags"), list) else []
    if diagnostics:
        lines.extend(
            f"- {_markdown_value(group.get('label'))}: {group.get('total', 0)} ({_markdown_value(group.get('level'))})"
            for group in diagnostics[:12]
            if isinstance(group, dict)
        )
    elif tags:
        lines.extend(
            f"- {_markdown_value(tag.get('label'))}: {tag.get('count', 0)}"
            for tag in tags[:12]
            if isinstance(tag, dict)
        )
    else:
        lines.append("- 未加载诊断")
    lines.extend(["", "## 复现包"])
    reproducibility = report.get("reproducibility") if isinstance(report.get("reproducibility"), dict) else {}
    lines.extend(f"- {_markdown_value(key)}: {_markdown_value(value)}" for key, value in reproducibility.items())
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    if model_runtime:
        lines.extend(
            [
                "",
                "## 模型运行配置",
                f"- 来源: {_markdown_value(model_runtime.get('source'))}",
                f"- 模型 ID: {_markdown_value(model_runtime.get('model_id'))}",
                f"- 配置 Hash: {_markdown_value(model_runtime.get('model_config_hash'))}",
                f"- Hash 来源: {'请求提供' if model_runtime.get('hash_provided') else '后端自动生成'}",
            ]
        )
    return "\n".join(lines)


def _benchmark_run_report_csv(report: dict[str, Any]) -> str:
    rows: list[list[Any]] = [["区段", "标签", "值", "详情"]]
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    rows.extend(
        [
            ["报告头", "运行 ID", report.get("run_id"), ""],
            ["报告头", "报告 ID", report.get("report_id"), ""],
            ["报告头", "套件", suite.get("label"), ""],
            ["报告头", "状态", report.get("status"), ""],
            ["报告头", "对象类型", suite.get("target_type"), ""],
            ["报告头", "评测集", suite.get("evaluation_set_id"), ""],
            ["报告头", "种子集", suite.get("seed_set_id"), ""],
            ["报告头", "评测对象", subject.get("label"), ""],
            ["报告头", "内容 Hash", report.get("content_hash"), ""],
        ]
    )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    rows.extend(
        [
            ["摘要", "结果数", summary.get("result_count", 0), ""],
            ["摘要", "可入榜", summary.get("rankable_count", 0), f"{summary.get('unrankable_count', 0)} 个未入榜"],
            ["摘要", "问题对局", summary.get("problem_game_count", 0), ""],
        ]
    )
    for gate in report.get("gates", []) or []:
        if isinstance(gate, dict):
            rows.append(["门禁", gate.get("title"), gate.get("status"), gate.get("reason")])
    for game in report.get("problem_games", []) or []:
        if isinstance(game, dict):
            rows.append(
                [
                    "对局",
                    game.get("game_id"),
                    game.get("status"),
                    f"种子 {game.get('seed')} / 诊断 {game.get('diagnostic_count', 0)} / 日志 {game.get('history_game_id') or ''}",
                ]
            )
    for group in report.get("diagnostics", []) or []:
        if isinstance(group, dict):
            rows.append(["诊断", group.get("label"), group.get("total"), group.get("level")])
    reproducibility = report.get("reproducibility") if isinstance(report.get("reproducibility"), dict) else {}
    rows.extend(["复现包", key, value, ""] for key, value in reproducibility.items())
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    if model_runtime:
        rows.extend(
            [
                ["模型运行配置", "来源", model_runtime.get("source"), ""],
                ["模型运行配置", "模型 ID", model_runtime.get("model_id"), ""],
                ["模型运行配置", "配置 Hash", model_runtime.get("model_config_hash"), ""],
                ["模型运行配置", "Hash 来源", "请求提供" if model_runtime.get("hash_provided") else "后端自动生成", ""],
            ]
        )
    return "\n".join(",".join(_csv_value(value) for value in row) for row in rows)


def _markdown_value(value: Any) -> str:
    return str(value if value is not None else "--").replace("\n", " ").replace("|", "\\|")


def _csv_value(value: Any) -> str:
    text = str(value if value is not None else "")
    if any(char in text for char in [",", "\"", "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def _text_content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

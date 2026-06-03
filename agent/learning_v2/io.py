"""File I/O helpers for learning_v2 evidence outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from agent.learning_v2.models import EvidenceRunResult, GameEvidenceBundle


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in rows:
        data = row.to_dict() if hasattr(row, "to_dict") else row
        lines.append(json.dumps(data, ensure_ascii=False, default=str))
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_game_bundle(game_dir: Path | str) -> GameEvidenceBundle:
    base = Path(game_dir)
    archive = read_json(base / "archive.json")
    meta_path = base / "meta.json"
    meta = read_json(meta_path) if meta_path.exists() else {}
    game_id = str(archive.get("game_id") or meta.get("game_id") or base.name)
    return GameEvidenceBundle(
        game_dir=base,
        game_id=game_id,
        archive=archive,
        agent_decisions=read_jsonl(base / "agent_decisions.jsonl"),
        game_events=read_jsonl(base / "game_events.jsonl"),
        meta=meta,
    )


def write_evidence_outputs(result: EvidenceRunResult, report_markdown: str, output_dir: Path | str) -> None:
    base = Path(output_dir)
    write_jsonl(base / "evidence_inputs.jsonl", result.evidence_inputs)
    write_json(base / "key_decisions.json", [item.to_dict() for item in result.key_decisions])
    write_jsonl(base / "decision_evidence.jsonl", result.decision_evidence)
    write_json(base / "game_evidence.json", result.game_evidence.to_dict())
    write_jsonl(base / "experience_candidates.jsonl", result.experience_candidates)
    write_text(base / "evidence_report.md", report_markdown)
    if result.raw_output:
        write_text(base / "raw_judge_output.txt", result.raw_output)
    if result.errors:
        write_json(base / "errors.json", result.errors)


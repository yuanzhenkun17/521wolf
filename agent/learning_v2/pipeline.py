"""Top-level learning_v2 evidence pipeline."""

from __future__ import annotations

from pathlib import Path

from agent.infrastructure.llm import ModelAdapter
from agent.learning_v2.io import load_game_bundle, write_evidence_outputs
from agent.learning_v2.judge import judge_game_evidence
from agent.learning_v2.models import DecisionEvidenceInput, EvidenceRunResult, GameEvidence, KeyDecision
from agent.learning_v2.normalizer import normalize_decisions
from agent.learning_v2.report import render_evidence_report
from agent.learning_v2.selector import select_key_decisions


async def run_evidence_pipeline(
    game_dir: Path | str,
    model: ModelAdapter | None = None,
    output_dir: Path | str | None = None,
    *,
    use_llm: bool = True,
) -> EvidenceRunResult:
    bundle = load_game_bundle(game_dir)
    evidence_inputs = normalize_decisions(bundle)
    key_decisions = select_key_decisions(evidence_inputs, bundle)

    if use_llm:
        if model is None:
            result = _base_result(bundle.game_id, bundle.archive.get("winner"), evidence_inputs, key_decisions)
            result.errors.append("use_llm=True requires a model")
        else:
            result = await judge_game_evidence(model, bundle, evidence_inputs, key_decisions)
    else:
        result = _base_result(bundle.game_id, bundle.archive.get("winner"), evidence_inputs, key_decisions)

    out = Path(output_dir) if output_dir else Path(game_dir) / "learning_v2"
    result.output_dir = out
    report = render_evidence_report(result)
    write_evidence_outputs(result, report, out)
    return result


def _base_result(
    game_id: str,
    winner: object,
    evidence_inputs: list[DecisionEvidenceInput],
    key_decisions: list[KeyDecision],
) -> EvidenceRunResult:
    return EvidenceRunResult(
        game_id=game_id,
        evidence_inputs=evidence_inputs,
        key_decisions=key_decisions,
        game_evidence=GameEvidence(winner=str(winner or "")),
    )

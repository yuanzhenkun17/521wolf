"""Mid-term memory — per-game LLM analysis report.

After each game completes, the LLM analyzes the full game to produce
a structured report with multi-dimensional scoring, key decision reviews,
counterfactual reasoning, strategic insights, and error patterns.

Reports are stored in ``data/mid_memory/`` and consumed by the
long-term consolidator every N games.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.models import Role

from agent.evaluation.review_enhanced import GameReviewReport
from agent.prompts.parsing import load_json_object
from agent.runtime.model import ModelAdapter


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MID_MEMORY_DIR = _PROJECT_ROOT / "data" / "mid_memory"


@dataclass(slots=True)
class TurningPointAnalysis:
    day: int
    phase: str
    description: str
    impact: str  # "positive" | "negative" | "mixed"
    affected_team: str
    root_cause: str

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "description": self.description,
            "impact": self.impact,
            "affected_team": self.affected_team,
            "root_cause": self.root_cause,
        }


@dataclass(slots=True)
class DecisionReview:
    player_id: int
    role: str
    day: int
    phase: str
    action_type: str
    quality_score: float  # 0-10
    verdict: str
    reasoning: str
    improvement: str

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "role": self.role,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "quality_score": round(self.quality_score, 1),
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "improvement": self.improvement,
        }


@dataclass(slots=True)
class CounterfactualAnalysis:
    scenario: str
    original_outcome: str
    counterfactual_outcome: str
    likelihood: str  # "high" | "medium" | "low"
    insight: str

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "original_outcome": self.original_outcome,
            "counterfactual_outcome": self.counterfactual_outcome,
            "likelihood": self.likelihood,
            "insight": self.insight,
        }


@dataclass(slots=True)
class GameAnalysis:
    game_id: str
    generated_at: str
    winner: str
    roles: dict[int, str]
    # Multi-dimensional scores (from review, no LLM needed)
    player_scores: dict[int, dict[str, Any]] = field(default_factory=dict)
    team_scores: dict[str, float] = field(default_factory=dict)
    # LLM analysis
    turning_points: list[TurningPointAnalysis] = field(default_factory=list)
    decision_reviews: list[DecisionReview] = field(default_factory=list)
    counterfactuals: list[CounterfactualAnalysis] = field(default_factory=list)
    strategic_insights: list[str] = field(default_factory=list)
    error_patterns: list[str] = field(default_factory=list)
    # Metadata
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "generated_at": self.generated_at,
            "winner": self.winner,
            "roles": {str(k): v for k, v in self.roles.items()},
            "player_scores": self.player_scores,
            "team_scores": self.team_scores,
            "turning_points": [tp.to_dict() for tp in self.turning_points],
            "decision_reviews": [dr.to_dict() for dr in self.decision_reviews],
            "counterfactuals": [cf.to_dict() for cf in self.counterfactuals],
            "strategic_insights": self.strategic_insights,
            "error_patterns": self.error_patterns,
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Game Analysis: {self.game_id}",
            "",
            f"- Winner: {self.winner}",
            f"- Generated: {self.generated_at}",
            "",
            "## Player Scores",
            "",
        ]
        for pid, scores in sorted(self.player_scores.items()):
            role = self.roles.get(pid, "?")
            total = scores.get("total_score", 0)
            lines.append(f"- P{pid} ({role}): {total:.1f}")
            dims = []
            for dim in ("speech_score", "vote_score", "skill_score", "information_score", "cooperation_score"):
                v = scores.get(dim)
                if v is not None:
                    dims.append(f"{dim.replace('_score', '')}={v:.1f}")
            if dims:
                lines.append(f"  - {', '.join(dims)}")

        if self.turning_points:
            lines.extend(["", "## Key Turning Points", ""])
            for tp in self.turning_points:
                lines.append(f"- **Day {tp.day} {tp.phase}**: {tp.description}")
                lines.append(f"  - Impact: {tp.impact} ({tp.affected_team})")
                lines.append(f"  - Root cause: {tp.root_cause}")

        if self.decision_reviews:
            lines.extend(["", "## Decision Reviews", ""])
            for dr in self.decision_reviews:
                lines.append(f"- **P{dr.player_id} ({dr.role}) Day {dr.day} {dr.action_type}**: {dr.verdict} (score={dr.quality_score:.1f})")
                lines.append(f"  - {dr.reasoning}")
                lines.append(f"  - Improvement: {dr.improvement}")

        if self.counterfactuals:
            lines.extend(["", "## Counterfactual Analysis", ""])
            for cf in self.counterfactuals:
                lines.append(f"- **{cf.scenario}** (likelihood: {cf.likelihood})")
                lines.append(f"  - Original: {cf.original_outcome}")
                lines.append(f"  - Counterfactual: {cf.counterfactual_outcome}")
                lines.append(f"  - Insight: {cf.insight}")

        if self.strategic_insights:
            lines.extend(["", "## Strategic Insights", ""])
            for insight in self.strategic_insights:
                lines.append(f"- {insight}")

        if self.error_patterns:
            lines.extend(["", "## Error Patterns", ""])
            for pattern in self.error_patterns:
                lines.append(f"- {pattern}")

        if self.errors:
            lines.extend(["", "## Errors", ""])
            for error in self.errors:
                lines.append(f"- {error}")

        return "\n".join(lines).rstrip() + "\n"


async def analyze_game(
    *,
    model: ModelAdapter,
    game_id: str,
    review: GameReviewReport,
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, Role],
    winner_team: str,
) -> GameAnalysis:
    """Run LLM analysis on a completed game."""
    player_scores: dict[int, dict[str, Any]] = {}
    for pid, pr in review.player_scores.items():
        player_scores[pid] = pr.to_dict()

    roles_str = {pid: role.value for pid, role in roles.items()}

    messages = _build_messages(
        review=review,
        agent_decisions=agent_decisions,
        roles=roles_str,
        winner_team=winner_team,
    )

    raw = ""
    try:
        raw = await model.complete(messages, name=f"mid_memory/{game_id}")
        return _parse_analysis(
            game_id=game_id,
            raw_output=raw,
            roles=roles_str,
            winner_team=winner_team,
            player_scores=player_scores,
            team_scores=review.team_scores,
        )
    except Exception as exc:
        return _fallback_analysis(
            game_id=game_id,
            roles=roles_str,
            winner_team=winner_team,
            player_scores=player_scores,
            team_scores=review.team_scores,
            raw_output=raw,
            error=str(exc),
        )


def write_game_analysis(
    analysis: GameAnalysis,
    *,
    output_dir: Path | str | None = None,
) -> Path:
    """Write GameAnalysis to JSON file."""
    base = Path(output_dir) if output_dir else MID_MEMORY_DIR
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{analysis.game_id}.json"
    json_path.write_text(
        json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path


def load_game_analysis(game_id: str, *, mid_memory_dir: Path | str | None = None) -> GameAnalysis | None:
    """Load a GameAnalysis from disk."""
    base = Path(mid_memory_dir) if mid_memory_dir else MID_MEMORY_DIR
    path = base / f"{game_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _analysis_from_dict(data)


def load_recent_analyses(count: int = 5, *, mid_memory_dir: Path | str | None = None) -> list[GameAnalysis]:
    """Load the most recent N game analyses."""
    base = Path(mid_memory_dir) if mid_memory_dir else MID_MEMORY_DIR
    if not base.exists():
        return []
    json_files = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    analyses: list[GameAnalysis] = []
    for path in json_files[:count]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            analyses.append(_analysis_from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    return analyses


# ── Internal helpers ──────────────────────────────────────────────────────


def _build_messages(
    *,
    review: GameReviewReport,
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, str],
    winner_team: str,
) -> list[dict[str, str]]:
    simplified_decisions: dict[int, list[dict]] = {}
    for pid, decisions in agent_decisions.items():
        simplified = []
        for d in decisions:
            parsed = d.get("parsed_decision") or {}
            simplified.append({
                "day": d.get("day"),
                "phase": d.get("phase"),
                "action_type": d.get("action_type"),
                "selected_skills": d.get("selected_skills", []),
                "target": d.get("selected_target") or parsed.get("target"),
                "choice": d.get("selected_choice") or parsed.get("choice"),
                "confidence": d.get("confidence"),
                "source": d.get("source"),
                "private_reasoning": parsed.get("private_reasoning", "")[:200],
            })
        simplified_decisions[pid] = simplified

    return [
        {
            "role": "system",
            "content": (
                "你是狼人杀游戏的赛后分析师。"
                "你需要对一局完整的游戏进行深度分析，包括关键转折点、决策质量评估、反事实推演、策略洞察和错误模式。"
                "必须输出 JSON，不要输出额外自然语言。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"游戏结果: {winner_team} 获胜\n"
                f"角色配置: {json.dumps(roles, ensure_ascii=False)}\n\n"
                f"规则评测报告:\n{_compact_json(review.to_dict())}\n\n"
                f"玩家决策记录:\n{_compact_json(simplified_decisions)}\n\n"
                "请生成结构化分析报告，要求:\n"
                "1. key_turning_points: 关键转折点，需要分析根因（不只是事件描述）\n"
                "2. decision_reviews: 对高影响决策的深度复盘，给出 0-10 分质量评分和改进建议\n"
                "3. counterfactuals: 反事实推演，分析'如果不是这样会怎样'\n"
                "4. strategic_insights: 3-5 条可复用的策略洞察\n"
                "5. error_patterns: 2-3 条反复出现的错误模式\n\n"
                "输出 JSON schema:\n"
                "{\n"
                '  "turning_points": [\n'
                "    {\n"
                '      "day": 1, "phase": "night",\n'
                '      "description": "事件描述",\n'
                '      "impact": "positive|negative|mixed",\n'
                '      "affected_team": "werewolves|villagers",\n'
                '      "root_cause": "根因分析"\n'
                "    }\n"
                "  ],\n"
                '  "decision_reviews": [\n'
                "    {\n"
                '      "player_id": 1, "role": "seer",\n'
                '      "day": 1, "phase": "night",\n'
                '      "action_type": "seer_check",\n'
                '      "quality_score": 7.5,\n'
                '      "verdict": "good|mediocre|poor",\n'
                '      "reasoning": "评估理由",\n'
                '      "improvement": "改进建议"\n'
                "    }\n"
                "  ],\n"
                '  "counterfactuals": [\n'
                "    {\n"
                '      "scenario": "假设场景",\n'
                '      "original_outcome": "实际结果",\n'
                '      "counterfactual_outcome": "假设结果",\n'
                '      "likelihood": "high|medium|low",\n'
                '      "insight": "洞察"\n'
                "    }\n"
                "  ],\n"
                '  "strategic_insights": ["策略洞察1", "策略洞察2"],\n'
                '  "error_patterns": ["错误模式1", "错误模式2"]\n'
                "}"
            ),
        },
    ]


def _parse_analysis(
    *,
    game_id: str,
    raw_output: str,
    roles: dict[int, str],
    winner_team: str,
    player_scores: dict[int, dict[str, Any]],
    team_scores: dict[str, float],
) -> GameAnalysis:
    data = load_json_object(raw_output)

    turning_points = [
        TurningPointAnalysis(
            day=int(tp.get("day", 0)),
            phase=str(tp.get("phase", "")),
            description=str(tp.get("description", "")),
            impact=str(tp.get("impact", "mixed")),
            affected_team=str(tp.get("affected_team", "")),
            root_cause=str(tp.get("root_cause", "")),
        )
        for tp in data.get("turning_points", [])
        if isinstance(tp, dict)
    ][:8]

    decision_reviews = [
        DecisionReview(
            player_id=int(dr.get("player_id", 0)),
            role=str(dr.get("role", "")),
            day=int(dr.get("day", 0)),
            phase=str(dr.get("phase", "")),
            action_type=str(dr.get("action_type", "")),
            quality_score=_as_float(dr.get("quality_score"), 5.0),
            verdict=str(dr.get("verdict", "")),
            reasoning=str(dr.get("reasoning", "")),
            improvement=str(dr.get("improvement", "")),
        )
        for dr in data.get("decision_reviews", [])
        if isinstance(dr, dict)
    ][:12]

    counterfactuals = [
        CounterfactualAnalysis(
            scenario=str(cf.get("scenario", "")),
            original_outcome=str(cf.get("original_outcome", "")),
            counterfactual_outcome=str(cf.get("counterfactual_outcome", "")),
            likelihood=str(cf.get("likelihood", "medium")),
            insight=str(cf.get("insight", "")),
        )
        for cf in data.get("counterfactuals", [])
        if isinstance(cf, dict)
    ][:8]

    return GameAnalysis(
        game_id=game_id,
        generated_at=_now(),
        winner=winner_team,
        roles=roles,
        player_scores=player_scores,
        team_scores=team_scores,
        turning_points=turning_points,
        decision_reviews=decision_reviews,
        counterfactuals=counterfactuals,
        strategic_insights=[str(s) for s in data.get("strategic_insights", [])][:5],
        error_patterns=[str(s) for s in data.get("error_patterns", [])][:3],
        raw_output=raw_output,
    )


def _fallback_analysis(
    *,
    game_id: str,
    roles: dict[int, str],
    winner_team: str,
    player_scores: dict[int, dict[str, Any]],
    team_scores: dict[str, float],
    raw_output: str = "",
    error: str = "",
) -> GameAnalysis:
    return GameAnalysis(
        game_id=game_id,
        generated_at=_now(),
        winner=winner_team,
        roles=roles,
        player_scores=player_scores,
        team_scores=team_scores,
        raw_output=raw_output,
        errors=[error] if error else [],
    )


def _analysis_from_dict(data: dict[str, Any]) -> GameAnalysis:
    return GameAnalysis(
        game_id=str(data.get("game_id", "")),
        generated_at=str(data.get("generated_at", "")),
        winner=str(data.get("winner", "")),
        roles={int(k): str(v) for k, v in data.get("roles", {}).items()},
        player_scores=data.get("player_scores", {}),
        team_scores=data.get("team_scores", {}),
        turning_points=[
            TurningPointAnalysis(**tp) for tp in data.get("turning_points", [])
        ],
        decision_reviews=[
            DecisionReview(**dr) for dr in data.get("decision_reviews", [])
        ],
        counterfactuals=[
            CounterfactualAnalysis(**cf) for cf in data.get("counterfactuals", [])
        ],
        strategic_insights=[str(s) for s in data.get("strategic_insights", [])],
        error_patterns=[str(s) for s in data.get("error_patterns", [])],
        raw_output=str(data.get("raw_output", "")),
        errors=[str(e) for e in data.get("errors", [])],
    )


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

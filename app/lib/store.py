"""Store helpers — GamePersistence, GameRunService, decision logging."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from engine import ActionType
from app.util.json import DictMixin, write_json


# ---------------------------------------------------------------------------
# DecisionRecord
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisionRecord(DictMixin):
    action_type: ActionType
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    day: int = 0
    phase: str = ""
    player_id: int | None = None
    role: str = ""
    candidates: list[int] = field(default_factory=list)
    selected_target: int | None = None
    selected_choice: str | None = None
    public_text: str = ""
    private_reasoning: str = ""
    confidence: float = 0.0
    alternatives: list[int] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    memory_summary: list[str] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)
    policy_adjustments: list[str] = field(default_factory=list)
    source: Literal["llm", "llm_error", "fallback", "policy_adjusted", "tot", "got"] = "llm"


class DecisionSink(Protocol):
    def record_decision(self, decision: DecisionRecord) -> None:
        """Persist one decision record."""


class AgentDecisionRecorder:
    def __init__(self, stream_path: str | Path | None = None, sink: DecisionSink | None = None) -> None:
        self.records: list[DecisionRecord] = []
        self._stream_path: Path | None = Path(stream_path) if stream_path else None
        if self._stream_path:
            self._stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream_path.touch()
        self._sink = sink

    def record(self, decision: DecisionRecord) -> None:
        self.records.append(decision)
        if self._stream_path:
            line = json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True)
            with self._stream_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if self._sink is not None:
            self._sink.record_decision(decision)

    def to_jsonl(self) -> str:
        lines = [json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True) for r in self.records]
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_jsonl(), encoding="utf-8")
        return output


# ---------------------------------------------------------------------------
# GameRunConfig + GameRunHandle
# ---------------------------------------------------------------------------

@dataclass
class GameRunConfig:
    """Configuration for creating a new game run."""
    run_type: str = "ordinary_game"
    mode: str = "dev"
    run_id: str | None = None
    game_dir: Path | str | None = None
    source_game_id: str | None = None
    seed: int | None = None
    max_days: int = 20
    player_count: int = 12
    ruleset_version: str = "werewolf_12p_v1"
    model_id: str | None = None
    model_config_hash: str | None = None
    role_version_config: dict[str, str] = field(default_factory=dict)
    comparison_group_id: str | None = None
    comparison_type: str | None = None
    target_role: str | None = None
    target_version_id: str | None = None
    seed_set_id: str | None = None
    evaluation_set_id: str | None = None
    paired_seed: bool = False


@dataclass
class GameRunHandle:
    """Handle returned by GameRunService.create_run()."""
    run_id: str
    config: GameRunConfig
    policy: Any
    persistence: Any

    @property
    def game_id(self) -> str:
        return self.run_id

    def close(self) -> None:
        self.persistence.close()


class GameRunService:
    """Central service for creating app-layer game persistence sessions."""

    def __init__(self, *, db_path: Path | str | None = None, paths: Any | None = None) -> None:
        self._db_path = Path(db_path) if db_path else None
        self._paths = paths

    def create_run(self, config: GameRunConfig) -> GameRunHandle:
        """Create a run with the correct storage policy and persistence handle."""
        return self._create_run(config=config, conn=None)

    def create_run_with_connection(
        self,
        config: GameRunConfig,
        conn: sqlite3.Connection | None,
    ) -> GameRunHandle:
        """Create a run backed by an existing SQLite connection."""
        return self._create_run(config=config, conn=conn)

    def _create_run(
        self,
        *,
        config: GameRunConfig,
        conn: sqlite3.Connection | None,
    ) -> GameRunHandle:
        from storage.run_policy import RunType, policy_for_run_type
        from storage.runtime import GamePersistence

        run_id = config.run_id or _generate_id()
        run_type = config.run_type if isinstance(config.run_type, RunType) else RunType(str(config.run_type))
        policy = policy_for_run_type(run_type)
        metadata = _run_metadata(config, run_id)

        persistence_kwargs: dict[str, Any] = {
            "game_id": run_id,
            "game_dir": config.game_dir,
            "source_game_id": config.source_game_id,
            "run_policy": policy,
            "run_metadata": metadata,
            "evolution_db_path": self._resolve_evolution_db_path(),
        }
        if conn is not None:
            persistence_kwargs["conn"] = conn
        else:
            persistence_kwargs["db_path"] = self._resolve_db_path()

        return GameRunHandle(
            run_id=run_id,
            config=config,
            policy=policy,
            persistence=GamePersistence(**persistence_kwargs),
        )

    def _resolve_db_path(self) -> Path | None:
        if self._db_path is not None:
            return self._db_path
        if self._paths is not None:
            if hasattr(self._paths, "wolf_db_path"):
                return Path(self._paths.wolf_db_path)
            if hasattr(self._paths, "db_path"):
                return Path(self._paths.db_path)
        from app.config import DEFAULT_PATHS

        return DEFAULT_PATHS.wolf_db_path

    def _resolve_evolution_db_path(self) -> Path | None:
        if self._paths is not None and hasattr(self._paths, "evolution_db_path"):
            return Path(self._paths.evolution_db_path)
        from app.config import DEFAULT_PATHS

        return DEFAULT_PATHS.evolution_db_path


# ---------------------------------------------------------------------------
# GameArchive + AgentTraceRecorder
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisionArchive:
    """Full trace of a single agent decision."""
    decision_id: str
    index: int
    player_id: int
    role: str
    day: int
    phase: str
    action_type: str
    candidates: list[int]
    observation_summary: dict
    memory_context: dict
    selected_skills: list[str]
    prompt_messages: list[dict]
    raw_output: str
    parsed_decision: dict
    final_response: dict
    source: str
    confidence: float | None
    policy_adjustments: list[str]
    errors: list[str]

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "index": self.index,
            "player_id": self.player_id,
            "role": self.role,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "candidates": list(self.candidates),
            "observation_summary": _sanitize(self.observation_summary),
            "memory_context": _sanitize(self.memory_context),
            "selected_skills": list(self.selected_skills),
            "prompt_messages": _sanitize(self.prompt_messages),
            "raw_output": self.raw_output,
            "parsed_decision": _sanitize(self.parsed_decision),
            "final_response": _sanitize(self.final_response),
            "source": self.source,
            "confidence": self.confidence,
            "policy_adjustments": list(self.policy_adjustments),
            "errors": list(self.errors),
        }

    @classmethod
    def from_context(cls, ctx: Any, index: int = 0) -> DecisionArchive:
        request = getattr(ctx, "request", None)
        observation = getattr(request, "observation", None)
        response = getattr(ctx, "response", None)
        record = getattr(ctx, "decision_record", None)
        decision_id = getattr(record, "decision_id", None) or uuid.uuid4().hex[:12]
        player_id = _required_player_id(ctx, request)
        return cls(
            decision_id=decision_id,
            index=index,
            player_id=player_id,
            role=_enum_value(getattr(ctx, "role", "")),
            day=int(getattr(observation, "day", 0) or 0),
            phase=_enum_value(getattr(request, "phase", getattr(observation, "phase", ""))),
            action_type=_enum_value(getattr(request, "action_type", "")),
            candidates=list(getattr(request, "candidates", ()) or ()),
            observation_summary={
                "day": int(getattr(observation, "day", 0) or 0),
                "phase": _enum_value(getattr(observation, "phase", getattr(request, "phase", ""))),
                "alive_players": list(getattr(observation, "alive_players", ()) or ()),
                "dead_players": list(getattr(observation, "dead_players", ()) or ()),
                "sheriff_id": getattr(observation, "sheriff_id", None),
            },
            memory_context=dict(getattr(ctx, "memory_context", {}) or {}),
            selected_skills=list(getattr(ctx, "selected_skills", []) or []),
            prompt_messages=list(getattr(ctx, "messages", []) or []),
            raw_output=str(getattr(ctx, "raw_output", "") or ""),
            parsed_decision=dict(getattr(ctx, "parsed_decision", {}) or {}),
            final_response=_response_to_dict(response),
            source=str(getattr(ctx, "source", "") or ""),
            confidence=getattr(ctx, "confidence", None),
            policy_adjustments=list(getattr(ctx, "policy_adjustments", []) or []),
            errors=list(getattr(ctx, "errors", []) or []),
        )


@dataclass(slots=True)
class GameArchive:
    """Complete archive of a single game."""
    game_id: str
    seed: int
    config: dict
    player_roles: dict[int, str]
    winner: str | None
    started_at: str
    finished_at: str | None
    public_events: list[dict]
    decisions: list[DecisionArchive]
    final_state: dict

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "seed": self.seed,
            "config": _sanitize(self.config),
            "player_roles": {str(k): v for k, v in self.player_roles.items()},
            "winner": self.winner,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "public_events": _sanitize(self.public_events),
            "decisions": [d.to_dict() for d in self.decisions],
            "final_state": _sanitize(self.final_state),
        }

    def write_json(self, path: Path) -> None:
        write_json(path, self.to_dict())


class AgentTraceRecorder:
    """Collects full decision traces during a game for post-game archive."""

    def __init__(self) -> None:
        self._traces: list[DecisionArchive] = []
        self._index = 1

    def record(self, ctx: Any) -> None:
        self._traces.append(DecisionArchive.from_context(ctx, self._index))
        self._index += 1

    def snapshot(self) -> list[DecisionArchive]:
        return list(self._traces)

    def flush(self, game_id: str, output_dir: Path, **meta) -> GameArchive:
        from app.util.manifest import build_run_manifest, write_manifest
        from app.util.time import beijing_now_iso

        output = Path(output_dir)
        config = dict(meta.get("config", {}) or {})
        started_at = str(meta.get("started_at") or beijing_now_iso())
        finished_at = str(meta.get("finished_at") or beijing_now_iso())
        error_summary = str(meta.get("error_summary") or meta.get("error") or "")
        archive = GameArchive(
            game_id=game_id,
            seed=int(meta.get("seed", 0) or 0),
            config=config,
            player_roles=dict(meta.get("player_roles", {}) or {}),
            winner=meta.get("winner"),
            started_at=started_at,
            finished_at=finished_at,
            public_events=list(meta.get("public_events", []) or []),
            decisions=self.snapshot(),
            final_state=dict(meta.get("final_state", {}) or {}),
        )
        archive.write_json(output / "archive.json")
        manifest = build_run_manifest(
            run_type="game",
            run_id=game_id,
            game_id=game_id,
            model_config_hash=str(meta.get("model_config_hash") or config.get("model_config_hash") or ""),
            seed=archive.seed,
            config=config,
            started_at=started_at,
            finished_at=finished_at,
            status=str(meta.get("status") or ("failed" if error_summary else "completed")),
            error_summary=error_summary,
            paths={"game_dir": str(output_dir), "archive": "archive.json"},
            metadata={"winner": archive.winner, "player_roles": archive.player_roles},
        )
        write_manifest(output / "manifest.json", manifest)
        return archive

    def clear(self) -> None:
        self._traces.clear()
        self._index = 1

    @property
    def count(self) -> int:
        return len(self._traces)


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]


def _run_metadata(config: GameRunConfig, run_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "mode": config.mode,
        "source_run_id": run_id,
        "model_id": config.model_id,
        "model_config_hash": config.model_config_hash,
        "ruleset_version": config.ruleset_version,
    }
    for key in (
        "comparison_group_id",
        "comparison_type",
        "target_role",
        "target_version_id",
        "seed_set_id",
        "evaluation_set_id",
    ):
        value = getattr(config, key)
        if value is not None:
            metadata[key] = value
    if config.paired_seed:
        metadata["paired_seed"] = True
    if config.role_version_config:
        metadata["role_version_config"] = dict(config.role_version_config)
    return metadata


def _enum_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "")


def _response_to_dict(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if hasattr(response, "to_dict"):
        return _sanitize(response.to_dict())
    return {
        "action_type": _enum_value(getattr(response, "action_type", "")),
        "target": getattr(response, "target", None),
        "choice": getattr(response, "choice", None),
        "text": getattr(response, "text", "") or "",
    }


def _required_player_id(ctx: Any, request: Any) -> int:
    value = getattr(ctx, "player_id", None)
    if value is None and request is not None:
        value = getattr(request, "player_id", None)
    if value is None:
        raise ValueError("player_id is required for decision archive")
    try:
        player_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid player_id for decision archive: {value!r}") from exc
    if player_id <= 0:
        raise ValueError(f"Invalid player_id for decision archive: {value!r}")
    return player_id


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)

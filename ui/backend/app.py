from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import Field

from ui.backend.game_runner import GameManager
from ui.backend.selfplay_runner import SelfplayManager
from ui.backend.role_evolution_runner import RoleEvolutionRunner
from ui.backend.batch_role_evolution_runner import RoleBatchEvolutionRunner
from agent.role_evolution.pipeline import InvalidRunStateError, BaselineChangedError


class StartGameRequest(BaseModel):
    seed: int | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    skill_dir: str | None = None
    player_count: int = Field(default=12, ge=12, le=12)
    role_versions: dict[str, str] | None = None  # {role: hash} per-role version selection


class SelfplayRequest(BaseModel):
    num_games: int = Field(default=10, ge=1, le=100)
    agent_version: str | None = None
    skill_dir: str | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    enable_batch_dream: bool = False
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)
    label: str | None = None


class RoleEvolutionStartRequest(BaseModel):
    role: str
    training_games: int = Field(default=20, ge=1, le=100)
    battle_games: int = Field(default=10, ge=1, le=100)
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)


class RoleEvolutionBatchStartRequest(BaseModel):
    roles: list[str] = Field(min_length=1)
    training_games: int = Field(default=20, ge=1, le=100)
    battle_games: int = Field(default=10, ge=1, le=100)
    role_concurrency: int = Field(default=2, ge=1, le=20)
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)


def _default_version_store():
    from agent.role_evolution.store import VersionStore
    return VersionStore(Path("role_versions"))


manager = GameManager()
selfplay_manager = SelfplayManager()
version_store = _default_version_store()
role_evolution_runner = RoleEvolutionRunner(store=version_store)
role_batch_evolution_runner = RoleBatchEvolutionRunner(store=version_store)
app = FastAPI(title="521wolf UI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


ROLE_LABELS = {
    "werewolf": "狼人",
    "white_wolf_king": "白狼王",
    "villager": "村民",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
    "guard": "守卫",
}
HIDDEN_EVENT_TYPES = {"invalid_response"}
PUBLIC_SPEECH_ACTIONS = {"speak", "sheriff_speak", "pk_speak", "last_word"}
PUBLIC_VOTE_ACTIONS = {"exile_vote", "pk_vote", "sheriff_vote", "vote"}
GOD_ONLY_ACTIONS = {
    "guard_protect",
    "werewolf_kill",
    "seer_check",
    "witch_act",
    "hunter_shoot",
    "white_wolf_explode",
}


def _current_game_id() -> str | None:
    games = manager.list_games()
    if not games:
        return None
    active = next((game for game in games if game.get("status") in {"starting", "running"}), None)
    return str((active or games[0]).get("game_id"))


def _discard_active_games() -> None:
    active_ids: list[str] = []
    for game_id, game in list(manager._games.items()):
        if not game.is_active:
            continue
        active_ids.append(game_id)
        if game.task is not None and not game.task.done():
            game.task.cancel()
        game.status = "cancelled"
    for game_id in active_ids:
        manager._games.pop(game_id, None)


def _compat_role_hint(role: str | None) -> str:
    return ROLE_LABELS.get(str(role or ""), str(role or "未知"))


def _compat_player(player: dict[str, Any], mode: str = "watch") -> dict[str, Any]:
    player_id = int(player.get("id") or player.get("seat") or 0)
    role = str(player.get("role") or "")
    return {
        **player,
        "id": player_id,
        "seat": player.get("seat") or player_id,
        "name": player.get("name") or f"{player_id}号",
        "role": role,
        "role_hint": player.get("role_hint") or _compat_role_hint(role),
        "alive": bool(player.get("alive", True)),
        "is_human": mode != "watch" and player_id == 1,
        "is_sheriff": bool(player.get("is_sheriff", False)),
    }


def _compat_log(entry: dict[str, Any], role_by_id: dict[int, str] | None = None) -> dict[str, Any] | None:
    actor = entry.get("actor", entry.get("actor_id"))
    target = entry.get("target", entry.get("target_id"))
    visibility = entry.get("visibility") or "god"
    event_type = str(entry.get("event_type") or entry.get("type") or "system")
    if event_type in HIDDEN_EVENT_TYPES:
        return None

    action_type = str((entry.get("payload") or {}).get("action_type") or "")
    speaker = "法官"
    role_label = _role_label_for(actor, role_by_id)
    message = _compat_log_message(entry, event_type, action_type, role_label)
    if event_type == "action_response" and actor is not None:
        speaker = f"{actor}号{role_label}" if role_label else f"{actor}号"
    display_type = "action_prompt" if event_type == "action_request" else action_type if event_type == "action_response" and action_type else event_type
    if visibility == "private":
        speaker = "系统"
    return {
        **entry,
        "id": str(entry.get("id") or entry.get("index") or ""),
        "sequence": entry.get("sequence") or entry.get("index") or 0,
        "actor_id": actor,
        "target_id": target,
        "speaker": entry.get("speaker") or speaker,
        "message": message,
        "type": display_type,
        "visibility": _compat_visibility(visibility, event_type, action_type),
        "phase": entry.get("phase") or "setup",
        "day": entry.get("day") or 0,
    }


def _compat_log_message(entry: dict[str, Any], event_type: str, action_type: str = "", role_label: str = "") -> str:
    payload = entry.get("payload") or {}
    actor = entry.get("actor", entry.get("actor_id"))
    target = entry.get("target", entry.get("target_id"))
    day = entry.get("day") or 0

    if event_type == "action_request":
        return _action_prompt_message(action_type, actor, role_label)
    if event_type == "action_response":
        return _action_response_message(action_type, target, payload.get("choice"), payload.get("text"))
    if event_type == "game_init":
        return "游戏初始化完成，12名玩家已入座。"
    if event_type == "night_start":
        return f"第 {day} 夜开始。"
    if event_type == "night_end":
        deaths = payload.get("deaths") or []
        return f"第 {day} 夜结束，死亡玩家：{_seat_list(deaths)}。" if deaths else f"第 {day} 夜结束，昨晚是平安夜。"
    if event_type == "night_death_reveal":
        deaths = payload.get("deaths") or []
        return f"昨晚死亡玩家：{_seat_list(deaths) if deaths else '无'}。"
    if event_type == "guard_result":
        return "守卫完成守护。"
    if event_type == "werewolf_result":
        return "狼人夜间行动完成。"
    if event_type == "seer_result":
        result = payload.get("result")
        result_text = "狼人阵营" if result == "werewolves" else "好人阵营" if result else "未知"
        return f"预言家查验 {target}号，结果为{result_text}。"
    if event_type == "witch_result":
        return "女巫夜间行动完成。"
    if event_type == "day_speech_start":
        return f"第 {day} 天白天发言开始。"
    if event_type == "day_speech_order":
        order = payload.get("order") or []
        return f"发言顺序：{_seat_list(order)}。" if order else "发言顺序已确定。"
    if event_type == "day_speech_end":
        return f"第 {day} 天白天发言结束。"
    if event_type == "exile_vote_start":
        return "放逐投票开始。"
    if event_type == "exile_vote_end":
        return f"放逐投票结束，{target}号出局。" if target else "放逐投票结束，无人出局。"
    if event_type == "exile_vote_tie":
        tied = payload.get("tied") or []
        return f"放逐投票平票，进入 PK：{_seat_list(tied)}。"
    if event_type == "pk_vote_end":
        return f"PK 投票结束，{target}号出局。" if target else "PK 再次平票，无人出局。"
    if event_type == "sheriff_election_start":
        return "警长竞选开始。"
    if event_type == "sheriff_election_end":
        winner = payload.get("winner")
        return f"警长竞选结束，{winner}号当选警长。" if winner else "无人当选警长。"
    if event_type == "sheriff_badge_transfer":
        return "警徽已移交。"
    if event_type == "sheriff_badge_destroy":
        return "警徽被撕毁。"
    if event_type == "white_wolf_explosion":
        return f"白狼王自爆，带走 {target}号。" if target else "白狼王自爆。"
    if event_type == "hunter_shot":
        return f"猎人 {actor}号开枪带走 {target}号。" if actor and target else "猎人开枪。"
    if event_type == "death":
        return f"{target}号玩家出局。" if target else "有玩家出局。"
    if event_type == "game_end":
        winner = payload.get("winner") or entry.get("winner")
        return f"游戏结束，胜利方：{winner}。" if winner else "游戏结束。"
    return str(entry.get("content") or entry.get("message") or "")


def _action_prompt_message(action_type: str, actor: Any, role_label: str = "") -> str:
    prompts = {
        "guard_protect": "请守卫选择守护的人。",
        "werewolf_kill": "请狼人选择击杀的目标。",
        "seer_check": "请预言家选择查验对象。",
        "witch_act": "请女巫选择是否使用解药或毒药。",
        "hunter_shoot": "请猎人选择是否开枪。",
        "sheriff_run": "请玩家选择是否上警。",
        "sheriff_speak": "请警上玩家发言。",
        "sheriff_vote": "请警下玩家投出警长票。",
        "speak": "请当前玩家发言。",
        "exile_vote": "请所有玩家投出放逐票。",
        "pk_speak": "请 PK 台上的玩家发言。",
        "pk_vote": "请玩家投出 PK 票。",
        "last_word": "请出局玩家发表遗言。",
        "sheriff_badge": "请警长选择移交或撕毁警徽。",
    }
    return prompts.get(action_type, "请玩家行动。")


def _action_response_message(action_type: str, target: Any, choice: Any, text: Any) -> str:
    text_value = str(text or "").strip()
    if action_type in PUBLIC_SPEECH_ACTIONS:
        return text_value or "过。"
    if action_type == "guard_protect":
        return f"我选择保护{target}号。"
    if action_type == "werewolf_kill":
        return f"我选择击杀{target}号。"
    if action_type == "seer_check":
        return f"我选择查验{target}号。"
    if action_type == "witch_act":
        if choice == "antidote":
            return f"我选择使用解药救{target}号。"
        if choice == "poison":
            return f"我选择使用毒药毒{target}号。"
        return "我选择不使用药。"
    if action_type == "hunter_shoot":
        return f"我选择开枪带走{target}号。" if target is not None else "我选择不开枪。"
    if action_type == "white_wolf_explode":
        return f"我选择自爆带走{target}号。" if target is not None else "我选择自爆。"
    if action_type == "sheriff_run":
        return "我选择上警。"
    if action_type == "sheriff_pass":
        return "我选择不上警。"
    if action_type == "sheriff_withdraw":
        return "我选择退水。"
    if action_type == "sheriff_stay":
        return "我选择留在警上。"
    if action_type in PUBLIC_VOTE_ACTIONS:
        return f"我投给{target}号。" if target is not None else "我选择弃票。"
    if action_type == "sheriff_badge":
        if choice == "destroy":
            return "我选择撕毁警徽。"
        return f"我选择把警徽移交给{target}号。" if target is not None else "我选择不移交警徽。"
    if target is not None:
        return f"我选择{target}号。"
    return text_value or f"我选择执行 {action_type}。"


def _compat_visibility(raw_visibility: str, event_type: str, action_type: str) -> str:
    if raw_visibility == "private":
        return "private"
    if event_type == "action_request" and action_type in GOD_ONLY_ACTIONS:
        return "god"
    if event_type == "action_response" and action_type in GOD_ONLY_ACTIONS:
        return "god"
    if event_type in {"guard_result", "werewolf_result", "seer_result", "witch_result", "night_start", "night_end"}:
        return "god"
    return "public"


def _role_label_for(player_id: Any, role_by_id: dict[int, str] | None = None) -> str:
    if player_id is None or not role_by_id:
        return ""
    try:
        role = role_by_id.get(int(player_id))
    except (TypeError, ValueError):
        return ""
    return _compat_role_hint(role) if role else ""


def _seat_list(values: Any) -> str:
    if not values:
        return ""
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return "、".join(f"{value}号" for value in values)


def _compat_decision(decision: dict[str, Any]) -> dict[str, Any]:
    actor = decision.get("actor_id") or decision.get("player_id")
    target = decision.get("target_id") or decision.get("selected_target")
    action = decision.get("action") or decision.get("action_type") or ""
    public_text = decision.get("public_summary") or decision.get("public_text") or decision.get("private_reasoning") or ""
    return {
        **decision,
        "actor_id": actor,
        "actor_name": decision.get("actor_name") or (f"{actor}号" if actor is not None else ""),
        "action": action,
        "target_id": target,
        "target_name": decision.get("target_name") or (f"{target}号" if target is not None else "无目标"),
        "public_summary": public_text,
        "reason": decision.get("reason") or decision.get("private_reasoning") or public_text,
    }


def _compat_snapshot(snapshot: dict[str, Any], *, mode: str = "watch") -> dict[str, Any]:
    players = [_compat_player(player, mode) for player in snapshot.get("players", [])]
    role_by_id = {int(player["id"]): str(player.get("role") or "") for player in players}
    logs = [
        log
        for entry in snapshot.get("logs") or snapshot.get("events") or []
        if (log := _compat_log(entry, role_by_id)) is not None
    ]
    decisions = [_compat_decision(decision) for decision in snapshot.get("decisions") or []]
    return {
        **snapshot,
        "mode": mode,
        "player_count": len(players) or snapshot.get("player_count") or 12,
        "phase": snapshot.get("phase") or "setup",
        "waiting_for": "none",
        "winner": snapshot.get("winner") or "",
        "players": players,
        "human_player_id": 1,
        "current_speaker_id": None,
        "logs": logs,
        "decisions": decisions,
        "votes": {},
        "vote_tally": _vote_tally(logs),
        "role_counts": _role_counts(players),
        "sheriff_id": snapshot.get("sheriff_id"),
        "sheriff_destroyed": False,
        "sheriff": {"started": False, "stage": "", "candidates": [], "initial_runners": [], "withdrawn": [], "votes": {}},
        "skill_state": {"witch_poison_used": False, "witch_antidote_used": False, "white_wolf_burst_used": False},
        "pending_action": {"type": "", "prompt": "", "candidate_ids": [], "options": {}},
        "private_view": {"role": "观战者" if mode == "watch" else players[0]["role_hint"] if players else "未知", "alive": True, "visible_decisions": [], "note": ""},
    }


def _role_counts(players: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        label = player.get("role_hint") or _compat_role_hint(player.get("role"))
        counts[label] = counts.get(label, 0) + 1
    return counts


def _vote_tally(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tally: dict[int, dict[str, Any]] = {}
    for log in logs:
        if log.get("type") in {"exile_vote_end", "pk_vote_end", "sheriff_election_end"}:
            for voter, target in (log.get("payload") or {}).get("votes", {}).items():
                _add_vote_tally(tally, voter, target)
            continue
        if log.get("type") not in PUBLIC_VOTE_ACTIONS:
            continue
        target = log.get("target_id")
        actor = log.get("actor_id")
        if target is None or actor is None:
            continue
        _add_vote_tally(tally, actor, target)
    return sorted(tally.values(), key=lambda row: (-row["count"], row["target_id"]))


def _add_vote_tally(tally: dict[int, dict[str, Any]], voter: Any, target: Any) -> None:
    if target is None or voter is None:
        return
    voter_id = int(voter)
    target_id = int(target)
    row = tally.setdefault(target_id, {"target_id": target_id, "count": 0, "voter_ids": [], "voters": []})
    row["count"] += 1
    row["voter_ids"].append(voter_id)
    row["voters"].append(f"{voter_id}号")


@app.on_event("startup")
def _on_startup() -> None:
    selfplay_manager.restore_runs()
    role_evolution_runner.recover_on_startup()
    role_evolution_runner.restore_runs()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mode": "external", "external": {"backend": "521wolf"}}


@app.get("/api/games")
def list_games() -> dict[str, Any]:
    return {"games": manager.list_games()}


@app.post("/api/games", status_code=201)
async def start_game(request: StartGameRequest | None = None) -> dict[str, Any]:
    try:
        role_skill_dirs = None
        if request is not None and request.role_versions:
            role_skill_dirs = {}
            for role, hash_val in request.role_versions.items():
                role_skill_dirs[role] = Path("role_versions") / role / hash_val / "skills"
        game = await manager.start_game(
            seed=request.seed if request is not None else None,
            max_days=request.max_days if request is not None else 20,
            enable_sheriff=request.enable_sheriff if request is not None else True,
            skill_dir=_resolve_allowed_skill_dir(request.skill_dir) if request is not None else None,
            player_count=request.player_count if request is not None else 12,
            role_skill_dirs=role_skill_dirs,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _compat_snapshot(manager.snapshot(game, include_events=False))


@app.get("/api/games/{game_id}")
def get_game(game_id: str) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return _compat_snapshot(manager.snapshot(game))


@app.get("/api/game")
def get_current_compat_game() -> dict[str, Any]:
    game_id = _current_game_id()
    if game_id is None:
        return _compat_snapshot(
            {
                "game_id": "",
                "log_name": "",
                "status": "idle",
                "day": 0,
                "phase": "setup",
                "players": [],
                "events": [],
                "decisions": [],
            }
        )
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return _compat_snapshot(manager.snapshot(game))


@app.post("/api/game/start")
async def start_compat_game(request: StartGameRequest | None = None) -> dict[str, Any]:
    _discard_active_games()
    game = await manager.start_game(
        seed=request.seed if request is not None else None,
        max_days=request.max_days if request is not None else 20,
        enable_sheriff=request.enable_sheriff if request is not None else True,
        skill_dir=_resolve_allowed_skill_dir(request.skill_dir) if request is not None else None,
        player_count=request.player_count if request is not None else 12,
    )
    return _compat_snapshot(manager.snapshot(game, include_events=False))


@app.post("/api/game/reset")
async def reset_compat_game(request: StartGameRequest | None = None) -> dict[str, Any]:
    return await start_compat_game(request)


@app.post("/api/game/step")
def step_compat_game() -> dict[str, Any]:
    return get_current_compat_game()


@app.post("/api/game/speech")
def speech_compat_game() -> dict[str, Any]:
    return get_current_compat_game()


@app.post("/api/game/vote")
def vote_compat_game() -> dict[str, Any]:
    return get_current_compat_game()


@app.post("/api/game/action")
def action_compat_game() -> dict[str, Any]:
    return get_current_compat_game()


@app.get("/api/game/events")
async def stream_current_compat_game_events() -> StreamingResponse:
    game_id = _current_game_id()
    if game_id is None:
        raise HTTPException(status_code=404, detail="game not found")
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    role_by_id = {
        int(player.get("id")): str(player.get("role") or "")
        for player in manager.snapshot(game, include_events=False).get("players", [])
        if player.get("id") is not None
    }

    async def event_stream():
        queue = await manager.subscribe(game)
        try:
            while True:
                item = await queue.get()
                event_name = item["kind"]
                payload = item["payload"]
                if event_name == "log":
                    payload = _compat_log(payload, role_by_id)
                    if payload is None:
                        continue
                elif isinstance(payload, dict):
                    payload = _compat_snapshot(payload)
                yield f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if event_name in {"done", "error"}:
                    break
        finally:
            manager.unsubscribe(game, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/games/{game_id}/events")
async def stream_game_events(game_id: str) -> StreamingResponse:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")

    async def event_stream():
        queue = await manager.subscribe(game)
        try:
            while True:
                item = await queue.get()
                event_name = item["kind"]
                payload = json.dumps(item["payload"], ensure_ascii=False)
                yield f"event: {event_name}\ndata: {payload}\n\n"
                if event_name in {"done", "error"}:
                    break
        finally:
            manager.unsubscribe(game, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/games/{game_id}/archive")
def get_game_archive(game_id: str) -> dict[str, Any]:
    """Read the full trace archive for a game (ToT candidates, prompts, etc.)."""
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    archive = manager.read_archive(game_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="archive not available")
    return archive


@app.get("/api/games/{game_id}/review")
def get_game_review(game_id: str) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    review = manager.build_review(game_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not available")
    return review


# ── Leaderboard ───────────────────────────────────────────────────────────────


_LEADERBOARD_PATHS = [
    Path("runs/version_battle/leaderboard.json"),
    Path("logs/version_battle/leaderboard.json"),
    Path("data/version_battle/leaderboard.json"),
    Path("leaderboard.json"),
]


@app.get("/api/leaderboards")
def list_leaderboards() -> dict[str, Any]:
    """Read leaderboard from known output paths."""
    for path in _LEADERBOARD_PATHS:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list):
                return {"entries": data, "source": str(path)}
            if isinstance(data, dict) and "entries" in data:
                return {**data, "source": str(path)}
    return {"entries": [], "source": None}


def _resolve_allowed_skill_dir(raw: str | None) -> str | None:
    if not raw:
        return None
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    allowed_roots = [
        (Path.cwd() / "skills").resolve(),
        (Path.cwd() / "role_versions").resolve(),
        (Path.cwd() / "runs").resolve(),
    ]
    for root in allowed_roots:
        try:
            candidate.relative_to(root)
            return str(candidate)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"skill_dir is outside allowed roots: {raw}")


# ── Selfplay Batch Runs ──────────────────────────────────────────────────────


@app.post("/api/selfplay", status_code=201)
async def start_selfplay(request: SelfplayRequest | None = None) -> dict[str, Any]:
    """Start a batch selfplay run in the background. Returns the run_id."""
    if request is None:
        request = SelfplayRequest()
    agent_version = request.agent_version or "agent"
    skill_dir = _resolve_allowed_skill_dir(request.skill_dir)
    run = await selfplay_manager.start_run(
        num_games=request.num_games,
        agent_version=agent_version,
        skill_dir=skill_dir,
        max_days=request.max_days,
        enable_sheriff=request.enable_sheriff,
        enable_batch_dream=request.enable_batch_dream,
        game_concurrency=request.game_concurrency,
        llm_concurrency=request.llm_concurrency,
        llm_rpm=request.llm_rpm,
        label=request.label,
    )
    return run.snapshot()


@app.get("/api/selfplay")
def list_selfplays() -> dict[str, Any]:
    """List all selfplay runs (active and completed)."""
    return {"runs": selfplay_manager.list_runs()}


@app.get("/api/selfplay/{run_id}")
def get_selfplay(run_id: str) -> dict[str, Any]:
    """Get status and progress of a specific selfplay run."""
    run = selfplay_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@app.post("/api/selfplay/{run_id}/stop")
def stop_selfplay(run_id: str) -> dict[str, Any]:
    """Stop a running selfplay task (can be resumed later)."""
    run = selfplay_manager.stop_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@app.post("/api/selfplay/{run_id}/resume")
def resume_selfplay(run_id: str) -> dict[str, Any]:
    """Resume a paused or interrupted selfplay task."""
    run = selfplay_manager.resume_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@app.post("/api/selfplay/{run_id}/terminate")
def terminate_selfplay(run_id: str) -> dict[str, Any]:
    """Permanently stop a selfplay run."""
    run = selfplay_manager.terminate_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


# ── Selfplay Game Detail ─────────────────────────────────────────────────────


def _resolve_selfplay_run_dir(run_id: str) -> Path | None:
    """Find the output directory for a selfplay run."""
    run = selfplay_manager.get_run(run_id)
    if run is not None and run.artifact_run_id:
        path = Path("runs/selfplay") / run.artifact_run_id
        if path.exists():
            return path
    # Fallback to direct path
    path = Path("runs/selfplay") / run_id
    return path if path.exists() else None


def _read_jsonl(path: Path, *, with_index: bool = False) -> list[dict[str, Any]]:
    """Read a JSONL file and return a list of parsed objects."""
    lines: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if line:
            value = json.loads(line)
            if with_index and isinstance(value, dict):
                value.setdefault("index", index)
            lines.append(value)
    return lines


def _list_games_in_run(run_id: str, run_dir: Path) -> dict[str, Any]:
    games_dir = run_dir / "games"
    if not games_dir.exists():
        return {"run_id": run_id, "games": []}
    game_dirs = sorted(g for g in games_dir.iterdir() if g.is_dir())
    games: list[dict[str, Any]] = []
    for gdir in game_dirs:
        game_id = gdir.name
        events_path = gdir / "game_events.jsonl"
        meta_path = gdir / "meta.json"
        info: dict[str, Any] = {"game_id": game_id}
        info["in_progress"] = not meta_path.exists()
        if events_path.exists():
            events = _read_jsonl(events_path)
            info["event_count"] = len(events)
            if events:
                last = events[-1]
                payload = last.get("payload") or {}
                info["winner"] = payload.get("winner")
                info["day"] = last.get("day")
                info["phase"] = last.get("phase")
        else:
            info["event_count"] = 0
        games.append(info)
    return {"run_id": run_id, "games": games}


@app.get("/api/selfplay/{run_id}/games")
def list_selfplay_games(run_id: str) -> dict[str, Any]:
    """List all games in a selfplay run with basic info."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return _list_games_in_run(run_id, run_dir)


@app.get("/api/selfplay/{run_id}/games/{game_id}/events")
def get_selfplay_game_events(run_id: str, game_id: str) -> dict[str, Any]:
    """Get all events for a specific game in a selfplay run."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    events_path = run_dir / "games" / game_id / "game_events.jsonl"
    if not events_path.exists():
        raise HTTPException(status_code=404, detail="game events not found")
    events = _read_jsonl(events_path)
    return {"run_id": run_id, "game_id": game_id, "events": events}


@app.get("/api/selfplay/{run_id}/games/{game_id}/decisions")
def get_selfplay_game_decisions(run_id: str, game_id: str) -> dict[str, Any]:
    """Get agent decisions for a specific game."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    decisions_path = run_dir / "games" / game_id / "agent_decisions.jsonl"
    if not decisions_path.exists():
        raise HTTPException(status_code=404, detail="game decisions not found")
    decisions = _read_jsonl(decisions_path, with_index=True)
    return {"run_id": run_id, "game_id": game_id, "decisions": decisions}


@app.get("/api/selfplay/{run_id}/games/{game_id}/archive")
def get_selfplay_game_archive(run_id: str, game_id: str) -> dict[str, Any]:
    """Get full archive for a specific game."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    archive_path = run_dir / "games" / game_id / "archive.json"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="game archive not found")
    return json.loads(archive_path.read_text(encoding="utf-8"))


def _resolve_role_evolution_training_run_dir(run_id: str) -> Path | None:
    """Find the nested selfplay run directory for role-evolution training games."""
    tracked = role_evolution_runner.get_run(run_id)
    evo_ids: list[str] = []
    training_ids: list[str] = []
    training_output_dirs: list[str] = []
    if tracked is not None:
        if tracked.artifact_run_id:
            evo_ids.append(tracked.artifact_run_id)
        if tracked.training_run_id:
            training_ids.append(tracked.training_run_id)
        if tracked.training_output_dir:
            training_output_dirs.append(tracked.training_output_dir)
        if tracked.run is not None:
            evo_ids.append(tracked.run.run_id)
            if tracked.run.training_run_id:
                training_ids.append(tracked.run.training_run_id)
            if tracked.run.training_output_dir:
                training_output_dirs.append(tracked.run.training_output_dir)
    evo_ids.append(run_id)
    if run_id.startswith("run_"):
        training_ids.append(run_id)

    for raw in dict.fromkeys(training_output_dirs):
        path = Path(raw)
        if path.exists() and (path / "games").exists():
            return path

    evo_root = version_store.base_dir / "runs" / "evolution"
    for evo_id in dict.fromkeys(evo_ids):
        evo_dir = evo_root / evo_id
        if not evo_dir.exists():
            continue
        state_path = evo_dir / "state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            training_run_id = state.get("training_run_id")
            if training_run_id:
                training_ids.append(str(training_run_id))
            training_output_dir = state.get("training_output_dir")
            if training_output_dir:
                path = Path(str(training_output_dir))
                if path.exists() and (path / "games").exists():
                    return path
        for training_id in dict.fromkeys(training_ids):
            candidate = evo_dir / training_id
            if candidate.exists() and (candidate / "games").exists():
                return candidate
        for candidate in sorted(evo_dir.glob("run_*"), reverse=True):
            if candidate.is_dir() and (candidate / "games").exists():
                return candidate

    if evo_root.exists():
        for candidate in sorted(evo_root.glob(f"*/{run_id}"), reverse=True):
            if candidate.is_dir() and (candidate / "games").exists():
                return candidate
    return None



# ── Role Evolution ──────────────────────────────────────────────────────────


def register_role_evolution_routes(
    app: FastAPI,
    runner: RoleEvolutionRunner,
    batch_runner: RoleBatchEvolutionRunner,
) -> None:
    """Register all role-evolution and role-version routes on *app*."""

    # -- Role versions -------------------------------------------------------

    @app.get("/api/roles")
    def list_roles() -> dict[str, Any]:
        """List all roles that have stored versions."""
        roles = runner.store.list_roles()
        return {"roles": roles}

    @app.get("/api/roles/{role}/versions")
    def list_role_versions(role: str) -> dict[str, Any]:
        """List all versions for a role."""
        try:
            versions = runner.store.list_versions(role)
            baseline = runner.store.get_baseline(role)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"role '{role}' not found")
        result = []
        for v in versions:
            d = v.to_dict()
            d["is_baseline"] = v.hash == baseline.hash
            result.append(d)
        return {"role": role, "versions": result}

    @app.get("/api/roles/{role}/versions/{hash}")
    def get_role_version(role: str, hash: str) -> dict[str, Any]:
        """Get full detail of a specific role version."""
        try:
            version = runner.store.load_version(role, hash)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"version {role}/{hash} not found",
            )
        data = version.to_dict()
        data["kind"] = "role_version"
        data["schema_version"] = 1
        return data

    @app.get("/api/roles/{role}/leaderboard")
    def role_leaderboard(role: str) -> dict[str, Any]:
        """Return the role evolution leaderboard for a role."""
        from agent.role_evolution.leaderboard import aggregate_role_leaderboard

        # Collect battle summaries from completed runs
        battle_summaries: list[dict] = []
        for tracked in runner.get_runs_for_role(role):
            # Try in-memory first
            if tracked.run is not None and tracked.run.battle_result is not None:
                battle_summaries.append(tracked.run.battle_result)
            else:
                # Fall back to disk
                evo_dir = runner.store.base_dir / "runs" / "evolution" / tracked.run_id
                summary_path = evo_dir / "battle_summary.json"
                if summary_path.exists():
                    try:
                        summary = json.loads(summary_path.read_text(encoding="utf-8"))
                        battle_summaries.append(summary)
                    except Exception:
                        pass

        entries = aggregate_role_leaderboard(
            role=role,
            battle_summaries=battle_summaries,
            store=runner.store,
        )
        return {
            "kind": "role_leaderboard",
            "schema_version": 1,
            "role": role,
            "entries": [e.to_dict() for e in entries],
        }

    @app.post("/api/roles/{role}/rollback/{hash}")
    async def rollback_baseline(role: str, hash: str) -> dict[str, Any]:
        """Rollback the baseline for a role to a specific version hash."""
        # Verify the target hash exists
        try:
            runner.store.load_version(role, hash)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"version {role}/{hash} not found",
            )

        try:
            history = runner.store.get_history(role)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"role '{role}' not found",
            )

        # CAS update
        success = await runner.store.set_baseline(
            role=role,
            target_hash=hash,
            expected_current=history.baseline,
        )
        if not success:
            raise HTTPException(
                status_code=409,
                detail="baseline changed concurrently; retry",
            )
        return {
            "kind": "role_rollback",
            "schema_version": 1,
            "role": role,
            "new_baseline": hash,
        }

    # -- Role evolution runs -------------------------------------------------

    @app.get("/api/role-evolution")
    def list_role_evolution_runs() -> dict[str, Any]:
        """List all tracked role evolution runs."""
        return {
            "kind": "role_evolution_runs",
            "schema_version": 1,
            "runs": runner.list_runs(),
        }

    @app.get("/api/role-evolution/batches")
    def list_role_batch_evolution_runs() -> dict[str, Any]:
        """List all tracked batch role evolution runs."""
        return {
            "kind": "role_batch_evolution_runs",
            "schema_version": 1,
            "batches": batch_runner.list_batches(),
        }

    @app.post("/api/role-evolution/batch/start", status_code=201)
    async def start_role_batch_evolution(request: RoleEvolutionBatchStartRequest) -> dict[str, Any]:
        """Start a batch role evolution run."""
        missing: list[str] = []
        for role in request.roles:
            try:
                runner.store.get_baseline(role)
            except FileNotFoundError:
                missing.append(role)
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"roles have no baseline version: {', '.join(missing)}",
            )
        try:
            tracked = await batch_runner.start_batch(
                roles=request.roles,
                training_games=request.training_games,
                battle_games=request.battle_games,
                role_concurrency=request.role_concurrency,
                game_concurrency=request.game_concurrency,
                llm_concurrency=request.llm_concurrency,
                llm_rpm=request.llm_rpm,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.get("/api/role-evolution/batch/{batch_id}/status")
    def get_role_batch_evolution_status(batch_id: str) -> dict[str, Any]:
        tracked = batch_runner.get_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/promote")
    async def promote_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        try:
            tracked = await batch_runner.promote_batch(batch_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="batch not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/reject")
    async def reject_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        try:
            tracked = await batch_runner.reject_batch(batch_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="batch not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/stop")
    def stop_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        tracked = batch_runner.stop_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/terminate")
    def terminate_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        tracked = batch_runner.terminate_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return tracked.snapshot()

    @app.get("/api/role-evolution/batch/{batch_id}/events")
    async def stream_role_batch_evolution_events(batch_id: str) -> StreamingResponse:
        tracked = batch_runner.get_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")

        async def event_stream():
            async for chunk in batch_runner.sse_events(batch_id):
                yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/role-evolution/start", status_code=201)
    async def start_role_evolution(request: RoleEvolutionStartRequest) -> dict[str, Any]:
        """Start a new role evolution run."""
        # Verify the role has a baseline
        try:
            runner.store.get_baseline(request.role)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"role '{request.role}' has no baseline version",
            )

        tracked = await runner.start_evolution(
            role=request.role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            game_concurrency=request.game_concurrency,
            llm_concurrency=request.llm_concurrency,
            llm_rpm=request.llm_rpm,
        )
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/status")
    def get_role_evolution_status(run_id: str) -> dict[str, Any]:
        """Get status of a role evolution run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/stop")
    def stop_role_evolution(run_id: str) -> dict[str, Any]:
        """Stop a running evolution task (can be resumed)."""
        tracked = runner.stop_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/terminate")
    def terminate_role_evolution(run_id: str) -> dict[str, Any]:
        """Permanently stop an evolution run."""
        tracked = runner.terminate_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/resume")
    async def resume_role_evolution(run_id: str) -> dict[str, Any]:
        """Resume a paused or failed evolution task."""
        try:
            tracked = await runner.resume_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/rerun-consolidation")
    async def rerun_role_evolution_consolidation(run_id: str) -> dict[str, Any]:
        """Re-run consolidation on existing training data with updated prompt."""
        try:
            tracked = await runner.rerun_consolidation(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/games")
    def list_role_evolution_training_games(run_id: str) -> dict[str, Any]:
        """List training games produced by a role evolution run."""
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        return _list_games_in_run(run_id, run_dir)

    @app.get("/api/role-evolution/{run_id}/games/{game_id}/events")
    def get_role_evolution_training_game_events(run_id: str, game_id: str) -> dict[str, Any]:
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        events_path = run_dir / "games" / game_id / "game_events.jsonl"
        if not events_path.exists():
            raise HTTPException(status_code=404, detail="game events not found")
        return {
            "run_id": run_id,
            "game_id": game_id,
            "events": _read_jsonl(events_path),
        }

    @app.get("/api/role-evolution/{run_id}/games/{game_id}/decisions")
    def get_role_evolution_training_game_decisions(run_id: str, game_id: str) -> dict[str, Any]:
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        decisions_path = run_dir / "games" / game_id / "agent_decisions.jsonl"
        if not decisions_path.exists():
            raise HTTPException(status_code=404, detail="game decisions not found")
        return {
            "run_id": run_id,
            "game_id": game_id,
            "decisions": _read_jsonl(decisions_path, with_index=True),
        }

    @app.get("/api/role-evolution/{run_id}/games/{game_id}/archive")
    def get_role_evolution_training_game_archive(run_id: str, game_id: str) -> dict[str, Any]:
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        archive_path = run_dir / "games" / game_id / "archive.json"
        if not archive_path.exists():
            raise HTTPException(status_code=404, detail="game archive not found")
        return json.loads(archive_path.read_text(encoding="utf-8"))

    # -- Battle games ---------------------------------------------------------

    def _resolve_battle_run_dir(run_id: str, side: str) -> Path | None:
        """Find the battle directory for baseline or candidate."""
        evo_dir = runner.store.base_dir / "runs" / "evolution" / run_id / "battle" / side
        if not evo_dir.exists():
            return None
        # Find the run_* directory
        for child in sorted(evo_dir.iterdir(), reverse=True):
            if child.is_dir() and child.name.startswith("run_") and (child / "games").exists():
                return child
        return None

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games")
    def list_battle_games(run_id: str, side: str) -> dict[str, Any]:
        """List battle games for baseline or candidate side."""
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            return {"run_id": run_id, "side": side, "games": []}
        result = _list_games_in_run(run_id, run_dir)
        result["side"] = side
        return result

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games/{game_id}/events")
    def get_battle_game_events(run_id: str, side: str, game_id: str) -> dict[str, Any]:
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="battle run not found")
        events_path = run_dir / "games" / game_id / "game_events.jsonl"
        if not events_path.exists():
            raise HTTPException(status_code=404, detail="game events not found")
        return {"run_id": run_id, "game_id": game_id, "side": side, "events": _read_jsonl(events_path)}

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games/{game_id}/decisions")
    def get_battle_game_decisions(run_id: str, side: str, game_id: str) -> dict[str, Any]:
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="battle run not found")
        decisions_path = run_dir / "games" / game_id / "agent_decisions.jsonl"
        if not decisions_path.exists():
            raise HTTPException(status_code=404, detail="game decisions not found")
        return {"run_id": run_id, "game_id": game_id, "side": side, "decisions": _read_jsonl(decisions_path, with_index=True)}

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games/{game_id}/archive")
    def get_battle_game_archive(run_id: str, side: str, game_id: str) -> dict[str, Any]:
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="battle run not found")
        archive_path = run_dir / "games" / game_id / "archive.json"
        if not archive_path.exists():
            raise HTTPException(status_code=404, detail="game archive not found")
        return json.loads(archive_path.read_text(encoding="utf-8"))

    @app.get("/api/role-evolution/{run_id}/diff")
    def get_role_evolution_diff(run_id: str) -> dict[str, Any]:
        """Get the skill diffs produced by a run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        # Try in-memory first
        if tracked.run is not None and tracked.run.diff is not None:
            return {
                "kind": "role_evolution_diff",
                "schema_version": 1,
                "run_id": run_id,
                "diffs": [d.to_dict() for d in tracked.run.diff],
            }
        # Fall back to disk
        evo_dir = runner.store.base_dir / "runs" / "evolution" / run_id
        diff_path = evo_dir / "diff.json"
        if diff_path.exists():
            return json.loads(diff_path.read_text(encoding="utf-8"))
        return {
            "kind": "role_evolution_diff",
            "schema_version": 1,
            "run_id": run_id,
            "diffs": [],
        }

    @app.post("/api/role-evolution/{run_id}/promote")
    async def promote_role_evolution(run_id: str) -> dict[str, Any]:
        """Promote a reviewing run's candidate to baseline."""
        try:
            tracked = await runner.promote_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BaselineChangedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/reject")
    async def reject_role_evolution(run_id: str) -> dict[str, Any]:
        """Reject a reviewing run."""
        try:
            tracked = await runner.reject_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/events")
    async def stream_role_evolution_events(run_id: str) -> StreamingResponse:
        """SSE stream of progress events for a role evolution run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")

        async def event_stream():
            async for chunk in runner.sse_events(run_id):
                yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")


register_role_evolution_routes(app, role_evolution_runner, role_batch_evolution_runner)


FRONTEND_3D_DIST_DIR = Path(__file__).resolve().parents[1] / "frontend-3d-match" / "dist"
if FRONTEND_3D_DIST_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_3D_DIST_DIR / "assets"),
        name="frontend_3d_assets",
    )

    @app.get("/{path:path}")
    async def serve_frontend_3d(path: str):
        requested = FRONTEND_3D_DIST_DIR / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_3D_DIST_DIR / "index.html")

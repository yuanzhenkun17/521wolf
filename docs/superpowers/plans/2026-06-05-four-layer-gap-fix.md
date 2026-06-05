# 四层架构 Gap 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复四层架构 review 中发现的 5 个 gap：统一事件模型、收敛存储路径、修复 SSE 断线。

**Architecture:** 合并 `GameEvent`/`GameLogEntry` 为单一事件模型，删除 `public_log` 改用 `events` + 可见性过滤，合并 wolf/battle DB，删除冗余导入工具，修复进化 run SSE 自动重连。

**Tech Stack:** Python (engine/storage/backend), Vue 3 (frontend), SQLite

**任务依赖关系：**
```
Task 1 (合并事件模型) → Task 2 (删 public_log) → Task 3 (删导入工具) [独立]
                                                  → Task 4 (合并 DB)  [独立]
                                                  → Task 5 (SSE 重连) [独立]
```

---

## Task 1: 合并 GameEvent 和 GameLogEntry

**目标：** 消除引擎内部的双轨事件模型，只保留 `GameEvent`，它同时承担游戏逻辑和持久化/UI 的职责。

**Files:**
- Modify: `engine/models.py` (GameEvent 类)
- Modify: `engine/logging.py` (删除 GameLogEntry，改 GameLogger)
- Modify: `engine/engine.py` (合并 `_log` 和 `_record`)
- Modify: `storage/runtime.py` (EventEntry 协议、SQLiteEventSink)
- Modify: `storage/schema.py` (game_events 表加 `public` 列)
- Modify: `engine/phases/night.py`, `engine/phases/day.py`, `engine/phases/exile.py`, `engine/phases/sheriff.py`
- Modify: `engine/actions.py`, `engine/rules/death.py`, `engine/rules/victory.py`, `engine/rules/sheriff.py`
- Modify: `engine/role_rules/werewolf.py`, `engine/role_rules/witch.py`, `engine/role_rules/seer.py`, `engine/role_rules/guard.py`, `engine/role_rules/hunter.py`, `engine/role_rules/white_wolf_king.py`
- Modify: `ui/frontend/src/composables/gameSnapshot.js`
- Modify: `ui/frontend/src/composables/useGameState.js`
- Modify: `ui/frontend/src/composables/useCouncilScene.js`
- Modify: `ui/frontend/src/composables/useHistoryDerivedState.js`
- Test: `tests/test_engine.py`, `tests/test_storage.py`

---

### Task 1.1: 扩展 GameEvent 字段

**Files:**
- Modify: `engine/models.py:107-150`

- [ ] **Step 1: 给 GameEvent 添加 `message` 和 `index` 字段**

在 `engine/models.py` 的 `GameEvent` dataclass 中，在 `public: bool = True` 之后添加两个字段：

```python
@dataclass(slots=True)
class GameEvent:
    type: str
    day: int
    phase: Phase
    actor: int | None = None
    target: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    public: bool = True
    message: str = ""          # 人类可读描述，供 UI/replay 使用
    index: int = 0             # 在本局事件流中的序号（1-based）
```

同步更新 `to_dict()` 方法，加入 `message` 和 `index`：

```python
def to_dict(self) -> dict[str, Any]:
    return {
        "index": self.index,
        "event_type": self.type,
        "day": self.day,
        "phase": self.phase.value if hasattr(self.phase, "value") else self.phase,
        "actor": self.actor,
        "target": self.target,
        "payload": dict(self.payload),
        "public": self.public,
        "message": self.message,
    }
```

注意 `to_dict()` 的 key 保持 `"event_type"` 以兼容 SQLite `game_events` 表的列名。

- [ ] **Step 2: 运行现有测试确认不破坏**

Run: `uv run python -m pytest tests/test_engine.py -v -x`
Expected: 全部 PASS（新字段有默认值，不破坏现有调用）

---

### Task 1.2: 改造 GameLogger 使用 GameEvent

**Files:**
- Modify: `engine/logging.py`

- [ ] **Step 1: 删除 GameLogEntry、LogLevel、LogVisibility，改 GameLogger**

删除 `GameLogEntry` dataclass（lines 70-114）、`LogLevel` enum（line 61）、`LogVisibility` enum（line 66）。

将 `EventSink` 协议改为接收 `GameEvent`：

```python
from engine.models import GameEvent

class EventSink(Protocol):
    def record_event(self, entry: GameEvent) -> None: ...
```

将 `GameLogger` 改为存储 `list[GameEvent]`：

```python
class GameLogger:
    def __init__(
        self,
        stream_path: str | Path | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self.entries: list[GameEvent] = []
        self._stream_path: Path | None = Path(stream_path) if stream_path is not None else None
        self._sink: EventSink | None = sink
        self._next_index = 1

    def record(
        self,
        *,
        day: int,
        phase: Any,
        event_type: str,
        message: str,
        actor: int | None = None,
        target: int | None = None,
        payload: dict[str, Any] | None = None,
        public: bool = True,
    ) -> GameEvent:
        phase_val = phase.value if hasattr(phase, "value") else phase
        entry = GameEvent(
            type=event_type,
            day=day,
            phase=phase,
            actor=actor,
            target=target,
            payload=payload or {},
            public=public,
            message=message,
            index=self._next_index,
        )
        self._next_index += 1
        self.entries.append(entry)
        if self._stream_path:
            self._write_jsonl_line(entry)
        if self._sink:
            self._sink.record_event(entry)
        return entry

    def _write_jsonl_line(self, entry: GameEvent) -> None:
        import json
        line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        with open(self._stream_path, "a", encoding="utf-8") as f:
            f.write(line)

    def to_jsonl(self) -> str:
        import json
        return "\n".join(json.dumps(e.to_dict(), ensure_ascii=False, sort_keys=True) for e in self.entries)

    def to_text(self) -> str:
        lines = []
        for entry in self.entries:
            actor = f" actor={entry.actor}" if entry.actor is not None else ""
            target = f" target={entry.target}" if entry.target is not None else ""
            lines.append(
                f"[{entry.index:04d}] 第 {entry.day} 天 {entry.phase} "
                f"{entry.type}{actor}{target}: {entry.message}"
            )
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_jsonl(), encoding="utf-8")
        return p

    def write_text(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_text(), encoding="utf-8")
        return p
```

保留 `to_jsonl()`、`to_text()`、`write_jsonl()`、`write_text()` 方法，内部改用 `GameEvent.to_dict()`。

删除 `_value()` 和 `_jsonable()` helper（不再需要，`GameEvent.to_dict()` 已处理序列化）。

保留 `next_game_log_name()` 函数（被外部使用）。

- [ ] **Step 2: 运行测试**

Run: `uv run python -m pytest tests/test_engine.py tests/test_storage.py -v -x`
Expected: 可能有因 `LogLevel`/`LogVisibility`/`GameLogEntry` 引用导致的失败，记录下来在后续 step 修复。

---

### Task 1.3: 合并 `_log` 和 `_record` 为统一方法

**Files:**
- Modify: `engine/engine.py:146-184`

- [ ] **Step 1: 将 `_log` 和 `_record` 合并为 `_record`**

删除 `_log()` 方法（lines 146-164），重写 `_record()` 方法（lines 166-184）为统一入口：

```python
def _record(
    self,
    event_type: str,
    *,
    message: str = "",
    actor: int | None = None,
    target: int | None = None,
    payload: dict | None = None,
    public: bool = True,
) -> None:
    self.logger.record(
        day=self.state.day,
        phase=self.state.phase,
        event_type=event_type,
        message=message,
        actor=actor,
        target=target,
        payload=payload,
        public=public,
    )
```

这个方法同时完成：
1. `GameLogger.record()` → 写入 `self.entries`（内存）+ JSONL（文件）+ `EventSink`（SQLite）
2. 无需再单独写 `GameState.events`，因为 `GameLogger.entries` 已经是全量事件列表

- [ ] **Step 2: 删除 `GameState.events` 字段**

在 `engine/models.py` 的 `GameState` 中删除 `events: list[GameEvent]` 字段。`GameLogger.entries` 取代它成为唯一的事件源。

- [ ] **Step 3: 全局替换所有 `_log(` 调用为 `_record(`**

需要修改的文件和调用点：

**`engine/phases/night.py`** — `_log` 调用（约 5 处）改为 `_record`，补充 `message=` 参数（已是关键字参数所以格式不变），补充 `public=` 参数：
- `night_start`: `public=True`
- `night_end` (两种): `public=True`
- 其余保持默认 `public=True`

**`engine/phases/day.py`** — `_log` 调用（约 3 处）改为 `_record`

**`engine/phases/exile.py`** — `_log` 调用（约 5 处）改为 `_record`

**`engine/phases/sheriff.py`** — `_log` 调用（约 3 处）改为 `_record`

**`engine/actions.py`** — `_log` 调用（约 4 处）改为 `_record`。`action_request` 和 `invalid_response` 是内部事件，设 `public=False`

**`engine/rules/death.py`** — `_log` 调用（约 3 处）改为 `_record`

**`engine/rules/victory.py`** — `_log` 调用改为 `_record`

**`engine/rules/sheriff.py`** — `_log` 调用（约 2 处）改为 `_record`

**`engine/role_rules/werewolf.py`** — `_log` 调用改为 `_record`，设 `public=False`（狼人内部结果）

**`engine/role_rules/witch.py`** — `_log` 调用（约 2 处）改为 `_record`，设 `public=False`

**`engine/role_rules/seer.py`** — `_log` 调用改为 `_record`，设 `public=False`

**`engine/role_rules/guard.py`** — `_log` 调用改为 `_record`，设 `public=False`

**`engine/role_rules/hunter.py`** — 如有 `_log` 调用，改为 `_record`

**`engine/role_rules/white_wolf_king.py`** — `_log` 调用改为 `_record`

所有调用点的模式统一为：
```python
# 之前
engine._log("night_start", f"第 {engine.state.day} 夜开始", payload={"alive": engine.alive_ids()})

# 之后
engine._record("night_start", message=f"第 {engine.state.day} 夜开始", payload={"alive": engine.alive_ids()}, public=True)
```

- [ ] **Step 4: 运行全部引擎测试**

Run: `uv run python -m pytest tests/test_engine.py -v -x`
Expected: 全部 PASS

---

### Task 1.4: 更新 SQLiteEventSink 适配 GameEvent

**Files:**
- Modify: `storage/runtime.py:28-71`

- [ ] **Step 1: 更新 EventEntry 协议和 SQLiteEventSink**

将 `EventEntry` 协议更新为接收 `GameEvent` 的字段：

```python
class EventEntry(Protocol):
    """Protocol describing the fields storage needs from a game event."""
    index: int
    day: int
    phase: Any  # has .value or is str
    type: str
    message: str
    actor: int | None
    target: int | None
    payload: dict[str, Any]
    public: bool
```

注意：字段名从 `event_type` 改为 `type`（与 `GameEvent` 一致），删除 `level` 和 `visibility`。

更新 `SQLiteEventSink.record_event()`：

```python
def record_event(self, entry: EventEntry) -> None:
    phase_val = entry.phase.value if hasattr(entry.phase, "value") else entry.phase
    self._conn.execute(
        "INSERT INTO game_events "
        "(game_id, idx, day, phase, event_type, message, public, actor, target, payload) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            self._game_id,
            entry.index,
            entry.day,
            phase_val,
            entry.type,
            entry.message,
            1 if entry.public else 0,
            entry.actor,
            entry.target,
            json.dumps(entry.payload, ensure_ascii=False),
        ),
    )
```

- [ ] **Step 2: 更新 SQLite schema 的 game_events 表**

在 `storage/schema.py` 中，将 `game_events` 表的 `level` 和 `visibility` 列替换为 `public` 列：

```sql
CREATE TABLE IF NOT EXISTS game_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    day INTEGER NOT NULL,
    phase TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT,
    public INTEGER DEFAULT 1,
    actor INTEGER,
    target INTEGER,
    payload TEXT,
    created_at TEXT
);
```

- [ ] **Step 3: 运行存储测试**

Run: `uv run python -m pytest tests/test_storage.py -v -x`
Expected: 全部 PASS

---

### Task 1.5: 更新前端适配新的事件字段

**Files:**
- Modify: `ui/frontend/src/composables/gameSnapshot.js:68-82`
- Modify: `ui/frontend/src/composables/useGameState.js:74-76`
- Modify: `ui/frontend/src/composables/useCouncilScene.js:83-96`
- Modify: `ui/frontend/src/composables/useHistoryDerivedState.js`

- [ ] **Step 1: 更新 `gameSnapshot.js` 的 `normalizeLogEntry`**

当前 `normalizeLogEntry` 已经兼容 `type` 和 `event_type`（line 78: `type: log.type || log.event_type || ''`），也兼容 `public` 字段（line 79: `visibility: log.visibility || (log.public === false ? 'private' : 'public')`）。

后端发来的事件现在没有 `visibility` 字段，只有 `public: bool`。确保 `normalizeLogEntry` 正确处理：

```javascript
function normalizeLogEntry(log = {}) {
  const actorId = log.actor_id ?? log.actor
  const targetId = log.target_id ?? log.target
  const visibility = log.visibility || (log.public === false ? 'private' : 'public')
  return {
    ...log,
    sequence: log.sequence ?? log.index ?? 0,
    phase: normalizePhase(log.phase),
    type: log.type || log.event_type || '',
    actor_id: actorId,
    target_id: targetId,
    speaker: log.speaker || (actorId ? `${actorId}号` : '法官'),
    visibility,
    message: log.message || ''
  }
}
```

这一行已经能正确处理 `public: false → 'private'`、`public: true (或 undefined) → 'public'` 的映射。无需改动，确认即可。

- [ ] **Step 2: 确认 `useGameState.js` 的 `canSeeLog` 兼容**

当前逻辑（line 74-76）：
```javascript
function canSeeLog(log) {
    return log.visibility !== 'private' && (log.visibility !== 'god' || liveState.isWatch?.value)
}
```

`normalizeLogEntry` 已经把 `public: false` 映射为 `'private'`，`public: true` 映射为 `'public'`。所以 `canSeeLog` 不需要改动。

但 `'god'` 这个值不再由后端产生。后端统一用 `public: bool`。前端的 `'god'` 判断永远不会触发。确认这不是问题：观战模式下 `isWatch=true`，所以 `god` 视角的日志本来就是通过 `visibility: 'god'` 显示的。现在所有非 private 日志都对观战者可见，行为一致。

- [ ] **Step 3: 确认 `useCouncilScene.js` 兼容**

当前逻辑（line 93-96）用 `visibility === 'god'` 设置夜间色调：
```javascript
tone: latestPlayerLog.phase === 'night' || latestPlayerLog.visibility === 'god' ? 'night' : 'day'
```

后端不再产生 `visibility: 'god'`。改为用 `public === false` 判断：
```javascript
tone: latestPlayerLog.phase === 'night' || latestPlayerLog.visibility === 'private' ? 'night' : 'day'
```

- [ ] **Step 4: 确认 `useHistoryDerivedState.js` 兼容**

检查 `useHistoryDerivedState.js` 中对 `visibility` 的使用。如果有 `=== 'god'` 的判断，改为 `=== 'private'`。

- [ ] **Step 5: 手动验证前端**

启动前端 dev server，确认对局观战页面正常显示事件日志。

---

### Task 1.6: Commit

- [ ] **Step 1: 运行全量测试**

Run: `uv run python -m pytest tests/ -v -x --timeout=30`
Expected: 全部 PASS

- [ ] **Step 2: Commit**

```bash
git add engine/models.py engine/logging.py engine/engine.py engine/phases/ engine/actions.py engine/rules/ engine/role_rules/ storage/runtime.py storage/schema.py ui/frontend/src/composables/
git commit -m "refactor: merge GameEvent and GameLogEntry into unified event model

- Add message/index fields to GameEvent, delete GameLogEntry
- Merge _log() and _record() into single _record() method
- Remove GameState.events (GameLogger.entries is now the single source)
- Update SQLiteEventSink to use public:bool instead of visibility:enum
- Update game_events schema: replace level/visibility with public column
- Frontend: normalizeLogEntry already handles public→visibility mapping"
```

---

## Task 2: 删除 public_log，改用 events + 可见性过滤

**目标：** 删除 `GameState.public_log` 字符串列表，`Observation` 改为输出 `visible_events: list[GameEvent]`，`observation_for()` 按 `public` 字段过滤。

**依赖：** Task 1 完成后才能执行（需要统一事件模型）。

**Files:**
- Modify: `engine/models.py` (GameState, Observation)
- Modify: `engine/engine.py` (observation_for)
- Delete: `engine/public_log.py`
- Modify: `engine/actions.py` (删除 append_public_action 调用)
- Modify: `agent/core/memory.py` (AgentMemory 适配 visible_events)
- Modify: `agent/knowledge/prompts/base.py` (Prompt Builder 适配)
- Modify: `ui/backend/game_runner.py` (human observation payload)
- Test: `tests/test_engine.py`

---

### Task 2.1: 修改 GameState 和 Observation

**Files:**
- Modify: `engine/models.py`

- [ ] **Step 1: 从 GameState 删除 public_log**

在 `engine/models.py` 的 `GameState` 中，删除 `public_log: list[str]` 字段。确认没有任何地方直接写 `engine.state.public_log`（Task 1.3 已将所有 `_log` 调用改为 `_record`，`public_log.py` 的 `append_public_event` 调用将在 Step 2 处理）。

- [ ] **Step 2: 修改 Observation，用 visible_events 替换 public_log**

将 `Observation` 的 `public_log: tuple[str, ...]` 替换为 `visible_events: tuple[GameEvent, ...]`：

```python
@dataclass(slots=True)
class Observation:
    player_id: int
    self_role: Role
    phase: Phase
    day: int
    alive_players: tuple[int, ...]
    dead_players: tuple[int, ...]
    sheriff_id: int | None
    visible_events: tuple[GameEvent, ...]  # 替换 public_log
    known_roles: dict[int, Role] = field(default_factory=dict)
    seer_checks: dict[int, Team] = field(default_factory=dict)
    role_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

### Task 2.2: 实现 observation_for 可见性过滤

**Files:**
- Modify: `engine/engine.py:88-104`

- [ ] **Step 1: 重写 observation_for**

```python
def observation_for(self, player_id: int, metadata: dict | None = None) -> Observation:
    ps = self.state.players[player_id]
    role_rule = get_role_rule(ps.role)
    visible = tuple(
        e for e in self.logger.entries
        if e.public or e.actor == player_id
    )
    return Observation(
        player_id=player_id,
        self_role=ps.role,
        phase=self.state.phase,
        day=self.state.day,
        alive_players=tuple(self.alive_ids()),
        dead_players=tuple(self.dead_ids()),
        sheriff_id=self.state.sheriff_id,
        visible_events=visible,
        known_roles=role_rule.visible_roles(self, player_id),
        seer_checks=role_rule.seer_checks(self, player_id),
        role_state=role_rule.get_role_state(self, player_id),
        metadata=metadata or {},
    )
```

过滤逻辑：`public=True` 的事件所有人可见，`public=False` 的事件只有 `actor == player_id` 可见（如女巫看到自己的用药记录）。

---

### Task 2.3: 删除 public_log.py 和相关调用

**Files:**
- Delete: `engine/public_log.py`
- Modify: `engine/actions.py` (删除 `append_public_action` 调用)

- [ ] **Step 1: 删除 engine/public_log.py**

```bash
rm engine/public_log.py
```

- [ ] **Step 2: 从 engine/actions.py 删除 append_public_action 导入和调用**

在 `engine/actions.py` 中搜索 `from engine.public_log import` 和 `append_public_action`，删除这些行。`append_public_action` 在 action 成功时被调用（约 line 74），删除该调用。Task 1 中已将 `_log` 调用改为 `_record`，所以 action 事件已经通过 `_record` 记录。

- [ ] **Step 3: 搜索所有 `public_log` 引用并清理**

```bash
grep -rn "public_log" engine/ agent/ ui/ storage/ tests/
```

确保没有任何残留引用。预期需要修改的地方：
- `engine/__init__.py` 如有导出 `public_log`
- 测试文件中的断言

---

### Task 2.4: 更新 AgentMemory 适配 visible_events

**Files:**
- Modify: `agent/core/memory.py`

- [ ] **Step 1: 修改 `_observe_request` 方法**

当前 `_observe_request` 从 `observation.public_log` 读取 JSON 字符串列表并正则解析。改为从 `observation.visible_events` 读取结构化 `GameEvent` 对象。

查找 `_observe_request` 方法中所有 `public_log` 引用，改为读 `visible_events`。每个 `GameEvent` 有 `type`、`day`、`phase`、`actor`、`target`、`payload`、`message` 字段，可以直接用字段匹配替代 JSON 解析 + 正则匹配。

关键改动：
```python
# 之前
for raw in observation.public_log:
    entry = json.loads(raw)
    event_type = entry.get("type", "")
    ...

# 之后
for event in observation.visible_events:
    event_type = event.type
    actor = event.actor
    target = event.target
    ...
```

- [ ] **Step 2: 运行 Agent 测试**

Run: `uv run python -m pytest tests/ -v -x -k "memory or agent"`
Expected: PASS

---

### Task 2.5: 更新 Prompt Builder 适配

**Files:**
- Modify: `agent/knowledge/prompts/base.py`

- [ ] **Step 1: 修改 prompt 组装中对 public_log 的引用**

搜索 `public_log` 引用，改为 `visible_events`。prompt 中展示事件时，直接读 `event.message`（已是人类可读文本），无需 JSON 解析。

---

### Task 2.6: 更新 UI 后端 human observation

**Files:**
- Modify: `ui/backend/game_runner.py:574`

- [ ] **Step 1: 修改 `_human_observation_payload`**

将 line 574 的：
```python
"public_log": list(observation.public_log),
```
改为：
```python
"visible_events": [e.to_dict() for e in observation.visible_events],
```

前端的 `gameSnapshot.js` 中 `normalizeLogEntry` 已经能处理 `type`/`event_type`、`public`/`visibility`、`message`、`index` 字段，无需额外改动。

---

### Task 2.7: Commit

- [ ] **Step 1: 运行全量测试**

Run: `uv run python -m pytest tests/ -v -x --timeout=30`
Expected: 全部 PASS

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "refactor: delete public_log, use visible_events with visibility filtering

- Remove GameState.public_log string list
- Observation.visible_events replaces public_log, filtered by public flag
- Delete engine/public_log.py
- AgentMemory reads structured GameEvent instead of JSON strings
- UI backend sends visible_events dict to frontend"
```

---

## Task 3: 删除 StorageRebuilder 和 ArchiveImporter

**目标：** 移除不再需要的文件导入工具。

**Files:**
- Delete: `storage/rebuilder.py`
- Delete: `storage/importer.py`
- Modify: 任何引用这两个模块的文件

---

### Task 3.1: 搜索引用并删除

- [ ] **Step 1: 搜索所有引用**

```bash
grep -rn "StorageRebuilder\|ArchiveImporter\|from storage.rebuilder\|from storage.importer\|storage.rebuilder\|storage.importer" --include="*.py" .
```

- [ ] **Step 2: 删除文件**

```bash
rm storage/rebuilder.py
rm storage/importer.py
```

- [ ] **Step 3: 清理引用**

从所有引用处删除 import 语句。预期涉及：
- `ui/backend/` 中如有调用 rebuilder 的路由
- `__init__.py` 中如有导出
- 测试文件中如有相关测试

- [ ] **Step 4: 运行测试**

Run: `uv run python -m pytest tests/ -v -x --timeout=30`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete StorageRebuilder and ArchiveImporter

All game data is now written to SQLite via GamePersistence at runtime.
JSON files serve only as backup; no import tools needed."
```

---

## Task 4: 合并 wolf.db 和 battle.db

**目标：** 将 battle 特有的表（evaluations, decision_reviews, counterfactuals, reports）合并到主 wolf.db，删除独立的 battle.db 连接管理。

**Files:**
- Modify: `storage/schema.py` (添加 battle 表)
- Delete: `storage/battle/schema.py`
- Modify: `storage/shared/connection.py` (删除 get_battle_connection)
- Modify: `storage/battle/evaluation_repo.py`, `review_repo.py`, `report_repo.py`, `leaderboard_repo.py`, `decision_repo.py`, `event_repo.py`, `game_repo.py`
- Test: `tests/test_storage.py`

---

### Task 4.1: 将 battle 表合并到主 schema

**Files:**
- Modify: `storage/schema.py`

- [ ] **Step 1: 将 battle 特有表追加到主 schema**

在 `storage/schema.py` 的 `SCHEMA` 字符串末尾追加：

```sql
-- Battle evaluation tables (merged from battle.db)
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    player_seat INTEGER,
    role TEXT,
    speech_score REAL,
    vote_score REAL,
    skill_score REAL,
    information_score REAL,
    cooperation_score REAL,
    overall_score REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS decision_reviews (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    decision_id TEXT,
    player_seat INTEGER,
    day INTEGER,
    phase TEXT,
    action_type TEXT,
    quality TEXT,
    reason TEXT,
    alternative_action TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS counterfactuals (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    decision_id TEXT,
    what_if TEXT,
    likely_outcome TEXT,
    confidence REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL UNIQUE REFERENCES games(id),
    summary TEXT,
    created_at TEXT
);
```

同时在索引部分追加 battle 表的索引：
```sql
CREATE INDEX IF NOT EXISTS idx_eval_game ON evaluations(game_id);
CREATE INDEX IF NOT EXISTS idx_eval_role ON evaluations(role);
CREATE INDEX IF NOT EXISTS idx_dr_game ON decision_reviews(game_id);
CREATE INDEX IF NOT EXISTS idx_dr_decision ON decision_reviews(decision_id);
CREATE INDEX IF NOT EXISTS idx_cf_game ON counterfactuals(game_id);
CREATE INDEX IF NOT EXISTS idx_cf_decision ON counterfactuals(decision_id);
```

注意：battle 的 `leaderboard` 表结构与主 schema 的 `leaderboard` 不同（battle 有 `avg_speech_score` 等评分维度字段）。决策是**使用主 schema 的 leaderboard 表**，battle 的评分维度如果需要可以加到主 leaderboard 表的 `scores` JSON 字段中。不为 battle leaderboard 创建单独表。

---

### Task 4.2: 更新 battle repo 使用主连接

**Files:**
- Modify: `storage/battle/evaluation_repo.py`
- Modify: `storage/battle/review_repo.py`
- Modify: `storage/battle/report_repo.py`
- Modify: `storage/battle/decision_repo.py`
- Modify: `storage/battle/event_repo.py`
- Modify: `storage/battle/game_repo.py`
- Modify: `storage/battle/leaderboard_repo.py`

- [ ] **Step 1: 修改各 repo 的连接获取方式**

每个 battle repo 当前通过 `get_battle_connection()` 获取独立的 battle.db 连接。改为使用主 `get_connection()`（from `storage.schema`）。

搜索所有 `get_battle_connection` 调用，替换为 `get_connection`。

- [ ] **Step 2: 删除 storage/battle/schema.py**

```bash
rm storage/battle/schema.py
```

- [ ] **Step 3: 修改 storage/shared/connection.py**

删除 `get_battle_connection()` 函数。保留 `get_evolution_connection()`。

- [ ] **Step 4: 运行测试**

Run: `uv run python -m pytest tests/ -v -x --timeout=30`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: merge battle.db tables into main wolf.db

- Add evaluations, decision_reviews, counterfactuals, reports to wolf.db schema
- Update battle repos to use main get_connection()
- Delete storage/battle/schema.py and get_battle_connection()
- evolution.db remains separate for learning pipeline data"
```

---

## Task 5: 修复进化 run SSE 自动重连

**目标：** 进化 run 的 SSE 断线后自动重连，而非静默关闭。

**Files:**
- Modify: `ui/frontend/src/composables/useEvolutionWorkbench.js:480-510`

---

### Task 5.1: 添加 SSE 重连逻辑

- [ ] **Step 1: 替换 error 处理为重连**

当前代码（lines 506-509）：
```javascript
source.addEventListener('error', () => {
  source.close()
  if (sse.value === source) sse.value = null
})
```

替换为带退避的重连逻辑：

```javascript
let retryDelay = 1000
const maxRetryDelay = 30000

function connect() {
  if (!id || typeof EventSource === 'undefined') return
  if (String(id).startsWith('mock-')) return
  sse.value?.close?.()
  const source = new EventSource(`${apiBase}/evolution-runs/${encodeURIComponent(id)}/events`)
  sse.value = source

  const handle = async (event) => {
    retryDelay = 1000  // 重置退避
    let payload = {}
    try { payload = JSON.parse(event.data || '{}') } catch {}
    eventLog.value = [
      { id: `${Date.now()}-${event.type}`, type: event.type, payload },
      ...eventLog.value
    ].slice(0, 24)
    await loadRuns()
    if (selectedRunId.value === id) {
      const current = runRows.value.find((item) => item.id === id)
      if (current) selectedRun.value = current
      await Promise.all([loadDiff(id), loadRunGames(id)])
    }
    if (['promoted', 'rejected', 'failed'].includes(event.type)) {
      source.close()
    }
  }

  ;['progress', 'reviewing', 'promoted', 'rejected', 'failed'].forEach((name) => {
    source.addEventListener(name, handle)
  })

  source.addEventListener('error', () => {
    source.close()
    if (sse.value === source) sse.value = null
    // 自动重连（指数退避）
    setTimeout(() => {
      if (selectedRunId.value === id) {  // 用户仍在查看该 run
        retryDelay = Math.min(retryDelay * 2, maxRetryDelay)
        connect()
      }
    }, retryDelay)
  })
}

connect()
```

核心改动：
1. 将 `subscribe` 函数体提取为 `connect` 函数
2. error handler 中加 `setTimeout` 重连，指数退避（1s → 2s → 4s → ... → 30s 上限）
3. 成功收到事件时重置退避为 1s
4. 只在用户仍在查看该 run 时才重连（`selectedRunId.value === id`）
5. 终态事件（promoted/rejected/failed）关闭后不重连

- [ ] **Step 2: 手动验证**

启动前端，启动一个进化 run，观察 SSE 事件正常接收。模拟断网（如重启后端），确认前端自动重连。

---

### Task 5.2: Commit

- [ ] **Step 1: Commit**

```bash
git add ui/frontend/src/composables/useEvolutionWorkbench.js
git commit -m "fix: add SSE auto-reconnect for evolution run events

- Exponential backoff retry on SSE error (1s → 30s max)
- Reset backoff on successful event receipt
- Only reconnect if user still viewing the same run
- No reconnect after terminal events (promoted/rejected/failed)"
```

---

## 完成验证

- [ ] **Step 1: 运行全量测试**

Run: `uv run python -m pytest tests/ -v --timeout=60`
Expected: 全部 PASS

- [ ] **Step 2: 启动后端并跑一局 AI 对战**

```bash
uv run python -m ui.backend.app
```

在前端启动一局 AI 对战，确认：
- 实时日志正常显示
- 复盘/决策详情正常
- 历史游戏列表正常

- [ ] **Step 3: 启动一局人机混战**

确认：
- SSE 推送 decision_needed 正常
- ActionPanel 展示正常
- 提交动作后游戏继续

- [ ] **Step 4: 启动一个进化 run**

确认：
- SSE 事件正常接收
- 断线后自动重连
- 进化流程完整运行

# Spec #1: 游戏引擎（规则系统）

> 范围：对局引擎、角色规则、阶段流转、信息隔离、胜负判定
> 不含：Agent 决策、记忆、Prompt（另见 Agent spec）

---

## 1. 现状分析

### 1.1 引擎架构

**GameEngine** (`engine/engine.py`) 是对局的核心控制器：

```
GameEngine
  ├── state: GameState          # 当前对局状态
  ├── agents: dict[int, PlayerAgent]  # 玩家 agent
  ├── config: GameConfig        # 游戏配置（角色数量、阶段顺序等）
  ├── logger: GameLogger        # 事件日志
  └── methods:
      ├── run_until_finished()  # 主循环
      ├── run_night()           # 夜间阶段
      ├── run_day_speeches()    # 白天发言
      ├── run_exile_vote()      # 放逐投票
      ├── ask()                 # 向 agent 请求行动
      └── check_winner()        # 胜负判定
```

**主循环** (`engine.py:209-238`)：

```
for day in range(max_days):
    if day == 0:
        night_without_death_reveal  # 第0天特殊：先警长竞选再揭示死亡
        sheriff_election (可选)
    else:
        run_night → reveal_night_deaths
    
    check_winner (夜间后)
    run_day_speeches
    check_winner (发言后)
    
    if white_wolf_exploded:
        skip exile_vote
    else:
        run_exile_vote
        check_winner (投票后)
```

### 1.2 角色系统

**7 个角色** (`engine/models.py:19-37`)：

| 角色 | 阵营 | 夜间行动 | 特殊能力 |
|------|------|----------|----------|
| werewolf | 狼人 | 选择杀人目标 | 狼人互认 |
| white_wolf_king | 狼人 | 选择杀人目标 | 自爆带走一人 |
| seer | 好人 | 查验一人身份 | 知道查验结果 |
| witch | 好人 | 用药（解药/毒药） | 知道被杀者身份 |
| guard | 好人 | 选择守护目标 | 同一人不能连续守护 |
| hunter | 好人 | — | 死亡时可开枪 |
| villager | 好人 | — | 无特殊能力 |

**RoleRule 协议** (`engine/role_rules/base.py:11-24`)：

```python
class RoleRule(Protocol):
    role: Role
    def visible_roles(self, engine, player_id) -> dict[int, Role]: ...
    def seer_checks(self, engine, player_id) -> dict[int, Team]: ...
    async def night_action(self, engine): ...
    def day_interrupt(self, engine, player_id) -> str | None: ...
```

**Registry** (`engine/role_rules/registry.py`)：模块级单例 dict，`rule_for(role)` 查找。规则实例无状态，所有状态通过 `engine` 参数读写。

### 1.3 GameState

```python
@dataclass
class GameState:
    players: dict[int, PlayerState]    # {seat: PlayerState}
    day: int = 0
    phase: Phase = Phase.SETUP
    events: list[GameEvent]            # 全局事件流
    public_log: list[str]              # 公开事件文本
    deaths: list[DeathRecord]
    sheriff_id: int | None
    badge_destroyed: bool = False
    # 角色特定状态（混在通用 state 里）
    witch_antidote_available: bool = True
    witch_poison_available: bool = True
    guard_last_target: int | None
    seer_checks: dict[int, dict[int, Team]]
    pending_last_words: list[int]
    pending_hunter_shots: list[int]
    winner: Winner | None
```

### 1.4 信息隔离

**现状**：`GameEvent` 有 `public: bool` 字段。`Observation.public_log` 是字符串列表。

**Observation** (`engine/models.py:122-134`)：

```python
@dataclass
class Observation:
    player_id: int
    self_role: Role
    phase: Phase
    day: int
    alive_players: tuple[int, ...]
    dead_players: tuple[int, ...]
    sheriff_id: int | None
    public_log: tuple[str, ...]      # 过滤后的公开事件（字符串）
    known_roles: dict[int, Role]     # 已知角色（仅特殊角色）
    seer_checks: dict[int, Team]     # 查验结果（仅预言家）
    metadata: dict[str, Any]
```

**夜间行动分发** (`engine/phases/night.py:62-71`)：

```python
for role in engine.config.night_order:
    if role is Role.GUARD:
        protected_target = await rule_for(Role.GUARD).night_action(engine)
    elif role is Role.WEREWOLF:
        killed_target = await rule_for(Role.WEREWOLF).night_action(engine)
    elif role is Role.SEER:
        await rule_for(Role.SEER).night_action(engine)
    elif role is Role.WITCH:
        saved, poisoned_target = await rule_for(Role.WITCH).night_action(engine, killed_target)
    else:
        await rule_for(role).night_action(engine)
```

### 1.5 胜负判定

**胜利条件** (`engine/rules/victory.py`)：
- 狼人阵营存活人数 ≥ 好人阵营存活人数 → 狼人胜
- 所有狼人死亡 → 好人胜
- 白狼王自爆 → 狼人阵营额外加分

### 1.6 ask() 机制

**现状** (`engine/actions.py:14-100`)：

```python
async def ask(engine, player_id, action_type, candidates, metadata, validator, default):
    for retry in range(2):  # 最多重试 2 次
        request = ActionRequest(player_id, action_type, engine.state.phase, observation, candidates, retry)
        response = await engine.agents[player_id].act(request)  # ← 无 try/except
        if response matches action_type and validator passes:
            return response
    return default  # 2 次失败后用默认值
```

**问题**：`engine.agents[player_id].act(request)` 没有 try/except，agent 异常会直接中断对局。

---

## 2. 改动方案

### 2.1 P1: GameEvent 加 visibility enum

**现状**：`GameEvent.public: bool` 只区分公开/私有。

**目标**：细粒度可见性控制。

```python
class Visibility(StrEnum):
    PUBLIC = "public"       # 所有存活玩家
    WEREWOLF = "werewolf"   # 仅狼人
    WITCH = "witch"         # 仅女巫
    SEER = "seer"           # 仅预言家
    GUARD = "guard"         # 仅守卫
    SYSTEM = "system"       # 仅引擎内部

@dataclass
class GameEvent:
    type: str
    day: int
    phase: Phase
    actor: int | None
    target: int | None
    payload: dict[str, Any]
    visibility: Visibility  # 替代原来的 public: bool
```

**影响范围**：
- `engine/phases/*.py`：所有 `engine._log()` 调用需要指定 visibility
- `engine/rules/*.py`：死亡触发等事件需要指定 visibility
- `engine/role_rules/*.py`：夜间行动事件需要指定 visibility

### 2.2 P1: Observation 用结构化事件替代字符串

**现状**：`Observation.public_log: tuple[str, ...]` 是过滤后的字符串列表。

**目标**：`Observation.visible_events: tuple[GameEvent, ...]` 是过滤后的结构化事件。

```python
@dataclass
class Observation:
    ...
    visible_events: tuple[GameEvent, ...]  # 替代 public_log
    ...

def filter_events(events: list[GameEvent], role: Role) -> list[GameEvent]:
    visible = {Visibility.PUBLIC, Visibility.SYSTEM}
    if role.is_wolf():  visible.add(Visibility.WEREWOLF)
    if role == WITCH:   visible.add(Visibility.WITCH)
    if role == SEER:    visible.add(Visibility.SEER)
    if role == GUARD:   visible.add(Visibility.GUARD)
    return [e for e in events if e.visibility in visible]
```

**影响范围**：
- `engine/engine.py`：构造 Observation 时调用 `filter_events`
- `engine/role_rules/*.py`：`visible_roles()` 和 `seer_checks()` 方法
- Agent 层：所有读取 `observation.public_log` 的代码改为读取 `observation.visible_events`

### 2.3 P1: ask() 捕获 agent 异常

**现状**：agent 异常直接中断对局。

**目标**：捕获异常，使用规则默认行为。

```python
async def ask(engine, player_id, action_type, candidates, metadata, validator, default):
    for retry in range(2):
        try:
            response = await engine.agents[player_id].act(request)
        except Exception as exc:
            engine._log("agent_disconnect",
                f"P{player_id} ({engine.state.players[player_id].role.value}) 断线: {exc}",
                actor=player_id)
            return default  # 用规则默认行为

        if response matches action_type and validator passes:
            return response
    return default
```

**断线规则**：

| 角色 | 断线默认行为 |
|------|-------------|
| werewolf | 随机选择一个非狼人目标 |
| seer | 不查验（跳过） |
| witch | 不用药（跳过） |
| guard | 不守护（跳过） |
| hunter | 不开枪（跳过） |
| villager | 不行动（跳过） |
| white_wolf_king | 不自爆（跳过） |

**统计**：`GameState` 新增 `llm_error_count: int` 字段，每次断线 +1。

### 2.4 P2: GameState 拆分角色状态

**现状**：`witch_antidote_available`、`guard_last_target` 等混在 GameState 里。

**目标**：角色状态移到 `GameEngine.role_state`。

```python
class GameEngine:
    role_state: dict[Role, dict] = field(default_factory=dict)
    # 初始化时:
    # {WITCH: {antidote: True, poison: True}, GUARD: {last_target: None}, ...}
```

**角色规则读写**：

```python
# 现在
engine.state.witch_antidote_available = False

# 改后
engine.role_state[Role.WITCH]["antidote"] = False
```

**影响范围**：所有角色规则（witch.py, guard.py, seer.py）+ engine.py 中读写这些字段的代码。

### 2.5 不改的部分

| 设计点 | 现状 | 理由 |
|--------|------|------|
| 夜间 if/elif 链 | 硬编码 7 角色 | 角色数量固定，不需要多态分发 |
| RoleRule 单例 | 无状态 singleton | 确认安全 |
| 主循环结构 | for day in range(max_days) | 结构清晰 |
| 胜负判定 | 狼人≥好人 or 全狼死 | 规则正确 |
| PlayerAgent 协议 | 单方法 `act()` | 简洁够用 |
| GameConfig | 角色数量 + 阶段顺序 | 够用 |
| DeathCause enum | 6 种死因 | 覆盖完整 |

---

## 3. 改动优先级

| 优先级 | 改动 | 工作量 | 理由 |
|--------|------|--------|------|
| **P1** | GameEvent visibility enum | 中 | 评审要求"信息隔离严格经测试无泄露" |
| **P1** | Observation visible_events | 中 | 配合 visibility，结构化事件比字符串更可测试 |
| **P1** | ask() 捕获异常 | 小 | 防止 agent 错误中断对局 |
| **P2** | GameState 拆分角色状态 | 大 | 架构改进，非必须 |

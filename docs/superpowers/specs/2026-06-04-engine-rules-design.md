# Spec #1: 游戏引擎（规则系统）

> 范围：对局引擎、角色规则、阶段流转、信息隔离、胜负判定、双模式支持
> 不含：Agent 决策、记忆、Prompt（另见 Agent spec）

---

## 1. 双模式支持

引擎必须支持两种对局模式：

| | AI vs AI | 人机混战 |
|---|---------|---------|
| 玩家组成 | 全部 LLM Agent | 部分人类 + 部分 LLM |
| 执行方式 | 全自动异步并发 | AI 自动执行，人类回合暂停等待 |
| 信息展示 | 无需 UI（可选上帝视角回放） | 人类需要实时看到游戏状态 + 自己的视角 |
| 速度 | 快（取决于 LLM 延迟） | 取决于人类操作速度 |
| 断线处理 | LLM 失败用规则 fallback | 人类超时 → 等待 / 踢出 |

### 1.1 PlayerAgent 扩展

**现状** (`engine/players.py`)：

```python
class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse: ...

class HumanPlayer:  # 已有，通过 Future 等待 UI 输入
    async def act(self, request):
        self._future = asyncio.get_event_loop().create_future()
        return await self._future
    def submit(self, response):
        self._future.set_result(response)
```

**目标**：`HumanPlayer` 已经实现了"暂停等待"模式，但缺少：
- 超时处理（人类长时间不操作）
- 视角信息推送（人类需要看到游戏状态）
- 游戏状态订阅（UI 需要实时更新）

### 1.2 引擎-UI 通信

**方式**：WebSocket/SSE（引擎推送，UI 订阅）

**事件流**：

```
引擎 → UI:
  game_start       {game_id, players: [{id, role}], config}
  phase_change     {day, phase}
  game_event       {type, day, phase, actor, target, payload, visibility}
  decision_needed  {player_id, action_type, candidates, observation}  ← 人类回合
  decision_made    {player_id, action_type, target, choice}
  night_result     {deaths: [...]}
  game_end         {winner, final_state}

UI → 引擎:
  submit_decision  {player_id, action_type, target, choice, text}  ← 人类提交
```

### 1.3 人类视角过滤

**关键**：人类玩家只能看到自己角色允许的信息，和 AI Agent 一样。

```python
# 引擎构造 Observation 时，根据角色过滤事件
observation = Observation(
    visible_events=tuple(filter_events(engine.state.events, player_role)),
    # 人类玩家和 AI Agent 拿到同样过滤后的 Observation
    ...
)
```

**UI 展示**：
- 上帝视角（管理员/观战者）：全量事件
- 人类玩家视角：过滤后的事件 + 自己的手牌信息
- AI Agent：无需 UI（后台自动运行）

### 1.4 对局会话管理

```python
class GameSession:
    """管理一局游戏的生命周期，支持 AI-only 和混合模式。"""
    game_id: str
    mode: Literal["ai_only", "mixed"]
    engine: GameEngine
    human_players: dict[int, HumanPlayer]  # seat → HumanPlayer
    ai_players: dict[int, AgentRuntime]    # seat → AgentRuntime
    event_queue: asyncio.Queue             # → UI 推送
    decision_futures: dict[int, asyncio.Future]  # 人类回合等待
```

**流程**：
```
1. 创建 GameSession，配置 AI/Human 玩家
2. 引擎主循环 run_until_finished()
3. 每个回合:
   - AI 玩家: 直接调用 agent.act()，结果自动返回
   - Human 玩家:
     a. 引擎暂停
     b. 推送 decision_needed 事件到 UI
     c. 等待 UI 返回 submit_decision
     d. 引擎继续
4. 所有事件通过 event_queue 推送到 UI
5. 游戏结束，推送 game_end
```

---

## 2. 引擎架构（现状分析）

### 2.1 GameEngine 主循环

**现状** (`engine/engine.py:209-238`)：

```
for day in range(max_days):
    if day == 0:
        night_without_death_reveal  # 第0天特殊
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

**问题**：主循环是同步阻塞的，无法暂停等待人类输入。

### 2.2 GameState

```python
@dataclass
class GameState:
    players: dict[int, PlayerState]
    day: int = 0
    phase: Phase = Phase.SETUP
    events: list[GameEvent]
    public_log: list[str]
    deaths: list[DeathRecord]
    sheriff_id: int | None
    badge_destroyed: bool = False
    witch_antidote_available: bool = True    # 角色特定
    witch_poison_available: bool = True      # 角色特定
    guard_last_target: int | None            # 角色特定
    seer_checks: dict[int, dict[int, Team]]  # 角色特定
    pending_last_words: list[int]
    pending_hunter_shots: list[int]
    winner: Winner | None
```

### 2.3 信息隔离

**现状**：`GameEvent.public: bool` + `Observation.public_log: tuple[str, ...]`

**问题**：粒度不够，字符串列表非结构化。

### 2.4 ask() 机制

**现状** (`engine/actions.py:14-100`)：重试 2 次，无 try/except，agent 异常中断对局。

---

## 3. 改动方案

### 3.1 P1: GameEvent 加 visibility enum

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
    visibility: Visibility
```

### 3.2 P1: Observation 用结构化事件

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

### 3.3 P1: ask() 捕获异常 + 支持 HumanPlayer

```python
async def ask(engine, player_id, action_type, candidates, metadata, validator, default):
    for retry in range(2):
        try:
            response = await engine.agents[player_id].act(request)
        except Exception as exc:
            engine._log("agent_disconnect", f"P{player_id} 断线: {exc}")
            return default
        if response matches action_type and validator passes:
            return response
    return default
```

**HumanPlayer 超时处理**：

```python
class HumanPlayer:
    async def act(self, request, timeout=300):  # 5 分钟超时
        self._future = asyncio.get_event_loop().create_future()
        try:
            return await asyncio.wait_for(self._future, timeout=timeout)
        except asyncio.TimeoutError:
            return default_action(request)  # 超时用默认行为
```

### 3.4 P1: GameSession 会话管理

```python
class GameSession:
    """管理一局游戏，支持 AI-only 和混合模式。"""
    
    async def start(self):
        """启动游戏，推送 game_start 事件。"""
        await self._emit("game_start", {...})
        await self.engine.run_until_finished()
    
    async def on_human_decision_needed(self, player_id, request):
        """人类回合：暂停引擎，推送 decision_needed，等待 UI 响应。"""
        await self._emit("decision_needed", {
            "player_id": player_id,
            "action_type": request.action_type.value,
            "candidates": list(request.candidates),
            "observation": self._filter_for_human(request),
        })
        # 等待 UI 提交（通过 WebSocket）
        response = await self.decision_futures[player_id]
        return response
    
    async def submit_human_decision(self, player_id, response):
        """UI 提交人类决策。"""
        if player_id in self.decision_futures:
            self.decision_futures[player_id].set_result(response)
```

### 3.5 P2: GameState 拆分角色状态

```python
class GameEngine:
    role_state: dict[Role, dict]  # 角色特定状态
    # {WITCH: {antidote: True, poison: True}, GUARD: {last_target: None}, ...}
```

### 3.6 不改的部分

| 设计点 | 理由 |
|--------|------|
| 夜间 if/elif 链 | 角色数量固定 |
| RoleRule 单例 | 确认安全 |
| 主循环结构 | 改为 async 支持暂停即可 |
| 胜负判定 | 规则正确 |
| PlayerAgent 协议 | `act()` 接口足够 |
| GameConfig | 够用 |

---

## 4. 改动优先级

| 优先级 | 改动 | 工作量 |
|--------|------|--------|
| **P1** | GameEvent visibility enum | 中 |
| **P1** | Observation visible_events | 中 |
| **P1** | ask() 捕获异常 | 小 |
| **P1** | HumanPlayer 超时处理 | 小 |
| **P1** | GameSession 会话管理 | 大 |
| **P2** | GameState 拆分角色状态 | 大 |

---

## 5. 前端交互设计（概要）

### 5.1 游戏状态页面

```
┌─────────────────────────────────────────────┐
│  狼人杀对局 #game_003                        │
│  第 3 天 | 夜间 | 当前行动: 预言家查验        │
├─────────────────────────────────────────────┤
│  [你的身份: 女巫]                             │
│  解药: ✅  毒药: ✅                           │
│                                              │
│  公共事件:                                    │
│  - 第1天: 3号死亡（狼人击杀）                  │
│  - 第1天: 1号竞选警长成功                      │
│  - 第2天: 5号被放逐                           │
│                                              │
│  你的信息:                                    │
│  - 第1夜: 你救了3号                           │
│                                              │
│  当前行动: [等待预言家查验...]                  │
├─────────────────────────────────────────────┤
│  玩家状态:                                    │
│  P1(警长) ✅  P2 ✅  P3 💀  P4 ✅  P5 💀    │
│  P6 ✅  P7 ✅  P8 ✅  P9 ✅  P10 ✅         │
│  P11 ✅  P12 ✅                               │
└─────────────────────────────────────────────┘
```

### 5.2 人类决策界面

```
┌─────────────────────────────────────────────┐
│  轮到你行动！                                 │
│  第 2 天 | 白天发言                           │
├─────────────────────────────────────────────┤
│  你的发言:                                    │
│  ┌─────────────────────────────────────────┐ │
│  │ 我是预言家，第一晚查验了7号是狼人。       │ │
│  │ 建议今天放逐7号。                         │ │
│  └─────────────────────────────────────────┘ │
│                                              │
│  [提交发言]  [跳过]                           │
└─────────────────────────────────────────────┘
```

## 三方向实施计划

编制日期：2026-06-04，基于当日代码快照。

---

## 一、Engine 结构化可见性 / role_state

### 1.1 现状问题

当前 `PlayerState` 只有 `id`、`role`、`alive` 三个字段，所有角色专属状态被"上浮"到 `GameState` 顶层平铺：`witch_antidote_available`、`witch_poison_available`、`guard_last_target`、`seer_checks`、`pending_hunter_shots`。这导致每新增一个角色 `GameState` 就膨胀一轮，且角色状态读写散落各处，没有统一抽象。

同时 `Observation` 缺少一个通用的 `role_state` 通道——守卫看不到自己上夜守了谁，女巫无法通过 Observation 结构化地得知药水剩余，这些信息要么依赖临时 `metadata` 传递，要么完全不暴露。

此外，引擎没有统一的快照查询接口（`snapshot()` / `to_dict()`），外部系统只能通过 `engine.state` 直接访问上帝视角的原始对象。

### 1.2 方案概览

分三层改造：PlayerState 下沉角色状态、RoleRule 协议扩展可见性方法、GameEngine 暴露统一快照 API。

### 1.3 实施步骤

**Phase 1：PlayerState 增加 role_state（约 1 天）**

在 `engine/models.py` 的 `PlayerState` 上新增字段：

```python
@dataclass(slots=True)
class PlayerState:
    id: int
    role: Role
    alive: bool = True
    role_state: dict[str, Any] = field(default_factory=dict)
```

各角色的 role_state 键值规划：

| 角色 | 键 | 类型 | 语义 |
|------|------|------|------|
| 女巫 | `antidote_available` | `bool` | 解药是否可用 |
| 女巫 | `poison_available` | `bool` | 毒药是否可用 |
| 女巫 | `antidote_history` | `list[{day, target}]` | 解药使用历史 |
| 女巫 | `poison_history` | `list[{day, target}]` | 毒药使用历史 |
| 守卫 | `last_target` | `int \| None` | 上一夜守护目标 |
| 守卫 | `protect_history` | `list[{day, target, success}]` | 守护历史 |
| 预言家 | `checks` | `dict[int, str]` | 查验结果 `{target_id: team_value}` |
| 猎人 | `has_shot` | `bool` | 是否已开过枪 |
| 猎人 | `shot_target` | `int \| None` | 开枪目标 |
| 白狼王 | `has_exploded` | `bool` | 是否已自爆 |

**Phase 2：RoleRule 协议扩展（约 1 天）**

在 `engine/role_rules/base.py` 中新增两个方法：

```python
class BaseRoleRule:
    def init_role_state(self) -> dict[str, Any]:
        """返回该角色的初始 role_state。"""
        return {}

    def get_role_state(self, engine, player_id: int) -> dict[str, Any]:
        """返回该角色对外暴露的 role_state（用于 Observation 和快照）。"""
        return {}
```

每个角色规则类实现自己的版本。例如女巫：

```python
class WitchRule(BaseRoleRule):
    def init_role_state(self):
        return {"antidote_available": True, "poison_available": True,
                "antidote_history": [], "poison_history": []}

    def get_role_state(self, engine, player_id):
        ps = engine.state.players[player_id]
        return dict(ps.role_state)  # 完整暴露给本人
```

**Phase 3：迁移 GameState 顶层字段（约 2 天）**

逐步将以下字段的读写从 `engine.state.witch_xxx` 迁移到 `engine.state.players[witch_id].role_state["xxx"]`：

1. `witch_antidote_available` / `witch_poison_available` → `PlayerState.role_state`
2. `guard_last_target` → `PlayerState.role_state`
3. `seer_checks` → `PlayerState.role_state`
4. `pending_hunter_shots` → 可保留在 `GameState`（这是跨角色的队列），或为猎人增加 `pending_shot` 标记

迁移策略：在 `GameState` 上保留 property 别名做兼容桥接，所有 role_rules 文件、phases 文件统一改完后移除桥接。需要同步修改的测试文件预估 10~15 个。

**Phase 4：Observation 增加 role_state（约 0.5 天）**

```python
@dataclass(slots=True)
class Observation:
    # ...现有字段...
    role_state: dict[str, Any] = field(default_factory=dict)
```

`observation_for()` 改为调用 `rule_for(role).get_role_state(self, player_id)`。

**Phase 5：统一快照 API（约 1 天）**

在 `GameEngine` 上新增：

```python
def snapshot(self) -> dict[str, Any]:
    """返回完整的引擎状态快照，可序列化。"""
    return {
        "day": self.state.day,
        "phase": self.state.phase.value,
        "sheriff_id": self.state.sheriff_id,
        "badge_destroyed": self.state.badge_destroyed,
        "winner": self.state.winner.value if self.state.winner else None,
        "players": {
            pid: {
                "id": ps.id,
                "role": ps.role.value,
                "alive": ps.alive,
                "role_state": rule_for(ps.role).get_role_state(self, pid),
            }
            for pid, ps in self.state.players.items()
        },
        "deaths": [asdict(d) for d in self.state.deaths],
        "events_count": len(self.state.events),
    }

def snapshot_for_player(self, player_id: int) -> dict[str, Any]:
    """返回面向特定玩家的私有视图（隐藏其他玩家角色）。"""
    obs = self.observation_for(player_id)
    return asdict(obs)
```

**Phase 6：测试更新（约 1 天）**

- 更新所有引用 `engine.state.witch_xxx` / `guard_last_target` / `seer_checks` 的测试
- 新增 role_state 初始化测试
- 新增 Observation 包含 role_state 的断言
- 新增 snapshot API 的序列化测试
- 信息隔离测试：验证 role_state 只对本角色暴露

预估总工时：5~6 天。

---

## 二、Skill 版本库统一

### 2.1 现状问题

当前版本系统在上下层之间有清晰的分离（上层用 hash，下层用目录），核心概念基本统一。但存在以下不一致和痛点：

1. **空 bootstrap 基线**：所有 7 个角色当前 baseline 都是 `bb9b945a`（空 skills）。项目中不存在任何 markdown skill 文件——`agent/knowledge/skills/` 只有 `loader.py` 和 `router.py`，`data/versions/` 下每个角色的 `skills/` 目录也是空的。`docs/ideas.md` 规划了大量 skill（悍跳、倒钩、冲票、警徽流等）但从未落地为文件。loader 和 router 是纯目录驱动的，当前运行时 skill 注入量为零
2. **双 Leaderboard 系统**：顶层 `learning/leaderboard.py` 用自由标签 `version: str`，进化层 `evolution/leaderboard.py` 用 hash，两套系统的版本标识不互通
3. **双 Consolidation 路径**：`consolidate_from_mid_memories()` 和 `consolidate_for_role()` 签名和上下文不同
4. **临时目录开销**：`build_composite_skill_dir()` 每次创建临时目录拷贝全部 skill 文件，无缓存
5. **版本缺少标签和性能摘要**：无法给版本打语义标签，也无法在版本上直接看到战绩
6. **History 无剪枝**：只增不减，长期运行后会累积大量版本

### 2.2 方案概览

以"统一版本标识 + 消除重复路径 + 增加版本元数据"为主线，不做大重构，而是补齐缺失的粘合层。

### 2.3 实施步骤

**Phase 1：种子 skill 创建与基线替换（约 2~3 天）**

当前所有角色 baseline 为空 skills（`bb9b945a`），运行时没有任何 skill 被注入 prompt。需要先为每个角色创建种子 skill 文件，然后通过 `VersionStore.save_version()` 注册为正式版本，替换空 baseline。

skill 文件**只存放在 `data/versions/<role>/<hash>/skills/` 中**，不在源码目录（如 `agent/knowledge/skills/`）中维护副本。版本库是 skill 的唯一权威来源。

具体做法：
1. 参考 `docs/ideas.md` 第 6 节的 skill 规划，为每个角色编写 2~3 个核心 skill 的 markdown 文件（含 YAML front matter）
2. 写一个一次性引导脚本 `scripts/seed_skills.py`，将种子 skill 内容通过 `store.save_version(role, skills_dict, parent_hash=None, source="seed")` 写入版本库
3. 调用 `store.set_baseline(role, new_hash)` 将 baseline 指针从 `bb9b945a` 切换到新 hash
4. 保留 `bb9b945a` 在 history 列表中作为历史记录

种子 skill 优先级（按角色重要性排序）：

| 角色 | 种子 skill（优先 2~3 个） |
|------|--------------------------|
| 狼人 | `fake_seer.md`（悍跳预言家）、`deep_wolf.md`（深水倒钩） |
| 预言家 | `claim_seer.md`（起跳预言家）、`check_priority.md`（查验优先级） |
| 女巫 | `save_decision.md`（解药决策）、`poison_decision.md`（毒药决策） |
| 猎人 | `shoot_decision.md`（开枪决策） |
| 守卫 | `guard_strategy.md`（守护策略） |
| 村民 | `speech_analysis.md`（发言分析）、`wolf_pit.md`（狼坑整理） |
| 白狼王 | `explode_decision.md`（自爆决策） |

**Phase 2：Leaderboard 标识统一（约 1 天）**

在顶层 `learning/leaderboard.py` 中，将 `version: str` 改为可选绑定 hash：

```python
@dataclass
class LeaderboardEntry:
    version: str          # 人类可读标签
    version_hash: str | None = None  # 可选：关联到 skill hash
    # ...其余字段不变
```

同时在 `SelfPlayConfig` 和 `selfplay.py` 中记录当前使用的 `SkillVersionConfig`（各角色 hash），让 selfplay 结果能追溯到精确的版本组合。

**Phase 3：版本标签和摘要（约 1 天）**

在 `RoleVersion` 模型（`evolution/models.py`）上扩展可选字段：

```python
@dataclass
class RoleVersion:
    hash: str
    role: str
    skills: dict[str, str]
    created_at: str
    source: str
    parent_hash: str | None = None
    source_run_id: str | None = None
    notes: list[str] = field(default_factory=list)
    # 新增
    tags: list[str] = field(default_factory=list)           # 语义标签
    performance_summary: dict[str, Any] = field(default_factory=dict)  # 战绩摘要
```

在 promote 时自动写入 `performance_summary`（来自 battle 结果），在 backend API 中支持按 tag 过滤版本。

**Phase 4：Consolidation 路径统一（约 1 天）**

保留 `consolidate_for_role()` 作为唯一入口，将 `consolidate_from_mid_memories()` 改为它的薄包装：

```python
async def consolidate_from_mid_memories(mid_memories, role, skill_root, llm_client):
    """向后兼容的薄包装。"""
    # 将 mid_memories 写入临时 run_dir
    # 调用 consolidate_for_role(run_dir=..., role=..., ...)
```

**Phase 5：Composite Skill Dir 缓存（约 0.5 天）**

在 `config.py` 的 `build_composite_skill_dir()` 中增加基于 hash 组合键的缓存：

```python
_cache: dict[str, Path] = {}

def build_composite_skill_dir(store, config: SkillVersionConfig) -> Path:
    cache_key = "|".join(f"{r}:{h}" for r, h in sorted(config.role_versions.items()))
    if cache_key in _cache and _cache[cache_key].exists():
        return _cache[cache_key]
    # ... 原逻辑 ...
    _cache[cache_key] = result
    return result
```

加一个 `cleanup_skill_cache()` 方法供手动清理。

**Phase 6：History 剪枝（约 0.5 天）**

在 `store.py` 上增加：

```python
def prune_history(self, role: str, keep: int = 20):
    """保留最近 N 个版本 + baseline（无论多旧），其余标记为 archived。"""
```

不是物理删除，而是在 `history.json` 中加一个 `archived` 列表，逻辑上不再出现在 `list_versions()` 结果中。

预估总工时：6~7 天。

---

## 三、真实浏览器人机长局手测

### 3.1 现状问题

当前人机对战全链路已经打通（配置 → 引擎 → SSE → 前端操作面板 → 提交 → 引擎继续），17 种 ActionType 全部有前端 UI 支持。但对于"长局"场景存在 4 个 P0 级阻塞问题：

1. `HumanPlayer` 的 `asyncio.Future` 无超时，游戏可能永久挂起
2. `GameManager` 纯内存，后端重启即丢失所有进行中的游戏
3. SSE 连接无心跳保活，空闲几十秒必被代理层断开
4. 浏览器断线无显式重连机制

另外还有一些 P1 级体验问题：无暂停/恢复、无连接状态指示、无操作超时提醒。

### 3.2 方案概览

以"让长局稳定可玩"为目标，优先解决 P0 问题，然后补齐 P1 体验。

### 3.3 实施步骤

**Phase 1：HumanPlayer 超时机制（约 0.5 天）**

在 `engine/players.py` 的 `HumanPlayer.act()` 中增加超时：

```python
class HumanPlayer:
    TIMEOUT_SECONDS = 300  # 5 分钟

    async def act(self, request: ActionRequest) -> ActionResponse:
        self._current_request = request
        self._pending = asyncio.get_event_loop().create_future()
        try:
            return await asyncio.wait_for(self._pending, timeout=self.TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._timed_out = True
            return self._default_response(request)

    def _default_response(self, request: ActionRequest) -> ActionResponse:
        """超时时的安全兜底：随机合法目标或弃票/跳过。"""
        if request.candidates:
            return ActionResponse(action_type=request.action_type,
                                  target=request.candidates[0], text="(超时自动)")
        return ActionResponse(action_type=request.action_type, choice="skip", text="(超时自动)")
```

同时在前端超时前 60 秒发出声音/浏览器通知提醒。

**Phase 2：GameManager 状态持久化（约 1.5 天）**

参考 `SelfplayManager.persist_state()` 模式：

1. 在 `RunningGame` 中增加 `persist_state()` 方法，将关键状态写入 `data/games/{game_id}/run_state.json`：
   - game_id, config (含 human_player_id)
   - status (running / paused / completed / failed)
   - 事件列表 game.events
   - 创建时间、最后活跃时间
2. `GameManager.start_game()` 时创建目录并写入初始状态
3. 每次新事件发布后增量追加事件到 `events.jsonl`
4. `GameManager` 启动时调用 `restore_runs()`，扫描 `data/games/` 目录恢复未完成的游戏
5. 游戏完成/失败时写入最终状态

注意：引擎的完整 GameState 序列化比较复杂（涉及 Phase 枚举、PlayerState 等），建议只持久化"元数据 + 事件日志"，不持久化引擎内存状态。如果后端在游戏进行中崩溃，恢复策略是"标记该游戏为 interrupted"，而非继续执行。

**Phase 3：SSE 心跳保活（约 0.5 天）**

后端：在 `GameManager._run_game()` 的轮询循环中，每 15 秒发送一次心跳：

```python
if time.time() - last_ping > 15:
    for q in game.subscribers:
        q.put_nowait({"kind": "ping"})
    last_ping = time.time()
```

前端：在 `connectEvents()` 中增加心跳超时检测：

```typescript
let lastMessageTime = Date.now();
const heartbeatCheck = setInterval(() => {
    if (Date.now() - lastMessageTime > 45000) {
        // 超过 45 秒没收到任何消息，主动重连
        source.close();
        reconnect();
    }
}, 5000);

source.onmessage = () => { lastMessageTime = Date.now(); };
```

Vite 代理配置补上超时：

```typescript
// vite.config.ts
proxy: {
    "/api": {
        target: "http://127.0.0.1:8000",
        timeout: 0,  // 不超时
        proxyTimeout: 0,
    }
}
```

**Phase 4：断线重连与连接状态（约 1 天）**

前端增加连接状态管理：

```typescript
type ConnectionStatus = "connected" | "disconnected" | "reconnecting";
const [connStatus, setConnStatus] = useState<ConnectionStatus>("connected");
```

重连逻辑：
1. SSE error 事件触发时设为 `reconnecting`
2. 关闭旧 EventSource，延迟 2 秒后重新创建
3. 重连成功后 `subscribe()` 会自动重放历史事件
4. 连续 3 次重连失败后设为 `disconnected`，显示手动重连按钮
5. 在页面顶部显示连接状态指示器（绿点/黄点/红点）

**Phase 5：暂停/恢复机制（约 1 天）**

后端：
1. 新增 `POST /api/games/{id}/pause` 和 `POST /api/games/{id}/resume`
2. 暂停时设置 `game.is_paused = True`
3. `HumanPlayer` 检查暂停状态，暂停期间不设置超时倒计时
4. 引擎循环在暂停点等待 `asyncio.Event`

前端：
1. 在游戏界面增加"暂停"按钮
2. 暂停时显示"游戏已暂停"覆盖层
3. 暂停时超时计时器停止

**Phase 6：浏览器通知与操作提醒（约 0.5 天）**

```typescript
// 轮到人类操作时
if (document.hidden && Notification.permission === "granted") {
    new Notification("狼人杀", { body: "轮到你行动了！" });
}
```

在 `HumanActionPanel` 显示操作剩余时间倒计时，最后 30 秒高亮警告。

**Phase 7：消除 500ms 冗余轮询（约 0.5 天）**

`HumanActionPanel` 当前同时使用 SSE `decision_needed` 事件和 500ms REST 轮询，二者冗余。改为：
1. 仅依赖 SSE `decision_needed` 触发
2. SSE 断线时 fallback 到 2 秒轮询（而非 500ms）
3. SSE 恢复后切回事件驱动

预估总工时：5~6 天。

---

## 四、总体优先级与排期建议

| 优先级 | 方向 | Phase | 预估 | 理由 |
|--------|------|-------|------|------|
| P0 | 人机长局 | Phase 1：HumanPlayer 超时 | 0.5 天 | 无超时直接导致游戏卡死 |
| P0 | 人机长局 | Phase 3：SSE 心跳保活 | 0.5 天 | 无保活 SSE 必断 |
| P0 | 人机长局 | Phase 4：断线重连 | 1 天 | 长局断线概率高 |
| P0 | 人机长局 | Phase 2：GameManager 持久化 | 1.5 天 | 后端重启丢局不可接受 |
| P1 | role_state | Phase 1~2：PlayerState + RoleRule | 2 天 | 后续所有可见性改造的基础 |
| P1 | role_state | Phase 3：迁移 GameState 字段 | 2 天 | 消除状态膨胀 |
| P1 | 人机长局 | Phase 5：暂停/恢复 | 1 天 | 长局体验核心 |
| P1 | 人机长局 | Phase 6~7：通知 + 去轮询 | 1 天 | 体验打磨 |
| P2 | role_state | Phase 4~5：Observation + 快照 API | 1.5 天 | 面向 UI 和调试 |
| P2 | 版本库 | Phase 1：种子 skill + baseline 替换 | 2.5 天 | 消除空 baseline 痛点 |
| P2 | 版本库 | Phase 2~3：Leaderboard + 标签 | 2 天 | 版本可追溯性 |
| P3 | role_state | Phase 6：测试更新 | 1 天 | 与 Phase 1~3 同步进行 |
| P3 | 版本库 | Phase 4~6：路径统一 + 缓存 + 剪枝 | 2 天 | 长期维护优化 |

**建议执行顺序**：先做人机长局 P0（约 3.5 天），再做 role_state P1（约 4 天），穿插版本库 P2（约 4.5 天），最后做各自的收尾（约 4 天）。总计约 16 个工作日。

---

## 五、风险与注意事项

**role_state 迁移的测试风险**：`engine.state.witch_xxx` 等字段在 role_rules、phases、rules、tests 中被大量引用。迁移时建议先加 property 桥接保持兼容，然后逐文件替换，每改一个文件跑一次测试。

**版本库 baseline 替换**：将种子 skill 注入版本库后，已有的 selfplay 和 battle 结果仍指向旧的空 baseline hash。需要在 Leaderboard 中标注"pre-skill-baseline"和"skill-baseline"区分。种子 skill 引导脚本是一次性的，创建完成后不需要在源码目录中维护 skill 文件副本——`data/versions/` 是唯一权威来源。

**GameManager 持久化的局限性**：引擎完整的 GameState 不容易序列化（dataclass + 枚举 + 引用关系）。建议只持久化元数据和事件日志，崩溃后标记为 "interrupted" 而非尝试恢复执行。这对"手测"场景已经足够——测试人员可以重新开始一局，但不会丢失日志。

**SSE vs WebSocket**：当前架构用 SSE 是合理的（单向推送 + 简单），不需要换成 WebSocket。心跳保活 + 断线重连足以覆盖长局需求。

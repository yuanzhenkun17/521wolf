# 521wolf Engine 系统架构文档

## 概览

Engine 是狼人杀游戏的规则层。它管理游戏状态、执行阶段流程、解析角色行动、判定胜负。
Engine 不知道 Agent 的存在——它只通过 PlayerAgent 协议与玩家交互。

## 目录结构

```
engine/
  models.py         所有数据模型（枚举、状态、请求/响应）
  config.py         游戏配置（角色数量、夜间行动顺序）
  engine.py         主编排器 GameEngine
  players.py        PlayerAgent 协议 + ScriptedAgent 测试实现
  actions.py        玩家行动请求/验证/重试/兜底
  roles.py          角色分配
  logging.py        上帝视角日志（GameLogger）
  public_log.py     公共事件日志
  phases/
    night.py        夜间阶段
    day.py          白天发言阶段
    exile.py        放逐投票阶段
    sheriff.py      警长选举阶段
  role_rules/
    base.py         RoleRule 协议
    registry.py     角色 -> 规则映射
    werewolf.py     狼人
    white_wolf_king.py  白狼王
    seer.py         预言家
    witch.py        女巫
    hunter.py       猎人
    guard.py        守卫
    villager.py     村民
  rules/
    death.py        死亡/复活/猎人枪/遗言
    voting.py       投票计票（含警长 1.5 票）
    sheriff.py      警徽流转/销毁
    victory.py      胜负判定
```

---

## 核心数据模型（models.py）

### 枚举
- Team: werewolves / villagers / gods
- Role: werewolf / white_wolf_king / villager / seer / witch / hunter / guard（每个有 team 属性）
- Phase: setup / sheriff_election / night / day_speech / exile_vote / finished
- ActionType: 17 种行动类型
- DeathCause: werewolf / witch_poison / exile / hunter_shot / white_wolf / self_explode

### 状态
- PlayerState: id, role, alive
- GameState: players, day, phase, events, public_log, deaths, sheriff_id, witch 药水状态, guard 上轮守护, seer 查验记录, pending 动作, winner

### 协议
- Observation: 玩家可见信息（自己身份、存活/死亡列表、已知角色、查验结果）
- ActionRequest: 引擎发给 Agent 的请求（玩家ID、动作类型、阶段、观察、候选列表）
- ActionResponse: Agent 返回的响应（目标、选择、文本）

---

## GameEngine（engine.py）

主编排器。持有 GameState、GameLogger、玩家 agents。

### 初始化
- 接收 roles（角色分配）、agents（玩家 Agent）、config（游戏配置）
- 验证玩家数量、角色数量、Agent 覆盖

### 查询方法
- alive_ids / dead_ids: 存活/死亡玩家
- role_ids / team_ids: 按角色/阵营查玩家
- observation_for(player_id): 构建该玩家的 Observation（按角色可见性过滤信息）

### 委托方法
- _ask() -> actions.ask（发送 ActionRequest，验证响应，重试/兜底）
- kill_player / revive_player -> rules.death
- run_night -> phases.night
- run_day_speeches -> phases.day
- run_exile_vote -> phases.exile
- run_sheriff_election -> phases.sheriff
- check_winner -> rules.victory

### 主循环 run_until_finished(max_days)

```
while True:
    run_night()          # 夜间行动 + 死亡揭示
    check_winner()       # 判胜负
    run_sheriff_election()  # 第一天选警长
    run_day_speeches()   # 白天发言
    run_exile_vote()     # 放逐投票
    check_winner()       # 判胜负
```

---

## Phases 层

### night.py — 夜间阶段
- resolve_night_actions(): 按 night_order 依次执行角色行动
  - 守卫守护 -> 狼人刀人 -> 预言家查验 -> 女巫用药
- NightResult: protected, killed, saved, poisoned, deaths
- reveal_night_deaths(): 应用死亡，触发猎人枪/遗言
- 计算最终死亡：刀人 - 守护 - 解药 + 毒药

### day.py — 白天发言阶段
- determine_speech_order(): 警长决定正序/逆序
- run_day_speeches(): 按顺序让每个存活玩家发言
- 支持角色特殊白天中断（白狼王自爆）

### exile.py — 放逐投票阶段
- run_exile_vote(): 收集投票，计票
- 平票时进入 PK 子阶段：平票者发言，非平票者再投
- PK 仍平票则无人出局
- collect_votes(): 通用投票收集（主投票/PK 投票复用）

### sheriff.py — 警长选举阶段
- run_sheriff_election(): 竞选演讲 -> 退选 -> 投票
- 设置 engine.state.sheriff_id

---

## Role Rules 层

### 协议（base.py）
每个角色实现 RoleRule 协议：
- visible_roles(engine, player_id): 该角色能看到谁的身份
- seer_checks(engine, player_id): 预言家查验结果
- night_action(engine, player_id, ...): 夜间行动
- day_interrupt(engine, player_id): 白天特殊中断

### 注册表（registry.py）
ROLE_RULES: dict[Role, RoleRule]，rule_for(role) 查找。

### 各角色规则

| 角色 | 夜间行动 | 特殊能力 |
|------|----------|----------|
| 狼人 | 全体狼投票选刀人目标（多数决） | 能看到所有狼队友 |
| 白狼王 | 继承狼人刀人 | 白天可自爆带走一人 |
| 预言家 | 选一人查验阵营 | 查验结果跨夜累积 |
| 女巫 | 收到刀人目标，可救/毒/跳过 | 解药毒药各一次 |
| 猎人 | 无夜间行动 | 死亡时可开枪带走一人 |
| 守卫 | 选一人守护 | 不能连续守同一人 |
| 村民 | 无行动 | 无 |

---

## Rules 层

### death.py — 死亡规则
- kill_player(): 标记死亡，记录死因
- revive_player(): 复活
- resolve_hunter_death(): 猎人死后开枪
- can_hunter_shoot(): 判断猎人是否能开枪
- last_words(): 遗言处理
- resolve_exile_votes(): 放逐计票后处理

### voting.py — 投票规则
- resolve_votes(): 计票，警长票权 1.5x，返回胜者或平票列表
- plurality(): 从列表中取最高频

### sheriff.py — 警长规则
- resolve_sheriff_death(): 警长死亡时流转或销毁警徽

### victory.py — 胜负判定
- determine_winner():
  - 狼人全死 -> 好人赢
  - 狼人数 >= 好人数 -> 狼人赢
  - 任何好人阵营全灭 -> 狼人赢

---

## actions.py — 行动处理

- ask(): 发 ActionRequest 给 PlayerAgent，验证 ActionResponse
  - 验证失败重试一次
  - 两次都失败则用默认值兜底
- append_public_action(): 将发言记录到公共日志

---

## 数据流

```
GameEngine.run_until_finished()
  |
  +-- night
  |     +-- 守卫守护 (guard.night_action)
  |     +-- 狼人刀人 (werewolf.night_action)
  |     +-- 预言家查验 (seer.night_action)
  |     +-- 女巫用药 (witch.night_action)
  |     +-- resolve_night_actions -> NightResult
  |     +-- reveal_night_deaths -> kill_player / resolve_hunter_death
  |
  +-- check_winner -> rules.victory
  |
  +-- sheriff_election (第一天)
  |     +-- 竞选 -> 演讲 -> 退选 -> 投票
  |
  +-- day_speeches
  |     +-- determine_speech_order (警长决定)
  |     +-- 每人发言 (actions.ask -> SPEAK)
  |     +-- 白狼王可自爆 (day_interrupt)
  |
  +-- exile_vote
  |     +-- 收集投票 -> 计票
  |     +-- 平票 -> PK发言 -> PK投票
  |     +-- 出局 -> 遗言 -> 猎人枪
  |
  +-- check_winner -> rules.victory
  |
  (循环)
```

---

## 与 Agent 的接口

Engine 通过 PlayerAgent 协议与 Agent 交互：

```
class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse: ...
```

Engine 构建 Observation（按角色可见性过滤），包装成 ActionRequest 发给 Agent。
Agent 返回 ActionResponse（target/choice/text），Engine 验证后执行。

信息隔离：observation_for() 按角色过滤，狼人看不到预言家查验，好人看不到狼队友。

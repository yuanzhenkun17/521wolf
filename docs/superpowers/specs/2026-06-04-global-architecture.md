# Spec #0: 全局架构设计

> 基于头脑风暴确认的设计决策：
> - 核心定位：比赛优先
> - 构建方式：改造现有代码，最大化复用
> - 杀手锏：自进化效果可视化
> - 演示方式：纯数据展示（给技术评委）
> - 开发顺序：引擎 → Agent → 评测 → 进化
> - 存储：SQLite 为主，JSON 仅用于导出

---

## 1. 系统定位

支持 **AI 对战** 和 **人机混战** 的 AI 狼人杀系统，具备 **自进化** 能力。

**评审目标**：满分 70 分，重点拿满以下维度：
- 单 Agent 能力 (20%) — 最容易拿满分
- 自进化 Agent (30%) — 杀手锏，用数据说话
- 评测+复盘 (30%) — 为进化提供评估基础

---

## 2. 四层架构

```
┌──────────────────────────────────────────────────────┐
│                    UI Layer                          │
│  对局观战 │ 人机操作 │ 进化数据 │ Leaderboard │ 回放  │
│  React + TypeScript + WebSocket/SSE + HTTP REST      │
├──────────────────────────────────────────────────────┤
│                   Agent Layer                        │
│  决策管线 │ 记忆系统 │ Skill 系统 │ Prompt 构建      │
│  自进化: Pipeline │ Battle │ Consolidation           │
│  评测: Evidence Pipeline │ Review │ Leaderboard      │
├──────────────────────────────────────────────────────┤
│                   Engine Layer                       │
│  规则引擎 │ 阶段流转 │ 信息隔离 │ 胜负判定          │
│  GameSession (AI-only + 混合模式)                    │
├──────────────────────────────────────────────────────┤
│                  Storage Layer                       │
│  SQLite (主存储) │ JSON (归档导出)                   │
└──────────────────────────────────────────────────────┘
```

### 2.1 Engine Layer

**职责**：狼人杀规则的完整实现，不感知 Agent 内部逻辑。

**核心组件**：
- `GameEngine` — 对局主循环（夜间→白天→投票→判定）
- `GameSession` — 会话管理（支持 AI-only 和人机混战）
- `RoleRule` — 角色规则（无状态 singleton）
- `GameState` — 对局状态（通用状态 + role_state 字典）
- `GameEvent` + `Visibility` — 结构化事件 + 可见性控制
- `PlayerAgent` 协议 — `act(request) -> response`

**与 Agent Layer 的接口**：
```python
response = await engine.agents[player_id].act(request)
# request 包含: observation (视角过滤后), action_type, candidates
# response 包含: target, choice, text
```

**与 Storage Layer 的接口**：
```python
# 游戏结束时写入 SQLite
game_store.insert_game(game_id, ...)
game_store.insert_players(game_id, ...)
# 事件实时写入
game_logger.record(conn=sqlite_conn, game_id=...)
```

### 2.2 Agent Layer

**职责**：Agent 的决策、记忆、技能、进化、评测。

**核心组件**：

```
Agent Layer
├── 决策系统
│   ├── AgentRuntime (act() 管线)
│   ├── AgentMemory (6 字段记忆)
│   ├── Skill Router (front matter 驱动)
│   └── Prompt Builder (2 消息结构)
│
├── 自进化系统
│   ├── Evolution Pipeline (5 阶段状态机)
│   │   ├── Training (selfplay → 中期记忆)
│   │   ├── Consolidation (LLM → SkillProposal)
│   │   ├── Apply (Proposal → 新 skill)
│   │   ├── Battle (baseline vs candidate)
│   │   └── Review (promote / reject)
│   ├── VersionStore (版本管理)
│   └── Battle Runner (A/B 对战)
│
└── 评测系统
    ├── Evidence Pipeline (每局自动评测)
    │   ├── Normalize (四面相拆分)
    │   ├── Select (关键决策选择)
    │   ├── Judge (LLM 批量评判)
    │   └── Report (Markdown 报告)
    ├── ExperienceCandidate (中期记忆)
    ├── Role Rubrics (角色评分标准)
    └── Leaderboard (多维度排行榜)
```

**与 Engine Layer 的接口**：
```python
class AgentRuntime:
    async def act(self, request: ActionRequest) -> ActionResponse
```

**与 Storage Layer 的接口**：
```python
# 版本管理
version_store.save_version(role, skills, hash)
version_store.load_version(role, hash)

# 评测数据
decision_store.insert_record(game_id, record)

# 排行榜
leaderboard.aggregate(game_results)
```

### 2.3 UI Layer

**职责**：用户交互、数据展示、对局可视化。

**核心页面**：

| 页面 | 功能 | 通信方式 |
|------|------|----------|
| 对局观战 | 实时展示游戏状态、事件流、玩家视角 | WebSocket |
| 人机操作 | 人类玩家的决策界面 | WebSocket (submit_decision) |
| 进化数据 | 进化曲线、版本对比、胜率趋势 | HTTP REST |
| Leaderboard | 多维度排行榜、版本排名 | HTTP REST |
| 对局回放 | 历史对局的完整回放 + 决策追溯 | HTTP REST |
| 评测报告 | 单局评测报告、bad case 分析 | HTTP REST |

**通信协议**：
```
引擎 → UI (WebSocket/SSE):
  game_start, phase_change, game_event, decision_needed, game_end

UI → 引擎 (WebSocket):
  submit_decision

UI ← 后端 (HTTP REST):
  /api/games, /api/leaderboard, /api/evolution, /api/reports
```

### 2.4 Storage Layer

**职责**：数据持久化，SQLite 为主。

**SQLite 表结构**：

| 表 | 用途 | 写入时机 |
|----|------|----------|
| games | 对局元数据 | 游戏结束时 |
| players | 玩家角色分配 | 游戏结束时 |
| game_events | 引擎事件流 | 实时写入 |
| decisions | Agent 决策记录 | 实时写入 |
| role_versions | Skill 版本快照 | 进化时 |
| skill_proposals | Skill 修改提案 | 进化时 |
| evolution_runs | 进化运行状态 | 进化时 |
| leaderboard | 排行榜数据 | 评测后聚合 |
| experience_candidates | 经验候选（中期记忆） | 评测后 |

**JSON 导出**：保留 `archive.json` 导出功能，用于分享和调试。但主查询走 SQLite。

---

## 3. 核心数据流

### 3.1 AI 对局

```
GameConfig + SkillVersionConfig
  → GameEngine.run_until_finished()
    → 每回合: ask() → agent.act() → 规则判定
    → 实时: GameLogger → SQLite game_events
    → 实时: DecisionRecorder → SQLite decisions
  → 游戏结束: 写入 games + players
  → 自动触发: Evidence Pipeline → experience_candidates
```

### 3.2 人机混战

```
GameSession(mode="mixed")
  → AI 玩家: GameEngine 直接调用
  → Human 玩家:
      → 引擎暂停
      → WebSocket → UI: decision_needed
      → 人类操作
      → UI → WebSocket: submit_decision
      → 引擎继续
  → 所有事件: WebSocket → UI 实时推送
```

### 3.3 自进化

```
EvolutionPipeline(role="seer")
  → Training: SelfplayRunner → N 局 → Evidence Pipeline
  → 中期记忆: experience_candidates[]
  → Consolidation: LLM + skill + rejected → SkillProposal[]
  → Apply: Proposal → 新 skill 文件 → 新 RoleVersion
  → Battle: baseline vs candidate, 同种子 N 局
  → Review: 胜率提升 → Promote / 未提升 → Reject
  → 结果: SQLite evolution_runs + leaderboard
```

---

## 4. 开发顺序

```
Phase 1: 引擎层 (Spec #1)
  ├── 现有引擎改造: visibility enum, visible_events, ask() 异常处理
  ├── GameSession: 支持 AI-only + 混合模式
  └── 目标: 能完整跑完一局，信息隔离正确

Phase 2: Agent 层 (Spec #4)
  ├── 决策管线: 现有 6 步 → 确认是否精简
  ├── 记忆系统: LLM 摘要替换规则压缩
  ├── Skill 系统: 现有 front matter 驱动（不改）
  └── 目标: Agent 能做出合理决策

Phase 3: 评测 (Spec #2)
  ├── Evidence Pipeline: 替换现有 review + game_analysis
  ├── ExperienceCandidate: 中期记忆
  ├── Leaderboard: 多维度排行榜
  └── 目标: 每局自动评测，产出结构化报告

Phase 4: 进化 (Spec #3)
  ├── Evolution Pipeline: 现有管线验证
  ├── Battle: A/B 对战
  ├── VersionStore: 版本管理
  └── 目标: 能跑完一轮进化，展示胜率提升

Phase 5: 存储 + UI (Spec #5)
  ├── SQLite: 替换 JSON 为主存储
  ├── WebSocket: 引擎 → UI 实时推送
  ├── 前端: 对局观战 + 人机操作 + 数据面板
  └── 目标: 完整可用的系统
```

---

## 5. 子 Spec 索引

| # | Spec | 覆盖模块 | 状态 |
|---|------|----------|------|
| 0 | **全局架构** | 全系统 | ✅ 本文档 |
| 1 | **游戏引擎（规则系统）** | Engine + Rules + Visibility + GameSession | ✅ 已完成 |
| 2 | **评测与复盘** | Evidence Pipeline + Review + Leaderboard | ✅ 已完成 |
| 3 | **自进化系统** | Evolution Pipeline + Battle + Consolidation | 待写 |
| 4 | **Agent 决策系统** | Runtime + Memory + Skills + Prompts | 待写 |
| 5 | **存储 + UI** | SQLite + WebSocket + Frontend | 待写 |

---

## 6. 评审维度 × 模块矩阵

| 评审维度 | 权重 | 核心模块 | 关键交付物 |
|----------|------|----------|-----------|
| 单 Agent 能力 | 20% | Agent 决策 (Spec #4) | Prompt 调优痕迹、角色策略差异、决策可追溯 |
| 多 Agent 协作 | 20% | Engine + Agent (Spec #1+#4) | 信息隔离测试、博弈行为展示 |
| 工程完整度 | 30% | Engine + Storage + UI (Spec #1+#5) | 引擎正确性、信息隔离无泄露、前端体验、文档 |
| 评测+复盘 | 30% | Evidence Pipeline (Spec #2) | 认识论分离、样本分类、bad case 定位 |
| 自进化 Agent | 30% | Evolution (Spec #3) | 初始 vs 进化后胜率对比、版本回溯、进化曲线 |

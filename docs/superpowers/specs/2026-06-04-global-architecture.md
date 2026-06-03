# Spec #0: 全局架构设计

> 目标：定义整个狼人杀 AI 系统的模块划分、数据流、接口边界
> 这是所有子 spec 的父文档，子 spec 只描述各自模块的内部设计

---

## 1. 系统定位

一个支持 **AI 对战** 和 **人机混战** 的 AI 狼人杀系统，具备**自进化**能力。

核心能力：
- 12 人标准狼人杀完整规则引擎
- 7 个角色各有独立 LLM Agent（skill + memory + prompt）
- 自进化闭环：对局 → 评测 → skill 调整 → 对战验证 → 版本晋升
- 人类玩家可通过 Web UI 参与对局
- 全链路可观测：决策追溯、评测报告、进化日志

---

## 2. 模块划分

```
┌──────────────────────────────────────────────────────────────┐
│                        UI Layer                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ 对局观战  │  │ 人机混战操作  │  │ 进化/评测数据面板  │     │
│  └────┬─────┘  └──────┬───────┘  └──────────┬─────────┘     │
│       │               │                      │                │
│  ─────┴───────────────┴──────────────────────┴─────────────  │
│                    WebSocket / SSE / HTTP                     │
├──────────────────────────────────────────────────────────────┤
│                      Backend Layer                           │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │GameSession│  │ SelfplayRunner│  │ EvolutionRunner   │     │
│  │(单局管理) │  │ (批量对弈)    │  │ (进化管线)        │     │
│  └────┬─────┘  └──────┬───────┘  └──────────┬─────────┘     │
├───────┴────────────────┴─────────────────────┴───────────────┤
│                     Core Layer                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                   GameEngine                         │    │
│  │  规则引擎 + 阶段流转 + 信息隔离 + 胜负判定          │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                    │
│  ┌──────────────────────┴───────────────────────────────┐    │
│  │                 AgentRuntime                         │    │
│  │  决策管线: select_skills → build_prompt →            │    │
│  │           call_and_parse → enforce_policy            │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                    │
│  ┌──────────┐  ┌────────┴───────┐  ┌──────────────────┐     │
│  │ Memory   │  │ Skill Router   │  │ Prompt Builder   │     │
│  └──────────┘  └────────────────┘  └──────────────────┘     │
├──────────────────────────────────────────────────────────────┤
│                   Learning Layer                             │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ Evidence │  │ Consolidation│  │ Battle             │     │
│  │ Pipeline │  │ (skill 修改) │  │ (A/B 验证)         │     │
│  └────┬─────┘  └──────┬───────┘  └──────────┬─────────┘     │
│       │               │                      │                │
│  ┌────┴─────┐  ┌──────┴───────┐  ┌──────────┴─────────┐     │
│  │ Review   │  │ Leaderboard  │  │ VersionStore       │     │
│  │ (评测)   │  │ (排行榜)     │  │ (版本管理)         │     │
│  └──────────┘  └──────────────┘  └────────────────────┘     │
├──────────────────────────────────────────────────────────────┤
│                   Storage Layer                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  SQLite (游戏数据、决策、版本、排行榜)               │    │
│  │  JSON Files (对局归档、进化日志)                     │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 核心数据流

### 3.1 AI 对局流

```
配置 (GameConfig + SkillVersionConfig)
  ↓
GameEngine.run_until_finished()
  ├── 夜间: ask(agent) → agent.act() → 规则判定
  ├── 白天: ask(agent) → agent.act() → 发言记录
  ├── 投票: ask(agent) → agent.act() → 放逐判定
  └── 每回合: GameLogger → game_events.jsonl
  ↓
GameArchive (archive.json)
  ↓
Evidence Pipeline (评测)
  ↓
ExperienceCandidate[] (中期记忆)
```

### 3.2 人机混战流

```
GameSession.start()
  ├── AI 玩家: GameEngine 直接调用 agent.act()
  ├── Human 玩家:
  │     ├── 引擎暂停
  │     ├── WebSocket → UI: decision_needed
  │     ├── UI → WebSocket → 引擎: submit_decision
  │     └── 引擎继续
  └── 所有事件: WebSocket → UI 实时推送
```

### 3.3 自进化流

```
EvolutionPipeline (单角色)
  │
  ├── Stage 1: Training
  │     SelfplayRunner → N 局对弈 → 每局 Evidence Pipeline
  │     → ExperienceCandidate[] (中期记忆)
  │
  ├── Stage 2: Consolidation
  │     LLM 读取中期记忆 + 当前 skill + rejected proposals
  │     → SkillProposal[] (skill 修改提案)
  │
  ├── Stage 3: Apply
  │     Proposal → 新 skill 文件 → 新 RoleVersion
  │
  ├── Stage 4: Battle
  │     Baseline vs Candidate, 同种子 N 局
  │     → 胜率对比 + 显著性检验
  │
  └── Stage 5: Review
        胜率提升 → Promote (新 baseline)
        未提升 → Reject (记录失败方向)
```

---

## 4. 模块间接口

### 4.1 Engine ↔ Agent

```python
# 引擎调用 Agent 的唯一入口
response: ActionResponse = await engine.agents[player_id].act(request: ActionRequest)

# ActionRequest 包含:
#   observation: Observation (视角过滤后的信息)
#   action_type: ActionType (当前需要的行动类型)
#   candidates: tuple[int, ...] (合法目标列表)

# ActionResponse 包含:
#   target: int | None
#   choice: str | None
#   text: str (发言内容)
```

### 4.2 Engine → UI (事件流)

```python
# 引擎推送事件到 UI
events = [
    "game_start",      # 对局开始
    "phase_change",    # 阶段切换
    "game_event",      # 游戏事件（含 visibility）
    "decision_needed", # 等待人类决策
    "decision_made",   # 决策已做出
    "night_result",    # 夜间结果
    "game_end",        # 对局结束
]
```

### 4.3 UI → Engine (人类决策)

```python
# 人类玩家提交决策
await session.submit_human_decision(player_id, ActionResponse(
    action_type=...,
    target=...,
    text="...",
))
```

### 4.4 Evidence Pipeline → Consolidation

```python
# 评测产出的经验候选（中期记忆）
experience_candidates: list[ExperienceCandidate]

# Consolidation 读取
consolidation_input = {
    "experiences": experience_candidates,  # 本批对局的中期记忆
    "current_skills": ...,                 # 当前 skill 文件
    "rejected_proposals": ...,             # 历史被拒绝的提案
}
```

### 4.5 Battle → Leaderboard

```python
# 对战结果
battle_result = {
    "baseline_win_rate": 0.50,
    "candidate_win_rate": 0.65,
    "significant": True,  # Wilson CI 显著性检验
}

# Leaderboard 聚合
leaderboard_entry = LeaderboardEntry(
    version="v5",
    games=20,
    win_rate=0.65,
    role_weighted_score=7.8,
    recommendation="promote",
)
```

---

## 5. 子 Spec 索引

| # | Spec | 覆盖模块 | 状态 |
|---|------|----------|------|
| 0 | **全局架构** | 全系统 | ✅ 本文档 |
| 1 | **游戏引擎（规则系统）** | Engine + Rules + Visibility | ✅ 已完成 |
| 2 | **评测与复盘** | Evidence Pipeline + Review + Leaderboard | ✅ 已完成 |
| 3 | **自进化系统** | Evolution Pipeline + Battle + Consolidation | 待写 |
| 4 | **Agent 决策系统** | Runtime + Memory + Skills + Prompts | 待写 |
| 5 | **存储 + UI** | SQLite + WebSocket + Frontend | 待写 |

---

## 6. 技术栈

| 层 | 技术 |
|----|------|
| 引擎 | Python asyncio |
| Agent LLM | 方舟 doubao-seed 2.0 pro / code |
| 存储 | SQLite (主存储) + JSON (归档) |
| 前端 | React + TypeScript |
| 通信 | WebSocket (实时) + HTTP REST (查询) |
| 测试 | unittest + pytest |

---

## 7. 评审维度对照

| 评审维度 | 对应模块 | 关键设计点 |
|----------|----------|-----------|
| 单 Agent 能力 (20%) | Agent 决策系统 (Spec #4) | Skill 系统、Prompt 质量、记忆管理 |
| 多 Agent 协作 (20%) | Agent + Engine (Spec #1+#4) | 信息隔离、博弈行为、技能调度 |
| 工程完整度 (30%) | Engine + Storage + UI (Spec #1+#5) | 引擎正确性、信息隔离测试、前端体验 |
| 评测+复盘 (30%) | Evidence Pipeline (Spec #2) | 认识论分离、样本分类、经验候选 |
| 自进化 Agent (30%) | Evolution (Spec #3) | 闭环验证、A/B 对战、版本回溯 |

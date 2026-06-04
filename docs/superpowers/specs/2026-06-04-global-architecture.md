# Spec #0: 全局架构设计

> 本文是基于 2026-06-04 当前代码现状校准后的全局架构 spec。
> 目的不是重新发明系统，而是把“已经可用的主路径”“目标架构”和“仍需补齐的 gap”分清楚，作为后续子 spec 和排期的总索引。

---

## 0. 设计决策

已确认的总体方向：

- 核心定位：比赛优先。
- 构建方式：改造现有代码，最大化复用。
- 杀手锏：自进化效果可视化。
- 演示方式：纯数据展示，面向技术评委。
- 开发顺序：先稳住引擎和 Agent 主路径，再补评测、进化、存储和 UI。
- 存储目标：SQLite 作为主查询存储，JSON/JSONL 保留为归档导出和调试文件。

状态标记：

| 标记 | 含义 |
|------|------|
| 已实现 | 当前代码已有可运行主路径 |
| 部分实现 | 有代码基础，但接口未打通或不是主路径 |
| 待补齐 | 设计需要，但当前没有完整实现 |
| 目标态 | 后续期望形态，不代表当前已完成 |

---

## 1. 系统定位

系统定位为支持 AI 对战、人机混战和角色 skill 自进化的 AI 狼人杀平台。

当前最稳定的主路径是：

```text
AI-only 对局
  -> AgentRuntime 决策
  -> GameEngine 结算
  -> JSONL + archive + SQLite 记录
  -> 复盘/统计/进化数据展示
```

评审重点：

| 维度 | 目标 |
|------|------|
| 单 Agent 能力 | 角色 persona、Prompt、记忆、skill、合法动作输出、决策追溯 |
| 多 Agent 协作 | 信息隔离、公开日志互动、发言/投票形成博弈 |
| 评测 + 复盘 | 每局可解释评分、bad case、关键决策、排行榜 |
| 自进化 Agent | skill 版本、训练局、版本对战、promote/reject、效果曲线 |
| 工程完整度 | 可运行 UI、可追溯存储、测试覆盖、稳定接口 |

---

## 2. 四层架构

当前架构按四层理解：

```text
┌────────────────────────────────────────────────────────────┐
│ UI Layer                                                   │
│ React + TypeScript + HTTP REST + SSE                       │
│ 对局观战 / 复盘 / 自博弈 / 角色进化 / Leaderboard          │
├────────────────────────────────────────────────────────────┤
│ Agent Layer                                                │
│ AgentRuntime / Memory / Skill / Prompt / Review / Evolution│
├────────────────────────────────────────────────────────────┤
│ Engine Layer                                               │
│ GameEngine / RoleRule / GameState / Observation / Logger   │
├────────────────────────────────────────────────────────────┤
│ Storage Layer                                              │
│ SQLite schema + Store + JSON/JSONL archive                 │
└────────────────────────────────────────────────────────────┘
```

关键边界：

- Engine 只负责规则、阶段、信息隔离、胜负和日志，不理解 Prompt、LLM、skill 和复盘。
- Agent 只通过 `ActionRequest -> ActionResponse` 参与游戏，不直接读写 `GameState`。
- UI 通过 HTTP 获取快照和归档，通过 SSE 接收实时事件。
- Storage 当前是混合形态：SQLite 已有 schema、运行期写入、历史 artifact 重建工具和 UI 回放查询；selfplay/role-evolution 新 run 会写入 `data/wolf.db`，并使用 artifact-relative namespace 避免 `game_001` 冲突；JSON/JSONL 仍承担 archive 和部分 fallback。

---

## 3. Engine Layer

### 3.1 当前已实现

核心组件：

| 组件 | 当前状态 |
|------|----------|
| `GameEngine` | 已实现完整主循环：夜晚、警长、白天、放逐、胜负判定 |
| `RoleRule` | 已实现无状态 singleton 角色规则 |
| `GameState` | 已实现，但当前混合了通用状态和角色私有状态 |
| `Observation` | 已实现按玩家构造可见信息 |
| `PlayerAgent` | 已实现协议：`act(request) -> ActionResponse` |
| `GameLogger` | 已实现 JSONL；SQLite 写入通过 `storage.runtime` sink 注入，不在 Engine 内直连 |
| `ask()` 异常兜底 | 已捕获 agent 异常，记录 `agent_error` 后重试，两次失败走 `default_action` |

当前信息隔离方式：

```text
GameEngine.observation_for(player_id)
  -> public_log: tuple[str, ...]
  -> known_roles: dict[int, Role]
  -> seer_checks: dict[int, Team]
  -> metadata: dict
```

角色私有信息目前通过 `known_roles`、`seer_checks` 和 action `metadata` 暴露给对应玩家。

### 3.2 当前缺口

| 缺口 | 说明 | 优先级 |
|------|------|--------|
| `role_state` | `GameState` 仍有 `witch_antidote_available`、`guard_last_target`、`seer_checks` 等角色状态 | P2 |
| 结构化可见事件 | 当前 `Observation` 仍使用 `public_log` 字符串列表；`GameEvent.public` 只是 bool，不足以表达角色/玩家可见性 | P1 |
| disconnected agent 语义 | 当前 `ask()` 已用重试 + default 保持对局继续；若要展示断线玩家，需要 Engine/统计/UI 增加新状态 | P2 |
| 独立 `GameSession` | 当前会话管理在 `ui.backend.game_runner.GameManager/RunningGame`，Engine 层没有独立 `GameSession` 类 | P2 |

### 3.3 目标态

目标 Engine 接口：

```python
response = await engine.agents[player_id].act(request)
```

目标数据结构方向：

```text
GameState:
  players
  day
  phase
  events
  deaths
  sheriff_id
  winner
  role_state: dict[str, dict]

GameEvent:
  type
  day
  phase
  actor
  target
  payload
  visibility
  visible_to_roles
  visible_to_players

Observation:
  visible_events
  known_roles
  seer_checks
  metadata
```

注意：`RoleRule` 仍应保持无状态 singleton；角色状态应放在 per-game 的 `role_state`，不能放在 Rule 实例属性里。

---

## 4. Agent Layer

### 4.1 当前已实现

当前 Agent 决策主链：

```text
ActionRequest
  -> remember_step
  -> select_skills_step
  -> build_prompt_step
  -> call_model_step
  -> parse_output_step
  -> enforce_policy_step
  -> ActionResponse
```

核心组件：

| 组件 | 当前状态 |
|------|----------|
| `AgentRuntime` | 已实现，直接满足 `PlayerAgent` 协议 |
| `AgentMemory` | 已实现短期记忆、阶段摘要、pinned facts、player models、self commitments、field notes |
| Skill Router | 已实现 front matter 驱动的 Markdown skill 路由 |
| Prompt Builder | 已实现 system/user 两消息结构和输出 JSON schema |
| LLM 接入 | 已实现 OpenAI SDK 兼容客户端、重试、超时、限流/并发包装 |
| Policy fallback | 已实现非法输出修正和兜底响应 |
| Trace/Decision archive | 已实现决策记录和完整上下文归档 |

当前错误处理原则：

```text
LLM 调用失败
  -> call_model_step 标记 source = "llm_error"
  -> enforce_policy_step 生成合法 fallback
  -> 游戏继续
```

这与“LLM 失败即 agent 断线”的目标设计不同。当前主路径选择的是比赛稳定性优先。

### 4.2 自进化当前已实现

当前角色进化主链：

```text
queued
  -> training
  -> consolidating
  -> applying
  -> battling
  -> reviewing
  -> promoted / rejected
```

已实现能力：

- `VersionStore`：文件系统版 skill 版本管理。
- `SkillVersionConfig`：每局固定的角色版本配置。
- Training：selfplay 训练局。
- Review：生成增强复盘。
- Mid memory：`game_analysis.py` 写入 `data/mid_memory` 风格的中期记忆。
- Consolidation：基于历史分析、当前 skill 和 rejected buffer 生成提案。
- Apply：校验并应用 skill proposal。
- Battle：baseline vs candidate 对战。
- Promote/Reject：候选版本晋级或写入 rejected buffer。

### 4.3 当前缺口

| 缺口 | 说明 | 优先级 |
|------|------|--------|
| Evidence Pipeline v2 | 已有 Normalize/Select/Judge/Report 骨架和 `experience_candidates` 写入；consolidation 已可把 candidates 作为附加证据，但还未完全替代旧 mid-memory | P0 |
| 中期记忆落库 | `learning_v2` candidates 已可落 SQLite 并进入 consolidation prompt；旧 `game_analysis` 中期记忆仍并存 | P1 |
| Agent 失败语义 | 当前 fallback 继续游戏，`ask()` 也会捕获 agent 异常并 default；如果要改成断线，需要 Engine/统计/UI 同步改 | P2 |
| Prompt 预算器 | 当前 Prompt 拼接没有统一 token/字符预算执行器 | P2 |

---

## 5. UI Layer

### 5.1 当前已实现

当前 UI 通信模型：

```text
HTTP REST:
  - 启动游戏
  - 查询游戏快照
  - 读取 archive
  - 读取 review
  - 管理 selfplay
  - 管理 role evolution
  - 读取 leaderboard

SSE:
  - 对局实时事件
  - 自进化进度事件
  - 批量自进化进度事件
```

当前不是 WebSocket 架构。前端用 `EventSource` 订阅实时事件。

当前主要页面：

| 页面/组件 | 当前状态 |
|-----------|----------|
| 对局观战 | 已实现 |
| 游戏列表 | 已实现 |
| 决策详情 / archive 展示 | 已实现 |
| 复盘面板 | 已实现 |
| Selfplay 管理 | 已实现 |
| Role Evolution 管理 | 已实现 |
| Leaderboard | 已实现 |
| 人类玩家操作面板 | 前后端 SSE 提醒 + HTTP 轮询/提交已接线，待真实长局手测 |

### 5.2 当前 API 现状

后端当前主要路由：

```text
/api/games
/api/games/{game_id}
/api/games/{game_id}/events
/api/games/{game_id}/human-action
/api/games/{game_id}/action
/api/games/{game_id}/archive
/api/games/{game_id}/review
/api/selfplay
/api/selfplay/{run_id}/...
/api/role-evolution/...
/api/role-evolution/batch/...
/api/evolution-runs/...   # role-evolution 兼容 facade，供当前前端调用
/api/roles
/api/roles/{role}/versions
/api/roles/{role}/leaderboard
/api/leaderboards
```

当前已知不一致：

- 前端 `api.ts` 调用 `/api/evolution-runs...`，后端已提供兼容 facade；底层仍复用 `/api/role-evolution...` runner。
- 前端已有 `/api/games/{game_id}/human-action` 和 `/api/games/{game_id}/action` 调用，后端已提供轮询和提交路由。

### 5.3 目标态

短期目标不引入 WebSocket，优先收敛为：

```text
实时下行: SSE
命令上行: HTTP POST
查询: HTTP GET
```

人机混战目标流：

```text
StartGameRequest(human_player_id)
  -> GameManager 传给 create_agents()
  -> 对应座位创建 HumanPlayer
  -> HumanPlayer.act() 等待输入
  -> SSE 推送 decision_needed
  -> GET /api/games/{id}/human-action 轮询 pending request
  -> UI POST /api/games/{game_id}/action
  -> HumanPlayer.submit(ActionResponse)
  -> GameEngine 继续
```

---

## 6. Storage Layer

### 6.1 当前已实现

SQLite schema 已存在并包含：

| 表 | 当前状态 |
|----|----------|
| `games` | 已定义，普通对局、selfplay、role-evolution 运行期写入 |
| `players` | 已定义，普通对局、selfplay、role-evolution 运行期写入 |
| `game_events` | 已定义，运行期通过 `GamePersistence` 注入 sink 写入 |
| `decisions` | 已定义，运行期通过 `GamePersistence` 注入 sink 写入 |
| `experience_candidates` | 已定义，`learning_v2` Evidence Pipeline 可写 |
| `role_versions` | 已定义，但角色进化主版本库当前主要走文件系统 `VersionStore` |
| `skill_proposals` | 已定义 |
| `evolution_runs` | 已定义，`StorageRebuilder` 可从 role-evolution `state.json` + `battle_summary.json` 导入 battle_result |
| `leaderboard` | 已定义，`/api/leaderboards` 已优先读取 SQLite |

JSON/JSONL 当前仍承担重要职责：

```text
runs/games/<game_id>/game_events.jsonl
runs/games/<game_id>/archive.json
runs/games/<game_id>/review.json
runs/selfplay/.../game_events.jsonl
runs/selfplay/.../archive.json
runs/evolution/.../state.json
runs/evolution/.../battle_summary.json
data/mid_memory/...
data/versions/<role>/<hash>/skills/*.md
```

### 6.2 当前缺口

| 缺口 | 说明 | 优先级 |
|------|------|--------|
| SQLite 主查询路径 | 普通对局、selfplay、role-evolution 的列表/详情/事件/决策已优先读 SQLite；普通 review 输入、consolidation candidate context、role leaderboard、通用 leaderboard 已 DB 优先；archive endpoint 保留 JSON 导出语义 | P1 |
| 版本库统一 | SQLite `role_versions` 和文件系统 `VersionStore` 并存 | P2 |
| archive 导入/迁移策略 | 已有 importer 和 `StorageRebuilder`，但还不是所有查询的默认维护路径 | P2 |

### 6.3 目标态

推荐目标：

```text
写入:
  GameLogger -> game_events
  DecisionRecorder -> decisions
  GameStore -> games / players
  Evidence Pipeline -> experience_candidates
  Evolution -> evolution_runs / role_versions / skill_proposals / leaderboard

读取:
  UI 列表/详情/复盘/排行榜优先读 SQLite
  archive.json 作为调试导出和离线分享
```

---

## 7. 核心数据流

### 7.1 AI-only 对局：当前主路径

```text
POST /api/games
  -> GameManager.start_game()
  -> random_standard_roles()
  -> create_agents()
  -> GameEngine.run_until_finished()
      -> engine._ask()
      -> AgentRuntime.act()
      -> rules settle
      -> GameLogger entries
  -> SSE /api/games/{id}/events 推送实时日志
  -> AgentTraceRecorder.flush() 写 archive.json
  -> GameStore 写 games / players
```

当前 review：

```text
Game finished
  -> generate_enhanced_review() 本地启发式复盘
  -> 写 runs/games/<id>/review.json 缓存

GET /api/games/{id}/review
  -> 优先读取 review.json
  -> 缺失时 SQLite 读取 game_events + decisions，缺失时 fallback 到 JSON/JSONL
  -> generate_enhanced_review() 并回写 review.json
  -> 返回 report dict
```

普通 AI-only 对局不自动触发 mid-memory 或 LLM game_analysis；这两者仍保留在 selfplay / role-evolution 训练链路中。

### 7.2 AI-only 对局：目标补齐

```text
Game finished
  -> 自动触发 Evidence Pipeline
  -> 写 experience_candidates
  -> 更新或重建 leaderboard 聚合数据
  -> UI 从 SQLite 查询 replay/review/decision
```

### 7.3 人机混战：当前状态

当前主链已接线：

- `HumanPlayer` 类已存在。
- `create_agents(..., human_player_id=...)` 已支持创建人类座位。
- 前端配置项和操作面板已存在。
- `StartGameRequest.human_player_id` 已进入 `GameManager.start_game()`。
- `GameManager` 已保存 `human_player_id` 并传给 `create_agents()`。
- `GET /api/games/{id}/human-action` 返回当前 pending request；没有 pending 时返回 `204`。
- `POST /api/games/{id}/action` 提交 `ActionResponse` 并唤醒 `HumanPlayer.act()`。
- `/api/games/{id}/events` 会在真人座位出现 action request 时推送 `decision_needed`，前端收到后立即刷新操作面板。

### 7.4 人机混战：当前流

```text
POST /api/games { human_player_id }
  -> GameManager 保存 human_player_id
  -> create_agents(human_player_id=...)
  -> HumanPlayer.act() 阻塞等待
  -> SSE 推送 decision_needed
  -> GET /api/games/{id}/human-action 返回 pending request
  -> POST /api/games/{id}/action 提交 ActionResponse
  -> HumanPlayer.submit()
  -> 游戏继续
```

剩余增强：真实浏览器长局手测、非法输入重试 UI 文案。

### 7.5 自进化：当前主路径

```text
RoleEvolutionRunner
  -> run_evolution(role)
  -> Training: run_selfplay(enable_mid_memory=True)
  -> Review: generate_enhanced_review()
  -> Mid memory: analyze_game() + write_game_analysis()
  -> Consolidation: load_game_analysis() + LLM -> SkillProposal[]
  -> Apply: validate + write skill files -> candidate hash
  -> Battle: baseline vs candidate
  -> Reviewing: 等待 promote / reject
```

### 7.6 自进化：目标补齐

```text
Training games
  -> Evidence Pipeline
  -> experience_candidates table
  -> Consolidation reads candidates by role/version/window
  -> Battle writes comparable metrics
  -> Leaderboard reads SQLite aggregate
  -> UI shows curve / diff / battle evidence
```

---

## 8. 开发路线

### Phase 0: 全局 spec 校准

目标：所有后续子 spec 都区分当前实现、目标态和 gap。

状态：本文档。

### Phase 1: 接口打通和演示主路径修复

优先级最高，因为它直接影响可演示性。

| 任务 | 目标 |
|------|------|
| API 命名统一 | 已提供 `/api/evolution-runs` 兼容 facade，旧 `/api/role-evolution` 保留 |
| 人机混战接线 | 已跑通 `human_player_id`、`decision_needed`、pending action、submit action；剩余真实长局手测 |
| SSE/HTTP 协议定稿 | 文档和代码统一，不再写 WebSocket |
| review 触发策略 | 普通对局结束后自动生成本地 `review.json`；不自动触发 mid-memory / LLM game_analysis |

### Phase 2: Engine 信息隔离升级

| 任务 | 目标 |
|------|------|
| `visible_events` | 用结构化事件替代 prompt 侧字符串 public_log |
| `Visibility` | 支持 public / role-private / player-private / system |
| `role_state` | 迁移女巫、守卫、预言家等角色状态 |
| agent 异常语义 | 已选择继续 fallback；后续如需断线态再扩展 Engine/统计/UI |

### Phase 3: Evidence Pipeline v2

| 任务 | 目标 |
|------|------|
| Normalizer | 分离 player_view 和 god_view |
| Selector | 选择高影响决策和关键事件 |
| Judge | LLM 批量评判，输出可学习样本 |
| Report | 生成 Markdown/JSON 报告 |
| ExperienceCandidate | 替代或兼容现有 `game_analysis` 中期记忆 |

### Phase 4: SQLite 主存储化

| 任务 | 目标 |
|------|------|
| `experience_candidates` 主查询化 | consolidation 已读取评测样本主表作为附加证据；继续推动替代旧 mid-memory |
| UI 读库 | 已覆盖普通对局/selfplay/role-evolution 列表、事件、决策、普通 review 输入、role leaderboard 和通用 leaderboard；archive endpoint 保留调试导出 |
| JSON 导出定位 | archive 只作为导出和调试 |
| 迁移工具 | `StorageRebuilder` 覆盖历史 archive/events/candidates，并可导入 role-evolution battle summaries |

### Phase 5: 自进化可视化增强

| 任务 | 目标 |
|------|------|
| 版本曲线 | baseline/candidate/历史版本效果趋势 |
| battle evidence | 展示同 seed 对战差异和关键样本 |
| promote/reject 审计 | 展示升级依据、rejected buffer 和 rollback |

---

## 9. 子 Spec 索引

| # | Spec | 覆盖模块 | 当前状态 |
|---|------|----------|----------|
| 0 | 全局架构 | 全系统 | 本文档，已按现状校准 |
| 1 | 游戏引擎 + Agent 决策系统 | Engine + Agent 基础接口 | 已写，需要按本文档拆分“当前/目标/gap” |
| 2 | 评测与复盘 | Evidence Pipeline + ExperienceCandidate | 已写目标设计，当前代码尚未完整实现 |
| 3 | 自进化系统 | Evolution Pipeline + Battle + Consolidation | 待写，现有代码已有主路径 |
| 4 | Agent 决策系统 | Runtime + Memory + Skills + Prompts | 待写，现有代码已有主路径 |
| 5 | 存储 + UI | SQLite + SSE/HTTP + Frontend | 待写，当前为混合存储和 SSE/HTTP |

---

## 10. 评审维度与模块矩阵

| 评审维度 | 核心模块 | 当前可展示 | 仍需补强 |
|----------|----------|------------|----------|
| 单 Agent 能力 | AgentRuntime + Memory + Skill + Prompt | 决策 trace、skill 注入、记忆字段、合法输出 | Prompt 预算、真实 LLM 稳定性 |
| 多 Agent 协作 | Engine + Observation + public log | 信息隔离测试、公开发言和投票互动 | 结构化 visibility、私有事件视角测试 |
| 工程完整度 | Engine + UI + Storage | 完整 AI 对局、SSE 观战、archive、部分 SQLite、接口兼容、人机混战接线 | SQLite 主查询收敛、真实长局稳定性 |
| 评测 + 复盘 | Review + game_analysis | 增强复盘、关键错误、角色指标、mid memory | Evidence Pipeline v2、ExperienceCandidate 落库 |
| 自进化 Agent | Evolution Pipeline + VersionStore + Battle | training/consolidation/apply/battle/promote/reject | 进化曲线、样本证据、版本效果统计稳定性 |

---

## 11. 当前总判断

当前项目已经有稳定的 AI-only 对局、Agent 决策、Markdown skill、复盘、selfplay、角色进化和 UI 展示主路径。

全局架构下一步不应大拆重写，而应优先做三件事：

1. 收敛接口：SSE/HTTP、API 路由和真实浏览器长局验证。
2. 收敛数据：SQLite 作为主查询路径，JSON/JSONL 退为导出和调试。
3. 收敛评测：用 Evidence Pipeline / ExperienceCandidate 替代当前分散的 review + game_analysis 概念。

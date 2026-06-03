# 当前已实现功能说明

本文档记录当前项目已经实现的主要功能，便于答辩、后续开发和对照评分标准。内容以当前代码结构为准：

- `engine/`：狼人杀规则层与对局引擎。
- `agent/`：Agent 层主实现。
- `ui/`：观战 UI 与后端接口。
- `docs/`：设计、计划、复盘和说明文档。

## 1. 项目结构现状

当前项目已经完成了一轮结构整理，旧的 `playeragent/` 和旧的 `src/` 目录已经不再作为主实现存在。

当前核心目录如下：

```text
521wolf/
├── agent/                  # Agent 层主实现
│   ├── api/                # AgentRuntime、Agent 工厂
│   ├── core/               # AgentContext、记忆（AgentMemory、FieldNotes、PlayerProfile）
│   ├── decision/steps/     # 决策流水线 step
│   ├── knowledge/          # Prompt 构造、Markdown skill 加载与路由
│   │   ├── prompts/        # system/user message 构造、输出 schema
│   │   └── skills/         # skill loader 与 router
│   ├── learning/           # 自博弈、复盘、统计、版本评测、game_analysis、calibration
│   ├── learning/evolution/ # skill 自进化与版本对战（consolidation、pipeline、battle、applier 等）
│   ├── infrastructure/     # LLM、决策日志、trace archive、tracing
│   └── common/             # 通用工具函数（paths、time、json、coercion、callbacks、winner）
├── engine/                 # 规则层和对局引擎
│   ├── phases/             # 夜晚、白天、投票、警长等流程
│   ├── role_rules/         # 各角色技能规则
│   └── rules/              # 胜负、投票、死亡、警长等通用规则
├── ui/                     # 前端和后端观战界面
├── tests/                  # 单元测试和结构测试
├── docs/                   # 项目文档
├── data/                   # 经验数据、版本化 skill
└── runs/                   # selfplay 和 evolution 运行产出
```

## 2. 规则层已实现功能

规则层位于 `engine/`，负责完整狼人杀对局流程和信息隔离。Agent 层只通过 `ActionRequest -> ActionResponse` 接口参与游戏，不直接修改规则层内部状态。

### 2.1 角色支持

当前已支持以下角色：

| 角色  | 实现位置                                   | 已实现行为           |
| --- | -------------------------------------- | --------------- |
| 狼人  | `engine/role_rules/werewolf.py`        | 夜晚刀人，多狼人投票取多数目标 |
| 白狼王 | `engine/role_rules/white_wolf_king.py` | 白天自爆并带走目标       |
| 村民  | `engine/role_rules/villager.py`        | 无夜间技能，参与发言和投票   |
| 预言家 | `engine/role_rules/seer.py`            | 夜晚查验玩家阵营        |
| 女巫  | `engine/role_rules/witch.py`           | 解药、毒药逻辑         |
| 猎人  | `engine/role_rules/hunter.py`          | 死亡后开枪，部分死亡原因禁枪  |
| 守卫  | `engine/role_rules/guard.py`           | 夜晚守护目标，处理连续守护限制 |

基础课题要求的 5 种角色：狼人、预言家、女巫、猎人、村民，已经覆盖。

### 2.2 对局流程

当前规则层已经实现完整主流程：

1. 角色分配。
2. 夜晚行动。
3. 警长竞选。
4. 死亡公布。
5. 白天发言。
6. 白狼王自爆检查。
7. 放逐投票。
8. PK 发言与 PK 投票。
9. 遗言和猎人开枪。
10. 胜负判定。

对应代码主要位于：

- `engine/engine.py`
- `engine/phases/night.py`
- `engine/phases/day.py`
- `engine/phases/exile.py`
- `engine/phases/sheriff.py`
- `engine/rules/victory.py`
- `engine/rules/voting.py`
- `engine/rules/sheriff.py`
- `engine/rules/death.py`

### 2.3 信息隔离

规则层通过 `Observation` 给每个玩家提供可见信息：

- 所有人可见：当前天数、阶段、存活玩家、死亡玩家、警长、公开日志。
- 狼人可见：狼队友身份。
- 预言家可见：自己的查验结果。
- 女巫可见：当夜刀口、是否可救、是否可毒等元信息。
- 普通村民不会获得狼人队友、查验结果等私有信息。

相关测试已覆盖：

- 村民看不到狼人队友。
- 狼人可以看到队友。
- 预言家查验结果只进入对应预言家的私有视角。

### 2.4 日志与可观测性

规则层已经实现对局日志：

- 记录游戏初始化。
- 记录夜晚行动结果。
- 记录发言。
- 记录投票。
- 记录死亡。
- 记录警长变化。
- 记录胜负结果。

日志可导出为：

- JSONL：便于机器分析。
- 文本：便于人工阅读。

实现位置：

- `engine/logging.py`
- `engine/public_log.py`

## 3. Agent 层已实现功能

Agent 层位于 `agent/`，当前已经从旧实现中独立出来，作为唯一主 Agent 实现。

### 3.1 AgentRuntime 决策流水线

当前 Agent runtime 是自研的轻量图式流水线，没有引入 LangGraph。每次收到规则层的 `ActionRequest` 后，按 step 顺序处理：

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

决策记录在 pipeline 之外由 `AgentRuntime.act()` 内联完成（`_build_decision_record` + `recorder.record`），不作为独立 step。

实现位置：

- `agent/api/runtime.py`
- `agent/api/factory.py`
- `agent/core/context.py`
- `agent/decision/steps/`

这个结构已经满足后续迁移到 LangGraph 的基本条件：每个 step 输入输出都是统一的 `AgentContext`。

### 3.2 规则层兼容

Agent 层通过 `AgentRuntime` 实现规则层要求的玩家接口：

```python
async def act(request: ActionRequest) -> ActionResponse
```

规则层不需要知道 Agent 内部是否使用 LLM、ToT、记忆或 skill。

实现位置：

- `agent/api/runtime.py`
- `agent/api/factory.py`
- `engine/players.py`

### 3.3 模型接入

当前 Agent 层已经实现 OpenAI SDK 兼容模型接入：

- 默认使用 `openai.AsyncOpenAI`。
- Langfuse tracing 完整配置后才切换到 `langfuse.openai.AsyncOpenAI`。
- 支持自定义 `base_url`。
- 支持自定义模型名。
- 支持超时时间。
- 支持 temperature。
- 支持 `.env` 加载。

环境变量：

```text
WEREWOLF_LLM_API_KEY=your-api-key
WEREWOLF_LLM_BASE_URL=https://router.shengsuanyun.com/api/v1
WEREWOLF_LLM_MODEL=ali/qwen3.5-flash
WEREWOLF_LLM_TIMEOUT=45
WEREWOLF_LLM_TEMPERATURE=0.4
LANGFUSE_TRACING_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

实现位置：

- `agent/infrastructure/llm.py`
- `.env.example`

### 3.4 Prompt 构造

当前 Prompt 已经包含：

- 玩家身份。
- 当前阶段。
- 当前行动类型。
- 可选目标。
- 存活和死亡玩家。
- 公开局势摘要。
- 结构化记忆。
- 私有可见信息。
- 主观 belief。
- Markdown skill。
- 长期经验提示。
- 输出 JSON schema。

实现位置：

- `agent/knowledge/prompts/base.py`
- `agent/knowledge/prompts/instructions.py`
- `agent/knowledge/prompts/formatting.py`
- `agent/knowledge/prompts/parsing.py`

### 3.5 输出解析与兜底策略

当前 Agent 要求模型输出 JSON，并通过 `parse_output_step` 转换为 `ActionResponse`。

已支持：

- 直接 JSON。
- Markdown code block 包裹的 JSON。
- 兼容旧字段：`text`、`reasoning`。
- 当前字段：`public_text`、`private_reasoning`、`confidence`、`alternatives`、`rejected_reasons`、`memory_refs`、`selected_skill`。

如果模型输出非法，`enforce_policy_step` 会进行兜底：

- 非法 target 修正为合法候选。
- 非法 choice 修正为默认 choice。
- 缺失响应时生成安全 fallback。
- 女巫、警徽、白狼王等 choice/target 强相关动作有独立校验。

实现位置：

- `agent/decision/steps/parse_output.py`
- `agent/decision/steps/enforce_policy.py`

## 4. 记忆已实现功能

### 4.1 短期记忆

当前已经实现单局内短期记忆：

- 公开事件去重。
- 发言记录。
- 投票记录。
- 死亡记录。
- 自己历史行动。
- 自己近期私有决策理由。
- 玩家身份声明。
- 怀疑对象。
- 结构化现场笔记。

实现位置：

- `agent/core/memory.py`

### 4.2 结构化现场笔记

`FieldNotes` 已经维护：

- 当前游戏状态。
- 每位玩家的行为档案。
- 发言次数。
- 投票记录。
- 被投票记录。
- 攻击对象。
- 辩护对象。
- 投票模式摘要。

这些信息会注入 Prompt，帮助 Agent 不只依赖原始日志。

### 4.3 自博弈复盘与长期整合

当前已经实现自博弈复盘和长期整合的基础设施：

- 按角色汇总自博弈结果。
- 从历史对局和 skill 表现中生成改进提案。
- 使用版本化 skill workspace 做候选版本。
- 通过版本对战验证候选版本。

实现位置：

- `agent/learning/selfplay.py`
- `agent/learning/review.py`
- `agent/learning/evolution/consolidation.py`
- `agent/learning/evolution/pipeline.py`

## 5. Markdown Skill 系统已实现功能

当前 skill 已经从代码策略迁移为 Markdown 文件。

### 5.1 Skill 目录结构

Skill 以 Markdown 文件存储在版本化路径下：

```text
data/versions/
├── werewolf/{hash}/skills/
├── seer/{hash}/skills/
├── witch/{hash}/skills/
├── hunter/{hash}/skills/
├── guard/{hash}/skills/
├── villager/{hash}/skills/
└── white_wolf_king/{hash}/skills/
```

Skill loader（`agent/knowledge/skills/loader.py`）接受可配置的 `skill_root` 参数。

### 5.2 通用规则与输出约束

当前不再通过 common skill 注入通用规则和输出 schema。

这满足当前要求：

- 游戏规则、信息边界和输出 JSON schema 由 prompt 本体提供。
- router 只注入当前角色、当前行动匹配的角色 skill。
- `output_schema` 不再作为 skill 注入，避免重复 prompt 和错误路由。

### 5.3 角色 Skill

角色 skill 只会按当前角色注入，不会把其他角色策略泄露给当前 Agent。

已支持角色策略：

| 角色 | 示例 skill |
| --- | --- |
| 狼人 | 悍跳预言家、深水狼、找神、冲票 |
| 预言家 | 起跳、对跳、查验优先级、警徽流 |
| 女巫 | 救人、毒人、隐藏身份 |
| 猎人 | 开枪、威慑、隐藏身份 |
| 守卫 | 守护策略 |
| 村民 | 发言分析、站边预言家、票型分析、狼坑整理 |
| 白狼王 | 隐藏、自爆 |

实现位置：

- `agent/knowledge/skills/loader.py`
- `agent/knowledge/skills/router.py`
- `agent/decision/steps/select_skills.py`

### 5.4 Skill 元数据

Markdown skill 支持 YAML-like front matter：

```markdown
---
name: witch_poison
scope: role
role: witch
applicable_actions:
  - witch_act
requires:
  can_poison: true
---

技能正文
```

当前支持：

- `name`
- `scope`
- `role`
- `applicable_actions`
- `requires`
- `output_constraints`
- `prompt_hints`

已经按你的要求移除了不必要的 skill 优先级机制。

## 6. 可观测性已实现功能

### 6.1 决策日志

Agent 每次决策会记录：

- 玩家编号。
- 角色。
- 天数和阶段。
- 行动类型。
- 选中的目标。
- choice。
- 公开文本。
- 私有推理。
- 置信度。
- 使用的 skill。
- policy 修正。
- fallback 原因。

实现位置：

- `agent/infrastructure/decision_log.py`
- `agent/api/runtime.py`（内联 `_build_decision_record`）

### 6.2 Trace Archive

当前已经实现 Agent trace 归档能力，记录每次决策上下文：

- observation。
- memory。
- belief。
- skill。
- prompt。
- raw output。
- parsed decision。
- policy adjustment。
- ToT candidates。
- ToT judge reason。

实现位置：

- `agent/infrastructure/archive.py`

UI 后端会为完成的游戏写出：

- `gameN.jsonl`
- `gameN.txt`
- `logs/gameN/agent_decisions.jsonl`
- `logs/gameN/archive.json`

### 6.3 决策归档

当前不再提供 WebSocket 调试流。Agent 决策通过 recorder 和 archive 持久化，前端在对局完成后通过 HTTP 读取完整归档。

实现位置：

- `agent/infrastructure/decision_log.py`
- `agent/infrastructure/archive.py`
- `ui/backend/app.py`

## 7. 评测与复盘已实现功能

当前已经实现“评测 + 复盘”方向的一部分基础能力。

### 7.1 基础复盘

已经支持根据对局日志和 Agent 决策生成复盘报告：

- 玩家结果。
- 团队得分。
- 关键转折点。
- 明显失误。
- fallback / policy_adjusted 检测。
- 女巫误毒好人检测。
- 猎人带走好人检测。
- 狼人刀神职检测。

实现位置：

- `agent/learning/review.py`

### 7.2 Self-play 结果统计

当前已经实现自博弈结果对象和统计能力：

- 多局结果汇总。
- 胜率统计。
- fallback rate。
- review score 汇总。
- JSON / Markdown 输出。

实现位置：

- `agent/learning/selfplay.py`

### 7.3 Leaderboard

当前已经实现 Leaderboard 基础能力：

- 加载不同版本 summary。
- 聚合多局统计。
- 排序。
- 输出 JSON。
- 输出 Markdown 表格。

实现位置：

- `agent/learning/leaderboard.py`

### 7.4 版本对战

当前已经实现版本对战基础能力：

- 版本配置。
- 使用同一 seed 范围对比不同版本。
- 输出 leaderboard。

实现位置：

- `agent/learning/evolution/battle.py`
- `agent/learning/evolution/leaderboard.py`

## 8. UI 已实现功能

当前 UI 至少已经达到观战模式基础要求。

### 8.1 后端接口

后端基于 FastAPI，已经支持：

- 健康检查。
- 启动一局 AI 对局。
- 查询当前游戏状态。
- 查询历史游戏。
- 读取游戏日志。
- 读取 Agent archive。
- 生成复盘报告。
- SSE 推送实时对局事件。
- HTTP 读取 Agent archive 和复盘报告。
- 自博弈管理（启动、停止、恢复、终止、列表、按局查看 events/decisions/archives）。
- 角色进化管理（启动、批量、promote、reject、diff、rollback）。
- Leaderboard 接口（`/api/leaderboards`、`/api/roles/{role}/leaderboard`）。
- 角色版本管理（`/api/roles`、`/api/roles/{role}/versions`）。
- 人类玩家动作接口。
- 多条 SSE 事件流（game events、role batch evolution、role evolution）。

实现位置：

- `ui/backend/app.py`
- `ui/backend/game_runner.py`
- `ui/backend/selfplay_runner.py`
- `ui/backend/role_evolution_runner.py`
- `ui/backend/batch_role_evolution_runner.py`

### 8.2 前端功能

前端基于 Vite + React，已经支持：

- 游戏列表。
- 对局观战。
- 玩家状态展示。
- 事件日志展示。
- 决策信息展示。
- 通过归档展示 Agent 决策细节。
- 调用后端 API。
- 自博弈管理页面（`SelfplayPage.tsx`）。
- 角色进化管理页面（`RoleEvolutionPage.tsx`）。
- Leaderboard 面板（`LeaderboardPanel.tsx`）。
- 人类玩家操作面板（`HumanActionPanel.tsx`）。
- 游戏配置对话框（`GameConfigDialog.tsx`）。
- 复盘面板（`ReviewPanel.tsx`）。

实现位置：

- `ui/frontend/src/App.tsx`
- `ui/frontend/src/api.ts`
- `ui/frontend/src/pages/`
- `ui/frontend/src/components/`

## 9. 测试覆盖现状

当前测试已经覆盖规则层、Agent 层、UI 后端和结构约束。

已验证通过：

```text
uv run python -m unittest discover -s tests -v
Ran 307 tests
OK

npm run build
build passed
```

测试覆盖方向包括：

- 规则引擎主流程。
- 夜晚行动。
- 警长流程。
- 投票和 PK。
- 白狼王自爆。
- 猎人开枪。
- 胜负判定。
- 信息隔离。
- Agent runtime step。
- Prompt 构造。
- Markdown skill 加载。
- Skill 按角色注入。
- Policy fallback。
- 经验和长期记忆。
- 复盘和 Leaderboard。
- 角色进化 pipeline。
- 置信度校准。
- UI 后端接口。
- 项目结构约束。

## 10. 对照评分标准的当前完成度

| 评分项 | 当前状态 | 说明 |
| --- | --- | --- |
| 至少 5 种角色 | 已完成 | 当前支持 7 种角色 |
| 完整对局流程 | 已完成 | 夜晚、白天、发言、投票、胜负判定均已实现 |
| 信息隔离 | 已完成基础验证 | 规则层按角色构造 Observation，已有测试 |
| 对局日志 | 已完成 | 规则日志、Agent 决策日志、archive 均已实现 |
| 前端界面 | 已完成 | 支持启动、观战、日志、自博弈管理、角色进化管理、Leaderboard |
| 单 Agent 能力 | 已完成 | 有角色 persona、Prompt、skill、分层记忆（短期 + 中期经验 + 长期整合） |
| 多 Agent 协作 | 已完成基础交互 | 多角色能通过公开日志、投票和发言间接交互 |
| 评测 + 复盘 | 已完成 | 有复盘、失误检测、Leaderboard、版本对战、置信度校准 |
| 自进化 Agent | 已完成基础版 | 有自博弈、经验提取、长期整合、skill 版本化、版本对战、promote/reject 闭环 |
| 通用 Agent | 未作为主线实现 | 没有代码自修改、构建测试、失败回滚闭环 |

## 12. 当前一句话总结

当前项目已经实现了一个能跑完整狼人杀对局的规则层、一个基于自研 runtime 的 Agent 层、Markdown skill 系统、分层记忆（短期 + 中期经验卡片 + 长期策略整合）、基础复盘评测、Leaderboard、版本对战、角色自进化和观战 UI。基础课题要求基本已经覆盖，后续最值得优先补的是：真实 LLM 调用稳定性、复盘质量、更强的 Agent 策略效果验证。

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
│   ├── runtime/            # AgentRuntime、模型适配、Agent 工厂
│   ├── nodes/              # 决策流水线节点
│   ├── cognition/          # 记忆、信念、经验、长期记忆
│   ├── skill_system/       # Markdown skill 加载与路由
│   ├── skills/             # Markdown 策略技能
│   ├── prompts/            # Prompt 构造与输出解析辅助
│   ├── reasoning/          # ToT 多候选推理
│   ├── evaluation/         # 自博弈、复盘、Leaderboard、版本对战
│   └── observability/      # 决策日志、归档、调试流
├── engine/                 # 规则层和对局引擎
│   ├── phases/             # 夜晚、白天、投票、警长等流程
│   ├── role_rules/         # 各角色技能规则
│   └── rules/              # 胜负、投票、死亡、警长等通用规则
├── ui/                     # 前端和后端观战界面
├── tests/                  # 单元测试和结构测试
├── docs/                   # 项目文档
└── data/                   # 经验数据样例
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

当前 Agent runtime 是自研的轻量图式流水线，没有引入 LangGraph。每次收到规则层的 `ActionRequest` 后，按节点顺序处理：

```text
ActionRequest
  -> observe_node
  -> memory_node
  -> belief_node
  -> skill_router_node
  -> prompt_node
  -> tot_node
  -> llm_node
  -> parse_node
  -> policy_node
  -> log_node
  -> ActionResponse
```

实现位置：

- `agent/runtime/agent.py`
- `agent/runtime/context.py`
- `agent/nodes/`

这个结构已经满足后续迁移到 LangGraph 的基本条件：每个节点输入输出都是统一的 `AgentContext`。

### 3.2 规则层兼容

Agent 层通过 `LLMPlayerAgent` 实现规则层要求的玩家接口：

```python
async def act(request: ActionRequest) -> ActionResponse
```

规则层不需要知道 Agent 内部是否使用 LLM、ToT、记忆或 skill。

实现位置：

- `agent/runtime/agent.py`
- `agent/runtime/factory.py`
- `engine/players.py`

### 3.3 模型接入

当前 Agent 层已经实现 OpenAI SDK 兼容模型接入：

- 使用 `langfuse.openai.AsyncOpenAI`。
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
```

实现位置：

- `agent/runtime/model.py`
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

- `agent/prompts/base.py`
- `agent/prompts/instructions.py`
- `agent/prompts/formatting.py`
- `agent/prompts/parsing.py`

### 3.5 输出解析与兜底策略

当前 Agent 要求模型输出 JSON，并通过 `parse_node` 转换为 `ActionResponse`。

已支持：

- 直接 JSON。
- Markdown code block 包裹的 JSON。
- 兼容旧字段：`text`、`reasoning`。
- 当前字段：`public_text`、`private_reasoning`、`confidence`、`alternatives`、`rejected_reasons`、`memory_refs`、`selected_skill`。

如果模型输出非法，`policy_node` 会进行兜底：

- 非法 target 修正为合法候选。
- 非法 choice 修正为默认 choice。
- 缺失响应时生成安全 fallback。
- 女巫、警徽、白狼王等 choice/target 强相关动作有独立校验。

实现位置：

- `agent/nodes/parse.py`
- `agent/nodes/policy.py`

## 4. 记忆与 Belief 已实现功能

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

- `agent/cognition/memory.py`

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

### 4.3 Belief 建模

当前已经实现基础信念模型：

- 每个玩家的狼人概率。
- 村民概率。
- 神职概率。
- 身份声明。
- 证据列表。
- 原因列表。
- 玩家关系图。

信念会根据以下信息更新：

- 自己身份。
- 狼人队友私有视角。
- 预言家查验。
- 死亡事件。
- 投票事件。
- 发言中的怀疑。
- 公开跳身份。

实现位置：

- `agent/cognition/belief.py`

### 4.4 中期经验与长期记忆

当前已经实现经验卡片和长期记忆的基础设施：

- 按角色保存经验数据。
- 从历史经验中整合长期提示。
- 将长期经验提示注入 Prompt。
- 支持测试数据目录。

实现位置：

- `agent/cognition/experience.py`
- `agent/cognition/long_memory.py`
- `data/experiences/`
- `tests/data/experiences/`

## 5. Markdown Skill 系统已实现功能

当前 skill 已经从代码策略迁移为 Markdown 文件。

### 5.1 Skill 目录结构

```text
agent/skills/
├── common/
│   ├── game_rules.md
│   └── output_schema.md
├── werewolf/
├── seer/
├── witch/
├── hunter/
├── guard/
├── villager/
└── white_wolf_king/
```

### 5.2 通用 Skill

`common/game_rules.md` 和 `common/output_schema.md` 会对所有角色注入。

这满足当前要求：

- 游戏规则作为通用 skill。
- 每个角色都能看到通用规则。
- 输出格式作为通用约束。

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

- `agent/skill_system/loader.py`
- `agent/skill_system/router.py`
- `agent/nodes/skill_router.py`

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

## 6. ToT 多候选推理已实现功能

当前已经实现轻量 ToT 节点，用于关键动作生成多个候选方案并选择最优方案。

### 6.1 触发动作

当前 ToT 会用于这些关键动作：

- 放逐投票。
- PK 投票。
- 女巫行动。
- 预言家查验。
- 狼人刀人。
- 猎人开枪。
- 白狼王自爆。
- 警长竞选。
- 警上发言。

实现位置：

- `agent/nodes/tot.py`
- `agent/reasoning/tot.py`

### 6.2 ToT 输出内容

ToT 会要求模型生成：

- 3 个候选方案。
- 每个方案的行动。
- 公开发言。
- 私有推理。
- 预期收益。
- 风险。
- 最终选择。
- 选择理由。
- 置信度。

这些内容会进入 trace archive 和决策记录，便于复盘。

## 7. 可观测性已实现功能

### 7.1 决策日志

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

- `agent/observability/decision_log.py`
- `agent/nodes/log.py`

### 7.2 Trace Archive

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

- `agent/observability/archive.py`

UI 后端会为完成的游戏写出：

- `gameN.jsonl`
- `gameN.txt`
- `gameN.agent.jsonl`
- `gameN.archive.json`

### 7.3 实时调试流

当前已实现调试 WebSocket 广播能力：

- 决策后向前端推送轻量 decision summary。
- 包含 player、role、action、source、confidence、target、choice、skill、errors、ToT 状态等。

实现位置：

- `agent/observability/stream.py`
- `ui/backend/app.py`
- `ui/frontend/src/components/DebugPanel.tsx`

## 8. 评测与复盘已实现功能

当前已经实现“评测 + 复盘”方向的一部分基础能力。

### 8.1 基础复盘

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

- `agent/evaluation/review.py`
- `agent/evaluation/review_enhanced.py`

### 8.2 Self-play 结果统计

当前已经实现自博弈结果对象和统计能力：

- 多局结果汇总。
- 胜率统计。
- fallback rate。
- review score 汇总。
- JSON / Markdown 输出。

实现位置：

- `agent/evaluation/selfplay.py`

### 8.3 Leaderboard

当前已经实现 Leaderboard 基础能力：

- 加载不同版本 summary。
- 聚合多局统计。
- 排序。
- 输出 JSON。
- 输出 Markdown 表格。

实现位置：

- `agent/evaluation/leaderboard.py`

### 8.4 版本对战

当前已经实现版本对战基础能力：

- 版本配置。
- 使用同一 seed 范围对比不同版本。
- 输出 leaderboard。

实现位置：

- `agent/evaluation/version_battle.py`

## 9. UI 已实现功能

当前 UI 至少已经达到观战模式基础要求。

### 9.1 后端接口

后端基于 FastAPI，已经支持：

- 健康检查。
- 启动一局 AI 对局。
- 查询当前游戏状态。
- 查询历史游戏。
- 读取游戏日志。
- 读取 Agent archive。
- 生成复盘报告。
- WebSocket 推送实时日志和调试信息。

实现位置：

- `ui/backend/app.py`
- `ui/backend/game_runner.py`

### 9.2 前端功能

前端基于 Vite + React，已经支持：

- 游戏列表。
- 对局观战。
- 玩家状态展示。
- 事件日志展示。
- 决策信息展示。
- DebugPanel 展示 Agent 决策摘要。
- 调用后端 API。

实现位置：

- `ui/frontend/src/App.tsx`
- `ui/frontend/src/api.ts`
- `ui/frontend/src/presentation.ts`
- `ui/frontend/src/components/DebugPanel.tsx`

## 10. 测试覆盖现状

当前测试已经覆盖规则层、Agent 层、UI 后端和结构约束。

已验证通过：

```text
uv run python -m unittest discover -s tests -v
Ran 267 tests
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
- Agent runtime 节点。
- Prompt 构造。
- Markdown skill 加载。
- Skill 按角色注入。
- Policy fallback。
- ToT。
- 经验和长期记忆。
- 复盘和 Leaderboard。
- UI 后端接口。
- 项目结构约束。

## 11. 对照评分标准的当前完成度

| 评分项 | 当前状态 | 说明 |
| --- | --- | --- |
| 至少 5 种角色 | 已完成 | 当前支持 7 种角色 |
| 完整对局流程 | 已完成 | 夜晚、白天、发言、投票、胜负判定均已实现 |
| 信息隔离 | 已完成基础验证 | 规则层按角色构造 Observation，已有测试 |
| 对局日志 | 已完成 | 规则日志、Agent 决策日志、archive 均已实现 |
| 前端界面 | 已完成观战基础版 | 支持启动、观战、日志、调试信息 |
| 单 Agent 能力 | 已完成基础版 | 有角色 persona、Prompt、skill、memory、belief、ToT |
| 多 Agent 协作 | 已完成基础交互 | 多角色能通过公开日志、投票和发言间接交互 |
| 评测 + 复盘 | 已完成基础版 | 有复盘、失误检测、Leaderboard、版本对战基础设施 |
| 自进化 Agent | 部分基础设施 | 有经验和长期记忆，但完整自动进化闭环还不是主线成品 |
| 通用 Agent | 未作为主线实现 | 没有代码自修改、构建测试、失败回滚闭环 |

## 12. 当前已知风险

以下不是“未实现功能”，而是当前代码 review 发现的优先修复点：

1. `agent/runtime/model.py` 当前给 `chat.completions.create()` 传了 `name` 参数，真实 OpenAI SDK 不支持这个顶层参数，真实 LLM 调用可能失败并进入 fallback。
2. ToT 当前按候选位置生成 `a/b/c`，没有严格使用模型返回的 `candidate_id`，在模型输出顺序异常时可能选错方案。
3. Langfuse 当前默认导入并初始化，没配置 key 时测试输出会有认证提示，建议增加 no-op tracing 或配置开关。
4. UI 后端创建 Agent 时没有把 `game_id` 传入 `create_agents()`，Langfuse session 和本地 archive 的关联不够完整。
5. `521wolf.egg-info/` 是构建产物，已被 `.gitignore` 忽略，不应提交。

## 13. 当前一句话总结

当前项目已经实现了一个能跑完整狼人杀对局的规则层、一个基于自研 runtime 的 Agent 层、Markdown skill 系统、短期记忆和 belief、ToT 多候选推理、基础复盘评测、Leaderboard、版本对战和观战 UI。基础课题要求基本已经覆盖，后续最值得优先补的是：真实 LLM 调用稳定性、复盘质量、长期记忆闭环和更强的 Agent 策略效果验证。

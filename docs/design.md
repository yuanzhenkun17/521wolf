# 521wolf 整体设计

本文档整合了 521wolf 项目的分层设计：**规则层**（werewolf engine）、**Agent 层**（Agent v2 决策流水线）、**UI 层**（观战与评测前端）。UI 层独立放在 `ui/` 下，不侵入规则层 `engine/werewolf`。

---

## 目录

1. [总体架构](#1-总体架构)
2. [规则层](#2-规则层)
3. [Agent v2 设计](#3-agent-v2-设计)
   - 3.1 [设计目标](#31-设计目标)
   - 3.2 [与规则层的兼容边界](#32-与规则层的兼容边界)
   - 3.3 [目录结构](#33-目录结构)
   - 3.4 [图式 Runtime](#34-图式-runtime)
   - 3.5 [AgentContext](#35-agentcontext)
   - 3.6 [节点职责](#36-节点职责)
   - 3.7 [决策输出格式](#37-决策输出格式)
   - 3.8 [角色策略设计](#38-角色策略设计)
   - 3.9 [Prompt 结构](#39-prompt-结构)
   - 3.10 [Fallback 策略](#310-fallback-策略)
   - 3.11 [LangGraph 迁移方案](#311-langgraph-迁移方案)
   - 3.12 [MVP 实现顺序](#312-mvp-实现顺序)
   - 3.13 [测试要求](#313-测试要求)
   - 3.14 [Agent 设计原则](#314-agent-设计原则)
       - 3.14.1 [边界原则](#3141-边界原则agent-不能破坏规则层)
       - 3.14.2 [视角原则](#3142-视角原则agent-只能看到玩家视角)
       - 3.14.3 [记忆原则](#3143-记忆原则每个玩家都有独立记忆)
       - 3.14.4 [事实与判断分离](#3144-事实与判断分离)
       - 3.14.5 [决策过程保留](#3145-决策过程必须保留)
       - 3.14.6 [发言与内心分离](#3146-发言与内心想法必须分离)
       - 3.14.7 [角色差异](#3147-角色差异原则)
       - 3.14.8 [玩家个性](#3148-玩家个性差异)
       - 3.14.9 [可扩展性](#3149-可扩展性)
4. [UI 层](#4-ui-层)
   - 4.1 [架构概览](#41-架构概览)
   - 4.2 [后端接口](#42-后端接口)
   - 4.3 [前端](#43-前端)
   - 4.4 [补齐计划](#44-补齐计划)
   - 4.5 [P0：接入 Agent V2](#45-p0接入-agent-v2)
   - 4.6 [P1：Agent 决策详情面板](#46-p1agent-决策详情面板)
   - 4.7 [P1：对局复盘页](#47-p1对局复盘页)
   - 4.8 [P2：Leaderboard / Version Battle](#48-p2leaderboard--version-battle)
   - 4.9 [P2：对局时间线增强](#49-p2对局时间线增强)
   - 4.10 [P3：人机混战](#410-p3人机混战)
   - 4.11 [推荐实现顺序](#411-推荐实现顺序)
   - 4.12 [答辩展示路径](#412-答辩展示路径)

---

## 1. 总体架构

项目采用严格的三层架构，自底向上为：

```text
┌──────────────────────────────────────────────┐
│              UI 层 (ui/)                      │
│  FastAPI 后端 → React 前端                    │
│  观战 / 决策详情 / 复盘 / Leaderboard         │
├──────────────────────────────────────────────┤
│           Agent 层 (agent/)                   │
│  Agent v2 图式决策流水线                      │
│  观察 → 记忆 → 信念 → 策略 → Prompt → LLM    │
│  → 解析 → 修正 → 日志                        │
├──────────────────────────────────────────────┤
│          规则层 (engine/werewolf/)             │
│  GameEngine / GameState / ActionRequest       │
│  角色 / 技能 / 胜负判定                       │
└──────────────────────────────────────────────┘
```

**关键约束：**

- Agent 层通过 `ActionRequest → ActionResponse` 协议与规则层交互，不能直接读写 `GameState`。
- UI 层只读 Agent 决策日志和规则层事件日志，不参与游戏逻辑。
- 每层可以独立开发、测试和替换。

---

## 2. 规则层

规则层是 521wolf 的固定协议层，负责：

- 管理 `GameState`（玩家生死、警长、药品、查验等）。
- 通过 `ActionRequest` 向玩家 Agent 请求行动。
- 通过 `ActionResponse` 接收玩家决策。
- 执行胜负判定。
- 输出结构化事件日志。

Agent 层和 UI 层都不得绕过规则层修改游戏状态。

### 2.1 游戏流程

整体流程：

```
第一夜（守卫→狼人→预言家→女巫）
→ 天亮
→ 警长竞选
→ 公布死亡 / 遗言 / 技能结算
→ 确定发言顺序
→ 白天发言
→ 警长归票
→ 投票 / 放逐
→ 遗言 / 技能结算
→ 检查胜负
→ 进入夜晚
```

### 2.2 胜负判定

**好人胜利条件：** 所有狼人（普通狼人 + 白狼王）全部出局。

**狼人胜利条件（屠边）：**

- *屠民：* 所有普通村民全部出局。
- *屠神：* 所有神职（预言家、女巫、猎人、守卫）全部出局。
- *人数碾压：* 狼人数量大于等于好人数量。

触发时机：只在人数变化及有人死亡时判定。

### 2.3 角色技能

**预言家：** 每晚可查验一名玩家，结果仅显示"好人"或"狼人"。在狼人行动之后、女巫行动之前触发。当晚死亡仍可完成查验。

**女巫：** 有两瓶药（解药 + 毒药），每瓶限用一次，一晚只能用一种。未使用解药时知道当晚刀口。第一晚可以自救，之后不能自救。当晚被刀仍可行动。守卫和女巫解药同时作用会导致"奶穿"（目标死亡）。

**猎人：** 死亡时可开枪带走一名玩家。被狼人夜杀或白天放逐可以开枪；被女巫毒死或白狼王自爆带走不能开枪。

**守卫：** 每晚可守护一名玩家，不能连续两晚守同一人，可以守自己。守卫只能防狼人刀，不能防女巫毒。

**普通狼人：** 夜晚共同选择一名玩家击杀，可以自刀。允许狼人内部轮流发言讨论。

**白狼王：** 属于狼人阵营。白天发言阶段可自爆并带走一名玩家，被带走者无遗言、不触发死亡技能。被投票放逐或夜晚死亡不能发动技能。

**村民：** 没有夜晚技能，通过发言、投票、分析站边帮助好人阵营。

### 2.4 发言规则

- **白天发言：** 警长选择顺序或逆序，从警长相邻玩家开始，警长最后发言并归票。
- **狼人夜聊：** 夜晚轮到狼人刀人时，狼人内部轮流发言，之后投票决定刀口。
- **白狼王自爆：** 打断发言和投票，直接进入夜晚。

#### 遗言规则

| 死亡方式 | 遗言 |
|----------|------|
| 白天被放逐 | 有遗言 |
| 被狼人夜杀 | 无遗言 |
| 被女巫毒死 | 无遗言 |
| 被白狼王带走 | 无遗言 |
| 被猎人枪杀 | 无遗言 |

### 2.5 投票规则

- 投票发生在白天发言之后，只能投存活玩家，允许弃票。
- 得票最高者被放逐，结算遗言和死亡技能。
- **平票处理：** 平票玩家进入 PK → PK 玩家再次发言 → 非 PK 玩家重新投票（只能投 PK 玩家）。PK 后再次平票 → 本轮无人出局，直接进入夜晚。
- 投票是公开的，每位玩家的投票对象所有玩家可见。

### 2.6 警长规则

警长是额外身份标记，不影响角色技能和遗言。

**权力：** 归票权（最后发言并给出建议投票对象）、额外票权（1.5 票）、警徽流（死亡时可移交警徽或撕毁）。

**竞选流程：** 第一夜之后、第一天白天正式发言之前进行。上警玩家依次发言，警下玩家投票。平票则 PK 后再投，再次平票则无警长。上警后可退水，退水后不能当选也不能投票。

**警长死亡：** 可选择移交警徽或撕掉警徽。

---

## 3. Agent v2 设计

### 3.1 设计目标

Agent v2 的目标不是简单替换 Prompt，而是重建一套清晰的多智能体决策层。

- 严格兼容现有规则层。
- 不直接读取或修改 `GameState`。
- 所有决策通过 `ActionRequest → ActionResponse` 协议完成。
- 每个角色有独立策略和行为差异。
- 支持短期记忆、局势信念、角色 skill、结构化决策日志。
- 先用轻量图式 runtime 跑通，后续可平滑迁移到 LangGraph。

### 3.2 与规则层的兼容边界

现有规则层只依赖玩家 Agent 的统一接口：

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

Agent v2 必须保持这个边界。

**允许做的事：**

- 读取 `request.player_id`、`request.action_type`、`request.phase`、`request.observation`、`request.candidates`、`request.metadata`
- 维护 Agent 自己的记忆、信念和策略状态
- 调用 LLM
- 记录 Agent 自己的决策日志
- 返回合法 `ActionResponse`

**禁止做的事：**

- 直接读取规则层内部 `GameState`
- 直接修改玩家生死、警长、药品、查验等规则状态
- 绕过规则层执行动作
- 要求规则层额外传递隐藏信息
- 把 LLM Prompt、记忆、策略逻辑写入规则层

最终输出必须是：

```python
ActionResponse(
    action_type=request.action_type,
    target=...,
    choice=...,
    text=...,
)
```

### 3.3 目录结构

```text
agent/
  __init__.py
  context.py           # AgentContext 定义
  runtime.py           # 轻量图式 runtime
  memory.py            # 短期记忆
  belief.py            # 局势信念
  prompts.py           # Prompt 模板
  parsing.py           # LLM 输出解析
  policy.py            # 策略修正与 fallback
  decision.py          # 决策日志定义
  llm.py               # LLM 客户端封装
  factory.py           # Agent 创建工厂
  nodes/
    __init__.py
    observe.py         # 观察节点
    memory.py          # 记忆节点
    belief.py          # 信念节点
    skill_router.py    # 策略路由
    prompt.py          # Prompt 构造
    llm.py             # 模型调用
    parse.py           # 输出解析
    policy.py          # 策略修正
    log.py             # 决策日志
  strategies/
    __init__.py
    base.py            # 策略基类
    werewolf.py        # 狼人策略
    seer.py            # 预言家策略
    witch.py           # 女巫策略
    hunter.py          # 猎人策略
    villager.py        # 村民策略
    guard.py           # 守卫策略
    white_wolf_king.py # 白狼王策略
  reasoning/
    tot.py             # Tree of Thought
  observability/
    decision_log.py    # AgentDecisionRecorder
    archive.py         # AgentTraceRecorder (完整上下文快照)
  evaluation/
    review_enhanced.py # 增强复盘评分
    version_battle.py  # 版本对战
    leaderboard.py     # 排行榜
  skill_system/
    ...                # Skill 注入系统
```

### 3.4 图式 Runtime

核心思想是图式决策流水线，每个节点只做一件事：

```text
ActionRequest
→ observe_node
→ memory_node
→ belief_node
→ skill_router_node
→ prompt_node
→ llm_node
→ parse_node
→ policy_node
→ log_node
→ ActionResponse
```

当前轻量实现（`runtime.py`）：

```python
class AgentV2Runtime:
    def __init__(self, player_id, role, model, memory, belief, strategy, decision_recorder=None, trace_recorder=None):
        self.player_id = player_id
        self.role = role
        self.model = model
        self.memory = memory
        self.belief = belief
        self.strategy = strategy
        self.decision_recorder = decision_recorder
        self.trace_recorder = trace_recorder

    async def act(self, request):
        ctx = AgentContext(
            request=request,
            player_id=self.player_id,
            role=self.role.value,
        )

        ctx = observe_node(ctx)
        ctx = memory_node(ctx, self.memory)
        ctx = belief_node(ctx, self.belief)
        ctx = skill_router_node(ctx, self.strategy)
        ctx = prompt_node(ctx)
        ctx = await llm_node(ctx, self.model)
        ctx = parse_node(ctx)
        ctx = policy_node(ctx)
        ctx = log_node(ctx, self.decision_recorder, self.trace_recorder)

        return ctx.response
```

后续迁移到 LangGraph 时，这些节点函数可以基本原样挂到 LangGraph 上，并增加条件边（parse 失败 → fallback、低置信度 → self_critique、关键行动 → ToT）。

### 3.5 AgentContext

`AgentContext` 是 Agent v2 内部流转状态，不传给规则层。

```python
@dataclass(slots=True)
class AgentContext:
    request: ActionRequest
    player_id: int
    role: str
    observation_summary: dict[str, Any] = field(default_factory=dict)
    memory_context: dict[str, Any] = field(default_factory=dict)
    belief_context: dict[str, Any] = field(default_factory=dict)
    selected_skill: str | None = None
    strategy_advice: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    raw_output: str = ""
    parsed_decision: dict[str, Any] = field(default_factory=dict)
    response: ActionResponse | None = None
    errors: list[str] = field(default_factory=list)
```

`private_reasoning` 等敏感信息只进入 Agent 日志，不进入公开发言。

### 3.6 节点职责

#### 3.6.1 observe_node

从 `ActionRequest` 和 `Observation` 中提取可见信息，生成结构化 observation summary，不添加规则层未提供的信息。

输出示例：

```json
{
  "day": 2,
  "phase": "day_speech",
  "action_type": "speak",
  "alive_players": [1, 2, 3, 5, 6, 8, 9, 10],
  "dead_players": [4, 7],
  "sheriff_id": 5,
  "known_roles": {"1": "werewolf"},
  "seer_checks": {"9": "villagers"},
  "candidates": [2, 7, 9]
}
```

#### 3.6.2 memory_node

更新本局短期记忆，从公开日志中提取发言、投票、死亡等事件，维护每个玩家的行为记录，输出当前决策所需的记忆摘要。记忆不应无限塞入 Prompt，优先结构化摘要。

**设计原则：** Memory 只存"已经发生过的事实"，不存主观判断。例如存"P3 第 1 天发言怀疑 P5"而不是"P3 是狼"。

每个玩家维护独立的 Memory，不能共享。第一版设计为结构化事件列表：

```python
class MemoryEvent:
    day: int
    phase: str
    event_type: str       # speech / vote / death / claim / check / etc.
    actor: str | None
    target: str | None
    content: str           # 事件描述
    visibility: str        # public / private
```

**Memory 与 Belief 的关系：** Memory 是原材料（事实），Belief 是加工结果（判断）。流程为：Observation → 写入 Memory → 根据 Memory 更新 Belief → 根据 Belief 决策。

#### 3.6.3 belief_node

基于 observation 和 memory 更新局势判断，维护每位玩家的身份嫌疑度并记录判断依据。

**设计原则：** Belief 存"这个玩家自己的判断"，不是事实。第一版围绕"每个玩家的身份概率/怀疑程度"：

```python
class PlayerBelief:
    player_id: str
    suspicion: float          # 狼人嫌疑 0-1
    trust: float              # 信任度 0-1
    possible_roles: dict      # 身份概率分布
    reasons: list[str]        # 判断理由
```

每个玩家维护独立的 Belief（狼人知道队友，村民不知道）。

示例：

```json
{
  "player_id": "P5",
  "suspicion": 0.75,
  "trust": 0.25,
  "possible_roles": {
    "werewolf": 0.7,
    "villager": 0.2,
    "seer": 0.1
  },
  "reasons": [
    "第 1 天发言前后矛盾",
    "投票跟随 P3，没有独立理由"
  ]
}
```

完整 belief 输出示例：

```json
{
  "players": {
    "7": {
      "wolf_score": 0.76,
      "good_score": 0.18,
      "god_score": 0.06,
      "reasons": ["连续跟票", "攻击预言家", "发言缺少独立视角"]
    }
  }
}
```

#### 3.6.4 skill_router_node

根据角色、阶段、行动类型和局势选择 skill，生成角色策略建议。示例 skill：

- 狼人：`werewolf_fake_seer`, `werewolf_vote_rush`
- 预言家：`seer_badge_flow`, `seer_claim`
- 女巫：`witch_save`, `witch_poison`
- 猎人：`hunter_shoot`
- 村民：`villager_vote_analysis`

#### 3.6.5 prompt_node

构造 LLM messages，注入角色目标、规则约束、可见信息、记忆摘要、信念摘要、skill 建议。明确要求模型输出 JSON，禁止泄露私有推理到公开发言。

Prompt 分层：

- system：角色设定、规则边界、输出格式
- developer / instruction：当前 skill 与策略约束
- user：当前 observation 和行动要求

#### 3.6.6 llm_node

调用模型，记录原始输出，捕获模型调用异常。异常时不抛给规则层，而是记录错误并交给 policy fallback。

#### 3.6.7 parse_node

从模型输出解析结构化决策，支持 Markdown 代码块中的 JSON，支持缺字段修复，解析失败时记录错误。

#### 3.6.8 policy_node

将 parsed decision 转成 `ActionResponse`，校验 `action_type` 匹配 request、`target` 在 candidates 中、`choice` 符合当前行动类型。非法时修正或 fallback。

策略：能修正则修正，不能修正则使用合法默认动作。狼人夜间刀人不允许空刀时，选择合法候选目标。

#### 3.6.9 log_node

记录 Agent v2 决策日志，日志不影响规则层，用于复盘、评分和前端展示。

记录字段：

```json
{
  "player_id": 7,
  "role": "witch",
  "day": 2,
  "phase": "night",
  "action_type": "witch_act",
  "selected_skill": "witch_poison",
  "candidates": [2, 3, 9],
  "selected_target": 3,
  "selected_choice": "poison",
  "public_text": "",
  "private_reasoning": "3号连续两天跟随疑似狼队票型，且发言中试图带走预言家。",
  "confidence": 0.71,
  "alternatives": [2, 9],
  "rejected_reasons": ["2号有狼面但可能是被带票村民", "9号发言弱但票型不够狼"],
  "belief_snapshot": {},
  "memory_summary": [],
  "errors": [],
  "source": "llm"
}
```

其中 `source` 字段表示决策来源：`"llm"`（正常 LLM 输出）、`"fallback"`（异常回退）、`"policy_adjusted"`（策略修正）、`"tot"`（Tree of Thought 多候选推理）。

除了上述 `DecisionRecord`（每步决策日志，写 `logs/gameX/agent_decisions.jsonl`），还会通过 `AgentTraceRecorder` 记录完整上下文 `DecisionArchive` 包含 `observation_summary`、`memory_context`、`belief_context`、`selected_skills`、`prompt_messages`、`raw_output`、`tot_candidates`、`tot_judge_reason`（写 `logs/gameX/archive.json`）。

### 3.7 决策输出格式

要求 LLM 输出 JSON，内部字段比 `ActionResponse` 更丰富：

```json
{
  "target": 7,
  "choice": null,
  "public_text": "我认为7号视角不开，今天优先出7。",
  "private_reasoning": "7号连续跟随2号投票，没有独立找狼逻辑，且攻击预言家时机异常。",
  "confidence": 0.74,
  "alternatives": [2, 10],
  "rejected_reasons": [
    "2号虽然可疑，但目前证据弱于7号",
    "10号发言偏划水，但投票行为暂不构成强狼面"
  ]
}
```

映射到规则层：

```python
ActionResponse(
    action_type=request.action_type,
    target=decision["target"],
    choice=decision["choice"],
    text=decision["public_text"],
)
```

### 3.8 角色策略设计

每个角色实现独立 strategy，统一接口：

```python
class RoleStrategy:
    def select_skill(self, ctx: AgentContext) -> str: ...
    def advice(self, ctx: AgentContext) -> str: ...
```

| 角色 | 重点能力 |
|------|----------|
| 狼人 | 找神、伪装、悍跳、倒钩、冲票、保护或切割队友 |
| 预言家 | 查验优先级、警徽流、是否跳身份、对跳处理、带队归票 |
| 女巫 | 是否救人、是否毒人、避免毒错神、隐藏身份、识别狼人骗药 |
| 猎人 | 隐藏身份、威慑狼人、开枪目标选择、避免被诱导带错人 |
| 村民 | 发言分析、票型分析、站边、狼坑构建、避免乱跳神 |

### 3.9 Prompt 结构

```
你是 {role} 角色 Agent。

你的目标：
...

你能看到的信息：
...

你不能做的事：
- 不得假设自己看不到的信息。
- 不得在公开发言中泄露 private_reasoning。
- 不得输出非法 target。

当前局势摘要：
...

你的记忆：
...

你的局势判断：
...

当前 skill 建议：
...

请输出 JSON：
{
  "target": null,
  "choice": null,
  "public_text": "...",
  "private_reasoning": "...",
  "confidence": 0.0,
  "alternatives": [],
  "rejected_reasons": []
}
```

### 3.10 Fallback 策略

任何时候 Agent v2 都必须返回合法 `ActionResponse`。

| 场景 | Fallback 行为 |
|------|---------------|
| 发言类 | 返回简短发言或空发言 |
| 投票类 | 优先 belief 中狼人嫌疑最高者；没有则弃票 |
| 狼人刀人 | 必须从合法候选中选择一个目标 |
| 预言家查验 | 选择未查验且嫌疑高的候选人 |
| 女巫行动 | 默认不用药 |
| 猎人开枪 | 选择嫌疑最高候选；没有则不开枪 |
| 警长相关 | 默认不上警或按角色策略决定 |

Fallback 记录日志并标记 `source = "fallback"`。

### 3.11 LangGraph 迁移方案

第一版不直接依赖 LangGraph，但节点设计保持可迁移。

当前轻量 runtime：顺序执行节点。

迁移到 LangGraph 时：

```python
graph.add_node("observe", observe_node)
graph.add_node("memory", memory_node)
# ... 每个节点对应一个 graph node
```

可增加条件边：

- parse 失败 → fallback policy
- 低置信度 → self_critique_node
- 关键行动 → tree_of_thought_node
- 普通行动 → policy_node

适合后续扩展的节点：

- `self_critique_node`
- `tree_of_thought_node`
- `graph_of_thought_node`
- `review_memory_node`
- `experience_retrieval_node`

### 3.12 MVP 实现顺序

| 阶段 | 内容 |
|------|------|
| 阶段 1：兼容跑通 | 新建 `agent/`，实现基础 `act()`、`AgentContext`、observe/prompt/llm/parse/policy/log 节点，能完整跑完一局 |
| 阶段 2：角色差异 | 实现各角色 strategy，独立 Prompt 建议，不同 fallback，日志记录 selected_skill |
| 阶段 3：记忆和信念 | 短期 memory，belief score，记录玩家行为，Prompt 注入摘要 |
| 阶段 4：复盘评测 | 赛后读取日志生成复盘报告，关键失误和改进建议，多版本对比 |
| 阶段 5：可选 LangGraph | 节点挂到 LangGraph，条件边，ToT / self-critique |

### 3.13 测试要求

- Agent v2 返回的 `action_type` 永远匹配 request
- target 必须来自 candidates
- 村民 observation 不包含狼人队友信息
- 狼人 observation 不包含预言家查验结果
- 预言家只看到自己的查验结果
- 模型输出非法 JSON 时 fallback 可用
- 模型输出非法 target 时 policy 可修正
- 每次决策都有日志
- 不同角色选择的 skill 不同

### 3.14 Agent 设计原则

#### 3.14.1 边界原则：Agent 不能破坏规则层

Agent 只能通过 `ActionRequest → ActionResponse` 协议交互，返回行动意图（投 P5、查验 P3、守护 P8），不能直接修改游戏状态（P5 出局、狼人胜利）。所有状态变更必须由规则层校验和结算。

#### 3.14.2 视角原则：Agent 只能看到玩家视角

Agent 不能拥有上帝视角，只能看到 `ActionRequest.observation` 允许的信息。普通村民只能看到公开发言/投票/死亡；预言家额外知道查验结果；狼人夜晚知道队友和刀人信息；女巫知道死亡信息和用药状态；守卫知道自己守过谁。Agent 的所有判断都必须基于玩家可见信息。

#### 3.14.3 记忆原则：每个玩家都有独立记忆

每个玩家维护个人记忆，不共享。至少记住：谁说过什么、谁投过谁、谁怀疑过谁、自己怀疑过谁、自己站边谁、自己做过什么动作。区分公开信息（所有玩家可见）和个人记忆（自己维护）。

#### 3.14.4 事实与判断分离

Agent 内部严格区分 Memory（事实记忆）和 Belief（主观判断）：

- **Memory：** 记已经发生的事情，如"第 1 天 P3 投了 P5"。
- **Belief：** 玩家根据事实形成的判断，如"我觉得 P3 有狼面"。

流程：Observation → 写入 Memory → 根据 Memory 更新 Belief → 根据 Belief 决策。

#### 3.14.5 决策过程必须保留

每个行动都要记录：行动结果、行动理由、备选方案、为什么没有选择其他方案。这些不全部展示给其他玩家，但写入日志以便分析 Agent 问题。

#### 3.14.6 发言与内心想法必须分离

Agent 内部可以有真实想法（"我是狼人，我要伪装并把怀疑引到 P5 身上"），但公开发言不能说内心独白。输出需区分：

- `private_reasoning`：内部判断，不公开
- `public_speech`：公开发言，其他玩家可见

#### 3.14.7 角色差异原则

不同角色的目标、信息、策略和行动方式都不同。每个角色应有独立策略模块或配置：

| 角色 | 核心目标 |
|------|----------|
| 预言家 | 查验、报信息、建立可信度 |
| 狼人 | 隐藏身份、带节奏、夜晚刀人 |
| 女巫 | 判断救药和毒药时机 |
| 猎人 | 判断死亡后是否开枪、带谁 |
| 守卫 | 保护关键身份，避免重复守护 |
| 村民 | 听发言、找矛盾、站边、投票 |
| 白狼王 | 伪装、找时机自爆或带走关键神 |

#### 3.14.8 玩家个性差异

不同的 Agent 可以有不同的风格：

- **P1：谨慎型** — 少下死结论
- **P2：强势型** — 喜欢带队
- **P3：摇摆型** — 容易被说服
- **P4：逻辑型** — 重视投票链

#### 3.14.9 可扩展性

系统需要注意后续扩展性，代码优雅简洁，模块解耦，方便后续 Agent 玩家策略优化。

---

## 4. UI 层

UI 层目标是让三层架构的能力可视可交互，核心回答三个问题：

1. **这局狼人杀发生了什么？** — 对局观战视图
2. **每个 Agent 为什么这么决策？** — Agent 决策解释视图
3. **不同 Agent / skill 版本谁更强，证据是什么？** — 评测与版本对战视图

### 4.1 架构概览

UI 层独立放在 `ui/` 下，不进入规则层。

```text
ui/
  backend/
    app.py              # FastAPI 应用
    game_runner.py       # GameManager（启动/管理/订阅游戏）
  frontend/
    src/
      App.tsx            # 主应用组件
      api.ts             # API 客户端
      types.ts           # TypeScript 类型定义
      components/        # UI 组件
```

**后端栈：** FastAPI + SSE 推送  
**前端栈：** React + Vite + Tailwind CSS + shadcn/ui 风格组件

### 4.2 后端接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/games` | 启动新游戏 |
| `GET` | `/api/games` | 列出当前和历史游戏 |
| `GET` | `/api/games/{game_id}` | 游戏快照 |
| `GET` | `/api/games/{game_id}/events` | SSE 实时事件流 |
| `GET` | `/api/games/{game_id}/review` | 复盘评测报告 |
| `GET` | `/api/games/{game_id}/archive` | Agent 完整决策存档 |
| `GET` | `/api/leaderboards` | 版本对战排行榜 |

**GameManager 核心流程：**

```
POST /api/games
  → 生成 roles
  → 创建 AgentDecisionRecorder + AgentTraceRecorder
  → create_v2_agents(roles, decision_recorder, trace_recorder)
  → GameEngine(...).run_until_finished()
  → 写 game log (.jsonl / .txt)
  → 写 agent decision log (logs/gameX/agent_decisions.jsonl)
  → 写 archive (logs/gameX/archive.json)
  → 返回 game_id
```

**SSE 事件格式：**

```text
event: message
data: {"kind": "log", "payload": {...}}

event: message
data: {"kind": "done", "payload": {...snapshot}}

event: message
data: {"kind": "error", "payload": {"message": "..."}}
```

### 4.3 前端

**启动开发服务器：**

```bash
cd ui/frontend
npm install
npm run dev
```

默认访问 `http://127.0.0.1:5173`，`/api` 代理到 `http://127.0.0.1:8000`。

**启动后端：**

```bash
uv run uvicorn ui.backend.app:app --reload --host 127.0.0.1 --port 8000
```

### 4.4 补齐计划

以下为 UI 层补齐计划，按优先级排列。

### 4.5 P0：接入 Agent V2

**目标：** 后端启动游戏时使用 `agent` 模块，而不是旧 Agent。

**后端改造：** 使用 `agent.runtime.factory.create_v2_agents` 和 `agent.observability` 替换旧导入。

**暴露的 v2 字段：**

`DecisionRecord` 字段：`player_id`、`role`、`action_type`、`candidates`、`selected_target`、`selected_choice`、`public_text`、`private_reasoning`、`confidence`、`selected_skill`、`memory_refs`、`belief_snapshot`、`memory_summary`、`raw_output`、`source`、`errors`、`policy_adjustments`

`DecisionArchive` 额外字段（通过 archive.json）：`observation_summary`、`memory_context`、`belief_context`、`selected_skills`、`prompt_messages`、`tot_candidates`、`tot_judge_reason`

**验收标准：**

- 后端不再依赖旧 `playeragent`
- 后端能启动一局 Agent v2 对局
- 前端能看到 v2 决策记录
- ToT 决策显示 `source = "tot"`
- policy 修正显示 `source = "policy_adjusted"`

### 4.6 P1：Agent 决策详情面板

在对局页面增加"决策详情"面板，分为多个 tab：

| Tab | 内容 |
|-----|------|
| **Overview** | 玩家编号、身份、阶段、行动类型、候选目标、最终选择、公开发言、私有推理、confidence、source |
| **Observation** | 当前天数、阶段、存活/死亡玩家、警长、可选目标、信息隔离验证 |
| **Memory** | 短期记忆、现场笔记、玩家画像、票型模式、历史动作 |
| **Belief** | 每位玩家的狼人/好人/神职概率、claimed role、evidence，以表格/概率条/关系图展示 |
| **Skills** | 注入的 markdown skill（通用规则、输出格式、角色 skill、action 匹配 skill） |
| **Prompt** | 最终发送的 prompt messages，默认折叠，区分 system/user |
| **ToT** | Tree of Thought 候选方案，包括 action、public_text、private_reasoning、expected_gain、risk、judge_reason |
| **Policy** | 是否修正、修正原因、修正前后目标、fallback 原因 |
| **Raw** | 原始模型输出、解析结果、错误信息 |

**验收标准：**

- 能点开任意决策查看详情
- 能看到 skill、belief、memory、ToT、policy
- private reasoning 不进入公共事件流，只在决策详情中展示
- ToT 候选可展开查看

### 4.7 P1：对局复盘页

将 `review_enhanced` 的结构化结果在前端展示。

**后端接口：** `GET /api/games/{game_id}/review`

返回内容：`game_id`、`winner`、`team_scores`、`player_reviews`、`turning_points`、`mistakes`、`skill_reviews`

**前端展示：**

- 胜利方标识
- 阵营平均分
- 玩家多维评分表（发言 / 投票 / 技能拆分）
- 关键失误列表
- 关键转折点时间线
- skill 表现统计
- 建议

**验收标准：**

- 已完成对局可以打开复盘页
- 每个玩家有多维评分
- 能定位至少一个关键失误或转折点
- UI 能把复盘和原始决策链接起来

### 4.8 P2：Leaderboard / Version Battle

展示不同 Agent / skill / prompt 版本效果对比。

**后端接口：**

- `GET /api/leaderboards` — 排行榜
- 读取 `runs/version_battle/`、`logs/version_battle/` 或 `data/version_battle/` 中的 `leaderboard.json`、`leaderboard.md`、`version_battle_result.json`

**展示指标：**

| 指标 | 说明 |
|------|------|
| version | 版本名称 |
| games | 对局数 |
| werewolf win rate | 狼人胜率 |
| villager win rate | 好人胜率 |
| avg review score | 平均复盘评分 |
| avg speech / vote / skill score | 发言/投票/技能分 |
| fallback rate | fallback 率 |
| policy adjusted rate | 策略修正率 |
| avg confidence | 平均置信度 |

**可视化：** 排名表、胜率柱状图、评分折线图、fallback 率警示色、点击版本查看对应游戏列表。

**验收标准：**

- UI 能展示至少一次 version battle 结果
- 能比较 baseline 和 ToT 版本
- 能看到多个指标，而不是只看胜负

### 4.9 P2：对局时间线增强

- 夜晚 / 白天分段
- 阶段图标
- 死亡事件高亮
- 投票结果高亮
- 警长 / 神职技能事件高亮
- 身份揭晓
- 按玩家 / action type 筛选
- 点击事件跳转相关决策

**验收标准：**

- 一局完整对局可以按时间线顺畅回放
- 关键事件不用读原始日志也能看懂
- 决策记录能和事件关联

### 4.10 P3：人机混战

允许部分座位由真人玩家控制。

**后端：** `POST /api/games` body 增加 `human_players: [1, 3]`。当规则层向 human player 请求行动时，后端挂起等待，前端通过 SSE 收到 action request，用户提交后游戏继续。

**前端：** 展示当前轮到谁、可选目标、可选 choice、发言输入框、投票/技能按钮。

**风险：** 异步等待和状态管理工程量明显大于观战和复盘，建议在 P0-P2 完成后进行。

### 4.11 推荐实现顺序

| Phase | 内容 | 优先级 |
|-------|------|--------|
| Phase 1 | 后端接入 Agent V2 | P0 |
| Phase 2 | 补充决策详情数据（archive） | P1 |
| Phase 3 | 前端决策详情面板 | P1 |
| Phase 4 | 复盘页 | P1 |
| Phase 5 | Leaderboard 页面 | P2 |
| Phase 6 | 人机混战 | P3 |

**最小可交付版本：** Phase 1-4，足够支撑答辩展示（观战 + 解释 Agent 决策 + 复盘 Agent 表现）。

### 4.12 答辩展示路径

推荐答辩时按此路径演示：

1. 打开 UI，启动一局 AI 狼人杀
2. 展示时间线：夜晚、白天、投票、死亡
3. 点击某次关键投票
4. 展示 Agent 当时看到的 observation
5. 展示注入的 skills 和 long memory
6. 展示 belief：谁最像狼
7. 展示 ToT：三个候选方案和 judge reason
8. 展示最终 public_text / private_reasoning
9. 打开复盘页：玩家评分、失误、转折点
10. 打开 leaderboard：baseline vs ToT / evolved skill

# Agent v2 差距分析与改进设计

本文档用于对比当前 `agent/` 实现、`docs/ideas.md` 想法池和 `docs/agent_v2_design.md` 设计目标，明确当前不足与后续改进方向。

## 1. 当前结论

当前 `agent_v2` 已经完成了最关键的基础工作：

- 与规则层兼容。
- 保持 `ActionRequest -> ActionResponse` 协议。
- 不侵入 `engine/werewolf` 规则层。
- 实现了图式 runtime 流水线。
- 拆分出 observe、memory、belief、skill router、prompt、llm、parse、policy、log 节点。
- 有基础测试覆盖。

但当前版本更接近：

```text
旧 Agent 能力的图式封装版
```

而不是完整的新 Agent 层。

主要原因是当前 `agent` 大量复用了旧 `playeragent` 中的 memory、belief、strategy、prompt、parser、policy 和 decision log。它具备了 Agent v2 的外壳和兼容边界，但核心智能能力还没有完全按 v2 文档重建。

## 2. 已实现内容

### 2.1 规则层兼容

当前 `AgentV2Runtime` 仍然实现：

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

这是正确的。

规则层仍然只看到：

- `ActionRequest`
- `ActionResponse`

Agent 内部的记忆、信念、Prompt、模型调用、解析、修正、日志都没有要求规则层额外配合。

### 2.2 图式 Runtime

当前 runtime 已经形成如下流程：

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

这符合 `agent_v2_design.md` 的核心方向。

### 2.3 基础节点

当前已实现：

- `observe_node`：提取结构化 observation summary。
- `memory_node`：调用 memory 构造上下文。
- `belief_node`：调用 belief 构造局势判断。
- `skill_router_node`：生成策略建议。
- `prompt_node`：构造 LLM messages。
- `llm_node`：调用模型并捕获异常。
- `parse_node`：解析模型输出。
- `policy_node`：修正或 fallback。
- `log_node`：记录 Agent 决策。

### 2.4 测试状态

当前测试通过：

```text
79 tests OK
```

说明当前改动没有破坏已有规则层、旧 Agent 和 UI 后端测试。

## 3. 主要不足

### 3.1 Agent v2 核心能力尚未真正重写

当前 `agent/runtime.py` 复用了旧实现：

- `playeragent.memory.AgentMemory`
- `playeragent.belief.BeliefState`
- `playeragent.strategies.strategy_for`
- `playeragent.prompts.build_messages`
- `playeragent.parsing`
- `playeragent.policies`
- `playeragent.decision_log`

这不是问题，但要清楚当前 v2 的主要价值是“流程重组”，不是“核心能力升级”。

后续需要逐步替换或增强：

- v2 memory
- v2 belief
- v2 strategy
- v2 prompt
- v2 parser
- v2 policy
- v2 decision log

### 3.2 Skill Router 目前偏占位

设计文档里希望 skill router 根据局势选择角色 skill，例如：

- `werewolf_fake_seer`
- `werewolf_vote_rush`
- `werewolf_deep_wolf`
- `seer_badge_flow`
- `seer_claim`
- `witch_save`
- `witch_poison`
- `hunter_shoot`
- `villager_vote_analysis`

但当前实现只是尝试读取：

```python
strategy.selected_skill
```

现有旧 strategy 并没有真正设置这个字段，因此多数情况下会退化成：

```python
ctx.selected_skill = ctx.request.action_type.value
```

这意味着当前还没有真正的“局势 skill 路由”。

#### 改进方向

新增 v2 strategy/skill 系统：

```text
agent/strategies/
  base.py
  werewolf.py
  seer.py
  witch.py
  hunter.py
  villager.py
  guard.py
  white_wolf_king.py

agent/skills/
  werewolf_fake_seer.py
  werewolf_vote_rush.py
  seer_badge_flow.py
  witch_poison.py
  villager_vote_analysis.py
```

每个 strategy 返回：

```python
SkillDecision(
    name="witch_poison",
    goal="判断是否使用毒药",
    preferred_targets=[...],
    avoid_targets=[...],
    prompt_hints=[...],
)
```

### 3.3 Prompt 仍然是旧通用 Prompt

当前 `prompt_node` 调用旧的：

```python
playeragent.prompts.build_messages
```

旧 Prompt 有基础身份差异，但还没有达到 v2 设计目标。

当前不足：

- 每个角色没有完全独立的 Prompt 模板。
- 缺少 skill 专属提示。
- 缺少 few-shot 示例。
- 缺少候选动作比较要求。
- 缺少 ToT / self-critique 提示。
- 输出字段与 v2 设计不完全一致。

当前旧 Prompt 使用：

```json
{
  "choice": "...",
  "target": 7,
  "text": "...",
  "reasoning": "...",
  "alternatives": [],
  "rejected_reasons": []
}
```

而 v2 设计倾向：

```json
{
  "choice": "...",
  "target": 7,
  "public_text": "...",
  "private_reasoning": "...",
  "confidence": 0.74,
  "alternatives": [],
  "rejected_reasons": [],
  "memory_refs": [],
  "selected_skill": "villager_vote_analysis"
}
```

#### 改进方向

先做兼容式升级：

- parser 同时兼容 `text` 和 `public_text`。
- parser 同时兼容 `reasoning` 和 `private_reasoning`。
- 新增 `confidence` 字段。
- 新增 `selected_skill` 字段。
- Prompt 明确要求输出 v2 字段。

### 3.4 记忆仍停留在短期摘要

当前 memory 主要提供：

- `public_summary`
- `memory_events`
- `private_facts`
- `self_history`
- `decisions`
- `suspicions`
- `claims_seen`

这是短期记忆的基础，但与 `ideas.md` 中的分层记忆还有差距。

缺少：

- 结构化现场笔记。
- 玩家建模表。
- 关键事件流。
- 每局结束后的经验卡片。
- 中期记忆。
- 长期 dream / consolidate。
- 按角色划分经验池。
- 完整对局归档用于复盘和训练。

#### 改进方向

先做最小可用分层记忆：

```text
短期记忆：
  当前局结构化笔记、玩家嫌疑、行为记录。

中期记忆：
  每局结束后生成 experience card。

长期记忆：
  多局后合并经验，生成角色策略原则。
```

第一阶段可以只做短期结构化现场笔记。

### 3.5 Belief 建模较浅

当前 belief 有：

- suspicion
- trust
- possible_roles
- reasons
- top_suspicions

但仍然是简单规则累加。

缺少：

- 狼人概率 / 好人概率 / 神职概率拆分。
- 玩家之间的关系图。
- 攻击、保护、跟票、切割、冲票关系。
- 票型分析。
- 站边关系。
- 阵营推断。
- 反事实分析。
- 证据权重和衰减机制。

#### 改进方向

增加 v2 belief schema：

```json
{
  "players": {
    "7": {
      "wolf_prob": 0.76,
      "villager_prob": 0.12,
      "god_prob": 0.12,
      "claimed_role": null,
      "stance": "attacks_seer",
      "evidence": [
        {
          "type": "vote",
          "weight": 0.2,
          "description": "连续跟随2号投票"
        }
      ]
    }
  },
  "relations": [
    {
      "source": 2,
      "target": 7,
      "type": "protects",
      "weight": 0.4
    }
  ]
}
```

### 3.6 Policy 校验不够强

当前 policy 主要做：

- 非法 target fallback。
- 警长退水最后一人强制 stay。
- 无 response 时 fallback。

不足：

- 没有完整校验每个 action 的合法 choice。
- 没有区分可修复错误和必须 fallback 的错误。
- 没有记录具体修正类型。
- 没有充分利用 belief 做 fallback 目标选择。

例如应该校验：

- `SHERIFF_RUN` 只能是 `run` 或 `pass`。
- `SHERIFF_WITHDRAW` 只能是 `withdraw` 或 `stay`。
- `SPEECH_ORDER` 只能是 `forward` 或 `reverse`。
- `WITCH_ACT` 只能是 `save`、`poison` 或 `none`。
- `WHITE_WOLF_EXPLODE` 不自爆时必须是 `pass`。
- `SHERIFF_BADGE` 只能是 `transfer` 或 `destroy`。

#### 改进方向

实现 v2 policy validator：

```python
def validate_response(request, response) -> ValidationResult:
    ...

def repair_response(request, response, belief_context) -> ActionResponse:
    ...
```

并记录：

- `source = "llm"`
- `source = "policy_adjusted"`
- `source = "fallback"`
- `policy_adjustments = [...]`

### 3.7 决策日志字段不完整

当前 `log_node` 已经能写 `DecisionRecord`，但字段仍然偏 v1。

缺少：

- `selected_skill`
- `confidence`
- `raw_output`
- `errors`
- `policy_adjustments`
- `prompt_version`
- `strategy_version`
- `model_name`
- `memory_refs`
- `used_nodes`

当前 `source` 判断也过于粗糙：

```python
source = "fallback" if ctx.errors else "llm"
```

这会把 policy 修正、parse 部分失败、LLM 调用异常都混在一起。

#### 改进方向

扩展 v2 决策日志 schema：

```json
{
  "player_id": 7,
  "role": "witch",
  "day": 2,
  "phase": "night",
  "action_type": "witch_act",
  "selected_skill": "witch_poison",
  "selected_target": 3,
  "selected_choice": "poison",
  "public_text": "",
  "private_reasoning": "...",
  "confidence": 0.71,
  "alternatives": [2, 9],
  "rejected_reasons": [],
  "belief_snapshot": {},
  "memory_summary": [],
  "raw_output": "...",
  "errors": [],
  "policy_adjustments": [],
  "source": "policy_adjusted"
}
```

### 3.8 DecisionRecord 没有写回 memory

当前 runtime 最后执行：

```python
self.memory.remember_action(request, ctx.response, None)
```

这里没有把 `log_node` 创建的 decision record 传回 memory。

结果：

- memory 的 `decision_history` 不会记录 v2 的私有推理。
- 后续 Prompt 中的“近期私有决策理由”不完整。

#### 改进方向

让 `log_node` 把 decision record 存入 `ctx.decision_record`，然后 runtime 执行：

```python
self.memory.remember_action(request, ctx.response, ctx.decision_record)
```

### 3.9 ToT / GoT / Self-Critique 尚未实现

`ideas.md` 中提到的强推理还没有落地：

- Tree of Thoughts
- Graph of Thoughts
- 多候选动作推演
- self-critique
- 关键动作二次确认
- 低置信度重试

当前仍然是：

```text
单次 Prompt → 单次 LLM 输出 → parse → policy
```

#### 改进方向

不要全局启用强推理，优先只在关键行动启用：

- 女巫毒人
- 猎人开枪
- 预言家跳身份
- 白狼王自爆
- 放逐投票
- PK 投票

增加可选节点：

```text
candidate_node
critique_node
tot_node
got_node
```

### 3.10 赛后复盘评测尚未实现

评分标准里最重要的进阶方向之一是“评测 + 复盘”。

当前还没有：

- 多维评分
- 发言质量评分
- 投票质量评分
- 技能质量评分
- 关键失误定位
- bad case 分析
- 反事实推演
- 结构化报告
- Leaderboard
- 多版本 Agent 对比

这是后续最值得做的加分项。

## 4. 建议优先级

### P0：保证 Agent v2 自身闭环质量

优先修这些，因为它们影响稳定性和日志可信度。

1. 强化 `policy_node`。
2. 统一 v2 输出字段。
3. 扩展 `AgentContext`，增加：
   - `confidence`
   - `policy_adjustments`
   - `decision_record`
   - `source`
4. 修正 `source` 标记。
5. 将 decision record 写回 memory。

### P1：做出真正的角色差异

1. 实现 v2 skill router。
2. 实现至少 5 个角色的明确 skill：
   - 狼人
   - 预言家
   - 女巫
   - 猎人
   - 村民
3. Prompt 根据 skill 注入不同策略。
4. 决策日志记录 `selected_skill`。

### P2：增强记忆与 Belief

1. 增加结构化现场笔记。
2. 增加玩家建模。
3. 增加票型分析。
4. 增加关系图。
5. belief 输出 `wolf_prob / good_prob / god_prob`。

### P3：实现复盘评测

1. 赛后读取游戏日志和 Agent 日志。
2. 生成结构化复盘报告。
3. 标记关键失误。
4. 给每个 Agent 生成决策质量分。
5. 支持多版本对比。

### P4：强推理与 LangGraph

1. 关键节点引入 ToT。
2. 低置信度时 self-critique。
3. 玩家关系图 GoT。
4. 如时间允许，再迁移到 LangGraph。

## 5. 推荐下一步任务拆分

### 任务 1：完善 v2 决策 schema

目标：

- parser 兼容 `public_text/private_reasoning/confidence`。
- `AgentContext` 保存结构化字段。
- 日志输出完整 v2 字段。

### 任务 2：强化 policy

目标：

- 每个 `ActionType` 都有 choice/target 校验。
- policy 能区分 repair 和 fallback。
- 日志中记录修正原因。

### 任务 3：真正实现 skill router

目标：

- 每个角色至少 2 到 3 个 skill。
- 当前行动能映射到明确 skill。
- Prompt 和日志都能看到 skill 名称。

### 任务 4：增加短期结构化记忆

目标：

- 维护本局玩家画像。
- 维护关键事件流。
- 维护当前发言/投票焦点。

### 任务 5：实现基础复盘报告

目标：

- 一局结束后输出 markdown/json 报告。
- 包含胜负、关键节点、投票准确率、技能命中、明显失误。

## 6. 答辩表述建议

当前版本可以这样讲：

```text
Agent v2 已经完成规则兼容和图式决策链重构。我们把观察、记忆、信念、策略路由、Prompt、模型调用、解析、策略修正和日志拆成独立节点，为后续迁移 LangGraph、引入 ToT 和复盘评测打下基础。
```

但如果想冲高分，需要进一步做到：

```text
在 v2 的图式 runtime 上，我们实现了角色 skill 路由、结构化信念建模、强 policy 校验、可审计决策日志和赛后复盘评分。系统不仅能玩完一局，还能解释每个 Agent 为什么这么做，并定位 bad case。
```

## 7. 总结

当前 `agent_v2` 的方向是正确的，但还处在第一阶段。

它已经完成：

- 兼容规则层。
- 图式 runtime。
- 基础节点。
- 基础测试。

它还缺少：

- 真正的 v2 skill。
- 更强的角色差异。
- 更完整的结构化决策 schema。
- 更严格的 policy。
- 更丰富的日志。
- 分层记忆。
- 深度 belief。
- ToT / GoT。
- 赛后复盘评测。

下一步不要急着上 LangGraph。更应该先把 v2 的节点能力做实，尤其是：

```text
policy → decision schema → skill router → role strategy → review
```

这条路线最贴合评分标准，也最容易形成答辩亮点。


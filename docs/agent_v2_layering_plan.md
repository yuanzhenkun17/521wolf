# Agent V2 分层重构方案

本文档记录 `agent` 的目标分层结构。核心目标是让 Agent 层项目结构更清晰，便于继续实现 ToT、长期记忆、skill 进化、复盘评测和版本对战。

本方案只讨论 Agent 层，不修改狼人杀规则层。

## 1. 重构原则

### 1.1 只兼容规则层

`agent` 的边界应该是：

```text
输入：werewolf.models.ActionRequest
输出：werewolf.models.ActionResponse
```

也就是说，Agent v2 只需要兼容当前规则层接口，不需要兼容旧 `playeragent` 实现。

### 1.2 去掉 adapters 层

之前设计中有 `adapters/`，用于兼容旧 agent 或旧模型接口。现在不再需要。

本项目中不再保留：

```text
agent/adapters/
```

也不再把“兼容旧 playeragent”作为设计目标。

### 1.3 v2 不依赖旧 playeragent 包

目标状态下，`agent` 不应该再依赖旧的 `playeragent` 内部模块。

需要逐步移除的依赖方向：

```text
agent -> playeragent.memory
agent -> playeragent.belief
agent -> playeragent.strategies
agent -> playeragent.prompts
agent -> playeragent.parsing
agent -> playeragent.policies
agent -> playeragent.decision
agent -> playeragent.decision_log
agent -> playeragent.adapters
```

允许保留的依赖：

```text
agent -> werewolf.models
agent -> werewolf.actions
```

也就是只依赖规则层公开数据结构。

### 1.4 分层要服务答辩表达

分层结构不只是为了代码整洁，也要方便答辩时讲清楚：

- Agent 是怎么做一次决策的。
- 信息隔离在哪里保证。
- 记忆、belief、skill、prompt、ToT 分别在哪里。
- 复盘评测和自进化闭环在哪里。

## 2. 目标目录结构

推荐最终结构如下：

```text
agent/
  __init__.py

  runtime/
    __init__.py
    agent.py
    context.py
    pipeline.py
    factory.py
    model.py

  nodes/
    __init__.py
    observe.py
    memory.py
    belief.py
    skill_router.py
    prompt.py
    reasoning.py
    llm.py
    parse.py
    policy.py
    log.py

  cognition/
    __init__.py
    memory.py
    belief.py
    experience.py
    long_memory.py

  skills/
    common/
      game_rules.md
      output_schema.md
    villager/
    werewolf/
    seer/
    witch/
    hunter/
    guard/

  skill_system/
    __init__.py
    loader.py
    router.py
    evolution.py

  reasoning/
    __init__.py
    schemas.py
    tot.py
    judge.py

  prompts/
    __init__.py
    base.py
    formatting.py
    tot.py
    review.py

  observability/
    __init__.py
    archive.py
    decision_log.py
    serializers.py

  evaluation/
    __init__.py
    review.py
    review_enhanced.py
    leaderboard.py
    selfplay.py
    version_battle.py

  config/
    __init__.py
    defaults.py
```

## 3. 各层职责

### 3.1 runtime

`runtime/` 是 Agent 决策主入口。

职责：

- 接收规则层的 `ActionRequest`。
- 组织一次完整 Agent 决策流程。
- 返回规则层可执行的 `ActionResponse`。
- 管理模型调用接口。
- 创建 Agent 实例。

建议文件：

```text
runtime/agent.py
runtime/context.py
runtime/pipeline.py
runtime/factory.py
runtime/model.py
```

说明：

- `agent.py` 放 `AgentV2Runtime`。
- `context.py` 放 `AgentContext`。
- `pipeline.py` 放节点编排。
- `factory.py` 放 `LLMPlayerAgentV2`、批量创建 Agent 的函数。
- `model.py` 放 v2 自己的模型协议与 LLM client，不再依赖 `playeragent.adapters`。

目标依赖：

```text
runtime
  -> nodes
  -> cognition
  -> observability
  -> werewolf.models
```

### 3.2 nodes

`nodes/` 是一次决策的流水线节点。

职责：

- 每个节点只做一个明确步骤。
- 节点之间通过 `AgentContext` 传递状态。
- 节点不直接操作全局状态。

当前节点链路：

```text
observe
  -> memory
  -> belief
  -> skill_router
  -> prompt
  -> reasoning
  -> llm
  -> parse
  -> policy
  -> log
```

建议职责：

| 节点 | 职责 |
|---|---|
| `observe.py` | 从 `ActionRequest` 提取可见信息 |
| `memory.py` | 更新和读取局内记忆 |
| `belief.py` | 更新玩家画像和身份概率 |
| `skill_router.py` | 调用 skill_system 选择当前要注入的 skill |
| `prompt.py` | 构造普通决策 prompt |
| `reasoning.py` | 判断是否启用 ToT / GoT |
| `llm.py` | 调用模型 |
| `parse.py` | 解析模型输出 |
| `policy.py` | 合法性校验和兜底修正 |
| `log.py` | 写决策记录 |

### 3.3 cognition

`cognition/` 是 Agent 的认知状态层。

职责：

- 局内短期记忆。
- 玩家画像和信念状态。
- 单局结束后的经验卡片。
- 多局聚合后的长期记忆。

建议文件：

```text
cognition/memory.py
cognition/belief.py
cognition/experience.py
cognition/long_memory.py
```

对应关系：

| 文件 | 内容 |
|---|---|
| `memory.py` | `AgentMemoryV2`，维护当前局现场笔记 |
| `belief.py` | `BeliefStateV2`，维护玩家身份概率和关系 |
| `experience.py` | 中期记忆，从一局完整对局中提取经验卡 |
| `long_memory.py` | 长期记忆，从多局经验卡聚合角色策略 |

### 3.4 skills

`skills/` 是可编辑策略资产层。

职责：

- 以 markdown 形式保存通用规则和角色策略。
- 非代码同学也能读懂和修改。
- 不存放 Python 逻辑。

目录：

```text
skills/
  common/
    game_rules.md
    output_schema.md
  villager/
  werewolf/
  seer/
  witch/
  hunter/
  guard/
```

设计原则：

- `common/game_rules.md` 是通用规则，所有角色都注入。
- `common/output_schema.md` 是统一输出约束，所有角色都注入。
- 角色 skill 只按当前角色注入。
- 不再使用 priority，避免无必要复杂度。
- 每个 skill 通过 front matter 声明适用角色、行动类型和 requires 条件。

### 3.5 skill_system

`skill_system/` 是 skill 加载、选择和进化层。

职责：

- 读取 markdown skill。
- 根据角色、行动、metadata 选择 skill。
- 后续根据复盘报告生成 skill 修改建议。
- 后续生成候选 skill 版本，用于 A/B 对战。

建议文件：

```text
skill_system/loader.py
skill_system/router.py
skill_system/evolution.py
```

说明：

- `loader.py` 只负责解析 markdown。
- `router.py` 只负责选择当前 action 要注入的 skill。
- `evolution.py` 后续负责从 review / experience / long memory 生成 skill 修改建议。

### 3.6 reasoning

`reasoning/` 是强推理增强层。

职责：

- ToT 多候选决策。
- 后续 GoT / self-critique。
- 候选生成、候选评审、最终选择。

建议文件：

```text
reasoning/schemas.py
reasoning/tot.py
reasoning/judge.py
```

说明：

- `schemas.py` 放 `ToTCandidate`、`ToTResult` 等数据结构。
- `tot.py` 放 ToT 主流程。
- `judge.py` 后续可拆出候选评审逻辑。

### 3.7 prompts

`prompts/` 是 prompt 构造层。

职责：

- 普通决策 prompt。
- ToT prompt。
- review prompt。
- 记忆、field notes、skill、长期经验的格式化。

建议文件：

```text
prompts/base.py
prompts/formatting.py
prompts/tot.py
prompts/review.py
```

设计原则：

- prompt 拼接逻辑不要散落在 runtime 或 nodes 中。
- 所有输出格式约束集中管理。
- ToT prompt 必须复用普通 prompt 的规则、skill 和记忆上下文。

### 3.8 observability

`observability/` 是可观测性层。

职责：

- 决策归档。
- 对局归档。
- 结构化日志。
- 序列化工具。

建议文件：

```text
observability/archive.py
observability/decision_log.py
observability/serializers.py
```

说明：

- `archive.py` 放 `DecisionArchive`、`GameArchive`、`AgentTraceRecorder`。
- `decision_log.py` 放 v2 自己的轻量决策记录，不再依赖旧 `playeragent.decision_log`。
- `serializers.py` 放通用 JSON 序列化辅助函数。

### 3.9 evaluation

`evaluation/` 是评测与自博弈层。

职责：

- 对局复盘。
- 多维评分。
- 失误定位。
- 自博弈。
- 多版本对战。
- Leaderboard。

建议文件：

```text
evaluation/review.py
evaluation/review_enhanced.py
evaluation/leaderboard.py
evaluation/selfplay.py
evaluation/version_battle.py
```

说明：

- `review.py` 保留基础复盘。
- `review_enhanced.py` 做多维评分、关键失误和转折点。
- `leaderboard.py` 聚合多版本结果。
- `selfplay.py` 跑多局 AI 自博弈。
- `version_battle.py` 对比不同 skill_dir / agent version。

### 3.10 config

`config/` 是默认配置层。

职责：

- 默认模型配置。
- 默认路径。
- 默认 selfplay 参数。
- 默认 ToT 开关。

建议文件：

```text
config/defaults.py
```

## 4. 目标依赖方向

理想依赖方向如下：

```text
runtime
  -> nodes
  -> cognition
  -> skill_system
  -> reasoning
  -> prompts
  -> observability
  -> werewolf.models

nodes
  -> cognition
  -> skill_system
  -> reasoning
  -> prompts
  -> observability

evaluation
  -> observability
  -> cognition
  -> runtime
  -> skill_system

skills
  -> no python dependency
```

禁止方向：

```text
cognition -> runtime
skills -> python code
prompts -> runtime
observability -> runtime
agent -> playeragent
```

## 5. 决策链路

重构后的运行链路可以表达为：

```text
规则层 ActionRequest
  -> runtime.agent.AgentV2Runtime
  -> runtime.pipeline
  -> nodes.observe
  -> cognition.memory
  -> cognition.belief
  -> skill_system.router + skills/*.md
  -> prompts.base
  -> reasoning.tot
  -> runtime.model
  -> nodes.parse
  -> nodes.policy
  -> observability.archive
  -> ActionResponse 返回规则层
```

这条链路清楚表达了：

- 规则层只给 Agent 可见信息。
- Agent 内部维护记忆和 belief。
- 当前角色 skill 被按需注入。
- 关键动作可以启用 ToT。
- 输出经过 parse 和 policy 校验。
- 所有关键输入输出会被 archive 记录。

## 6. 赛后学习链路

赛后链路可以表达为：

```text
observability.archive
  -> evaluation.review_enhanced
  -> cognition.experience
  -> cognition.long_memory
  -> skill_system.evolution
  -> data/skill_versions
  -> evaluation.version_battle
  -> evaluation.leaderboard
```

含义：

- 每局对局被完整归档。
- 复盘模块定位关键失误和评分。
- 经验模块生成按角色划分的经验卡。
- 长期记忆模块聚合跨局策略。
- skill evolution 后续生成候选 markdown skill。
- version battle 用固定 seed 对比版本效果。
- leaderboard 输出可展示结果。

## 7. 迁移计划

### Phase 1：建立目录骨架

新增目录：

```text
runtime/
cognition/
skill_system/
reasoning/
prompts/
observability/
evaluation/
config/
```

先不改业务逻辑，只建立结构。

### Phase 2：移动低风险模块

优先移动纯数据和评测模块：

```text
archive.py -> observability/archive.py
leaderboard.py -> evaluation/leaderboard.py
review.py -> evaluation/review.py
review_enhanced.py -> evaluation/review_enhanced.py
selfplay.py -> evaluation/selfplay.py
version_battle.py -> evaluation/version_battle.py
experience.py -> cognition/experience.py
long_memory.py -> cognition/long_memory.py
```

每移动一批跑一次全量测试。

### Phase 3：移动 skill 系统

移动：

```text
skill_loader.py -> skill_system/loader.py
skill_router.py -> skill_system/router.py
```

然后更新 nodes 中的 import。

### Phase 4：移动 prompt 系统

拆分：

```text
prompts.py -> prompts/base.py + prompts/formatting.py
```

后续 ToT prompt 可以移动到：

```text
prompts/tot.py
```

### Phase 5：移动 cognition 主模块

移动：

```text
memory_v2.py -> cognition/memory.py
belief_v2.py -> cognition/belief.py
```

同时移除对旧 `playeragent.memory` 和 `playeragent.belief` 的 fallback。

### Phase 6：移动 runtime

移动：

```text
runtime.py -> runtime/agent.py
context.py -> runtime/context.py
factory.py -> runtime/factory.py
```

并新增：

```text
runtime/pipeline.py
runtime/model.py
```

`pipeline.py` 负责统一编排节点，避免 `AgentV2Runtime.act()` 太长。

### Phase 7：移除旧 playeragent 依赖

逐步替换：

```text
playeragent.adapters.ModelAdapter -> agent.runtime.model.ModelAdapter
playeragent.decision.DecisionRecord -> agent.observability.decision_log.DecisionRecord
playeragent.decision_log.AgentDecisionRecorder -> agent.observability.decision_log.AgentDecisionRecorder
playeragent.prompts.action_instruction -> agent.prompts.base.action_instruction
playeragent.prompts.strategy_instruction -> agent.prompts.base.strategy_instruction
playeragent.parsing.load_json_object -> agent.prompts/parsing utility
```

最终用 `rg "from playeragent"` 确认 `agent` 内不再依赖旧包。

## 8. 是否保留旧路径 shim

如果当前测试和其他模块大量使用旧路径，例如：

```python
from agent.runtime import AgentV2Runtime
```

可以短期保留 shim：

```python
# agent/runtime.py
from agent.runtime.agent import AgentV2Runtime

__all__ = ["AgentV2Runtime"]
```

但是如果目标是让结构彻底清晰，最终建议删除平铺旧文件，只保留分层后的 import。

推荐策略：

1. 迁移初期保留 shim，降低改动风险。
2. 全部模块改完后，统一替换测试和调用方 import。
3. 最后删除 shim。

## 9. 最终验收标准

重构完成后，应该满足：

- `agent` 目录结构按层组织。
- `agent` 不再依赖旧 `playeragent` 包。
- `adapters/` 不存在。
- markdown skills 仍在 `skills/` 下。
- 规则层接口不变：输入 `ActionRequest`，输出 `ActionResponse`。
- ToT、长期记忆、skill 注入、复盘和版本对战都能正常运行。
- 全量测试通过。

验证命令：

```bash
uv run python -m unittest discover -s tests -v
rg "from playeragent|import playeragent" agent
```

第二条命令最终应该没有结果，或只剩明确允许的迁移期 shim。

## 10. 答辩表达

答辩时可以这样介绍 Agent 层：

```text
我们的 Agent 层按职责分成 runtime、nodes、cognition、skills、skill_system、reasoning、prompts、observability 和 evaluation。

runtime 负责接入规则层并编排决策流程；
nodes 负责一次决策中的每个步骤；
cognition 维护短期记忆、belief、中期经验和长期记忆；
skills 是 markdown 策略资产；
skill_system 负责按角色和行动注入 skill；
reasoning 提供 ToT 多候选决策；
observability 记录完整决策轨迹；
evaluation 负责复盘、自博弈和版本对战。

规则层只看到 ActionRequest 和 ActionResponse，Agent 内部的记忆、推理和复盘都在 v2 层完成。
```

这个表达能突出：

- Agent 层独立清晰。
- 与规则层边界明确。
- 信息隔离可控。
- 策略资产可编辑。
- 决策过程可追溯。
- 后续自进化和评测有明确落点。

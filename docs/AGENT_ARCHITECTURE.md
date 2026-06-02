# 521wolf Agent 架构

## 概览

Agent 层是狼人杀 AI 的决策层。它只接收规则层的 `ActionRequest`，经过一条 step pipeline 生成合法 `ActionResponse`，不直接读写规则层状态。

## 目录结构

```text
agent/
  api/                # AgentRuntime、LLMPlayerAgent、create_agents
  core/               # AgentContext、AgentMemory、BeliefState
  decision/steps/     # 决策流水线 step
  knowledge/          # prompt 构造和 Markdown skill 加载/路由
  reasoning/          # Tree-of-Thought / Graph-of-Thought 推理内核
  learning/           # selfplay、review、metrics、leaderboard
  learning/evolution/ # skill 自进化、版本存储、battle、promote/reject
  infrastructure/     # LLM client、decision log、archive、tracing
  common/             # 通用工具函数
```

## 决策链路

```text
ActionRequest
  -> remember_step
  -> update_belief_step
  -> select_skills_step
  -> build_prompt_step
  -> reason_with_graph_step
  -> reason_with_tree_step
  -> call_model_step
  -> parse_output_step
  -> enforce_policy_step
  -> record_decision_step
  -> ActionResponse
```

GoT/ToT 只在关键动作上接管决策。成功时会生成结构化输出并跳过普通 `call_model_step`；失败时回到普通 LLM 路径。

## 核心模块

- `agent.api.runtime`: 编排 step pipeline，并提供 `LLMPlayerAgent` 适配规则层玩家协议。
- `agent.core.context`: pipeline 内部共享状态，只在 Agent 层流转。
- `agent.core.memory`: 短期记忆和结构化现场笔记。
- `agent.core.belief`: 玩家主观局势判断。
- `agent.knowledge.skills`: 加载并筛选当前角色、当前动作可用的 Markdown skill。
- `agent.knowledge.prompts`: 构造 system/user messages，并内建输出 schema。
- `agent.infrastructure.decision_log`: 轻量决策日志。
- `agent.infrastructure.archive`: 完整决策上下文归档。
- `agent.infrastructure.tracing`: 可选 Langfuse 追踪门面，未配置 key 时自动 no-op。

## 可观测性

Agent 输出两类数据：

- `logs/gameX/agent_decisions.jsonl`: 轻量决策记录，适合 UI 列表和复盘统计。
- `logs/gameX/archive.json`: 完整上下文，包括 observation、memory、belief、skills、prompt、raw output、policy adjustment、ToT/GoT 推理细节。

Langfuse 是可选能力。只有同时配置 `LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY`，且未显式关闭 `LANGFUSE_TRACING_ENABLED` 时才启用；否则所有 tracing hook 都是 no-op。

## 设计原则

1. Step 职责单一：每个 step 只读写 `AgentContext` 中自己负责的字段。
2. 规则边界清楚：Agent 不直接修改 `GameState`。
3. Prompt 与 skill 分层：通用规则和输出 schema 在 prompt 中，角色策略在 Markdown skill 中。
4. Policy 必须兜底：任何模型异常或非法输出都要返回合法 `ActionResponse`。
5. Learning 独立于决策主链：selfplay、review、evolution 不污染 `api/core/decision` 的边界。

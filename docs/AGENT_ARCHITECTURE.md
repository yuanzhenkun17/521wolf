# 521wolf Agent 架构

## 概览

Agent 层是狼人杀 AI 的决策层。它只接收规则层的 `ActionRequest`，经过一条 step pipeline 生成合法 `ActionResponse`，不直接读写规则层状态。

## 目录结构

```text
agent/
  api/                # AgentRuntime、create_agents（factory.py）
  core/               # AgentContext、AgentMemory（含 FieldNotes、PlayerProfile）
  decision/steps/     # 决策流水线 step
  knowledge/
    prompts/          # system/user message 构造、输出 schema
    skills/           # Markdown skill 加载（loader.py）与路由（router.py）
  learning/           # selfplay、review、game_analysis、calibration、statistics
  learning/evolution/ # skill 自进化、版本存储、battle、promote/reject、consolidation
  infrastructure/     # LLM client、decision log、archive、tracing
  common/             # 通用工具函数（paths、time、json、coercion、callbacks、winner）
```

## 决策链路

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


## 核心模块

- `agent.api.runtime`: 编排 step pipeline，直接实现规则层玩家协议。
- `agent.api.factory`: 工厂函数 `create_agents`，负责创建一组 Agent 实例。
- `agent.core.context`: pipeline 内部共享状态（request、memory_context、selected_skills、messages、parsed_decision、response 等），只在 Agent 层流转。
- `agent.core.memory`: 短期记忆（`AgentMemory`）、结构化现场笔记（`FieldNotes`）、玩家行为档案（`PlayerProfile`），含阶段感知事件摘要、pinned facts、滚动摘要和过期管理。
- `agent.knowledge.skills`: 加载并筛选当前角色、当前动作可用的 Markdown skill（loader + router）。
- `agent.knowledge.prompts`: 构造 system/user messages，并内建输出 schema。
- `agent.infrastructure.decision_log`: 轻量决策日志。
- `agent.infrastructure.archive`: 完整决策上下文归档。
- `agent.infrastructure.tracing`: 可选 Langfuse 追踪门面，未配置 key 时自动 no-op。

## 可观测性

Agent 输出两类数据：

- `logs/gameX/agent_decisions.jsonl`: 轻量决策记录，适合 UI 列表和复盘统计。
- `logs/gameX/archive.json`: 完整上下文，包括 observation、memory、skills、prompt、raw output、policy adjustment。

Langfuse 是可选能力。只有同时配置 `LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY`，且未显式关闭 `LANGFUSE_TRACING_ENABLED` 时才启用；否则所有 tracing hook 都是 no-op。

## 设计原则

1. Step 职责单一：每个 step 只读写 `AgentContext` 中自己负责的字段。
2. 规则边界清楚：Agent 不直接修改 `GameState`。
3. Prompt 与 skill 分层：通用规则和输出 schema 在 prompt 中，角色策略在 Markdown skill 中。
4. Policy 必须兜底：任何模型异常或非法输出都要返回合法 `ActionResponse`。
5. Learning 独立于决策主链：selfplay、review、evolution 不污染 `api/core/decision` 的边界。

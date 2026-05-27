# Agent 层说明

本文说明当前 `agent/` 目录的职责和运行方式。旧 `playeragent/` 已删除，当前项目只有这一套 Agent 主实现。

## 边界

Agent 层只负责“玩家如何思考”，不负责修改狼人杀规则。

规则层通过统一协议调用玩家：

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

Agent 只能读取 `ActionRequest.observation` 中允许看到的信息，因此信息隔离仍由规则层负责。

## 目录结构

```text
agent/
  runtime/          # AgentContext、AgentV2Runtime、LLM client factory
  nodes/            # observe/memory/belief/skill/prompt/llm/tot/parse/policy/log
  cognition/        # 短期记忆、belief、经验卡片、长期记忆
  skills/           # Markdown skill，按 common 和 role 分组
  skill_system/     # skill front matter 解析、筛选、格式化
  reasoning/        # ToT 多候选推理
  prompts/          # prompt 构造、输出解析辅助
  observability/    # decision log、完整 archive
  evaluation/       # review、selfplay、leaderboard、version battle
```

## 决策链路

当前 runtime 是手写的图式 pipeline：

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

其中 ToT 只在关键动作上启用。ToT 成功时会生成多个候选动作并由 judge 选择，随后跳过普通 LLM 调用；ToT 失败时会回到普通 LLM 决策链路。

## 模型接入

模型入口在：

```python
agent.runtime.factory.load_llm_client()
```

配置来自 `.env` 或系统环境变量：

```env
WEREWOLF_LLM_API_KEY=your-api-key
WEREWOLF_LLM_BASE_URL=https://router.shengsuanyun.com/api/v1
WEREWOLF_LLM_MODEL=ali/qwen3.5-flash
WEREWOLF_LLM_TIMEOUT=45
WEREWOLF_LLM_TEMPERATURE=0.4
```

底层通过 OpenAI-compatible `/chat/completions` HTTP 接口调用模型。

## 可观测性

Agent 层会输出两类记录：

- `logs/gameX.agent.jsonl`：轻量决策日志，供 UI 快速展示。
- `logs/gameX.archive.json`：完整决策链路，包括 observation、memory、belief、selected skills、prompt、raw output、ToT candidates、policy adjustments。

这些数据用于 UI 展示、复盘评测、经验提取和 leaderboard。

## Skill 注入

Skill 使用 Markdown 文件维护：

```text
agent/skills/common/
agent/skills/werewolf/
agent/skills/seer/
agent/skills/witch/
agent/skills/hunter/
agent/skills/villager/
```

`common` skill 对所有角色注入；角色 skill 只在对应身份和动作条件满足时注入。

## 与 LangGraph 的关系

当前没有引入 LangGraph。现有 `nodes/` 已经按图式 runtime 组织，后续如果确实需要 checkpoint、resume 或更复杂的分支，可以把这些节点迁移到 LangGraph；但当前主线保持轻量自研 runtime。

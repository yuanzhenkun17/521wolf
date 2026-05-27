# Prompt 优化设计

> **目标：** 将每次 agent 决策的 LLM prompt 从 ~4000 tokens 降到 ~1850 tokens。手段：两阶段 skill 选择、memory 去重、schema 去重、belief 压缩。

## 问题

每次 agent 决策发送 ~4000 tokens 给 LLM。一局 12 人游戏有 ~60-90 次 LLM 调用。主要浪费：

1. **Skill 过度注入**（~1500 tokens）：所有角色匹配的 skill 全文注入，不管是否相关。`seer_counter_claim`（对跳策略）在没人对跳时也被注入。
2. **Memory 重复**（~600 tokens）：`public_summary`（引擎 JSON）和 `memory_events`（agent 文本）记录的是同一批事件。
3. **Schema 重复**（~200 tokens）：输出 JSON schema 在 `output_schema.md` skill 里写了一遍，prompt 尾部又写了一遍。
4. **Belief 噪声**（~800 tokens）：没有证据的玩家显示默认值 0.33/0.33/0.34，零信息量。

## 架构

### 组件 1：两阶段 Skill 选择

**第一阶段 — Skill 选择（新增轻量 LLM 调用，~500 tokens）：**

```
System: 你是狼人杀 AI，需要选择当前场景最相关的策略技能。
User:
当前角色: seer
当前动作: sheriff_speak
已有声明: {3: 'seer'}

可用技能:
- seer_badge_flow: 警徽流策略，通过警徽传递死后信息
- seer_claim: 预言家起跳，公布查验结果引导好人
- seer_counter_claim: 与悍跳狼对抗，证明自己是真预言家
- persona: 角色性格设定

请选择最相关的技能（JSON 数组）:
```

LLM 输出：`["seer_claim", "seer_badge_flow"]`

**第二阶段 — 正式决策：**

只注入选中 skill 的 full body，未选中的完全省略。

**实现：**

- `MarkdownSkill` 加 `description: str` 字段（从 YAML front matter 解析）
- 所有 skill `.md` 文件加 `description` 字段（1-2 句话摘要）
- `agent/skill_system/router.py` 新增 `select_skills_by_llm()` 函数
- 新增 `skill_select_node` 放在 `skill_router_node` 之前
- `skill_router_node` 改为根据 LLM 选择过滤，不再注入全部

**兜底：** 第一阶段 LLM 调用失败时，回退到当前行为（注入所有角色匹配的 skill）。

### 组件 2：Memory 去重

**改动：** prompt 中去掉 `public_summary`，只保留 `memory_events`。

**原因：** `public_summary` 来自 `observation.public_log`（游戏引擎），`memory_events` 来自 agent 自己的 `AgentMemory.events`。两者记录的是同一批公开事件。只保留 `memory_events` 可以降低与游戏引擎的耦合度——agent 与引擎只通过 `ActionRequest`/`ActionResponse` 通信。

**文件：**
- `agent/cognition/memory.py`：从 `memory_context` 中去掉 `public_summary`
- `agent/prompts/base.py`：从 `build_request_prompt()` 中去掉 `公开局势摘要` 行

### 组件 3：Schema 去重

**改动：** 去掉 `build_request_prompt()` 尾部的内联 JSON schema 块。改为引用 `output_schema.md` skill（它是 common skill，始终注入）。

prompt 尾部改为简短引用：
```
必须只输出 JSON，格式参见 output_schema 技能。
```

**文件：**
- `agent/prompts/base.py`：用简短引用替换内联 schema 块

### 组件 4：Belief 默认值省略

**改动：** 在 `BeliefState.build_context()` 中，跳过所有信念值都是默认值的玩家（wolf_prob ≈ 0.33，无证据）。只输出有实际证据或偏离均匀先验的玩家。

**文件：**
- `agent/cognition/belief.py`：在 `build_context()` 中加过滤逻辑

## 数据流

```
ActionRequest
  -> observe_node
  -> memory_node（去掉 public_summary）
  -> belief_node（省略默认值玩家）
  -> skill_select_node [新增]（第一阶段：LLM 从 description 选择 skill）
  -> skill_router_node（第二阶段：只注入选中 skill 的 full body）
  -> prompt_node（精简 prompt，无重复 schema）
  -> got_node / tot_node / llm_node
  -> parse_node -> policy_node -> log_node
  -> ActionResponse
```

## Token 预算估算

| 部分 | 优化前 | 优化后 |
|------|--------|--------|
| 第一阶段 skill 选择 | — | ~500 |
| 第二阶段选中 skill | ~1500 | ~800 |
| Memory | ~600 | ~300 |
| Belief | ~800 | ~200 |
| Schema | ~200 | ~50 |
| 其他（observation、instructions） | ~900 | ~900 |
| **合计** | **~4000** | **~2750** |

净减少 ~31%。第一阶段增加 ~1 秒延迟，但第二阶段处理更少 token，总时间可能反而更快。

## 需要修改的文件

| 文件 | 改动 |
|------|------|
| `agent/skill_system/loader.py` | `MarkdownSkill` 加 `description` 字段，从 front matter 解析 |
| `agent/skill_system/router.py` | 新增 `select_skills_by_llm()`，更新 `select_skills()` 支持 LLM 选择过滤 |
| `agent/nodes/skill_router.py` | 集成两阶段流程 |
| `agent/cognition/memory.py` | 从 `memory_context` 去掉 `public_summary` |
| `agent/cognition/belief.py` | `build_context()` 过滤默认信念值 |
| `agent/prompts/base.py` | 去掉 `public_summary` 行，用引用替换内联 schema |
| `skills/**/*.md` | 所有 skill 文件加 `description` 字段 |

## 测试

- 单元测试：`select_skills_by_llm()` 用 mock LLM 返回正确子集
- 单元测试：`build_context()` 省略默认信念值
- 单元测试：`build_request_prompt()` 不含 `public_summary` 和内联 schema
- 集成测试：跑一局 selfplay，在 langfuse trace 中验证 prompt 大小已缩减

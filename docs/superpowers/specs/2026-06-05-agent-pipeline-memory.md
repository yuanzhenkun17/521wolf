# Spec: Agent Pipeline 与短期记忆管理

> 本文记录 2026-06-05 对 Agent runtime pipeline、上下文管理、多层记忆边界的设计结论。
> 目标是保持系统简单、可解释：运行时只有一个固定 pipeline，短期记忆只管理当前局上下文，跨局长期知识只通过 Markdown Skill 进入 prompt。

---

## 1. 设计原则

1. **一个固定 pipeline**
   第一阶段只做一个 Agent pipeline 版本，不做用户可配置 pipeline，不做 Agent 配置榜。

2. **短期记忆只属于当前局**
   AgentMemory 只保存当前 game、当前 player-view 下的上下文窗口和压缩摘要。

3. **长期运行时知识只认 Skill**
   运行时 prompt 不直接注入 Pattern、Episodic、历史案例或全局 evolution.db 查询结果。

4. **压缩摘要不参与自进化学习**
   压缩摘要只辅助当前局决策，不跨局复用，不作为 evolution evidence。

5. **严格 player-view 信息隔离**
   每个 Agent 只能压缩自己可见的事件，不能产生上帝视角事实。

---

## 2. Runtime Pipeline

第一阶段固定 pipeline：

```text
1. remember_step
2. compress_memory_step
3. select_skills_step
4. build_prompt_step
5. call_model_step
6. parse_output_step
7. enforce_policy_step
```

旧的 `inject_memory_step` 第一阶段移除或保持 no-op：

```text
不做 Pattern runtime injection
不做 Episodic runtime injection
不实时查询 evolution.db 注入 prompt
```

---

## 3. Step 职责

### 3.1 `remember_step`

职责：

```text
接收 ActionRequest / Observation.visible_events
按 segment_key 归档到 AgentMemory
维护 open / closed segment 状态
标记哪些 closed segments 需要压缩
```

不做：

```text
不做人写规则分析
不更新玩家画像
不抽取 pinned facts
不生成长期策略
不访问跨局经验
不选择 Skill
不调用 LLM
```

### 3.2 `compress_memory_step`

职责：

```text
条件触发 LLM 压缩
当 closed segments 超过保留数量时，压缩最旧 segment
把压缩结果写入 compressed_segment_summaries
```

约束：

```text
压缩的是该 Agent 可见事件，不是全局完整事件
压缩输出必须是结构化 JSON
压缩失败不阻塞游戏
每个 segment 最多重试 2 次
```

不做：

```text
不访问 evolution.db
不写 Skill
不写 Pattern
不产生跨局 evidence
不推断上帝视角身份真相
```

### 3.3 `select_skills_step`

职责：

```text
按 role / action_type / phase 选择 Markdown skills
输出 selected_skills / skill_context
```

说明：

```text
Skill 是唯一长期运行时知识入口。
```

第一阶段不做语义检索：

```text
不使用 embedding
不按历史相似局面检索
不按玩家号检索
不按 game_id / run_id / seed 检索
不按 model_id / provider 检索
```

确定性路由优先级：

```text
1. role 必须匹配当前角色
2. status = active
3. applicable_phases 匹配当前阶段
4. applicable_actions 匹配当前动作类型
5. 超过 3 个时按 priority / 最近 promotion 时间排序
6. 只注入 runtime_body
```

### 3.4 `build_prompt_step`

职责：

```text
组装最终 LLM messages
```

输入：

```text
当前可见局势
当前 open segment 完整事件
最近 4 个 closed segments 完整事件
更早 segments 的压缩摘要
selected Markdown skills
输出 JSON schema / 合法动作约束
```

不做：

```text
不调用模型
不做压缩
不做策略修正
```

### 3.5 `call_model_step`

职责：

```text
调用当前 model_id 获取决策输出
记录 raw_output / llm_error / source
```

说明：

```text
compress_memory_step 和 call_model_step 第一阶段使用同一个 model_id。
模型榜评估的是 model_id 驱动 Agent 的端到端能力，包括压缩和决策。
```

### 3.6 `parse_output_step`

职责：

```text
解析模型输出 JSON
输出 parsed_decision / confidence
```

不做：

```text
不修正非法动作
```

### 3.7 `enforce_policy_step`

职责：

```text
保证 ActionResponse 合法
根据候选动作和规则约束修正 target / choice
生成 fallback response
记录 policy_adjustments
```

---

## 4. AgentMemory 第一阶段结构

第一阶段短期记忆只保留：

```text
current_visible_state
open_segment_events
recent_closed_segments
compressed_segment_summaries
compression_state
```

### 4.1 `current_visible_state`

当前 ActionRequest / Observation 中的权威状态：

```text
player_id
role
day
phase
alive_players
dead_players
sheriff_id
candidates
role_state / private info
```

### 4.2 `open_segment_events`

当前仍在进行中的 segment 的完整 player-view 可见事件。

例如玩家在第 2 天发言阶段早位发言时：

```text
day_speech:2 仍是 open segment
不能压缩，因为后位玩家还没发言
```

### 4.3 `recent_closed_segments`

最近若干个已闭合 segment 的完整 player-view 可见事件。

默认：

```text
max_recent_closed_segments = 4
```

第一阶段不做字符预算兜底：

```text
不做 max_prompt_context_chars
不做 max_recent_event_chars
不做 token budget
```

后续如果长局 prompt 过大，再补预算器。

### 4.4 `compressed_segment_summaries`

更早 closed segments 的 LLM 压缩摘要。

特点：

```text
player-view
当前 game 内有效
不跨局复用
不进入 Skill
不作为 evolution evidence
```

### 4.5 第一阶段不做的记忆结构

第一阶段不做：

```text
pinned_facts
player_models
self_commitments
episodic runtime memory
pattern runtime injection
跨局历史案例注入
```

如果后续发现模型在长局中遗忘早期关键查验、身份声明或用药状态，再考虑加 `pinned_facts`。

---

## 5. Segment 策略

### 5.1 Segment Key

```text
segment_key = phase_group + ":" + day
```

推荐 phase group：

```text
night:{day}
sheriff:{day}
day_speech:{day}
exile_vote:{day}
death_resolution:{day}
```

实现上可先按 `Observation.phase` 映射：

```text
phase_group = normalize_phase(observation.phase)
```

### 5.2 Segment 闭合条件

```text
当 observation.phase 的 phase_group 发生变化时，
上一个 phase_group:day 对该 Agent 视为 closed。
```

注意：

```text
closed 是该 Agent 视角下的 closed。
每个玩家有自己的 AgentMemory。
```

### 5.3 Prompt 窗口

每次决策 prompt 使用：

```text
当前 open segment 完整事件
+ 最近 4 个 closed segments 完整事件
+ 更早 closed segments 的压缩摘要
```

这个策略解决发言顺序问题：

```text
P1 在 day_speech:2 先发言时，day_speech:2 是 open segment，不会被压缩。
P1 下一次行动时，如果 day_speech:2 已结束，它才可能进入 closed segments。
只有当它进一步滑出最近 4 个 closed segments 时才被压缩。
```

---

## 6. LLM 压缩

### 6.1 触发条件

```text
closed_segments 数量 > max_recent_closed_segments
```

触发后：

```text
选择最旧 closed segment
调用同一个 model_id 压缩
成功后移入 compressed_segment_summaries
失败则保留完整 segment
```

### 6.2 压缩输入

```text
game_id
player_id
role
segment_key
该 Agent 可见的 segment events
```

只输入 player-view 事件，不输入上帝视角完整日志。

### 6.3 压缩 Prompt 约束

压缩 prompt 必须明确：

```text
你只能根据输入事件总结。
输入事件可能包含该玩家私有信息。
不得补充输入中没有出现的身份真相。
不得推断上帝视角。
不确定的信息写入 unknowns。
输出合法 JSON。
```

### 6.4 压缩输出 Schema

第一版至少要求：

```json
{
  "segment_key": "day_speech:2",
  "summary": "本阶段主要围绕P3预言家身份争议展开。",
  "key_events": [
    "P3 claimed seer",
    "P5 countered P3"
  ],
  "player_notes": {
    "3": "跳预言家并报查验，可信度待验证",
    "5": "强烈反驳P3，形成对跳线"
  },
  "unknowns": [
    "P3身份未被证实"
  ]
}
```

字段说明：

```text
segment_key:
  被压缩的 segment

summary:
  给 prompt 使用的短摘要

key_events:
  本 segment 中的重要事件描述

player_notes:
  针对玩家的短观察，只能基于输入事件

unknowns:
  明确未知事项，防止模型把推测当事实
```

### 6.5 压缩失败策略

压缩失败包括：

```text
LLM 调用失败
输出不是 JSON
JSON schema 不合格
```

失败处理：

```text
不阻塞游戏
不删除原 segment
不写错误摘要
当前决策继续
下次可重试
每个 segment 最多重试 2 次
超过后保留完整事件并标记 compression_failed
```

建议记录：

```text
compression_errors
compressed_segments_added
segment.compression_retry_count
segment.compression_failed
```

---

## 7. Player-view 信息隔离

每个 Agent 独立压缩自己的可见事件。

允许：

```text
预言家摘要中写自己的查验结果
女巫摘要中写自己的用药结果
狼人摘要中写狼队夜间击杀目标
村民摘要中只写公开事件
```

禁止：

```text
普通好人摘要中出现狼人夜间击杀内部信息
女巫不知道目标身份时写“救了预言家”
预言家未查验时写“P7 是狼人”
任何玩家摘要中出现输入事件没有提供的真实身份
```

压缩记录建议带：

```text
game_id
player_id
role
segment_key
source_visibility = player_view
```

---

## 8. Prompt 上下文结构

`build_prompt_step` 不直接全量使用 `Observation.visible_events`。

关系：

```text
Observation = 更新 memory 的权威输入
AgentMemory window = prompt 的历史输入
```

Prompt 建议结构：

```text
1. 当前可见局势
   - player_id
   - role
   - day
   - phase
   - alive_players
   - dead_players
   - sheriff_id
   - candidates
   - role_state / private info

2. 更早阶段摘要
   - compressed_segment_summaries

3. 最近完整事件
   - open_segment_events
   - recent_closed_segments

4. 角色技能
   - selected Markdown skills

5. 输出要求
   - legal action constraints
   - JSON schema
```

---

## 9. Skill / Pattern / Episodic 边界

### 9.1 Runtime 长期知识

运行时长期知识只认：

```text
Markdown Skill
```

Prompt 不直接注入：

```text
Pattern
Episodic
历史案例
全局 evolution.db 查询结果
```

### 9.2 Skill

Skill 是角色长期策略知识：

```text
Markdown 文件
按 role / action / phase 路由
可版本化
可由自进化修改
运行时进入 prompt
```

第一阶段 skill package 约束：

```text
每个 role_version 是一个 skill package。
每个 package 可包含多个 skill 文件。
每角色最多 8 个 active skills。
每次决策最多注入 3 个 skills。
runtime_body_soft_limit = 1800 chars。
runtime_body_hard_limit = 2400 chars。
```

Skill lifecycle：

```text
status = active | deprecated
runtime 只注入 active。
deprecated 不计入 active skill 上限。
第一阶段不允许自动 deprecate whole skill。
只允许 deprecate_rule。
```

允许的自进化改动：

```text
create_skill
append_rule
rewrite_section
deprecate_rule
```

`create_skill` 必须通过严格校验：

```text
target_file = <slug>.md
不允许路径穿越
必须 .md
role 匹配 target role
frontmatter.evolution.enabled = true
frontmatter.evolution.allowed_actions 只能是 skill modification actions
applicable_actions 只能是合法游戏动作
```

`rewrite_section` 约束：

```text
允许压缩合并重复规则。
允许把旧规则改写得更精确。
不允许一次引入多个行为变化。
不允许修改 Deprecated Rules / Changelog / Provenance / Evaluation Notes / frontmatter。
必须记录 old_rule_refs / new_rule_summary / evidence_candidate_ids。
```

`deprecate_rule` 约束：

```text
不物理删除旧规则。
不静默 rewrite。
写入 ## Deprecated Rules。
记录 rule summary、reason、evidence source_game_id、deprecated_at。
runtime_body 完全忽略 deprecated 内容。
```

Runtime sections：

```text
## Strategy
## Heuristics
## Decision Rules
## Risk Boundaries
```

System / non-runtime sections：

```text
## Examples
## Deprecated Rules
## Changelog
## Provenance
## Evaluation Notes
```

`select_skills_step` 只使用 runtime sections 生成 `runtime_body`；Applier 和审计工具可以读取完整 Markdown。

Runtime sections 禁止出现：

```text
具体玩家号或座位:
  P1 / P2 / 7号玩家 / 一号位 等

历史定位信息:
  game_id / run_id / seed / source_game_id / evaluation_set_id

模型相关信息:
  model_id / provider / 模型名 / 温度 / thinking / 某模型擅长某策略

证据链文本:
  llm_rationale 原文 / 具体历史案例 / A-B 结果细节
```

System sections 允许记录证据来源、game_id、seed、模型配置、A/B 结果和 provenance，但这些内容绝对不能进入 runtime prompt。

人工编辑边界：

```text
第一阶段不提供人工创建、编辑、导入 skill 的 UI/API。
registry skill 只允许系统通过 Applier 写入。
每次运行前校验 content_hash / skill_package_hash。
hash 不匹配标记 registry dirty，并中断自进化和榜单运行。
不自动回滚。
```

### 9.3 Pattern

Pattern 第一阶段不进入 runtime，也不作为正式 candidate 生成主路径。

如果旧代码中保留 Pattern，只能视为 legacy / debug：

```text
不写新 Pattern
不从 Pattern 生成 proposal
不注入 prompt
不参与 leaderboard
```

第一阶段 Pattern 不直接进入 runtime prompt。

### 9.4 Episodic

Episodic 是具体历史案例：

```text
某局第2天女巫毒了P6，结果P6是猎人，好人失败
```

第一阶段：

```text
不做 runtime episodic injection
不把历史案例塞进 prompt
```

Episodic 第一阶段只保留为 legacy / debug 概念：

```text
不写新 situational_records / decision_outcomes
不从 Episodic 生成 proposal
不注入 prompt
不参与 leaderboard
```

---

## 10. 自进化关系

自进化唯一运行时产物：

```text
Markdown Skill 角色版本
```

自进化链路：

```text
evolution_training
  -> events / decisions / roles / winner
  -> review / evaluation / counterfactual
  -> EvidencePipeline
  -> experience_candidates
  -> consolidation
  -> skill proposal
  -> candidate role version
  -> A/B 验证
  -> promote baseline
```

明确不做：

```text
运行时动态 pattern injection
运行时 episodic case injection
压缩摘要跨局复用
压缩摘要直接进入 evolution evidence
不把 Pattern / Episodic 作为新学习事实
不把 mid_memory 作为新 candidate 来源
```

自进化 evidence 必须从更权威数据生成：

```text
events
decisions
roles
winner
review/evaluation
```

而不是从运行时压缩摘要中学习。

Consolidation 第一阶段只读取：

```text
experience_candidates
current active skills
rejected_proposals as guardrail
```

不读取：

```text
ReviewService tables
Pattern
Episodic
runtime compressed summaries
ordinary_game
evaluation_batch
evolution_ab
imported_mistake_case
mid_memory
```

---

## 11. AgentContext 建议字段

第一阶段可扩展 `AgentContext`：

```text
memory_context
compression_errors
compressed_segments_added
selected_skills
skill_context
messages
raw_output
parsed_decision
response
policy_adjustments
errors
```

其中：

```text
memory_context:
  build_prompt_step 使用的上下文窗口

compression_errors:
  compress_memory_step 的失败信息

compressed_segments_added:
  本次决策前新增的压缩摘要 segment keys
```

`DecisionRecord` 可选记录：

```text
memory_compression_status
compressed_segments_added
```

用于复盘排查上下文压缩是否影响决策。

---

## 12. 第一阶段非目标

第一阶段不做：

```text
可配置 pipeline
多 Agent pipeline 版本
Pattern runtime injection
Episodic runtime injection
Pattern 新写入
Episodic 新写入
pinned_facts
player_models
self_commitments
token / 字符预算器
LLM 压缩模型单独配置
压缩摘要跨局复用
从压缩摘要生成 evolution evidence
人工 skill 编辑 / 导入
语义检索式 skill selection
runtime/pipeline/memory/prompt hash 记录
```

---

## 13. TODO

后续可考虑：

```text
1. Prompt token / 字符预算器
   长局时按优先级裁剪或进一步压缩。

2. pinned_facts
   如果模型在长局中忘记早期查验、身份声明、死亡、用药状态，再引入。

3. 单独 summarizer model
   如果压缩成本太高，可用固定小模型压缩。

4. 压缩质量评测
   用 fixture 检查摘要是否漏掉关键公开事件或私有信息。
```

---

## 14. 验收标准

### Pipeline

```text
AgentRuntime 使用固定 7 步:
remember -> compress_memory -> select_skills -> build_prompt -> call_model -> parse_output -> enforce_policy
```

### Segment Memory

```text
当前 open segment 不被压缩
最近 4 个 closed segments 保留完整可见事件
更早 closed segments 被 LLM 压缩
```

### 信息隔离

```text
村民摘要不包含狼人私密事件
预言家摘要可以包含自己的查验
女巫摘要可以包含自己的用药
狼人摘要可以包含狼队自己的夜间目标
```

### 压缩失败

```text
LLM 压缩失败时游戏继续
原 segment 不丢失
最多重试 2 次
```

### Runtime 知识

```text
Prompt 中长期知识只来自 Markdown Skill
Pattern / Episodic 不直接注入 prompt
压缩摘要不跨局复用
Skill prompt 只包含 runtime_body
runtime_body 不包含玩家号、game_id、seed、模型名或历史证据定位信息
```

---

## 15. 总结

最终运行时上下文：

```text
Prompt =
  当前可见局势
+ 当前 open segment 完整可见事件
+ 最近 4 个 closed segments 完整可见事件
+ 更早 segment 的 LLM 压缩摘要
+ 当前角色 Markdown skills
+ 输出 JSON schema / 合法动作约束
```

最终知识边界：

```text
Observation = Engine 给的当前权威可见局势
AgentMemory = 当前局 player-view segment window + 压缩摘要
Skill = 跨局长期策略知识
```

核心原则：

```text
短期记忆管理当前局；
Markdown Skill 承载长期策略；
Pattern / Episodic 不进入运行时 prompt；
自进化最终必须沉淀成 Skill。
```

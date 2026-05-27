# 521wolf Agent 系统架构文档

## 概览

Agent 系统是狼人杀 AI 的决策引擎。它接收游戏引擎的 ActionRequest，通过一条 10 节点的管道生成 ActionResponse。

## 目录结构

```
agent/
  runtime/          运行时：管道编排、上下文、模型适配、工厂
  nodes/            10 个管道节点（每个是纯函数或 async 函数）
  cognition/        认知系统：记忆、信念、经验、长期记忆、做梦
  reasoning/        推理增强：Tree-of-Thought 多候选推理
  prompts/          Prompt 构建：模板、指令、格式化、JSON 解析
  skill_system/     Skill 加载与路由
  observability/    可观测性：决策日志、完整决策存档
  evaluation/       评估系统：复盘、自对弈、排行榜、版本对战
  skills/           Markdown 策略文件（按角色组织）
```

---

## 1. Runtime 层

### context.py — AgentContext
管道中流动的共享状态对象。每个节点读取和写入这个 dataclass。

### model.py — ModelAdapter
LLM 接口抽象。Protocol 定义 complete(messages) -> str。默认实现使用 langfuse.openai.AsyncOpenAI（自动 Langfuse 追踪）。

### agent.py — AgentRuntime & LLMPlayerAgent
- AgentRuntime: 编排 10 个节点的管道
- LLMPlayerAgent: 适配器，包装 AgentRuntime 满足 PlayerAgent 协议

### factory.py — create_agents
批量创建 LLMPlayerAgent，共享一个 ModelAdapter 客户端。

---

## 2. Nodes 层

管道顺序：observe -> memory -> belief -> skill_router -> prompt -> tot -> llm -> parse -> policy -> log

| 节点 | 读取 | 写入 | 职责 |
|------|------|------|------|
| observe | request, observation | observation_summary | 提取结构化场上信息 |
| memory | request, role | memory_context | 构建短期记忆 + 长期记忆提示 |
| belief | request | belief_context | 更新嫌疑人概率，输出 top 5 |
| skill_router | role, request | selected_skills, skill_context | 选择匹配的 Markdown skill |
| prompt | 所有上下文 | messages | 组装 system + user 消息 |
| tot | request | raw_output, source | 多候选推理（可跳过 LLM） |
| llm | messages | raw_output | 调用 LLM |
| parse | raw_output | response, parsed_decision | 解析 JSON 为 ActionResponse |
| policy | request, response | response | 验证/修复决策合法性 |
| log | 全部上下文 | decision_record | 构建 DecisionRecord |

所有节点有 @observe 装饰器用于 Langfuse 追踪。

---

## 3. Cognition 层

### memory.py — 短期记忆
AgentMemory 跟踪结构化事件（投票、发言、死亡）、玩家行为画像、投票协调模式。

### belief.py — 信念状态
BeliefState 维护每个玩家的 wolf/villager/god 概率（总和=1.0）。根据投票、发言、查验、身份声称更新。

### experience.py — 经验卡提取
每局结束后为每个玩家生成 ExperienceCard，写入 data/experiences/{role}/cards.jsonl。

### long_memory.py — 长期记忆聚合
统计同角色多张经验卡：胜率、高频策略、高频失误。输出 data/long_memory/{role}.json。

### dream.py — LLM 反思
DreamAgent 读取经验卡 + 当前 skill，调用 LLM 生成 DreamReport（insights + skill edit proposals）。

### skill_evolution.py — Skill 进化
将高置信度 dream proposals 转为 SkillProposal，满足阈值时自动 append 规则到 Markdown skill。

---

## 4. Reasoning 层

### tot.py — Tree-of-Thought
对高风险动作（投票、杀人、用药、查验），LLM 一次调用生成 3 个候选策略，自选最佳。成功时跳过 llm_node。

---

## 5. Prompts 层

- base.py: build_messages() 组装消息；build_system_prompt() 设置人设；build_request_prompt() 打包游戏状态
- instructions.py: default_persona() 分配行为风格；action_instruction() 映射 ActionType 到指令
- formatting.py: format_field_notes() 转 FieldNotes 为文本
- parsing.py: load_json_object() 从 LLM 输出提取 JSON

---

## 6. Skill System

- loader.py: 递归扫描 .md 文件，解析 YAML front-matter
- router.py: select_skills() 按角色和动作类型选择 skill；format_skill_context() 渲染为 prompt 文本
- skills/: 23 个 Markdown 策略文件，按角色组织（werewolf/seer/witch/hunter/guard/villager/white_wolf_king/common）

---

## 7. Observability 层

- decision_log.py: AgentDecisionRecorder 记录 DecisionRecord（轻量），导出 JSONL
- archive.py: AgentTraceRecorder 记录完整决策上下文（重量级），GameArchive 写入 `logs/gameN/archive.json`

---

## 8. Evaluation 层

- review.py: 基础复盘：评分、失误检测、转折点识别
- review_enhanced.py: 增强复盘：16 种失误类型、反事实分析、GameReviewReport
- selfplay.py: 多局自对弈、收集 archive、生成 review、经验卡、触发做梦
- leaderboard.py: 跨版本排行榜
- version_battle.py: 版本对战

---

## 数据流全景

```
GameEngine -> ActionRequest
  -> observe_node       (observation_summary)
  -> memory_node        (memory_context, long_memory_hints)
  -> belief_node        (belief_context, top 5 嫌疑)
  -> skill_router_node  (skill_context)
  -> prompt_node        (messages)
  -> tot_node           (ToT 多候选推理, 可跳过 LLM)
  -> llm_node           (raw_output)
  -> parse_node         (response, parsed_decision)
  -> policy_node        (验证/修复)
  -> log_node           (decision_record)
  -> ActionResponse -> GameEngine

后处理（游戏结束后）：
  archive.json   <- AgentTraceRecorder
  agent.jsonl    <- AgentDecisionRecorder
  review         <- generate_enhanced_review()
  experiences    <- extract_experiences()
  long_memory    <- consolidate_role_memory()
  dream          <- DreamAgent.reflect()
  skill_update   <- apply_skill_proposals()
  langfuse       <- session_id = game_id
```

---

## 关键设计决策

1. 节点式管道：每个节点是纯函数，读写 AgentContext，易于测试
2. ToT 短路：高风险动作用多候选推理，成功时跳过 LLM
3. Policy 兜底：保证返回合法 ActionResponse
4. Skill 可热更新：Markdown 文件修改即时生效
5. 三层记忆：短期(AgentMemory) -> 中期(ExperienceCard) -> 长期(RoleLongTermMemory)
6. Langfuse 全链路追踪：每个节点 @observe，按 game_id 分 session

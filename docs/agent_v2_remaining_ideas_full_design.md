# Agent v2 剩余 Ideas 详细落地设计

本文档用于把 `docs/ideas.md` 中尚未完全实现的 Agent 层想法，整理成一套非常详细的工程设计方案。

当前项目已经有 `agent`，并且已经完成了规则层兼容、图式 runtime、短期记忆、belief、Markdown skill 注入、policy 修正和基础 review 能力。本文档不重复描述这些已完成基础能力，而是聚焦：

- 相比 ideas 还缺什么。
- 每个缺口应该怎么设计。
- 如何兼容现有规则层。
- 如何逐步实现，避免一次性重写过大。
- 如何验证效果。
- 如何形成答辩亮点。

## 1. 设计结论

对比 `docs/ideas.md`，当前 Agent v2 最大缺口不是“能不能玩完一局”，而是还没有形成完整的 Agent 调优闭环。

当前系统大致处于：

```text
单局决策可运行
→ 单次决策有日志
→ 角色 skill 已 Markdown 化
→ 规则层兼容稳定
```

而 ideas 中真正高分的方向是：

```text
多局自博弈
→ 全量数据归档
→ 赛后复盘
→ 经验卡片
→ 跨局长期记忆
→ Skill 版本调优
→ Leaderboard 对比
→ 关键决策强推理
```

所以推荐后续主线是：

```text
selfplay
→ archive
→ review
→ experience
→ long_memory
→ leaderboard
→ skill_update
→ tot/got
```

其中最值得优先做的是：

1. `selfplay`：让系统自动跑多局，产生可评测数据。
2. `archive`：把每局所有规则事件、Agent 输入、Prompt、输出、修正都完整保存。
3. `review`：把胜负之外的决策质量评出来。
4. `experience`：每局结束后为每个角色生成经验卡片。
5. `leaderboard`：比较不同 skill / prompt / agent 版本。

这条路线最贴合评分标准中的 Agent 调优、多 Agent 系统设计、可观测性和进阶“评测 + 复盘”方向。

## 2. 当前基线

### 2.1 已有能力

当前 `agent` 已经具备：

- 通过 `ActionRequest -> ActionResponse` 兼容现有规则层。
- 不直接读取或修改规则层内部 `GameState`。
- 图式 runtime 节点：
  - observe
  - memory
  - belief
  - skill_router
  - prompt
  - llm
  - parse
  - policy
  - log
- `AgentMemoryV2` 维护本局短期记忆。
- `BeliefStateV2` 维护玩家嫌疑、信任和关系信息。
- Markdown skill：
  - 通用规则 skill。
  - 通用输出格式 skill。
  - 角色 skill。
- `skill_router` 根据角色和 action 注入 Markdown skill。
- `policy` 对非法 target / choice 做校验、修正或 fallback。
- `DecisionRecord` 记录决策字段。
- `review` 已有初步评分和报告能力。
- 测试已覆盖基本兼容和流程。

### 2.2 当前边界

Agent 层必须继续遵守：

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

允许：

- 使用 `request.observation` 中可见信息。
- 使用 `request.candidates` 中合法候选。
- 使用 `request.metadata` 中规则层显式给出的元数据。
- 维护 Agent 私有记忆。
- 写 Agent 自己的日志。
- 调用 LLM。
- 做 Prompt 调优。
- 做决策复盘。

禁止：

- 直接读取规则层 `GameState`。
- 从规则层之外偷看隐藏身份。
- 让村民看到狼人队友。
- 让狼人看到预言家查验结果。
- 让任意 Agent 看到自己身份权限之外的信息。
- 绕过规则层执行行动。
- 修改规则层死亡、投票、技能结果。

### 2.3 当前未完成的 idea 分组

未完成内容可以分成八类：

| 类别 | idea 来源 | 当前状态 | 推荐优先级 |
| --- | --- | --- | --- |
| 自博弈数据收集 | 张勇杰 | 未形成批量 runner | P1 |
| 完整记忆归档 | 张勇杰 | 只有分散日志 | P1 |
| 中期经验卡片 | 张勇杰、苑震坤 | 未实现 | P2 |
| 长期记忆 / dream | 张勇杰 | 未实现 | P3 |
| 角色经验池 | 张勇杰 | 未实现 | P3 |
| ToT / GoT | 张勇杰 | 未实现 | P4 |
| 多局评测 + Leaderboard | 评分标准 | 未完整实现 | P2 |
| Skill 自动调优 | ideas 延伸 | 未实现 | P4 |

## 3. 目标架构

### 3.1 总体闭环

目标系统应该形成如下闭环：

```text
单次行动
→ Agent 决策 trace
→ 单局完整 archive
→ 赛后 review
→ 每角色 experience card
→ 跨局 long-term memory
→ skill 更新建议
→ 新 skill 版本
→ 多局 selfplay 对比
→ leaderboard
```

### 3.2 分层结构

推荐把 Agent v2 分成五层：

```text
规则兼容层
  - ActionRequest / ActionResponse
  - 不侵入规则层

单局决策层
  - runtime nodes
  - memory
  - belief
  - skill router
  - prompt
  - policy

单局观测层
  - decision trace
  - game archive
  - review report

跨局学习层
  - experience cards
  - long-term memory
  - role memory pool

评测与调优层
  - selfplay runner
  - leaderboard
  - skill version compare
  - update suggestions
```

### 3.3 推荐新增模块

建议后续新增或增强如下模块：

```text
agent/
  archive.py
  selfplay.py
  review.py
  experience.py
  long_memory.py
  leaderboard.py
  skill_version.py
  evaluation/
    __init__.py
    metrics.py
    report.py
    mistakes.py
    counterfactual.py
  reasoning/
    __init__.py
    tot.py
    got.py
    critique.py
  storage/
    __init__.py
    jsonl.py
    paths.py
    schemas.py
```

不要求一次性全做。建议先实现：

```text
archive.py
selfplay.py
experience.py
leaderboard.py
```

## 4. 数据目录设计

### 4.1 推荐落盘目录

为了避免污染源码目录，建议把运行数据放在 `logs/` 或 `data/` 下。

推荐：

```text
logs/
  selfplay/
    run_20260526_001/
      config.json
      summary.json
      summary.md
      games/
        game_001/
          game_events.jsonl
          agent_decisions.jsonl
          agent_traces.jsonl
          archive.json
          review.json
          review.md
          experiences/
            player_1_werewolf.json
            player_2_seer.json
        game_002/
          ...

data/
  experiences/
    werewolf/
      cards.jsonl
    seer/
      cards.jsonl
    witch/
      cards.jsonl
    hunter/
      cards.jsonl
    villager/
      cards.jsonl
    guard/
      cards.jsonl
    white_wolf_king/
      cards.jsonl
  long_memory/
    werewolf.md
    seer.md
    witch.md
    hunter.md
    villager.md
  leaderboards/
    leaderboard.json
    leaderboard.md
  skill_update_suggestions/
    run_20260526_001.md
```

### 4.2 为什么运行数据不放进 `agent/`

源码目录应该放稳定代码、Prompt 和 skill。运行产生的数据量会越来越大，且不是代码的一部分。

不建议：

```text
agent/experience_store/
agent/runs/
agent/logs/
```

推荐：

```text
logs/selfplay/
data/experiences/
data/long_memory/
```

这样更利于：

- git 忽略运行产物。
- 答辩时单独展示数据。
- 后续清理历史 run。
- 多版本对比。

## 5. Selfplay 多局自博弈

### 5.1 目标

Selfplay 是后续所有评测和学习的基础。

目标：

- 自动运行 N 局狼人杀。
- 每局使用指定 Agent 配置。
- 每局保存完整数据。
- 汇总胜负、轮次、fallback、policy 修正、评分等指标。
- 支持不同 Agent / skill / model 版本对比。

### 5.2 非目标

第一版不需要：

- 并发跑 100 局。
- 训练模型。
- 自动改代码。
- 自动改 skill。
- 接入 LangGraph。

第一版只需要：

```text
能稳定跑多局
→ 能保存数据
→ 能汇总指标
```

### 5.3 核心接口

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SelfPlayConfig:
    games: int
    seed_start: int
    output_dir: Path
    agent_version: str = "agent_v2"
    skill_dir: Path | None = None
    model_name: str | None = None
    max_days: int = 20
    enable_review: bool = True
    enable_experience: bool = True
    temperature: float = 0.2


@dataclass(slots=True)
class SelfPlayGameResult:
    game_id: str
    seed: int
    winner: str
    days: int
    player_roles: dict[int, str]
    decision_count: int
    fallback_count: int
    policy_adjusted_count: int
    avg_confidence: float
    review_score: float | None
    output_dir: Path


@dataclass(slots=True)
class SelfPlayResult:
    config: SelfPlayConfig
    games: list[SelfPlayGameResult]
    summary: dict
```

入口：

```python
async def run_selfplay(config: SelfPlayConfig) -> SelfPlayResult:
    ...
```

### 5.4 流程

```text
读取 SelfPlayConfig
→ 创建 run 目录
→ 保存 config.json
→ for i in games:
    → 使用 seed 创建一局游戏
    → 创建 agent agents
    → 注入 skill_dir / model 配置
    → 运行规则层直到胜负产生
    → 收集规则日志
    → 收集 Agent 决策日志
    → 生成 archive
    → 生成 review
    → 生成 experience cards
    → 写 game result
→ 聚合 summary
→ 生成 summary.json
→ 生成 summary.md
→ 返回 SelfPlayResult
```

### 5.5 单局目录

```text
game_001/
  meta.json
  game_events.jsonl
  agent_decisions.jsonl
  agent_traces.jsonl
  archive.json
  review.json
  review.md
  experiences/
    player_1_werewolf.json
    player_2_villager.json
```

### 5.6 `meta.json`

```json
{
  "game_id": "game_001",
  "seed": 1,
  "agent_version": "agent_v2",
  "skill_dir": "skills",
  "model_name": "doubao-seed-2.0-pro",
  "started_at": "2026-05-26T14:00:00+08:00",
  "finished_at": "2026-05-26T14:02:31+08:00",
  "winner": "villagers",
  "days": 4,
  "players": {
    "1": {"role": "werewolf", "team": "werewolves"},
    "2": {"role": "seer", "team": "villagers"}
  }
}
```

### 5.7 `summary.json`

```json
{
  "games": 20,
  "werewolf_wins": 9,
  "villager_wins": 11,
  "werewolf_win_rate": 0.45,
  "villager_win_rate": 0.55,
  "avg_days": 3.7,
  "avg_decision_score": 7.1,
  "avg_vote_accuracy": 0.58,
  "avg_skill_accuracy": 0.63,
  "fallback_rate": 0.04,
  "policy_adjusted_rate": 0.06,
  "avg_confidence": 0.71
}
```

### 5.8 验证

单元测试：

- `SelfPlayConfig` 能正常序列化。
- runner 能用 fake model 跑 2 局。
- 每局目录存在。
- 每局至少有 `archive.json`。
- summary 中存在胜率、平均轮次、fallback rate。

集成测试：

- 使用当前规则层跑 1 局真实流程。
- 不依赖网络模型时可用 dummy model。
- 不因某个 Agent 输出非法 JSON 而中断整局。

## 6. Archive 完整记忆归档

### 6.1 目标

Archive 是“完整记忆”。它和短期 memory 不一样。

短期 memory 用于当前局内决策，只给 Agent 看必要摘要。

Archive 用于赛后：

- 回放。
- 复盘。
- 数据集构建。
- 评测。
- Prompt 调试。
- 答辩展示。

### 6.2 Archive 应该包含什么

每一局的 archive 至少包含：

- 游戏基本信息。
- 玩家身份。
- 最终胜负。
- 规则层公开事件。
- 每次 Agent 收到的可见 observation 摘要。
- 每次注入的 skill。
- 每次 Prompt。
- 每次模型原始输出。
- 每次解析结果。
- 每次 policy 修正。
- 每次最终 `ActionResponse`。
- 每次 fallback。
- 每次错误。
- 每个 Agent 的记忆摘要和 belief 快照。

### 6.3 数据结构

```python
@dataclass(slots=True)
class GameArchive:
    game_id: str
    seed: int
    config: dict
    player_roles: dict[int, str]
    winner: str | None
    started_at: str
    finished_at: str | None
    public_events: list[dict]
    decisions: list["DecisionArchive"]
    final_state: dict


@dataclass(slots=True)
class DecisionArchive:
    decision_id: str
    index: int
    player_id: int
    role: str
    day: int
    phase: str
    action_type: str
    candidates: list[int]
    observation_summary: dict
    memory_context: dict
    belief_context: dict
    selected_skills: list[str]
    prompt_messages: list[dict]
    raw_output: str
    parsed_decision: dict
    final_response: dict
    source: str
    confidence: float | None
    policy_adjustments: list[str]
    errors: list[str]
```

### 6.4 `source` 枚举

建议统一：

```text
llm
policy_adjusted
fallback
parse_failed
model_failed
human
```

含义：

- `llm`：模型输出合法，未被修正。
- `policy_adjusted`：模型有输出，但被 policy 修正。
- `fallback`：无法使用模型输出，采用默认策略。
- `parse_failed`：模型输出无法解析。
- `model_failed`：模型调用失败。
- `human`：真人玩家输入。

### 6.5 Trace 与 DecisionRecord 的关系

当前 `DecisionRecord` 是轻量决策日志，适合 memory 和 review 使用。

Archive 里的 `DecisionArchive` 更重，包含 Prompt 和 raw output。

建议：

```text
DecisionRecord:
  轻量、常驻、可进 memory、可进 review。

DecisionArchive:
  重量、落盘、可包含 Prompt 和 raw output。
```

不要把完整 Prompt 全部塞进短期 memory，否则会导致上下文膨胀。

### 6.6 AgentTraceRecorder

新增：

```python
class AgentTraceRecorder:
    def __init__(self, output_path: Path):
        ...

    def record(self, ctx: AgentContext) -> None:
        ...

    def flush(self) -> None:
        ...
```

Runtime 集成方式：

```python
ctx = log_node(ctx, self.logger)
if self.trace_recorder:
    self.trace_recorder.record(ctx)
return ctx.response
```

### 6.7 信息隔离要求

Archive 可以保存每个 Agent 的 observation，但必须保存的是“该 Agent 当时可见的 observation”，不能为了复盘方便把全量 `GameState` 塞进去。

可保存最终身份表，但必须放在单局结束后的 `final_state` 中，不能混进某个 Agent 当时的 prompt 或 observation。

也就是说：

```text
decision.observation_summary:
  只保存当时可见信息。

archive.final_state.player_roles:
  只在游戏结束后保存，用于复盘。
```

### 6.8 验证

测试：

- 村民的 `DecisionArchive.observation_summary` 中没有狼队友信息。
- 狼人的 `DecisionArchive.observation_summary` 中没有预言家查验结果。
- 预言家的 `DecisionArchive.observation_summary` 只包含自己的查验结果。
- `final_state` 可以包含所有身份，但只在游戏结束后出现。

## 7. Review 复盘系统

### 7.1 目标

Review 的目标不是复述日志，而是回答：

- 这局为什么赢 / 输？
- 哪些决策是关键转折点？
- 每个 Agent 决策质量如何？
- 哪些 skill 起作用？
- 哪些 skill 导致坏决策？
- 哪些 bad case 可以变成后续经验？
- 如果换一个决策，可能会怎样？

### 7.2 Review 输入

```python
@dataclass(slots=True)
class ReviewInput:
    archive: GameArchive
    public_events: list[dict]
    decisions: list[DecisionArchive]
    final_roles: dict[int, str]
    winner: str
```

### 7.3 Review 输出

```python
@dataclass(slots=True)
class GameReviewReport:
    game_id: str
    winner: str
    summary: str
    team_scores: dict[str, float]
    player_scores: dict[int, "PlayerReview"]
    key_turning_points: list["TurningPoint"]
    mistakes: list["DecisionMistake"]
    skill_summary: dict[str, "SkillReview"]
    counterfactuals: list["Counterfactual"]
    suggestions: list[str]
```

### 7.4 PlayerReview

```python
@dataclass(slots=True)
class PlayerReview:
    player_id: int
    role: str
    team: str
    outcome: str
    total_score: float
    speech_score: float
    vote_score: float
    skill_score: float
    information_score: float
    cooperation_score: float
    highlights: list[str]
    mistakes: list[str]
    suggestions: list[str]
```

### 7.5 决策评分维度

每次决策可以从以下维度打分：

| 维度 | 说明 | 示例 |
| --- | --- | --- |
| 合法性 | 是否被 policy 修正或 fallback | 非法 target 扣分 |
| 信息一致性 | 是否基于可见信息推理 | 村民说出夜间刀人信息扣分 |
| 阵营贡献 | 是否帮助本阵营获胜 | 狼人成功抗推好人加分 |
| 风险控制 | 是否避免高风险低收益动作 | 女巫无证据盲毒扣分 |
| 推理质量 | 发言或行动理由是否连贯 | 票型分析充分加分 |
| Skill 匹配 | 当前 skill 是否适合局势 | 女巫 poison skill 用在 save 阶段扣分 |

### 7.6 mistake_type

建议标准化错误类型：

```text
illegal_action
policy_adjusted
fallback_used
low_confidence
wrong_vote
missed_wolf
protected_wolf
poisoned_good
shot_good
killed_teammate_without_gain
bad_claim
revealed_private_info
ignored_seer_check
ignored_vote_pattern
over_trusted_wolf
failed_to_coordinate
bad_skill_selection
```

### 7.7 关键转折点识别

关键转折点可以优先从以下事件中识别：

- 第一次白天放逐。
- 女巫用毒。
- 女巫救人。
- 猎人开枪。
- 预言家跳身份。
- 白狼王自爆。
- 狼人冲票成功。
- 狼人刀中关键神职。
- 好人票出真预言家。
- 狼人队友连续暴露。

### 7.8 反事实推演

第一版可以用模板，不必调用 LLM。

示例：

```text
事实：女巫第 2 晚毒杀 5 号，5 号最终身份为预言家。

反事实：
如果女巫没有毒杀 5 号，5 号可能在第 3 天继续公开查验结果，好人阵营可以获得额外信息。该决策大概率降低了好人胜率。
```

模板规则：

- 女巫毒死好人神职：认为高风险负面。
- 猎人带走好人：认为高风险负面。
- 票出狼人：认为正面。
- 票出预言家 / 女巫 / 猎人：认为负面。
- 狼人刀中神职：狼人正面。
- 狼人白天被放逐：狼人负面。

### 7.9 Review Markdown 报告结构

```markdown
# Game 001 复盘报告

## 1. 基本信息

## 2. 胜负概览

## 3. 阵营表现

## 4. 关键转折点

## 5. 玩家评分

## 6. 关键错误

## 7. Skill 表现

## 8. 反事实推演

## 9. 可沉淀经验

## 10. 建议更新的 Skill
```

### 7.10 验证

测试：

- 给定一局含女巫毒错好人的 archive，review 能识别 `poisoned_good`。
- 给定一局含猎人开枪带走狼人的 archive，review 给正向 skill_score。
- 给定非法 target 的 decision，review 记录 `policy_adjusted`。
- `review.md` 能生成并包含关键转折点。

## 8. Experience Cards 中期记忆

### 8.1 目标

中期记忆以“一局结束”为单位提取。

它不是当前局即时上下文，而是：

```text
这一局我作为某个角色学到了什么
```

Experience Card 的价值：

- 供后续同角色检索。
- 作为 long-term memory 的输入。
- 作为 skill 调优依据。
- 答辩时展示 Agent 的学习痕迹。

### 8.2 生成时机

```text
游戏结束
→ archive 完成
→ review 完成
→ 为每个玩家生成 experience card
→ 按角色写入 data/experiences/{role}/cards.jsonl
```

### 8.3 ExperienceCard Schema

```python
@dataclass(slots=True)
class ExperienceCard:
    card_id: str
    game_id: str
    player_id: int
    role: str
    team: str
    outcome: str
    created_at: str
    summary: str
    situation_tags: list[str]
    key_decisions: list["ExperienceDecision"]
    lessons: list[str]
    avoid_next_time: list[str]
    reusable_strategies: list[str]
    related_skills: list[str]
    evidence_decision_ids: list[str]
    score: float
    confidence: float
```

### 8.4 ExperienceDecision Schema

```python
@dataclass(slots=True)
class ExperienceDecision:
    day: int
    phase: str
    action_type: str
    selected_skills: list[str]
    context: str
    action: str
    expected_outcome: str
    actual_result: str
    lesson: str
```

### 8.5 示例

```json
{
  "card_id": "game_042_p3_werewolf",
  "game_id": "game_042",
  "player_id": 3,
  "role": "werewolf",
  "team": "werewolves",
  "outcome": "lose",
  "summary": "首日悍跳预言家失败，查验链解释不足，被好人集中放逐。",
  "situation_tags": ["fake_seer", "day1", "counter_claim"],
  "key_decisions": [
    {
      "day": 1,
      "phase": "day",
      "action_type": "speak",
      "selected_skills": ["game_rules", "output_schema", "werewolf/fake_seer"],
      "context": "真预言家前置位已跳，自己作为狼人选择对跳。",
      "action": "声称自己是预言家，并给真预言家查杀。",
      "expected_outcome": "扰乱好人视野，争夺警徽和归票权。",
      "actual_result": "发言缺少查验理由和后续警徽流，被多数玩家识破。",
      "lesson": "狼人悍跳必须准备查验链、警徽流和被反打后的回应。"
    }
  ],
  "lessons": [
    "狼人悍跳不能只给结论，需要完整信息链。",
    "如果发言位置靠后且队友未铺垫，悍跳风险较高。"
  ],
  "avoid_next_time": [
    "无铺垫强行对跳。",
    "给出无法解释的查杀。"
  ],
  "reusable_strategies": [
    "如果真预言家可信度较高，可以改用倒钩策略。"
  ],
  "related_skills": ["werewolf/fake_seer", "werewolf/deep_wolf"],
  "score": 4.2,
  "confidence": 0.82
}
```

### 8.6 生成方式

第一版建议规则生成：

- 从 review 中取 highlights、mistakes、suggestions。
- 从 archive 中取关键 decision。
- 用模板生成 summary 和 lesson。

第二版再增加 LLM 生成：

- 给 LLM 输入 archive 摘要和 review。
- 要求输出严格 JSON。
- policy 校验 JSON。

### 8.7 按角色经验池

落盘：

```text
data/experiences/
  werewolf/cards.jsonl
  seer/cards.jsonl
  witch/cards.jsonl
  hunter/cards.jsonl
  villager/cards.jsonl
  guard/cards.jsonl
  white_wolf_king/cards.jsonl
```

每个角色只读取自己的经验池。

例如：

- 狼人 Agent 不读女巫经验。
- 女巫 Agent 不读狼人夜间协作经验。
- 村民 Agent 不读狼人队友信息。

注意：经验卡片是赛后数据，可能包含最终身份。它不能原样注入下一局 prompt，否则可能形成“身份泄露风格”的不良习惯。

注入下一局时应该转成抽象策略：

```text
坏例子：
上一局 3 号是狼人，他悍跳失败。

好例子：
狼人悍跳时需要准备查验链和警徽流。
```

### 8.8 验证

测试：

- 每局结束后每个玩家都有 experience card。
- card 按角色写入正确文件。
- card 中不包含下一局具体玩家 id 作为策略先验。
- 失败方至少有一条 lesson。
- 使用关键错误生成对应 `situation_tags`。

## 9. Long-Term Memory 长期记忆

### 9.1 目标

长期记忆是跨多局经验的压缩结果。

它不保存某一局细节，而是保存：

- 高频成功策略。
- 高频失败模式。
- 角色打法原则。
- 不同局势下的行动偏好。
- skill 更新建议。

### 9.2 触发条件

建议触发条件：

```text
某角色 experience card 数量 >= 5
或 selfplay run 结束
或 手动执行 consolidate
```

### 9.3 输入输出

输入：

```text
data/experiences/{role}/cards.jsonl
```

输出：

```text
data/long_memory/{role}.json
data/long_memory/{role}.md
```

### 9.4 RoleLongTermMemory Schema

```python
@dataclass(slots=True)
class RoleLongTermMemory:
    role: str
    generated_at: str
    source_card_count: int
    win_rate: float
    avg_score: float
    effective_strategies: list["StrategyPrinciple"]
    recurring_mistakes: list["StrategyPrinciple"]
    situational_rules: list["SituationalRule"]
    deprecated_rules: list[str]
    skill_update_suggestions: dict[str, list[str]]
```

### 9.5 StrategyPrinciple

```python
@dataclass(slots=True)
class StrategyPrinciple:
    title: str
    description: str
    evidence_count: int
    avg_score_delta: float | None
    confidence: float
    source_cards: list[str]
```

### 9.6 SituationalRule

```python
@dataclass(slots=True)
class SituationalRule:
    situation: str
    recommendation: str
    avoid: str
    confidence: float
```

### 9.7 示例：狼人长期记忆

```markdown
# Werewolf Long-Term Memory

## 有效策略

### 悍跳前准备完整信息链

当选择悍跳预言家时，必须同时准备：

- 查验目标。
- 查验理由。
- 后续警徽流。
- 被真预言家反打时的回应。

证据：5 张经验卡片中，缺少查验链的悍跳平均评分低于 4 分。

## 高频失误

### 队友未铺垫时强行对跳

在真预言家可信度已较高、队友没有提前站边时，强行对跳容易被集中放逐。

## 局势规则

- 如果真预言家已被多数好人认可，优先考虑倒钩或切割。
- 如果狼队已有队友暴露，不要所有狼同时冲票，避免票型过于集中。
```

### 9.8 注入 Prompt 的方式

长期记忆不能无限注入。

建议：

- 每个角色最多注入 3 到 5 条长期原则。
- 按 action_type 筛选相关原则。
- 与当前 skill 一起注入。

示例：

```text
长期策略提示：
1. 女巫毒人前优先排除疑似预言家和猎人。
2. 仅凭划水不能作为第一毒杀理由。
3. 如果已经有强查杀信息，毒药应配合信息链使用。
```

### 9.9 是否使用向量数据库

第一版不建议上向量数据库。

原因：

- 当前数据规模小。
- 角色和 action_type 标签足够过滤。
- 向量库会增加工程复杂度。

第一版可以用：

```text
role + tags + action_type + score
```

做简单检索。

后续经验卡片超过几百张，再考虑向量检索。

### 9.10 验证

测试：

- 5 张同类 card 能合并成一条 recurring mistake。
- 低分策略能进入 `deprecated_rules`。
- 长期记忆按角色输出。
- Prompt 注入时不超过长度限制。

## 10. Skill 更新建议与版本化

### 10.1 目标

当前 skill 已经是 Markdown，这非常适合人工调优和版本化。

后续需要把 review / experience / long memory 的结论转成 skill 更新建议。

### 10.2 不建议第一版自动写回

原因：

- 自动写回可能把错误经验写进 skill。
- LLM 可能生成过拟合策略。
- skill 越改越长，Prompt 质量下降。
- 版本不可控。

推荐第一版：

```text
只生成建议，不自动改文件。
```

### 10.3 更新建议格式

```markdown
# Skill 更新建议

## skills/witch/poison.md

### 建议新增

- 毒人前检查目标是否疑似预言家、猎人或其他神职。
- 仅凭划水不应作为毒杀强理由。

### 依据

- game_003 中女巫毒杀真预言家，导致好人信息链断裂。
- game_007 中女巫盲毒村民，狼人获得轮次优势。

## skills/werewolf/fake_seer.md

### 建议新增

- 悍跳时必须同时给出查验链和后续警徽流。
- 如果队友没有铺垫，避免多人同时强冲。
```

### 10.4 Skill 版本目录

两种方案：

#### 方案 A：复制完整 skill 目录

```text
skillsets/
  v1/
    skills/
  v2/
    skills/
  exp_witch_poison_v1/
    skills/
```

优点：

- 对比清晰。
- selfplay 可指定 skillset。
- 易回滚。

缺点：

- 文件重复。

#### 方案 B：保留默认 `skills`，额外记录 git commit

```text
data/skill_versions/
  v1.json
  v2.json
```

优点：

- 简单。
- 不复制文件。

缺点：

- 运行时切换不方便。

推荐：

第一版使用方案 B。

等 Leaderboard 需要稳定比较多个版本时，再做方案 A。

### 10.5 Selfplay 指定 skill_dir

SelfplayConfig 应支持：

```python
skill_dir: Path | None = None
```

如果为 `None`，使用默认：

```text
skills
```

如果指定：

```text
skillsets/v2/skills
```

则加载对应版本。

### 10.6 验证

测试：

- 给定 long memory，能生成 skill update suggestions。
- suggestions 指向存在的 Markdown skill。
- selfplay 能加载不同 skill_dir。
- 不同 skill_dir 的 selected_skills 记录到 archive。

## 11. Leaderboard 多版本评测

### 11.1 目标

Leaderboard 用于证明：

```text
Agent 调优真的有效。
```

它是答辩中最有说服力的部分之一。

### 11.2 对比对象

可以比较：

- `agent_v1`
- `agent_v2_base`
- `agent_v2_md_skill`
- `agent_v2_review_tuned`
- `agent_v2_long_memory`
- `agent_v2_tot`
- 不同模型
- 不同 skillset
- 不同 temperature

### 11.3 LeaderboardEntry Schema

```python
@dataclass(slots=True)
class LeaderboardEntry:
    version: str
    games: int
    werewolf_win_rate: float
    villager_win_rate: float
    avg_days: float
    avg_score: float
    avg_speech_score: float
    avg_vote_score: float
    avg_skill_score: float
    vote_accuracy: float
    skill_accuracy: float
    fallback_rate: float
    policy_adjusted_rate: float
    avg_confidence: float
    notes: str
```

### 11.4 指标定义

#### 胜率

```text
werewolf_win_rate = 狼人胜局 / 总局数
villager_win_rate = 好人胜局 / 总局数
```

狼人杀阵营胜率本身受规则配置影响，所以不能只看某一方越高越好。

更重要的是角色决策质量。

#### 投票准确率

好人视角：

```text
投票目标是狼人 → 正确
投票目标是好人 → 错误
```

狼人视角：

```text
投票目标是好人 → 正确
投票目标是狼人 → 视情况判断
```

狼人投队友可能是倒钩，不一定错误。因此 review 中需要结合局势，不宜纯规则化。

第一版可以简化：

- 好人投狼加分。
- 好人投好人扣分。
- 狼人投好人加分。
- 狼人投狼人轻微扣分或中性。

#### 技能准确率

示例：

- 预言家查验狼人：加分。
- 预言家重复查验低价值目标：扣分。
- 女巫毒狼人：加分。
- 女巫毒神职：大扣分。
- 猎人带走狼人：加分。
- 猎人带走好人：扣分。
- 狼人刀神职：加分。

#### fallback rate

```text
fallback_count / decision_count
```

低 fallback rate 代表模型输出格式和 policy 兼容性更好。

#### policy adjusted rate

```text
policy_adjusted_count / decision_count
```

该指标过高说明 Prompt 或 parser 仍不稳定。

### 11.5 Leaderboard 输出

```markdown
| 版本 | 局数 | 狼胜率 | 好人胜率 | 平均分 | 投票准确率 | 技能准确率 | Fallback | Policy修正 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v2_base | 20 | 55% | 45% | 6.4 | 51% | 58% | 8% | 11% |
| v2_md_skill | 20 | 50% | 50% | 7.1 | 59% | 64% | 4% | 6% |
| v2_review_tuned | 20 | 48% | 52% | 7.6 | 64% | 70% | 3% | 5% |
```

### 11.6 公平性控制

为了让比较可信，需要控制：

- 相同 seeds。
- 相同角色分布。
- 相同规则配置。
- 相同模型。
- 相同 temperature。
- 相同局数。

推荐：

```text
每个版本跑同一组 seeds，例如 1 到 20。
```

### 11.7 验证

测试：

- 能从多个 selfplay summary 生成 leaderboard。
- markdown 表格字段完整。
- 缺失指标时不会崩溃。
- 同版本重复运行能合并或区分 run id。

## 12. ToT 关键决策强推理

### 12.1 目标

ToT 不是每次决策都用。它只用于高影响动作。

适合 ToT 的动作：

- 女巫是否毒人。
- 猎人是否开枪。
- 白狼王是否自爆。
- 预言家是否跳身份。
- 放逐投票。
- PK 投票。
- 狼人是否悍跳。

### 12.2 不适合 ToT 的动作

- 普通过渡发言。
- 候选目标很少且无关紧要的动作。
- 已经很确定的技能动作。
- 规则强制动作。

### 12.3 模块设计

```text
agent/reasoning/
  tot.py
  critique.py
```

### 12.4 ToTResult Schema

```python
@dataclass(slots=True)
class ThoughtCandidate:
    index: int
    target: int | None
    choice: str | None
    public_text: str
    private_reasoning: str
    expected_gain: str
    risk: str
    likely_reaction: str
    score: float


@dataclass(slots=True)
class ToTResult:
    enabled: bool
    reason: str
    candidates: list[ThoughtCandidate]
    selected_index: int | None
    final_decision: dict
```

### 12.5 Runtime 集成方式

新增节点：

```text
reasoning_router_node
```

位置：

```text
skill_router_node
→ reasoning_router_node
→ prompt_node
→ llm_node
```

或者：

```text
llm_node
→ critique_node
→ parse_node
```

推荐第一版：

```text
skill_router_node
→ prompt_node 构造 ToT prompt
→ 单次 LLM 输出候选和最终决策
```

不要第一版就做多轮 LLM 调用。

### 12.6 ToT Prompt 结构

```text
这是一个关键决策。请先比较 3 个候选动作：

候选动作需要包含：
- target
- choice
- expected_gain
- risk
- likely_reaction
- score

然后选择一个最终动作，并只在 final 字段里给出最终 JSON。
```

模型输出：

```json
{
  "candidates": [
    {
      "target": 3,
      "choice": "poison",
      "expected_gain": "可能毒中狼人",
      "risk": "如果3号是预言家会导致信息链断裂",
      "likely_reaction": "白天会引发对女巫判断的质疑",
      "score": 0.48
    }
  ],
  "final": {
    "target": null,
    "choice": "none",
    "public_text": "",
    "private_reasoning": "当前证据不足，毒药保留价值更高。",
    "confidence": 0.67
  }
}
```

### 12.7 验证

测试：

- 女巫毒人 action 会启用 ToT。
- 普通发言不会启用 ToT。
- ToT 输出 final 字段后，parse 只采用 final。
- ToT candidates 写入 archive。
- 即使 ToT 输出解析失败，policy 仍 fallback。

## 13. GoT 玩家关系图

### 13.1 目标

GoT 的核心不是画图，而是把玩家关系作为结构化推理输入。

狼人杀中很多判断来自关系：

- 谁攻击谁。
- 谁保护谁。
- 谁跟票谁。
- 谁和谁对跳。
- 谁和已知狼人关系紧密。
- 谁在关键轮次一起冲票。

### 13.2 当前 Belief 与 GoT 的关系

当前 `BeliefStateV2` 已经有玩家嫌疑和关系雏形。

GoT 可以作为 belief 的增强，不必另起一套完全独立系统。

推荐：

```text
BeliefStateV2
  + PlayerGraph
  + RelationEdge
  + graph_summary_for_prompt()
```

### 13.3 数据结构

```python
@dataclass(slots=True)
class RelationEdge:
    source: int
    target: int
    relation_type: str
    weight: float
    evidence: str
    day: int
    phase: str


@dataclass(slots=True)
class PlayerGraph:
    players: list[int]
    edges: list[RelationEdge]
```

### 13.4 relation_type

```text
attacks
defends
votes_against
votes_with
claims_role
counter_claims
follows
cuts
rushes
protects
suspected_teammate
confirmed_opponent
```

### 13.5 关系提取规则

第一版可以基于规则事件：

- A 投 B：`votes_against(A, B)`
- A 和 B 同票 C：`votes_with(A, B)`
- A 发言攻击 B：如果日志中可解析“怀疑/票/出 B”，记录 `attacks`
- A 发言保护 B：如果出现“相信/保/站边 B”，记录 `defends`
- A 和 B 都宣称预言家：`counter_claims`

中文发言解析第一版不用太复杂，可以先从结构化决策的 `target` 和 `public_text` 提取。

### 13.6 图摘要 Prompt

不把整张图塞进 Prompt，只塞摘要：

```text
玩家关系摘要：
- 2号和7号连续两轮同票9号，疑似有阵营一致关系。
- 3号多次保护2号，但2号被查杀，3号狼面上升。
- 5号和8号均声称预言家，二者不能同真。
- 6号在关键轮次切割已知狼人4号，可能是倒钩，也可能是好人。
```

### 13.7 验证

测试：

- 同票事件生成 `votes_with`。
- 投票事件生成 `votes_against`。
- 对跳事件生成 `counter_claims`。
- 图摘要不会超过指定长度。
- belief 能根据图关系调整 wolf_prob。

## 14. Background Note Agent 后台笔记维护

### 14.1 目标

ideas 里提到“后台 forked agent 维护结构化笔记”。这是一个不错的增强，但不建议第一优先级。

它的目标：

- 主 Agent 专注决策。
- 后台 Note Agent 负责整理局势笔记。
- 每轮行动前主 Agent 读取最新笔记。

### 14.2 为什么不是优先级最高

因为当前已经有 `AgentMemoryV2` 和 `BeliefStateV2`，可以先用确定性代码维护结构化笔记。

后台 LLM note agent 会增加：

- token 成本。
- 延迟。
- 不稳定性。
- 信息泄露风险。

### 14.3 推荐设计

第一版：

```text
deterministic memory updater
```

第二版：

```text
LLM note agent only after day end
```

不要每次行动都调用 note agent。

### 14.4 Note Schema

```python
@dataclass(slots=True)
class FieldNotes:
    game_state: dict
    player_models: dict[int, dict]
    key_events: list[dict]
    current_focus: list[str]
    self_strategy: dict
```

### 14.5 验证

测试：

- note 只基于可见信息更新。
- note 不覆盖人工规则生成的确定事实。
- note 更新失败不影响主 Agent 决策。

## 15. 人机混战

### 15.1 目标

人机混战是加分项，但不是 Agent 层主线。

目标：

- 部分玩家由真人控制。
- 其余玩家由 Agent 控制。
- 真人只看到自己身份权限内的信息。
- 规则层仍然通过统一 `act()` 调用。

### 15.2 HumanAgent

```python
class HumanAgent:
    async def act(self, request: ActionRequest) -> ActionResponse:
        # 等待 UI 提交输入
        ...
```

### 15.3 与 Agent v2 的关系

HumanAgent 不需要 memory、belief 和 skill。

但它的行动也应进入：

- game archive
- review
- leaderboard 可选排除

### 15.4 优先级

建议低优先级。

原因：

- 主要评分点是 Agent。
- 人机混战前端工作量高。
- 先把 selfplay/review/experience 做好更能体现 Agent 调优能力。

## 16. 与现有规则层的兼容设计

### 16.1 规则层不需要知道新增模块

新增模块不应该改变规则层。

规则层仍然只负责：

- 回合流转。
- 夜间行动。
- 发言。
- 投票。
- 胜负判定。
- observation 构造。
- ActionResponse 合法执行。

Agent v2 新增能力都在规则层之外：

```text
Agent runtime
Selfplay runner
Archive recorder
Review generator
Experience extractor
Leaderboard aggregator
```

### 16.2 Selfplay 如何运行规则层

Selfplay 可以作为规则层的调用者，而不是规则层的一部分。

```text
selfplay.py
→ 创建游戏配置
→ 创建 Agent 列表
→ 调用现有 engine / runner
→ 收集输出
```

如果当前项目已有命令行或测试 helper 跑一局，则 selfplay 应复用它。

### 16.3 Agent 层新增 recorder

Agent v2 runtime 可以接受可选 recorder：

```python
class AgentV2Runtime:
    def __init__(..., decision_recorder=None, trace_recorder=None):
        ...
```

如果没有 recorder，照常运行。

这样不会影响现有规则层和测试。

## 17. Prompt 与 Skill 注入细节

### 17.1 Skill 注入原则

用户已明确要求：

- 游戏规则是通用 skill，每个角色都要注入。
- 其他 skill 只能根据角色注入。
- 不需要 skill 优先级。

后续继续遵守：

```text
common/game_rules.md
common/output_schema.md
role/action matching skills
```

### 17.2 长期记忆与 skill 的区别

Skill：

- 稳定策略。
- 手写或人工确认。
- 作为 Prompt 的主要策略依据。

Long-term memory：

- 多局经验沉淀。
- 可以自动生成。
- 作为补充提示。
- 不应覆盖 skill。

注入顺序建议：

```text
1. 通用游戏规则 skill
2. 输出格式 skill
3. 角色 Markdown skill
4. 当前行动相关经验/长期记忆
5. 当前 observation / memory / belief
```

### 17.3 Prompt 长度控制

每次 Prompt 不应注入全部经验。

建议限制：

- 通用 skill：固定注入。
- 角色 skill：按 role + action 注入。
- 长期记忆：最多 5 条。
- experience card：最多 3 张，而且只注入抽象 lesson。
- field notes：只注入摘要，不注入全量日志。

## 18. 测试设计

### 18.1 单元测试

新增测试文件建议：

```text
tests/test_agent_v2_archive.py
tests/test_agent_v2_selfplay.py
tests/test_agent_v2_experience.py
tests/test_agent_v2_leaderboard.py
tests/test_agent_v2_reasoning.py
```

### 18.2 Archive 测试

- `DecisionArchive` 可以从 `AgentContext` 构造。
- archive 可以写入 JSON。
- archive 可以读回。
- prompt_messages 存在。
- raw_output 存在。
- policy_adjustments 存在。
- 不可见信息不进入 observation_summary。

### 18.3 Selfplay 测试

- fake model 跑 2 局。
- 每局有目录。
- 每局有 archive。
- summary 有胜率。
- 某局异常不影响后续局，或至少能记录失败。

### 18.4 Review 测试

- 女巫毒错好人识别为 mistake。
- 猎人射中狼人识别为 highlight。
- 票出狼人提高 vote score。
- fallback 降低 decision score。
- review.md 能生成。

### 18.5 Experience 测试

- 每个玩家生成一张 card。
- card 角色正确。
- card 存到对应 role 文件。
- card 中有 lesson。
- card 可被 long memory 读取。

### 18.6 Long Memory 测试

- 5 张相似 card 合并成 recurring mistake。
- 输出 role markdown。
- Prompt 注入条数受限。
- 不把具体历史玩家 id 当作下一局事实。

### 18.7 Leaderboard 测试

- 多个 summary 可以聚合。
- markdown 表格可生成。
- 缺字段时使用默认值。
- 同 seeds 比较时记录 seeds 范围。

### 18.8 ToT / GoT 测试

- 关键 action 启用 ToT。
- 普通 action 不启用 ToT。
- ToT 解析失败 fallback。
- 投票关系生成 graph edge。
- 图摘要长度受控。

## 19. 分阶段实施计划

### Phase 0：稳定当前 Agent v2

目标：

- 修复当前已发现的小问题。
- 保证已有测试继续通过。

任务：

- 检查女巫 save / poison skill 是否有 `requires`。
- 防止模型输出的 `selected_skill` 覆盖系统注入的 `selected_skills`。
- 清理无用 dependency group。
- 确保 `DecisionRecord.selected_skill` 记录系统实际注入的 skill。

验收：

- 全量测试通过。
- Agent 决策日志中的 skill 与 `ctx.selected_skills` 一致。

### Phase 1：Archive

目标：

- 保存完整单局 trace。

任务：

- 新增 `archive.py`。
- 新增 `DecisionArchive` 和 `GameArchive`。
- 新增 `AgentTraceRecorder`。
- runtime 可选写 trace。
- 单局结束后生成 `archive.json`。

验收：

- 跑一局后有 `archive.json`。
- 每次决策都有 observation、skills、raw_output、final_response。
- 信息隔离测试通过。

### Phase 2：Selfplay

目标：

- 自动跑多局。

任务：

- 新增 `selfplay.py`。
- 新增 `SelfPlayConfig`。
- 支持 seed。
- 支持 output_dir。
- 支持 skill_dir。
- 生成 summary。

验收：

- fake model 跑 2 局通过。
- 真实配置可跑 5 局。
- `summary.json` 和 `summary.md` 生成。

### Phase 3：Review 增强

目标：

- 复盘质量从“简单总结”提升到“决策级评分”。

任务：

- 新增 mistake_type。
- 识别关键转折点。
- 计算 player score。
- 计算 skill score。
- 生成 review.md。

验收：

- 至少能识别女巫毒错、猎人带错、票出狼人、fallback。
- review.md 包含关键转折点和改进建议。

### Phase 4：Experience Cards

目标：

- 每局结束后沉淀角色经验。

任务：

- 新增 `experience.py`。
- 从 review 生成 card。
- 按角色写入 `data/experiences/{role}/cards.jsonl`。
- card 可读回。

验收：

- 每局每个玩家生成一张 card。
- 失败方有 lesson。
- card 引用相关 skill。

### Phase 5：Leaderboard

目标：

- 对比不同版本。

任务：

- 新增 `leaderboard.py`。
- 从多个 selfplay summary 聚合。
- 输出 json 和 markdown。
- 支持版本名、skill_dir、model_name。

验收：

- 至少比较两个版本。
- markdown 表格可用于答辩。

### Phase 6：Long Memory

目标：

- 跨局经验沉淀。

任务：

- 新增 `long_memory.py`。
- 按角色聚合经验。
- 输出 role long memory。
- Prompt 可选注入长期原则。

验收：

- 5 张经验卡生成长期记忆。
- Prompt 注入不超过长度限制。

### Phase 7：Skill Update Suggestions

目标：

- 从复盘生成 Markdown skill 修改建议。

任务：

- 从 long memory 生成 suggestions。
- 指向具体 skill 文件。
- 不自动写回。

验收：

- suggestions.md 可读。
- 每条建议有来源 card 或 game。

### Phase 8：ToT / GoT

目标：

- 提升关键动作质量。

任务：

- ToT prompt for critical actions。
- GoT relation graph。
- archive 记录 ToT candidates。

验收：

- 关键 action 有候选比较。
- review 能统计 ToT 是否改善评分。

## 20. 答辩展示设计

### 20.1 展示主线

答辩时建议按以下顺序讲：

```text
1. 规则层与 Agent 层解耦
2. Agent v2 图式决策链
3. Markdown skill 角色策略
4. 信息隔离与 policy 校验
5. 多局 selfplay 数据收集
6. 单局 review 复盘
7. experience cards 经验沉淀
8. leaderboard 证明调优有效
```

### 20.2 可展示材料

建议准备：

- 一局完整对局回放。
- 某个关键决策的 Prompt / raw output / policy 修正。
- 一份 review.md。
- 一张 experience card。
- 一份 long_memory.md。
- 一张 leaderboard 表。
- 一段 skill 更新前后对比。

### 20.3 高分表达

可以这样表达：

```text
我们没有让大模型直接控制游戏状态，而是把规则层作为稳定协议层。Agent 只能通过 ActionRequest 接收自己身份权限内的信息，并通过 ActionResponse 返回合法动作。

Agent v2 内部采用图式决策链，将观察、短期记忆、局势信念、Markdown skill、Prompt、模型调用、解析、policy 校验和日志拆成独立节点。

在此基础上，我们构建了多局自博弈闭环：每局完整归档 Agent 输入输出和规则事件，赛后生成决策级复盘，再沉淀成按角色划分的经验卡片和长期记忆，最后通过 Leaderboard 对比不同策略版本的效果。
```

## 21. 风险与取舍

### 21.1 Token 成本

风险：

- ToT、review、experience、long memory 都可能调用 LLM。

取舍：

- 第一版 review 和 experience 尽量规则生成。
- ToT 只用于关键 action。
- 长期记忆只在 selfplay run 结束后生成。

### 21.2 策略过拟合

风险：

- 某几局经验可能不可靠。
- 自动写回 skill 可能引入坏策略。

取舍：

- 第一版只生成 skill suggestions。
- long memory 记录 evidence_count 和 confidence。
- Leaderboard 用多局验证。

### 21.3 信息泄露

风险：

- 经验卡和 review 包含最终身份。
- 如果原样注入下一局，可能导致 Prompt 学到不合理信息。

取舍：

- 下一局只注入抽象策略，不注入历史具体玩家身份。
- archive 区分当时 observation 和赛后 final_state。
- 增加信息隔离测试。

### 21.4 工程复杂度

风险：

- 一次性做 selfplay、review、experience、long memory、leaderboard 会过大。

取舍：

- 按 Phase 实现。
- 每阶段都有独立验收。
- 优先做可展示、可验证的模块。

## 22. 最小可交付版本

如果时间有限，最小高价值版本建议只做：

```text
1. Archive
2. Selfplay
3. Review 增强
4. Experience Cards
5. Leaderboard
```

不要急着做：

```text
1. LangGraph 迁移
2. 自动改 skill
3. 后台 Note Agent
4. 人机混战
5. 多轮 ToT
```

原因：

- 前五项直接对应评分标准中的可观测、评测、Agent 调优。
- 后五项更酷，但工程风险更高，短期内未必能证明效果。

## 23. 最终验收清单

### 23.1 Agent 运行

- [ ] Agent v2 仍兼容 `ActionRequest -> ActionResponse`。
- [ ] 不侵入规则层。
- [ ] 所有角色能完成一局。
- [ ] policy 能处理非法模型输出。

### 23.2 Skill

- [ ] 通用游戏规则 skill 注入所有角色。
- [ ] 输出格式 skill 注入所有角色。
- [ ] 角色 skill 只按角色注入。
- [ ] 条件 skill 有明确 requires。
- [ ] 日志记录实际注入 skill。

### 23.3 Archive

- [ ] 每次决策保存 observation summary。
- [ ] 每次决策保存 selected_skills。
- [ ] 每次决策保存 raw_output。
- [ ] 每次决策保存 parsed_decision。
- [ ] 每次决策保存 final_response。
- [ ] 每次决策保存 policy_adjustments。
- [ ] archive 中 final_state 与 decision observation 分离。

### 23.4 Selfplay

- [ ] 可配置局数。
- [ ] 可配置 seed。
- [ ] 可配置 skill_dir。
- [ ] 每局有输出目录。
- [ ] run 有 summary。

### 23.5 Review

- [ ] 有玩家评分。
- [ ] 有阵营评分。
- [ ] 有关键转折点。
- [ ] 有 mistake_type。
- [ ] 有 skill 表现。
- [ ] 有改进建议。

### 23.6 Experience

- [ ] 每个玩家生成 card。
- [ ] card 按角色保存。
- [ ] card 有 lesson。
- [ ] card 有 related_skills。
- [ ] card 可用于 long memory。

### 23.7 Long Memory

- [ ] 按角色聚合。
- [ ] 输出 markdown。
- [ ] 记录 evidence_count。
- [ ] Prompt 注入长度受控。

### 23.8 Leaderboard

- [ ] 多版本对比。
- [ ] 多局统计。
- [ ] 输出 markdown 表格。
- [ ] 记录 fallback / policy_adjusted。
- [ ] 记录 vote / skill 指标。

## 24. 总结

当前 Agent v2 已经完成了很重要的基础设施：规则层兼容、图式 runtime、Markdown skill 和基本日志。

相比 ideas，剩余最重要的是把“单局会玩”升级成“多局可评测、可复盘、可沉淀、可调优”。

推荐实施路线：

```text
Archive
→ Selfplay
→ Review
→ Experience
→ Leaderboard
→ Long Memory
→ Skill Suggestions
→ ToT / GoT
```

这条路线既能体现 Agent 层设计能力，也能形成可量化展示材料，最符合本课题的评分重点。

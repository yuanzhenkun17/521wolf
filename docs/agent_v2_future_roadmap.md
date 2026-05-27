# Agent v2 后续能力详细设计文档

本文档用于规划 `agent` 后续建设方向。它基于当前已实现的 Agent v2、`docs/ideas.md` 中的想法池，以及当前比赛评分标准，详细拆解还未实现或只实现雏形的能力。

目标不是一次性全部实现，而是把后续方向整理成一套可选择、可排期、可验证、可答辩展示的设计方案。

## 1. 当前状态概览

当前 Agent v2 已经具备以下能力：

- 与现有规则层兼容，仍然通过 `ActionRequest -> ActionResponse` 交互。
- 使用图式 runtime：
  - observe
  - memory
  - belief
  - skill routing
  - prompt
  - llm
  - parse
  - policy
  - log
- 使用 `AgentMemoryV2` 维护本局结构化记忆。
- 使用 `BeliefStateV2` 维护主观身份概率和关系信息。
- 使用 Markdown skill 作为策略库。
- 有通用 `game_rules` 和 `output_schema` skill。
- role skill 按角色注入。
- policy 使用 per-action validator 修正非法动作。
- decision log 记录扩展字段。
- review 模块有初步评分和报告能力。
- unittest 全量测试通过。

但是，对比 `docs/ideas.md`，当前仍缺少几个更高阶的 Agent 能力：

- 多局自博弈数据收集。
- 每局结束后的经验卡片。
- 跨局长期记忆沉淀。
- 角色经验池。
- ToT / GoT 强推理。
- 更完整的赛后复盘和 bad case 诊断。
- Leaderboard。
- 多版本 Agent 对战。
- 经验自动写回 Markdown skill。
- 人机混战。

## 2. 后续建设总目标

后续 Agent v2 可以沿着一个核心闭环推进：

```text
单局对局
→ 决策日志
→ 赛后复盘
→ 经验卡片
→ 多局统计
→ 策略版本对比
→ Markdown skill 调优
→ 新版本 Agent
→ 再次对局
```

最终希望形成：

```text
一个可自博弈、可复盘、可评价、可调优、可版本对比的 AI 狼人杀 Agent Team。
```

## 3. 后续模块总览

建议新增或增强以下模块：

```text
agent/
  selfplay.py
  archive.py
  review.py
  experience.py
  leaderboard.py
  evaluation.py
  evolution.py
  reasoning/
    __init__.py
    tot.py
    got.py
    critique.py
  experience_store/
    werewolf/
    seer/
    witch/
    hunter/
    villager/
    guard/
    white_wolf_king/
  skill_versions/
    v1/
    v2/
    experiments/
```

不一定全部马上实现。建议按阶段推进。

## 4. 多局自博弈数据收集

### 4.1 目标

当前系统可以跑一局游戏，但还没有一个专门的自博弈 runner，用来自动跑多局、收集数据、生成统计结果。

自博弈模块目标：

- 自动运行 N 局。
- 每局使用指定 Agent 版本。
- 每局保存完整规则日志。
- 每局保存 Agent 决策日志。
- 每局保存 review 报告。
- 汇总胜率、平均分、技能命中率、投票准确率等指标。

### 4.2 新增文件

建议新增：

```text
agent/selfplay.py
```

### 4.3 核心接口

```python
@dataclass(slots=True)
class SelfPlayConfig:
    games: int = 20
    max_days: int = 20
    seed_start: int = 1
    agent_version: str = "v2"
    log_dir: Path = Path("logs/selfplay")
    model_name: str = ""
    skill_dir: Path | None = None


@dataclass(slots=True)
class SelfPlayResult:
    games: list[dict]
    summary: dict
```

```python
async def run_selfplay(config: SelfPlayConfig) -> SelfPlayResult:
    ...
```

### 4.4 单局输出目录

建议输出：

```text
logs/selfplay/run_2026xxxx/
  config.json
  summary.json
  summary.md
  game_001/
    game.jsonl
    game.txt
    agent.jsonl
    archive.json
    review.json
    review.md
  game_002/
    ...
```

### 4.5 每局记录内容

每局记录：

- `game_id`
- `seed`
- `roles`
- `winner`
- `days`
- `event_count`
- `decision_count`
- `fallback_count`
- `policy_adjusted_count`
- `average_confidence`
- `werewolf_win`
- `villager_win`
- `review_score`

### 4.6 汇总指标

```json
{
  "games": 20,
  "werewolf_win_rate": 0.55,
  "villager_win_rate": 0.45,
  "avg_days": 3.8,
  "avg_decision_score": 7.2,
  "avg_vote_accuracy": 0.61,
  "avg_skill_accuracy": 0.68,
  "fallback_rate": 0.04,
  "policy_adjusted_rate": 0.07
}
```

### 4.7 验证方式

测试要求：

- 能跑 2 局 dummy model 自博弈。
- 每局都有 `game.jsonl`、`agent.jsonl`、`review.json`。
- summary 中胜率字段存在。
- 不要求真实 LLM 接口即可测试。

## 5. 完整记忆归档 Archive

### 5.1 目标

当前规则日志和 Agent 日志分散存在，缺少一个统一的完整归档。

完整归档用于：

- 复盘。
- bad case 定位。
- prompt 调试。
- 训练/评测数据集。
- 答辩展示。

### 5.2 新增文件

```text
agent/archive.py
```

### 5.3 Archive 内容

每局生成一个 `archive.json`：

```json
{
  "game_id": "game001",
  "seed": 1,
  "roles": {
    "1": "werewolf",
    "2": "seer"
  },
  "winner": "villagers",
  "events": [],
  "decisions": [],
  "prompts": [],
  "raw_outputs": [],
  "policy_adjustments": [],
  "fallbacks": [],
  "final_state": {}
}
```

### 5.4 每次决策归档

```json
{
  "index": 42,
  "player_id": 5,
  "role": "witch",
  "day": 2,
  "phase": "night",
  "action_type": "witch_act",
  "observation_summary": {},
  "memory_context": {},
  "belief_context": {},
  "selected_skills": [
    "game_rules",
    "output_schema",
    "witch_poison"
  ],
  "prompt_messages": [],
  "raw_output": "...",
  "parsed_decision": {},
  "final_response": {},
  "source": "llm",
  "policy_adjustments": [],
  "errors": []
}
```

### 5.5 当前需要补的 runtime 能力

目前 `DecisionRecord` 里有很多字段，但没有完整 prompt messages 和 observation summary。

可以新增一个可选 recorder：

```python
class AgentTraceRecorder:
    def record_context(self, ctx: AgentContext) -> None:
        ...
```

也可以扩展 `AgentDecisionRecorder`，但不建议直接污染 v1。

### 5.6 验证方式

- 单次 `act()` 后能产出 trace record。
- trace record 包含 prompt messages 和 raw output。
- trace 不泄露规则层不可见的 `GameState`。

## 6. 中期记忆：每局经验卡片

### 6.1 目标

中期记忆不是每轮都总结，而是在整局结束后生成经验卡片。

原因：

- 单次发言或投票很难判断好坏。
- 一局结束后才知道胜负。
- 可以根据最终身份、胜负和关键节点评价决策。

### 6.2 新增文件

```text
agent/experience.py
```

### 6.3 ExperienceCard 数据结构

```python
@dataclass(slots=True)
class ExperienceCard:
    game_id: str
    player_id: int
    role: str
    team: str
    outcome: str
    summary: str
    key_decisions: list[dict]
    lessons: list[str]
    avoid_next_time: list[str]
    reusable_strategies: list[str]
    related_skills: list[str]
    score: float
```

### 6.4 JSON 示例

```json
{
  "game_id": "game_042",
  "player_id": 3,
  "role": "werewolf",
  "team": "werewolves",
  "outcome": "lose",
  "summary": "首日悍跳预言家失败，发言逻辑漏洞导致被放逐。",
  "key_decisions": [
    {
      "day": 1,
      "action_type": "sheriff_speak",
      "selected_skill": "werewolf_fake_seer",
      "action": "悍跳预言家并给真预言家查杀",
      "expected_outcome": "扰乱好人视野",
      "actual_result": "逻辑不自洽，被多数玩家怀疑",
      "lesson": "悍跳前需要检查发言位置和队友铺垫"
    }
  ],
  "lessons": [
    "狼人悍跳不能只给结论，需要查验链和后续警徽流。",
    "发言位置靠后时，悍跳风险更高。"
  ],
  "avoid_next_time": [
    "没有队友铺垫时强行悍跳。",
    "给出无法解释的查验理由。"
  ],
  "reusable_strategies": [
    "如果真预言家已跳，狼人可以选择倒钩而不是对跳。"
  ],
  "related_skills": [
    "werewolf_fake_seer",
    "werewolf_deep_wolf"
  ],
  "score": 4.2
}
```

### 6.5 生成方式

两种模式：

#### 规则型生成

优点：

- 稳定。
- 不依赖 LLM。
- 适合测试。

缺点：

- 总结质量有限。

#### LLM 复盘生成

优点：

- 文字更像人。
- 能总结策略。

缺点：

- 成本更高。
- 需要防止胡编。

建议：

第一版先规则型，后续增加 LLM review。

### 6.6 存储目录

```text
memories/experience/
  werewolf/
    game_001_p3.json
  seer/
    game_001_p5.json
  witch/
    game_001_p6.json
```

或者：

```text
logs/selfplay/run_xxx/game_001/experience/
```

### 6.7 验证方式

- 给定一局 review 和 decisions，能生成每个玩家一张 card。
- 失败方玩家的 card 包含至少一个 lesson。
- card 按角色存储。

## 7. 长期记忆 Dream / Consolidate

### 7.1 目标

长期记忆是跨多局经验的沉淀。

触发条件：

- 某角色经验卡片数量 >= 5。
- 或一次 selfplay run 结束。

目标：

- 合并相似经验。
- 统计高频失误。
- 生成长期策略原则。
- 给 Markdown skill 提供修改建议。

### 7.2 新增接口

```python
def consolidate_role_experiences(role: Role, cards: list[ExperienceCard]) -> RoleLongTermMemory:
    ...
```

### 7.3 LongTermMemory 数据结构

```python
@dataclass(slots=True)
class RoleLongTermMemory:
    role: str
    total_games: int
    win_rate: float
    recurring_mistakes: list[str]
    effective_strategies: list[str]
    low_value_strategies: list[str]
    skill_update_suggestions: dict[str, list[str]]
```

### 7.4 示例输出

```json
{
  "role": "witch",
  "total_games": 12,
  "win_rate": 0.58,
  "recurring_mistakes": [
    "毒药过早使用导致后期无法处理悍跳狼",
    "毒杀疑似预言家导致好人信息链断裂"
  ],
  "effective_strategies": [
    "首夜救人平均提升好人存活轮次",
    "第二天结合票型再毒人更稳定"
  ],
  "low_value_strategies": [
    "第一天无强证据盲毒"
  ],
  "skill_update_suggestions": {
    "witch_poison": [
      "毒人前检查目标是否有预言家行为特征",
      "如果目标只是划水，不应作为第一毒杀目标"
    ]
  }
}
```

### 7.5 是否自动写回 skill

不建议第一版自动改 Markdown skill。

建议第一版生成 patch 建议：

```text
建议更新 skills/witch/poison.md：
- 增加规则：毒人前检查目标是否疑似预言家。
- 增加规则：仅划水不是强毒理由。
```

第二版再考虑自动写回。

## 8. Markdown Skill 自动/半自动更新

### 8.1 目标

把复盘经验沉淀到 Markdown skill。

当前 skill 已经 Markdown 化，这是很好的基础。

### 8.2 更新模式

#### 人工确认模式

系统生成建议，人手确认。

```text
review → suggestions → human accepts → update .md
```

#### 半自动 patch 模式

系统生成 patch，但不自动应用。

```diff
## 策略原则
+ 毒人前检查目标是否有预言家行为特征。
+ 仅划水不是强毒理由。
```

#### 自动写回模式

不建议早期做。风险：

- 策略漂移。
- LLM 生成坏规则。
- 版本不可控。

### 8.3 Skill 版本目录

建议后续支持：

```text
agent/skill_versions/
  v1/
  v2/
  experiment_witch_poison/
```

或者：

```text
skills/
  current/
  versions/
```

但当前不建议马上改目录结构，先把默认 `skills/` 跑稳。

## 9. ToT 强推理

### 9.1 目标

Tree of Thoughts 用于关键决策，不适合每次都启用。

关键决策包括：

- 女巫是否毒人。
- 猎人是否开枪。
- 白狼王是否自爆。
- 预言家是否跳身份。
- 放逐投票。
- PK 投票。

### 9.2 新增目录

```text
agent/reasoning/
  __init__.py
  tot.py
```

### 9.3 ToT 流程

```text
生成候选动作
→ 分析每个动作收益
→ 分析每个动作风险
→ 预测其他玩家反应
→ 选择最佳动作
→ 输出最终 JSON
```

### 9.4 数据结构

```python
@dataclass(slots=True)
class CandidateThought:
    target: int | None
    choice: str | None
    public_text: str
    private_reasoning: str
    expected_gain: float
    risk: float
    confidence: float
```

```python
@dataclass(slots=True)
class ToTResult:
    candidates: list[CandidateThought]
    selected_index: int
    final_decision: dict
```

### 9.5 集成方式

新增 node：

```text
reasoning_node
```

放在：

```text
prompt_node
→ llm_node
```

或者只在 `llm_node` 前替换 prompt。

更推荐：

```text
skill_router_node
→ reasoning_router_node
→ prompt_node
```

如果当前 action 是关键动作，就构造 ToT prompt。

### 9.6 MVP 方案

第一版不真正多轮调用 LLM，只在单次 prompt 中要求：

```text
先列出 3 个候选动作，再选择最终动作。
```

解析仍只取最终 JSON。

第二版再做多轮 LLM 调用。

## 10. GoT 玩家关系图

### 10.1 目标

Graph of Thoughts 用于玩家关系推理。

当前 `BeliefStateV2` 有 relations，但还没有形成显式图推理。

### 10.2 关系类型

```text
attacks
defends
votes_against
votes_with
claims_same_role
counter_claims
protects
follows
cuts_teammate
possible_teammate
```

### 10.3 图结构

```python
@dataclass(slots=True)
class PlayerRelation:
    source: int
    target: int
    relation_type: str
    weight: float
    evidence: str
    day: int
```

```python
@dataclass(slots=True)
class PlayerGraph:
    nodes: dict[int, PlayerNode]
    edges: list[PlayerRelation]
```

### 10.4 推理指标

- 同票次数。
- 互保次数。
- 互踩次数。
- 对跳关系。
- 关键时刻同向投票。
- 是否和已知狼有强关系。

### 10.5 Prompt 注入

```text
玩家关系图摘要：
- P2 和 P7 连续两次同票 P9，疑似阵营一致。
- P3 多次保护 P2，且 P2 被查杀，P3 狼面上升。
- P5 与 P8 对跳预言家，二者不能同为真。
```

### 10.6 验证方式

- 给定 public log，图中能产生 votes_with relation。
- 对跳预言家时产生 counter_claim relation。
- belief top_suspicions 受图关系影响。

## 11. Self-Critique 低置信度复核

### 11.1 目标

当模型输出低置信度或 policy 即将修正时，让 Agent 自我复核。

触发条件：

- `confidence < 0.4`
- `policy_adjusted`
- `fallback`
- 关键技能动作

### 11.2 流程

```text
初始决策
→ 检查置信度
→ 如果低置信度，构造 critique prompt
→ 让模型指出风险
→ 生成修正决策
→ 再走 policy
```

### 11.3 风险

- token 成本上升。
- 决策时间变长。
- 需要避免无限重试。

### 11.4 建议

只对关键 action 开启：

- `WITCH_ACT`
- `HUNTER_SHOOT`
- `WHITE_WOLF_EXPLODE`
- `EXILE_VOTE`
- `PK_VOTE`

## 12. Review 复盘增强

### 12.1 当前不足

当前 review 能粗略评分，但还不够深：

- 不会分析关键轮次为何输。
- 不会做反事实。
- 不会解释某个 skill 是否有效。
- 不会对 Markdown skill 给出修改建议。

### 12.2 增强方向

#### 关键决策识别

识别：

- 女巫毒人。
- 猎人开枪。
- 白狼王自爆。
- 放逐投票。
- PK 投票。
- 预言家跳身份。

#### 决策质量评分

```python
@dataclass(slots=True)
class DecisionScore:
    decision_index: int
    player_id: int
    action_type: str
    selected_skill: str
    score: float
    reason: str
    mistake_type: str | None
```

#### mistake_type

```text
wrong_target
missed_wolf
poisoned_good
shot_good
revealed_private_info
low_confidence
fallback
policy_adjusted
bad_vote
bad_claim
```

### 12.3 反事实推演

示例：

```text
如果女巫没有毒 P5：
- P5 作为真预言家可能在第3天继续报查验。
- 好人信息链不会断裂。
- 狼人需要额外一刀处理 P5。
```

第一版可以规则模板生成，不必 LLM。

### 12.4 Review 报告结构

```markdown
# 游戏复盘报告

## 基本信息

## 胜负概览

## 阵营表现

## 关键转折点

## 每个 Agent 评分

## 关键错误

## Skill 表现

## 反事实分析

## 改进建议

## 建议更新的 Markdown Skill
```

## 13. Leaderboard

### 13.1 目标

用于比较不同 Agent 版本、不同 skill 版本、不同模型。

### 13.2 新增文件

```text
agent/leaderboard.py
```

### 13.3 数据结构

```python
@dataclass(slots=True)
class LeaderboardEntry:
    version: str
    games: int
    werewolf_win_rate: float
    villager_win_rate: float
    avg_score: float
    avg_vote_accuracy: float
    avg_skill_accuracy: float
    fallback_rate: float
    policy_adjusted_rate: float
```

### 13.4 输出

```markdown
| 版本 | 局数 | 狼胜率 | 好人胜率 | 平均分 | 投票准确率 | 技能准确率 | fallback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v1-basic | 20 | 55% | 45% | 6.1 | 43% | 50% | 8% |
| v2-md-skill | 20 | 48% | 52% | 7.4 | 61% | 67% | 3% |
```

## 14. 多版本 Agent 对战

### 14.1 版本类型

可以比较：

- v1 原始 agent。
- v2 Markdown skill agent。
- v2 + ToT。
- v2 + long-term memory。
- 不同模型。
- 不同 skill 目录。

### 14.2 配置

```json
{
  "versions": [
    {
      "name": "v2_base",
      "skill_dir": "skills"
    },
    {
      "name": "v2_exp_witch",
      "skill_dir": "experiments/witch_poison_v2"
    }
  ],
  "games_per_version": 20
}
```

### 14.3 注意

狼人杀本身有座位和身份随机性。

对比时要控制：

- seed。
- 角色分配。
- 模型。
- 温度参数。

否则结论不稳定。

## 15. 人机混战

### 15.1 目标

让某些 seat 由真人控制，其余由 Agent 控制。

### 15.2 规则层兼容

仍然实现：

```python
async def act(request: ActionRequest) -> ActionResponse:
    ...
```

真人玩家 agent：

```python
class HumanPlayerAgent:
    async def act(self, request):
        # 等待 UI 输入
        ...
```

### 15.3 UI 需求

需要新增：

- 玩家登录/选择座位。
- 仅显示该玩家可见信息。
- 行动请求弹窗。
- 发言输入框。
- 投票选择。
- 技能按钮。

### 15.4 当前优先级

不建议现在优先做。

原因：

- 工程量大。
- 主要评分点还是 Agent。
- 观战 UI 已经满足基础加分。

可以作为后期展示增强。

## 16. 优先级规划

### P0：稳定当前 v2

目标：

- 修复已发现的小问题。

任务：

- 给带条件 skill 加 `requires`。
- 防止模型输出的 `selected_skill` 覆盖系统注入 skill。
- 删除空 dependency group。

### P1：Selfplay + Archive

目标：

- 自动跑多局。
- 统一归档数据。

任务：

- `selfplay.py`
- `archive.py`
- `AgentTraceRecorder`

### P2：Review 增强

目标：

- 复盘更像评分系统。

任务：

- decision-level score。
- mistake_type。
- skill-level summary。
- markdown report。

### P3：Experience Cards

目标：

- 每局结束后提取角色经验。

任务：

- `experience.py`
- 按角色存储经验卡片。

### P4：Leaderboard

目标：

- 多版本可比较。

任务：

- `leaderboard.py`
- selfplay summary aggregation。

### P5：Long-term Memory / Skill Update

目标：

- 跨局沉淀策略。

任务：

- consolidate。
- skill update suggestions。
- patch proposal。

### P6：ToT / GoT

目标：

- 提升关键决策质量。

任务：

- `reasoning/tot.py`
- `reasoning/got.py`
- critical action routing。

## 17. 推荐近期三步

### 第一步：Selfplay Runner

优先实现：

```text
自动跑 5 局 → 输出 summary.json
```

这是后续所有复盘、经验、leaderboard 的基础。

### 第二步：Review Report

增强 `review.py`，让每局输出：

```text
review.json
review.md
```

### 第三步：Experience Card

从 review 中提取每个角色的经验卡片。

这三步完成后，项目会从：

```text
能玩一局
```

升级成：

```text
能自博弈、能评测、能沉淀经验
```

这非常贴合评分标准。

## 18. 答辩表达方式

可以这样讲：

```text
我们将狼人杀作为信息不对称多智能体博弈环境。规则层只负责游戏合法性，Agent v2 通过 ActionRequest / ActionResponse 与规则层解耦。

Agent v2 内部采用图式决策链：观察、记忆、信念、Markdown skill 注入、Prompt 构造、模型调用、结构化解析、policy 校验和决策日志。

Skill 全部使用 Markdown 管理，通用游戏规则对所有角色注入，角色策略只按身份注入，方便 Prompt 调优和策略版本对比。

下一步系统将形成自博弈闭环：多局对战、完整归档、赛后复盘、经验卡片、长期记忆和 Leaderboard，用数据驱动 Agent 调优。
```

## 19. 总结

当前 Agent v2 已经完成基础架构和 Markdown skill 化。

对比 ideas，后续最大缺口是：

- 多局数据闭环。
- 复盘评测深度。
- 经验沉淀。
- 版本对比。
- 强推理。

建议优先做：

```text
selfplay → archive → review → experience → leaderboard
```

这条路线最贴近评分标准，也最容易在答辩中展示 Agent 调优能力。


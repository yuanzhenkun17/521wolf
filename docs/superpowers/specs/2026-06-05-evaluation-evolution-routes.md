# Spec: 三路线评测与自进化边界

> 本文记录 2026-06-05 对“普通对局 + 评测复盘 / 批量对局评测 / 自进化”三条路线的产品与数据边界设计。
> 目标是让三条路线共享评测语言，但严格隔离数据用途：普通和批量评测负责展示与比较，自进化只学习自己的训练局，A/B 只验证不学习。

---

## 1. 背景

当前系统已经具备：

- 普通 UI 对局：可跑 AI-only / 观战 / 人机混战，并生成 events、decisions、archive、review。
- 批量 selfplay / evolution 训练链路：可批量跑局并产出统计、review、mid-memory / evidence。
- 角色自进化：以单角色为单位训练、归纳、生成候选版本、A/B 验证、promote / reject。

现在需要明确一个核心边界：

```text
普通对局和批量评测可以用于展示、复盘和排行榜；
自进化只能使用 evolution_training 自己产生的经验；
A/B 验证局只用于验证 candidate，不产生经验。
```

---

## 2. 设计原则

1. **共享评测语言**
   三条路线都使用同一套多维评测、关键决策复盘、反事实推演和结构化报告。

2. **隔离经验来源**
   自进化默认只消费 `evolution_training` 产生的 evidence，不消费普通对局、批量评测或 A/B 验证局。

3. **A/B 只验证**
   `evolution_ab_baseline` 和 `evolution_ab_candidate` 只用于 promote / reject，不写 experience、pattern、episodic memory。

4. **批量评测只比较两个维度**
   第一阶段只比较：
   - `model_id`
   - 单角色 `role/version_id`

   不比较 Agent 配置、Prompt 管线、Memory 策略、temperature、thinking mode。

5. **排行榜必须控制变量**
   模型榜只在角色版本相同的情况下比较模型；单角色版本榜只在模型相同、其他角色版本相同的情况下比较目标角色版本。

---

## 3. 三条路线

### 3.1 普通对局：`ordinary_game`

普通单局演示 + 评测复盘。

用途：

- 对局演示
- AI-only / 观战 / 人机混战
- 单局多维评测
- 关键决策复盘
- 反事实推演
- 结构化报告展示

产物：

```text
events
decisions
archive
evaluations
decision_reviews
counterfactuals
reports
review.json
```

不做：

```text
不写 evolution evidence
不写 patterns
不写 situational_records / decision_outcomes
不参与自进化
不触发 promote / reject
```

策略：

```text
run_type = ordinary_game
learning_eligible = false
leaderboard_scope = demo
promote_eligible = false
```

### 3.2 批量对局评测：`evaluation_batch`

批量跑局，用于验证模型或单角色版本能力。

用途：

- 验证不同 `model_id` 的能力
- 验证单角色 `role/version_id` 的能力
- 生成普通评测 Leaderboard
- 做同 seed 公平对比

第一阶段只比较：

```text
model_id
单角色 role/version_id
```

第一阶段不比较：

```text
Agent 配置
AgentRuntime 版本
Prompt 管线
Memory 策略
temperature
thinking_enabled
provider / base_url
```

产物：

```text
batch summary
evaluations
decision_reviews
counterfactuals
reports
model leaderboard
single-role version leaderboard
comparison_group 对比结果
```

不做：

```text
不写 evolution evidence
不写 patterns
不参与自进化
不触发 promote / reject
```

策略：

```text
run_type = evaluation_batch
learning_eligible = false
leaderboard_scope = benchmark
promote_eligible = false
```

### 3.3 自进化：`evolution_*`

自进化闭环由训练局和 A/B 验证局组成。

#### `evolution_training`

用途：

- 自进化训练
- 从训练局自然产生的好/坏决策中提取 evidence
- 归纳 experience_candidates / skill proposal 候选

允许使用：

```text
evolution_training 自然产生的 bad decisions
evolution_training 自然产生的 good decisions
evolution_training 中的高影响关键样本
```

不允许使用：

```text
ordinary_game bad case
evaluation_batch bad case
人工构造 bad case
手工导入 bad case
evolution_ab_baseline / evolution_ab_candidate 对局经验
```

策略：

```text
run_type = evolution_training
learning_eligible = true
leaderboard_scope = evolution_training
promote_eligible = false
```

#### `evolution_ab_baseline` / `evolution_ab_candidate`

用途：

- 固定 seed 验证 candidate 是否强于 baseline
- 作为 promote / reject 的依据
- 写 version history

不做：

```text
不产生 experience_candidates
不更新 patterns
不写 episodic memory
不参与下一轮 candidate 生成
```

策略：

```text
run_type = evolution_ab_baseline
learning_eligible = false
leaderboard_scope = evolution_ab
promote_eligible = false

run_type = evolution_ab_candidate
learning_eligible = false
leaderboard_scope = evolution_ab
promote_eligible = true only through paired A/B summary
```

---

## 4. 共享评测内核

三条路线共享：

```text
GameEngine
AgentRuntime
GameEvaluator
GameReviewer
ReportGenerator
```

统一评测数据流：

```text
events + decisions + roles + winner
  -> GameEvaluator.evaluate_game()
  -> GameReviewer.review_game()
  -> ReportGenerator.generate()
  -> evaluations / reviews / counterfactuals / reports
```

统一评测产物：

```text
GameEvaluation
PlayerEvaluation
DecisionReview
Counterfactual
GameReport
LeaderboardMetrics
```

关键要求：

```text
评测事实可以被所有 run_type 写入统一评测表；
学习事实只能由 learning_eligible = true 的 run 写入。
```

评测事实：

```text
evaluations
decision_reviews
counterfactuals
reports
leaderboard_metrics
```

学习事实：

```text
experience_candidates
skill_proposals
candidate_packages
promotion_decisions
rejected_proposals
```

第一阶段不把 `patterns`、`situational_records`、`decision_outcomes` 作为新学习事实写入；如果旧表保留，只作为 legacy/debug，不进入 runtime、Consolidation 或 Leaderboard。

---

## 5. 批量评测公平对比

批量评测支持可选公平对比组：

```text
comparison_group_id
comparison_type: model_id | role_version
```

### 5.1 模型对比

模型榜第一阶段只按 `model_id` 比较。

固定项：

```text
temperature = 1.0
thinking_enabled = false / not tracked
AgentRuntime = 当前固定实现
Prompt / Memory / Policy = 当前固定实现
```

公平对比要求：

```text
同 evaluation_set_id
同 seed_set_id
同 game_count
同 max_days
同 player_count
同 ruleset_version = werewolf_12p_v1
同 role_version_config
一局内所有 AI 玩家使用同一个 model_id
只改变 model_id
```

示例：

```text
comparison_group_id = compare_models_001
comparison_type = model_id

Batch A:
  model_id = qwen
  evaluation_set_id = model_eval_v1_20
  role_versions = baseline

Batch B:
  model_id = gpt
  evaluation_set_id = model_eval_v1_20
  role_versions = baseline
```

### 5.2 单角色版本对比

角色版本榜第一阶段做单角色版本榜，和当前单角色自进化路线保持一致。

公平对比要求：

```text
同 model_id
同 evaluation_set_id
同 seed_set_id
同 game_count
同 max_days
同 player_count
同 ruleset_version = werewolf_12p_v1
其他角色版本相同
只改变目标 role 的 version_id
```

示例：

```text
comparison_group_id = compare_witch_versions_001
comparison_type = role_version
target_role = witch

Batch A:
  model_id = qwen
  witch = baseline_witch
  other_roles = baseline
  evaluation_set_id = role_eval_v1_20

Batch B:
  model_id = qwen
  witch = witch_v2
  other_roles = baseline
  evaluation_set_id = role_eval_v1_20
```

---

## 6. 强弱判断指标

### 6.1 模型强弱

不要只看胜率。狼人杀胜率受身份分配、随机 seed、队友和对手影响较大。

模型强弱应基于：

```text
固定 evaluation_set_id
同一组 paired seeds
同一 ruleset_version
同一 scoring_version
同一 evaluator_config_hash
同一 role_version_config
同一局内所有 AI 玩家使用同一个 model_config_hash
```

第一阶段主指标不是胜率，而是综合能力分：

```text
role_score = weighted_base_score - risk_penalty
```

基础维度：

```text
speech_score
vote_score
skill_score
logic_score
team_score
risk_penalty
```

默认权重：

```text
speech_score: 25%
vote_score: 25%
skill_score: 20%
logic_score: 20%
team_score: 10%
risk_penalty: 从总分扣除，常规上限 30
```

无技能角色的 `skill_score` 是 `not_applicable`，权重重归一化；有技能角色本局未用技能不能自动免除评分，需要判断是否“该用而未用”。

模型榜聚合：

```text
先计算每个玩家 role_score
同类角色内部平均
角色类别之间固定等权平均
展示各角色类别分
胜率仅辅助展示
```

12 人固定规则下，角色类别来自 `ruleset_version = werewolf_12p_v1`。多个狼人/平民先类别内平均，预言家、女巫、猎人等神职按具体角色类别统计。

判定规则：

```text
formal + paired_seed + game_count >= 20 才能 rankable
少于 20 局只显示 diagnostic / data_sufficient=false
valid_game_rate >= 0.8
同一 leaderboard snapshot 不混 ruleset_version / scoring_version / evaluator_config_hash / evaluation_set_id
```

### 6.2 单角色版本强弱

单角色版本榜主指标：

```text
target_role_score
delta_vs_baseline
```

公平条件：

```text
同 evaluation_set_id
同 gameplay model_config_hash
同 target_role
同 target_slot
同 other_role_version_config_hash
只替换 target_role_version_id
必须包含当前 baseline 或指定 baseline run 作为参照
```

说明：

- 主排序看目标角色样本的 `role_score`。
- 其他角色只用于 safety gate，不进入目标主分。
- 多槽位角色（如狼人）进化的是通用角色版本；A/B 和榜单固定 target slot 验证。
- 普通对局中同角色多个槽位共享同一个 current baseline role version。

判定规则：

```text
formal + paired_seed + game_count >= 20
valid_game_rate >= 0.8
target_role_score_delta >= 0.05 才认为有实质提升
样本不足或非 paired 只能作为 demo/diagnostic
```

--- 

## 7. 自进化 A/B 晋升标准

批量评测中的单角色版本榜是开放 benchmark；自进化 A/B 是 promotion gate。

二者可以共享公式，但后果不同：

```text
evaluation_batch:
  read-only benchmark
  不改变 baseline
  不触发 promote/reject

evolution_ab:
  promotion gate
  只比较 parent baseline vs candidate
  触发 promote/reject
  写 version history
```

推荐默认晋升条件：

```text
minimum_pairs >= 20
valid_game_rate >= 0.8

target_role_score_delta >= +0.05
或者 win_rate_delta >= +0.10

fallback_rate_delta <= +0.03
policy_adjusted_rate_delta <= +0.05
non_target_role_score_delta >= -0.03
```

阈值应配置化，并写入 promotion decision。

A/B 失败语义：

```text
valid pairs 不足或 A/B 跑崩:
  round failed / candidate invalid
  不写 rejected_proposals

完整 A/B 但提升不明显:
  candidate rejected
  rejection_reason = insufficient_improvement
  proposal 写 rejected_proposals

核心分数提升但 safety gate 失败:
  candidate rejected
  rejection_reason = safety_gate_failed
  记录 failed_gates
```

A/B 验证局：

```text
跑结构化评分和必要风险复盘
不生成完整人类报告，除非 debug
不生成 experience_candidates
不生成 skill_proposals
不作为下一轮训练数据
```

---

## 8. ReviewService 与评分边界

统一评测链路：

```text
Game facts
  -> ReviewService
    -> MetricExtractor / GameEvaluator
    -> LLM structured judgments
    -> deterministic scorer
    -> GameReviewer
    -> ReportGenerator
```

硬边界：

```text
ReviewService 是报告、Leaderboard、EvidencePipeline 的唯一评测上游。
ReportGenerator 只组织展示文本，不重新计算评分。
EvidencePipeline 不绕过 ReviewService 直接读原始日志抽经验。
```

LLM 的职责：

```text
允许评估发言质量、推理一致性、关键决策上下文。
不允许直接决定最终分数。
如果发现评分缺口，只能输出 score_adjustment_suggestion。
最终 role_score 由 deterministic scorer 合成。
```

LLM judgment 必须结构化落库：

```text
judgment_id
game_id
player_id
dimension
prompt_version
evaluator_config_hash
input_refs
raw_json
normalized_fields
validator_status
created_at
```

失败处理：

```text
LLM judgment schema 校验失败最多重试 1-2 次。
仍失败则 judgment invalid。
missing/failed 维度不能静默重归一化。
not_applicable 维度可以重归一化。
required 维度缺失超过阈值时 role_sample invalid。
```

状态拆分：

```text
evaluation_status
review_status
report_status
evidence_status
```

不同路线的要求：

```text
leaderboard 至少需要 scoring/risk completed。
ordinary full report 需要 review/report completed，否则显示 partial。
evolution candidates 需要 evaluation + structured key decision review completed。
A/B promotion 至少需要 scoring/risk completed。
```

---

## 9. Leaderboard、Seed Set、Ruleset 与 Version

### 9.1 Leaderboard Snapshot

Leaderboard 不实时聚合 review tables，必须写快照：

```text
review facts = 原始评测事实
leaderboard snapshots = 聚合事实
```

快照必须记录：

```text
snapshot_id
scope = model | role_version
evaluation_set_id
seed_set_id
ruleset_version
scoring_version
evaluator_config_hash
included_run_ids
excluded_sample_ids
exclusion_reasons
created_at
```

不同 `ruleset_version`、`scoring_version`、`evaluator_config_hash`、`evaluation_set_id` 的结果不混排。

### 9.2 Seed Set

正式 seed set 存在 `wolf.db`，不可变，可导出为 artifact。

```text
seed_set_id
purpose = training | ab | model_leaderboard | role_leaderboard
seeds_json
ruleset_version
created_at
immutable = true
```

要求：

```text
training seeds / A-B seeds / leaderboard seeds 互不重叠。
seed_set_id 不可原地修改，变更必须新建 v2。
正式 leaderboard 和 promotion decision 必须记录 seed_set_id。
临时 seed set 可用于 dev，但默认不 rankable。
```

### 9.3 Ruleset

第一阶段只支持当前引擎默认 12 人规则：

```text
ruleset_version = werewolf_12p_v1
```

规则：

```text
固定玩家数
固定角色配置
固定阶段流程
固定胜负判定
API 不开放规则编辑
```

`ruleset provider` 属于引擎层，提供：

```text
玩家数
角色组成
阶段顺序
可用动作
胜负条件
seed 如何映射初始局面
各角色 applicable dimensions
```

评分权重归 `scoring_version`，不归 ruleset provider。

### 9.4 Scoring Version

`scoring_version` 是硬字段：

```text
ReviewService 输出带 scoring_version
Leaderboard snapshot 带 scoring_version
A/B promotion decision 带 scoring_version
不同 scoring_version 不混排
```

第一阶段固定：

```text
scoring_version = scoring_v1
```

规则变化通常要求新 scoring version；评分权重、风险扣分、结构化判断口径变化也要求新 scoring version。只改报告措辞不一定 bump。

---

## 10. Registry、Baseline 与 Role Version

### 10.1 Registry 边界

版本 registry 是独立物理边界：

```text
data/registry/registry.db
data/registry/skills/...
```

职责：

```text
registry DB 存 role_versions / role_current_baseline / role_baseline_history / skill_files。
Markdown 文件是 skill 内容实体。
wolf.db 和 evolution.db 只引用 role_version_id。
runtime 先查 registry 版本，再加载对应 Markdown。
hash 校验失败直接中断，不自动回滚。
```

### 10.2 Baseline

`baseline` 是可变指针，不是特殊版本。

```text
普通对局永远读取 current_baseline_version_id。
开局创建 game_run 时锁定具体 role_version_id。
中途 baseline promotion 不影响已开始对局。
Leaderboard 和 game facts 记录实际 role_version_id。
```

baseline 只能由系统更新：

```text
bootstrap
formal promotion
```

第一阶段不允许人工切 baseline，不允许 rollback，不实现 admin_override 路径。schema 可预留 `admin_override` 枚举，但代码禁止写入。

### 10.3 Role Version

硬规则：

```text
role_version_id 全局唯一、不可变。
内容变化必须生成新 version_id。
role_version.status = candidate | promoted | rejected | invalid | deprecated
第一阶段不自动产生 deprecated，只预留。
current baseline 必须指向 promoted version。
多个 promoted 历史版本可同时存在。
```

每个角色版本是一个 skill package，可以包含多个 skill 文件。

```text
skill_package_hash:
  按 skill_id/path 排序
  统一换行和末尾空白
  包含 frontmatter、runtime sections、system sections
  sha256(canonical package)
```

游戏运行时在 `wolf.db.game_players` 冗余记录：

```text
role_version_id
skill_package_hash
```

这是角色内容 hash，不是 runtime/prompt/pipeline hash。

### 10.4 Bootstrap

全清后从 `ruleset provider` 读取 `werewolf_12p_v1` 角色列表，为每个具体角色创建空 baseline：

```text
status = promoted
reason = bootstrap
generation = 0
skill_count = 0
created_by = system_bootstrap
```

空 baseline hash 应包含 role 和 package manifest，不同角色不共用 hash。

### 10.5 Branch 与 Round

自进化以单角色为单位。

```text
同一 branch 内 generation 从 0 递增。
parent_version_id 单父节点，第一阶段不支持 merge。
formal evolution experiment 创建 evolution_branch_id。
换 trained_gameplay_model 或 start_from_empty=true 时创建新 branch。
同一 role 同时只允许一个 formal round running。
promotion 前校验 current baseline 仍等于 round.parent_version_id。
promotion 成功后，同 role 其他 active formal branches 全部 stale。
```

round 终态：

```text
promoted
rejected
completed_no_proposal
failed
stale
```

---

## 11. Skill Proposal、Experience 与 Rejection

### 11.1 Experience Candidates

第一阶段 `experience_candidates` 只能由 `run_evidence_pipeline` 产生，且只写 `evolution.db`。

准入硬规则：

```text
run_type = evolution_training
learning_eligible = true
至少 2 个不同 source_game_id 支持同一个行为变化
必须绑定 role
必须绑定 applicable_phase 或 applicable_action
candidate_type in positive_pattern_candidate | anti_pattern_candidate | correction_candidate
confidence >= 0.7
不能来自 ordinary_game / evaluation_batch / A-B / imported_mistake_case
```

Consolidation 只读取：

```text
experience_candidates
current active skills
rejected_proposals as guardrail
```

不直接读取：

```text
ReviewService tables
Pattern
Episodic
runtime summaries
ordinary/evaluation/A-B/imported mistake
mid_memory
```

### 11.2 Proposal 生成

硬规则：

```text
每轮最多 3 个 proposals。
每个 proposal 只影响一个 skill 文件。
每个 proposal 只表达一个 behavior change。
禁止跨角色泛化。
默认禁止跨阶段泛化，除非 phase_general=true 且有多阶段证据。
如果 active skill 已覆盖，标记 already_covered，不出 proposal。
证据冲突时 group_status=conflicted，不出 proposal。
```

允许的改动：

```text
create_skill
append_rule
rewrite_section
deprecate_rule
```

限制：

```text
每角色 max_active_skills = 8。
每次决策 max_selected_skills = 3。
active skills 达上限时禁止 create_skill。
runtime_body_soft_limit = 1800 chars。
runtime_body_hard_limit = 2400 chars。
总文件软上限建议 6000 chars。
```

### 11.3 Rejected Proposals

`rejected_proposals` 是 guardrail，不是学习经验。

```text
A/B 失败且数据充分时写入。
A/B 数据不足或跑崩不写。
失败无法归因时，包内所有 proposal 写入，rejection_scope=package_level_uncertain，confidence=low。
同 role/phase/action 范围内永久有效。
不跨角色阻止。
不进入 runtime prompt。
```

`rejected_proposals` 优先级高于 `Deprecated Rules`。

---

## 12. Mode、Rankable 与失败语义

### 12.1 dev/formal

所有路线可带 `mode = dev | formal`，但语义不同：

```text
ordinary_game 默认 dev/diagnostic，不进榜、不学习。
evaluation_batch 可 dev 小样本；只有 formal + paired + >=20 + valid 达标才 rankable。
self-evolution dev 可调试 candidates/proposals，但不能 promotion、不能写 rejected_proposals、不能进榜。
```

dev 数据可写 DB，但必须标记 mode，正式 consolidation 默认只读 formal。

### 12.2 Rankable

`rankable` 由后端根据事实计算，禁止请求参数传入。

```text
run_type = evaluation_batch
mode = formal
paired_seed = true
game_count >= 20
valid_sample_rate >= threshold
比较维度合法
配置 hash 满足公平约束
```

### 12.3 失败语义

游戏事实和路线任务状态分开：

```text
game_status = completed:
  游戏引擎已完成并写入 wolf.db。

review_status = failed:
  不能进入完整报告或 leaderboard。

evidence_status = failed:
  evolution_training 不产生 candidates。

evolution round 有效训练局 < 80%:
  round failed。
```

已写入的游戏事实不回滚，失败状态必须可查询。

---

## 13. 模型配置与系统模型

`model_config_hash` 只描述 gameplay model 配置：

```text
provider
model_id
temperature = 1.0
max_tokens / budget policy
response_format / structured output mode
tool_choice
```

不包含：

```text
system prompt
role prompt
memory compression prompt
skill 内容
pipeline step hash
runtime code hash
evaluator/evidence/consolidation 配置
```

系统模型单独记录：

```text
evaluator_config_hash
evidence_config_hash
consolidation_config_hash
learning_pipeline_version
```

正式 ReviewService 使用固定 evaluator model；EvidencePipeline 和 Consolidation 使用固定独立学习器。配置变化影响正式结果时必须记录并视情况 bump `scoring_version` 或 `learning_pipeline_version`。

---

## 14. 第一阶段非目标

第一阶段显式不做：

```text
Agent 配置榜
AgentRuntime 版本榜
Prompt 管线对比
Memory 策略对比
temperature 对比
thinking_enabled 对比
provider / base_url 归因
人工 bad case 加入自进化
imported_mistake_case
失误案例库
scenario_tag
人工 skill 编辑 / 导入
手动 baseline 切换
rollback
跨角色 skill 泛化
语义检索式 skill selection
runtime/pipeline/memory/prompt hash 记录
```

---

## 15. TODO: Imported Mistake Case / 失误案例库

后续单独写 spec 和实现。

用途：

```text
导入人工构造或外部明显失误对局
验证复盘系统能否精准定位失误
作为评审展示
作为复盘系统回归测试
形成失误案例库供 UI 浏览
```

可能的未来 `run_type`：

```text
imported_mistake_case
```

策略：

```text
learning_eligible = false
leaderboard_scope = none 或 review_demo
promote_eligible = false
```

输入：

```text
events
decisions
roles
winner
expected_mistakes
```

验收方式：

```text
导入一局女巫毒好人 / 猎人带好人 / 好人放逐预言家的明细对局
系统生成 review
review 必须命中 expected_mistakes
必须给出 reason / alternative_action / counterfactual
```

明确不参与：

```text
不进入模型榜
不进入单角色版本榜
不进入自进化 evidence
不参与 promote/reject
```

---

## 16. 实施建议

### Phase 1: 数据边界

```text
新增 run_type
新增 learning_eligible
新增 leaderboard_scope
新增 promote_eligible
普通对局停止写 evolution evidence / episodic memory / patterns
```

### Phase 2: 普通评测结构化落库

```text
ordinary_game 结束后:
  -> evaluations
  -> decision_reviews
  -> counterfactuals
  -> reports
  -> review.json
```

### Phase 3: 批量评测

```text
新增 evaluation_batch runner
支持 model_id 批量评测
支持单角色 version_id 批量评测
支持 comparison_group_id / comparison_type
实现公平性校验
```

### Phase 4: Leaderboard

```text
模型榜
单角色版本榜
同组对比视图
```

### Phase 5: 自进化过滤

```text
evidence 查询强制 learning_eligible = true
A/B 对局强制 learning_eligible = false
promote/reject 只读取 paired A/B summary
```

---

## 17. 验收标准

### 普通对局

```text
普通单局可以生成多维评分、关键决策复盘、反事实和结构化报告
普通对局不写入 evolution evidence
普通对局不影响自进化 candidate 生成
```

### 批量评测

```text
同 seed 比较两个 model_id，系统能生成模型榜和同组对比
同 seed 比较同一角色的两个 version_id，系统能生成单角色版本榜
不满足控制变量的 batch 不进入归因榜
batch 结果不写入 evolution evidence
```

### 自进化

```text
evolution_training 产生 evidence
ordinary_game / evaluation_batch / evolution_ab 不产生 evidence
candidate 只通过 A/B 验证晋升
A/B 结果写 version history，但不进入经验池
```

---

## 18. 总结

最终边界：

```text
ordinary_game:
  单局展示和复盘，不学习。

evaluation_batch:
  批量 benchmark 和 Leaderboard，不学习。

evolution_training:
  自进化训练，唯一默认经验来源。

evolution_ab_baseline / evolution_ab_candidate:
  自进化验证，只决定 promote/reject，不学习。
```

核心原则：

```text
共享评测内核，隔离数据用途。
普通和批量评测负责展示与比较；
自进化只学习自己的训练局；
A/B 只验证不学习。
```

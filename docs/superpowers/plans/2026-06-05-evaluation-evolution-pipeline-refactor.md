# Plan: 三路线评测、自进化隔离与 Agent Pipeline 重构执行计划

> 基于：
>
> - `docs/superpowers/specs/2026-06-05-evaluation-evolution-routes.md`
> - `docs/superpowers/specs/2026-06-05-agent-pipeline-memory.md`
>
> 本计划只描述重构执行路径，不改变两份 spec 的产品边界。
> 核心目标：三条路线共享评测能力，但严格隔离学习来源；Agent runtime 收敛为一个固定 pipeline，运行时长期知识只通过 Markdown Skill 进入 prompt。

---

## 1. 最终目标

重构完成后，系统有三条清晰路线：

```text
ordinary_game:
  单局演示 + 评测复盘，不学习，不进 benchmark leaderboard，不 promote。

evaluation_batch:
  批量 benchmark + Leaderboard，不学习，不 promote。
  第一阶段只比较 model_id 和单角色 role/version_id。

evolution:
  evolution_training: 唯一默认学习来源。
  evolution_ab_baseline / evolution_ab_candidate: 只验证，不学习。
```

Agent runtime 有且只有一个固定 pipeline：

```text
remember_step
-> compress_memory_step
-> select_skills_step
-> build_prompt_step
-> call_model_step
-> parse_output_step
-> enforce_policy_step
```

运行时 prompt 只包含：

```text
当前可见局势
+ 当前 open segment 完整可见事件
+ 最近 4 个 closed segments 完整可见事件
+ 更早 segment 的 LLM 压缩摘要
+ Markdown skills
+ 输出 JSON schema / 合法动作约束
```

---

## 2. 当前实现切入点

### 2.1 Agent Runtime

当前主要入口：

```text
agent/api/runtime.py
agent/core/context.py
agent/core/memory.py
agent/decision/steps/remember.py
agent/decision/steps/select_skills.py
agent/decision/steps/inject_memory.py
agent/decision/steps/build_prompt.py
agent/decision/steps/call_model.py
agent/decision/steps/parse_output.py
agent/decision/steps/enforce_policy.py
agent/knowledge/prompts/base.py
```

当前问题：

```text
AgentRuntime 仍执行 inject_memory_step。
inject_memory_step 会尝试注入 Pattern + Episodic。
AgentContext 保留 memory_injection。
AgentMemory 比第一阶段目标复杂，包含 pinned_facts / player_models / self_commitments / rolling_summary。
Prompt 会渲染旧 memory_context 字段和 memory_injection。
```

### 2.2 对局与评测

当前主要入口：

```text
ui/backend/game_runner.py
agent/runner/battle_runner.py
agent/learning/evolution/games.py
agent/runner/evolution_runner.py
agent/learning/review/evaluator.py
agent/learning/review/reviewer.py
agent/learning/review/report_gen.py
storage/battle/evaluation_repo.py
storage/battle/review_repo.py
```

当前问题：

```text
ordinary UI game 会尝试写 episodic memory 到 evolution.db。
agent/runner/battle_runner.py 在单局结束后会更新 episodic + patterns。
selfplay runner 同时承担 benchmark 和 evolution training，依赖 enable_mid_memory 控制是否写经验。
A/B battle 已关闭 mid-memory，但 run_type/learning_eligible 不是强约束。
普通 review 主要缓存 review.json，评测表落库路径还不统一。
```

### 2.3 存储与榜单

当前主要入口：

```text
storage/schema.py
storage/evolution/schema.py
storage/runtime.py
storage/experience_store.py
storage/evolution/experience_repo.py
storage/evolution/pattern_repo.py
storage/evolution/situational_repo.py
storage/evolution/outcome_repo.py
storage/battle/leaderboard_repo.py
ui/backend/battle/leaderboard_routes.py
```

当前问题：

```text
games 表没有 run_type / learning_eligible / leaderboard_scope / promote_eligible 等一等公民字段。
experience_candidates 没有强制记录 run_type。
现有 leaderboard 表更偏 role/version，不适合直接承载 model leaderboard 和 benchmark role-version leaderboard。
缺少 comparison_group_id / comparison_type 的公平对比元数据。
```

### 2.4 Current Pattern / Episodic Audit

本节记录当前代码中 Pattern / Episodic 的实际产生和使用路径。
这是后续重构时必须切断或重定向的污染源清单。

#### 2.4.1 Episodic 当前是什么

当前 Episodic 指跨局具体案例记忆，主要落在 `evolution.db`：

```text
situational_records
decision_outcomes
```

语义：

```text
situational_records:
  某一局结束后，从单个玩家 AgentMemory 中抽出的局势快照。
  包括 role、seat、day、phase、alive_players、key_events、outcome。

decision_outcomes:
  某一局结束后，对单个决策打出的质量标签。
  包括 decision_id、role、action_type、day、phase、quality、reason。
```

核心生成代码：

```text
agent/core/episodic_memory.py
  EpisodicMemoryWriter.persist_game()
```

输入：

```text
player_memories
player_roles
winner
decisions
game_events
```

当前生成逻辑：

```text
每个玩家:
  AgentMemory.final_state -> SituationalRecord

每个决策:
  rule heuristic + winner + true roles -> DecisionOutcome
```

注意：

```text
Episodic 当前不是 LLM 总结。
它依赖局后真实角色和胜负，因此天然是 post-game / God-view 标注。
```

#### 2.4.2 Episodic 当前写入点

当前可能写 Episodic 的位置：

```text
agent/runner/battle_runner.py
  run_game() 结束后:
    EpisodicMemoryWriter.persist_game()
    SituationalRecordStore.save_batch()
    DecisionOutcomeStore.save_batch()
```

```text
ui/backend/game_runner.py
  _run_game() 结束后:
    尝试读取 game.agent_memories
    如果存在则 EpisodicMemoryWriter.persist_game()
```

当前判断：

```text
ui/backend/game_runner.py 的 game.agent_memories 当前未看到赋值路径，
所以这段大概率是死路径或未完成路径。
但重构时仍必须显式删除或加 run_policy gate，不能依赖“现在可能没触发”。
```

必须整改：

```text
ordinary_game:
  禁止写 situational_records / decision_outcomes。

evaluation_batch:
  禁止写 situational_records / decision_outcomes。

evolution_ab_baseline / evolution_ab_candidate:
  禁止写 situational_records / decision_outcomes。

evolution_training:
  第一阶段不再新写 situational_records / decision_outcomes。
  旧表只作为 legacy/debug，不进入新学习链。
```

#### 2.4.3 Episodic 当前读取和使用点

当前 runtime 会读取 Episodic：

```text
agent/api/runtime.py
  AgentRuntime.act()
    -> create_providers(self.paths)
    -> inject_memory_step(... episodic_provider=...)
```

Provider：

```text
agent/learning/providers.py
  EpisodicProvider.__call__()
    -> SituationalRecordStore.query(role=role, limit=3)
```

Prompt 注入：

```text
agent/decision/steps/inject_memory.py
  _format_episodic_memories()
    -> "历史案例:"
```

最终进入 prompt：

```text
agent/knowledge/prompts/base.py
  memory_injection_block
    -> "已注入经验记忆:"
```

必须整改：

```text
AgentRuntime 不再 create_providers。
inject_memory_step 从固定 pipeline 移除或 no-op。
build_prompt_step / prompt template 不再渲染 memory_injection。
```

#### 2.4.4 Pattern 当前是什么

当前 Pattern 是统计规律，不是具体案例。

核心模型：

```text
agent/learning/pattern_engine.py
  Pattern
  PatternEngine
```

Pattern 字段：

```text
pattern_id
role
situation
recommendation
win_rate_with
win_rate_without
sample_size
confidence
status
source_games
alpha
beta
```

状态：

```text
candidate
active
crystallized
archived
deprecated
```

当前 situation signature：

```text
{role}:{action_type}:{phase}:{day_bucket}
```

示例：

```text
seer:seer_check:night:early
witch:witch_act:night:early
villager:exile_vote:day:early
```

当前 recommendation：

```text
如果 selected_target 存在:
  "{action_type}:target={selected_target}"

如果 selected_choice 存在:
  "{action_type}:choice={selected_choice}"

否则:
  "{action_type}"
```

注意：

```text
Pattern 当前粒度很粗。
它不是 LLM 总结出的策略规则，而是基于 action_type / phase / day_bucket / target 的统计相关性。
```

#### 2.4.5 Pattern 当前生成和写入点

当前 Pattern 生成逻辑：

```text
agent/learning/pattern_engine.py
  PatternEngine.update_after_game(game_id, decisions, winner, player_roles)
```

流程：

```text
for decision in decisions:
  build situation signature
  determine whether actor's side won
  find existing pattern by role + signature
  if exists:
    bayesian_update(pattern, won)
  else:
    create candidate pattern
```

写入点：

```text
agent/runner/battle_runner.py
  run_game() 结束后:
    create_pattern_update_provider(paths)
    provider._ensure_engine()
    pat_engine.update_after_game(...)
    PatternStore.save_pattern(...)
```

存储：

```text
storage/evolution/pattern_repo.py
  patterns table
```

必须整改：

```text
ordinary_game:
  禁止 update_after_game / save_pattern。

evaluation_batch:
  禁止 update_after_game / save_pattern。

evolution_ab_baseline / evolution_ab_candidate:
  禁止 update_after_game / save_pattern。

evolution_training:
  第一阶段不再 update_after_game / save_pattern。
  旧 patterns 只作为 legacy/debug，不进入新学习链。
```

#### 2.4.6 Pattern 当前读取和使用点

当前 runtime 会读取 active / crystallized patterns：

```text
agent/learning/providers.py
  PatternProvider._ensure_engine()
    -> PatternStore.list_patterns(status="active")
    -> PatternStore.list_patterns(status="crystallized")
```

当前匹配：

```text
PatternEngine.get_relevant_patterns(role, phase, day, action_type)
```

注入：

```text
agent/decision/steps/inject_memory.py
  _format_patterns()
    -> "经验规律:"
```

最终进入 prompt：

```text
agent/knowledge/prompts/base.py
  memory_injection_block
    -> "已注入经验记忆:"
```

必须整改：

```text
运行时不再加载 PatternProvider。
运行时不再查询 patterns table。
运行时 prompt 不再出现 "经验规律"。
Pattern 第一阶段只作为 legacy/debug 保留，不作为 EvidencePipeline 或 Consolidation 输入。
```

#### 2.4.7 KnowledgePackage.patterns 当前状态

除了 `evolution.db` 的 `patterns` 表，版本包里还有：

```text
KnowledgePackage.patterns
data/registry/<role>/versions/<version_id>/patterns.json
```

相关代码：

```text
agent/learning/evolution/models.py
  KnowledgePackage.patterns

agent/learning/evolution/registry.py
  publish()
  diff()
  _diff_patterns()
```

当前实际状态：

```text
publish_skills() 默认 patterns=[]。
自进化主链路当前主要发布 Markdown skills。
patterns.json 更像预留 / UI diff 展示字段，不是当前 runtime 主输入。
```

必须整改：

```text
第一阶段不要把 KnowledgePackage.patterns 作为 runtime prompt 输入。
如果保留该字段，只作为版本包元数据或未来实验字段。
长期策略最终仍必须沉淀到 Markdown Skill。
```

#### 2.4.8 重构后的目标边界

最终目标：

```text
Runtime:
  只用当前局短期记忆 + Markdown Skill。
  不读 evolution.db。
  不注入 Pattern。
  不注入 Episodic。

ordinary_game:
  只写 events / decisions / review / report。
  不写 Pattern / Episodic / experience。

evaluation_batch:
  只写 benchmark 所需评测事实和 leaderboard metrics。
  不写 Pattern / Episodic / experience。

evolution_training:
  唯一默认学习来源。
  可写 experience_candidates。
  不新写 Pattern/Episodic。
  不读取 Pattern/Episodic/mid_memory 作为 candidate 来源。

evolution_ab_baseline / evolution_ab_candidate:
  只写评测和 A/B summary。
  不写 Pattern / Episodic / experience。
```

#### 2.4.9 必须删除或加 gate 的点

必须处理的代码点：

```text
agent/api/runtime.py
  删除 create_providers / inject_memory_step 主路径。

agent/core/context.py
  memory_injection 字段删除或废弃。

agent/decision/steps/inject_memory.py
  移出固定 pipeline，保留 no-op 或 deprecated。

agent/knowledge/prompts/base.py
  删除 memory_injection_block。

agent/runner/battle_runner.py
  删除/禁用 EpisodicMemoryWriter 主路径。
  删除/禁用 PatternEngine.update_after_game 主路径。

ui/backend/game_runner.py
  删除/禁用 EpisodicMemoryWriter 死路径。

agent/learning/evolution/games.py
  learning writes 必须要求 run_type=evolution_training。

agent/runner/evolution_runner.py
  A/B 必须 run_type=evolution_ab_* 且 learning_eligible=false。

storage/runtime.py
  save_experience_candidates 必须检查 learning_eligible。
```

---

## 3. 执行原则

1. **先切断污染源，再做功能扩展**
   先保证 ordinary_game / evaluation_batch / evolution_ab 不会写学习数据，再实现新榜单。

2. **先加显式 run policy，再改调用点**
   不依赖 `enable_mid_memory=False` 这种隐式开关判断学习资格。

3. **运行时不再读 evolution.db**
   AgentRuntime 不创建 pattern / episodic providers，不查询 evolution.db 注入 prompt。

4. **旧数据全清，不做兼容迁移**
   第一阶段重构前清空 `data/wolf.db`、`data/evolution.db`、`data/registry/*`、`runs/*` 和旧学习 artifacts。新系统从空 DB、空 registry、空 baseline bootstrap 开始。

5. **第一阶段不做失误案例库**
   `imported_mistake_case` 只写 TODO，不实现导入、榜单或学习逻辑。

6. **三库物理边界**
   `wolf.db` 只存游戏事实、复盘事实、benchmark/leaderboard 事实；`evolution.db` 只存学习事实、自进化 round/proposal/promotion 事实；`data/registry` 存 role version 元数据和 Markdown skill package。

7. **普通对局只用 baseline**
   ordinary_game 创建时把每个角色的 current baseline 解析成具体 `role_version_id` 并锁定；中途 baseline promotion 不影响已开始对局。

8. **正式结论只认 formal + paired**
   dev 小样本允许调试，但不能 rankable、不能 promotion、不能写 rejected_proposals。

---

## 4. Phase 0: 基线与保护网

### 4.1 目标

在改动前确认当前可运行测试集合，随后执行全清启动策略，建立新系统的空 DB、空 registry 和空 baseline。

### 4.2 任务

1. 记录当前测试基线：

```text
uv run pytest tests/test_agent.py
uv run pytest tests/test_agent_integration.py
uv run pytest tests/test_role_evolution
uv run pytest tests/test_agent_leaderboard.py
```

2. 补两个 characterization tests：

```text
普通 GameManager.build_review(game_id) 仍能从 events + decisions 生成 review。
AgentRuntime.act() 在模型 stub 下能完整返回合法 ActionResponse。
```

3. 明确暂不处理的既有改动：

```text
.gitignore 当前已有未提交改动，重构时不要回滚。
```

4. 全清旧数据：

```text
删除 data/wolf.db
删除 data/evolution.db
删除 data/registry/*
删除 runs/*
删除旧 pattern / episodic / mid_memory / experience artifacts
```

5. Bootstrap registry：

```text
从 engine ruleset provider 读取 ruleset_version=werewolf_12p_v1。
为所有具体角色创建 generation=0 空 baseline role version。
role 字符串使用 engine.models.Role.value:
  werewolf / white_wolf_king / villager / seer / witch / hunter / guard。
role_version.status=promoted。
role_baseline_history.reason=bootstrap。
每个角色空 package hash 包含 role + manifest，不共用 hash。
不从旧手写 skills 初始化。
```

6. 禁止旧 fallback：

```text
runtime 不再 fallback 到 repo handwritten skills。
registry 缺 current baseline 时普通对局启动失败。
hash 校验失败标记 registry dirty 并中断，不自动回滚。
agent.learning.evolution.registry.VersionRegistry.initialize_from_skills() 删除或禁用。
scripts/seed_skills.py 不再作为 bootstrap 路径。
```

### 4.3 验收

```text
现有核心测试可运行，或者已记录失败原因。
新增 characterization tests 能在重构前后定位行为变化。
全清后每个 werewolf_12p_v1 角色都有空 baseline。
ordinary_game 可从空 baseline 启动。
```

---

## 5. Phase 1: Run Type 与数据边界

### 5.1 目标

把三条路线变成代码中的显式策略，而不是分散在 runner 参数里的隐式约定。

同时引入唯一底层运行入口：

```text
GameRunService
```

强制规则：

```text
只有 GameRunService.create_run() 分配 run_id。
只有 GameRunService 创建 games / game_players。
ordinary_game / evaluation_batch / evolution_training / evolution_ab 都调用 GameRunService。
GameManager / BattleRunner / run_selfplay / EvolutionRunner 只能作为 facade / adapter。
只有 GameRunService 创建 GamePersistence 并拥有 post-game writes。
```

### 5.2 新增模块

建议新增：

```text
agent/common/run_policy.py
agent/game_run/service.py
agent/game_run/models.py
agent/game_run/persistence.py
```

定义：

```python
class RunType(str, Enum):
    ORDINARY_GAME = "ordinary_game"
    EVALUATION_BATCH = "evaluation_batch"
    EVOLUTION_TRAINING = "evolution_training"
    EVOLUTION_AB_BASELINE = "evolution_ab_baseline"
    EVOLUTION_AB_CANDIDATE = "evolution_ab_candidate"

class LeaderboardScope(str, Enum):
    DEMO = "demo"
    BENCHMARK = "benchmark"
    EVOLUTION_TRAINING = "evolution_training"
    EVOLUTION_AB = "evolution_ab"
    NONE = "none"

@dataclass(frozen=True)
class RunPolicy:
    run_type: RunType
    learning_eligible: bool
    leaderboard_scope: LeaderboardScope
    promote_eligible: bool
```

提供：

```text
policy_for_run_type(run_type)
run_policy_to_config(policy, extra_metadata)
run_policy_from_config(config)
assert_learning_allowed(policy)
assert_benchmark_allowed(policy)
```

### 5.3 存储扩展

第一阶段旧数据全清，因此可以直接建立新 schema；关键字段必须是表列，不能只塞 JSON。

当前代码事实：

```text
storage/schema.py 现在仍在 wolf.db 中创建:
  experience_candidates
  role_versions
  skill_proposals
  evolution_runs

这和三库物理边界冲突。第一阶段全清后不做兼容迁移，必须从 wolf.db 主 schema 移除这些 authoritative 表。
```

`storage/schema.py` 新边界：

```text
保留:
  games
  players / game_players
  decisions
  game_events
  evaluations
  decision_reviews
  counterfactuals
  reports
  seed_sets
  evaluation_batches
  leaderboard_snapshots / benchmark_leaderboard

移出:
  experience_candidates -> evolution.db
  skill_proposals -> evolution.db
  evolution_runs -> evolution.db
  role_versions -> registry.db
```

在 `storage/schema.py` 的 `games` 表增加字段：

```text
run_type TEXT DEFAULT 'ordinary_game'
mode TEXT DEFAULT 'dev'
learning_eligible INTEGER DEFAULT 0
leaderboard_scope TEXT DEFAULT 'demo'
promote_eligible INTEGER DEFAULT 0
source_run_id TEXT
comparison_group_id TEXT
comparison_type TEXT
model_id TEXT
model_config_hash TEXT
target_role TEXT
target_version_id TEXT
ruleset_version TEXT DEFAULT 'werewolf_12p_v1'
seed_set_id TEXT
seed INTEGER
evaluation_set_id TEXT
paired_seed INTEGER DEFAULT 0
rankable INTEGER DEFAULT 0
```

当前代码表名是 `players`。第一阶段可以选择：

```text
方案 A: 继续使用 players 表，但扩展字段。
方案 B: 新增 game_players 表，并迁移调用点。
```

不论采用哪种表名，每局玩家记录必须记录：

```text
game_id TEXT
player_id INTEGER
role TEXT
role_version_id TEXT
skill_package_hash TEXT
model_id TEXT
model_config_hash TEXT
role_sample_status TEXT DEFAULT 'valid'
role_sample_invalid_reason TEXT
```

新增 seed set 表：

```text
seed_sets:
  seed_set_id TEXT PRIMARY KEY
  purpose TEXT
  seeds_json TEXT
  ruleset_version TEXT
  created_at TEXT
  immutable INTEGER DEFAULT 1
```

seed set 规则：

```text
training_seed_set_id / ab_eval_set_id / leaderboard_eval_set_id 互不重叠。
seed_set_id 不可原地修改，变更必须新建 v2。
正式 leaderboard snapshot 必须记录 seed_set_id。
promotion decision 必须记录 seed_set_id。
临时 seed set 可用于 dev，但默认不 rankable。
```

ruleset provider：

```text
引擎层提供 ruleset_version=werewolf_12p_v1。
GameRunService 用它创建 game。
registry bootstrap 用它创建空 baseline。
ReviewService 用它校验动作合法性和评分适用维度。
UI 只展示后端返回的 ruleset metadata。
```

新增 review / scoring 硬字段：

```text
reviews / evaluations:
  scoring_version TEXT
  evaluator_model_id TEXT
  evaluator_config_hash TEXT
  review_prompt_version TEXT
  ruleset_version TEXT
  evaluation_status TEXT
  review_status TEXT
  report_status TEXT

llm_judgments:
  judgment_id TEXT PRIMARY KEY
  game_id TEXT
  player_id INTEGER
  dimension TEXT
  prompt_version TEXT
  evaluator_config_hash TEXT
  input_refs TEXT
  raw_json TEXT
  normalized_fields TEXT
  validator_status TEXT
  created_at TEXT

leaderboard_snapshots:
  snapshot_id TEXT PRIMARY KEY
  scope TEXT
  evaluation_set_id TEXT
  seed_set_id TEXT
  ruleset_version TEXT
  scoring_version TEXT
  evaluator_config_hash TEXT
  included_run_ids TEXT
  excluded_sample_ids TEXT
  summary TEXT
  created_at TEXT
```

新增 registry 物理库：

```text
data/registry/registry.db:
  role_versions
  role_current_baseline
  role_baseline_history
  skill_files
  evolution_branches
```

在 `storage/evolution/schema.py` 的学习事实表增加字段：

```text
experience_candidates:
  run_type TEXT
  source_run_id TEXT
  source_game_id TEXT
  artifact_game_id TEXT
  learning_eligible INTEGER DEFAULT 0
  mode TEXT
  candidate_type TEXT
  role TEXT
  applicable_phase TEXT
  applicable_action TEXT
  confidence REAL
  evidence_refs TEXT
  llm_rationale TEXT
  validator_status TEXT

legacy Pattern/Episodic tables:
  patterns
  situational_records
  decision_outcomes

第一阶段不扩展为新主路径，不新写，不查询。
如果保留表定义，只作为 legacy/debug，正式 schema bootstrap 可以选择不创建。
```

新增自进化控制表：

```text
evolution_rounds
candidate_packages
skill_proposals
rejected_proposals
promotion_decisions
ab_comparison_groups
```

旧数据全清后不做 legacy migration/backfill。可以新增 schema bootstrap/version assert 工具：

```text
storage/schema_bootstrap.py
initialize_wolf_schema(conn)
initialize_evolution_schema(conn)
initialize_registry_schema(conn)
assert_schema_version(conn, expected)
```

并在 `get_connection()` / `get_evolution_connection()` / registry connection 初始化后执行。

### 5.4 持久化策略

更新：

```text
storage/runtime.py
```

`model_config_hash` 边界：

```text
只描述 gameplay model 调用配置:
  provider
  model_id
  temperature = 1.0
  max_tokens / budget policy
  response_format / structured output mode
  tool_choice

不包含:
  system prompt
  role prompt
  memory compression prompt
  skill 内容
  pipeline step hash
  runtime code hash
  evaluator/evidence/consolidation 配置
```

系统模型配置单独记录：

```text
review facts:
  evaluator_model_id
  evaluator_config_hash

experience_candidates:
  evidence_config_hash

skill_proposals / candidate_packages:
  consolidation_config_hash
  learning_pipeline_version

evolution_rounds / promotion_decisions:
  learning_pipeline_version
```

`GamePersistence.__init__` 增加：

```text
run_policy: RunPolicy | None
run_metadata: dict[str, Any] | None
```

`save_game_result()`：

```text
把 run_type / learning_eligible / leaderboard_scope / promote_eligible 写入 games columns。
同时写入 mode / ruleset_version / seed_set_id / model_config_hash / role_version_id / skill_package_hash。
```

`save_experience_candidates()`：

```text
当前 storage/runtime.py 的 GamePersistence.save_experience_candidates() 会通过 storage.experience_store 写当前连接。
第一阶段必须停止让 wolf.db GamePersistence 写 experience。

新规则:
  GamePersistence 只写 wolf.db game/review facts。
  evolution_training 的 EvidencePipeline 输出由 EvolutionPersistence / ExperienceCandidateRepository 写 evolution.db。
  storage/evolution/experience_repo.py 必须接收并写入 run_type / mode / source_run_id / source_game_id / learning_eligible。
  repository 层拒绝非 evolution_training 或 learning_eligible=false 的正式写入。
  如果 run_policy.learning_eligible != true，EvidencePipeline 不运行，experience repository 不写入。
```

注意：这一层是最后一道防线。即使上层误开了 `enable_mid_memory=True`，非学习局也不能写 experience。

post-game writes 归属：

```text
wolf.db:
  game facts
  review facts
  leaderboard snapshots
  seed sets

evolution.db:
  evolution rounds
  experience_candidates
  skill_proposals
  candidate_packages
  promotion_decisions
  rejected_proposals

registry:
  role versions
  baseline pointer/history
  skill files
```

### 5.5 调用点改造

1. `ui/backend/game_runner.py`

```text
start_game / _run_game 使用 run_type=ordinary_game。
GamePersistence 注入 ordinary_game policy。
config 写入 _run。
创建 run 时从 registry 解析每个角色 current baseline。
写入每个 player 的 role_version_id / skill_package_hash。
不允许用户为 ordinary_game 选择非 baseline version。
registry 缺 baseline 则启动失败。
```

2. `agent/runner/battle_runner.py`

```text
BattleGameConfig 增加 run_type，默认 ordinary_game。
普通单局默认不学习。
删除或 gate post-game evolution persistence。
```

3. `agent/learning/evolution/games.py`

```text
SelfPlayConfig 增加 run_type / source_run_id / comparison metadata。
默认建议 evaluation_batch，evolution pipeline 必须显式传 evolution_training 或 evolution_ab_*。
_run_single_game 创建 GamePersistence 时注入 run_policy。
evaluation_batch 可以显式选择 role_version_config。
如果 UI 传 current baseline，后端必须在创建 run 时解析为具体 version_id。
```

4. `agent/runner/evolution_runner.py`

```text
TrainingConfig 默认 run_type=evolution_training。
ABConfig baseline side 使用 evolution_ab_baseline。
ABConfig candidate side 使用 evolution_ab_candidate。
training round 锁定 parent_version_id。
A/B baseline 使用 round.parent_version_id，不使用 A/B 开始时的 current baseline。
promotion 前校验 current baseline 仍等于 parent_version_id。
```

### 5.6 测试

新增：

```text
tests/test_run_policy.py
tests/test_learning_boundaries.py
```

覆盖：

```text
ordinary_game: learning_eligible=false
evaluation_batch: learning_eligible=false
evolution_training: learning_eligible=true
evolution_ab_baseline: learning_eligible=false
evolution_ab_candidate: learning_eligible=false
非 learning_eligible 调用 save_experience_candidates 不写库
games.config["_run"] 和 games columns 一致
```

### 5.7 验收

```text
普通 UI 单局不写 evolution.db 的 situational_records / decision_outcomes / patterns。
evaluation_batch 不写 experience_candidates / patterns。
evolution_training 可以写 experience_candidates。
evolution_ab 两侧不写 experience_candidates / patterns。
```

---

## 6. Phase 2: 切断 Runtime Cross-game Injection

### 6.1 目标

运行时 prompt 不再直接注入 Pattern / Episodic / 历史案例。

### 6.2 改造文件

```text
agent/api/runtime.py
agent/core/context.py
agent/decision/steps/inject_memory.py
agent/decision/steps/__init__.py
agent/knowledge/prompts/base.py
tests/test_agent.py
```

### 6.3 任务

1. `AgentRuntime.__init__` 删除：

```text
self._providers_ready
self._pattern_provider
self._episodic_provider
```

2. `AgentRuntime.act()` 删除：

```text
create_providers(self.paths)
inject_memory_step(...)
```

3. `AgentContext` 删除或废弃：

```text
memory_injection
```

第一阶段可以先保留字段但不再写入，避免一次性改动过大。

4. `build_prompt_step()` 不再传：

```text
memory_injection=ctx.memory_injection
```

5. `agent/knowledge/prompts/base.py` 删除 prompt 中：

```text
已注入经验记忆:
```

6. `agent/decision/steps/inject_memory.py`：

```text
方案 A: 保留文件但标记 deprecated，不再从 __init__ 导出。
方案 B: 改成 deprecated no-op，避免未清理 import 立即炸裂。
```

推荐第一阶段用方案 B，但必须新增测试确保主 pipeline 不调用它。

### 6.4 测试

新增或修改：

```text
AgentRuntime.act 不调用 agent.learning.providers.create_providers。
build_request_prompt 输出不包含 “已注入经验记忆”。
PatternProvider / EpisodicProvider 不影响运行时决策 prompt。
```

### 6.5 验收

```text
任意普通对局决策 prompt 中没有 Pattern / Episodic / 历史案例注入。
运行时不再打开 evolution.db 查询经验。
```

---

## 7. Phase 3: Segment AgentMemory 与 LLM 压缩

### 7.1 目标

把当前复杂短期记忆收敛为 spec 中的 player-view segment window。

### 7.2 新增/改造模块

建议拆分：

```text
agent/core/memory.py
agent/core/memory_segments.py
agent/decision/steps/compress_memory.py
agent/knowledge/skills/loader.py
agent/knowledge/skills/router.py
agent/decision/steps/select_skills.py
agent/knowledge/prompts/base.py
```

`agent/core/memory_segments.py` 定义：

```python
@dataclass
class SegmentEvent:
    day: int
    phase: str
    event_type: str
    actor: int | None
    target: int | None
    content: str
    public: bool
    index: int | None

@dataclass
class Segment:
    segment_key: str
    day: int
    phase_group: str
    events: list[SegmentEvent]
    closed: bool = False
    compression_retry_count: int = 0
    compression_failed: bool = False

@dataclass
class CompressedSegmentSummary:
    segment_key: str
    summary: str
    key_events: list[str]
    player_notes: dict[str, str]
    unknowns: list[str]
```

### 7.3 Phase Group 映射

新增：

```text
normalize_phase_group(phase: str) -> str
```

第一版映射：

```text
night
sheriff
day_speech
exile_vote
death_resolution
```

未知 phase：

```text
直接使用原 phase 字符串，避免丢事件。
```

`segment_key`：

```text
f"{phase_group}:{day}"
```

### 7.4 AgentMemory 结构

`AgentMemory` 第一阶段只保留：

```text
current_visible_state
open_segment
closed_segments
compressed_segment_summaries
compression_state
seen_event_keys
```

`build_context(request)` 产出：

```json
{
  "current_visible_state": {},
  "compressed_segment_summaries": [],
  "recent_closed_segments": [],
  "open_segment": {},
  "compression_state": {}
}
```

不再产出：

```text
rolling_summary
pinned_facts
player_models
self_commitments
field_notes
```

过渡策略：

```text
第一步让 prompt formatter 忽略旧字段。
第二步测试全部迁移后，删除旧字段相关 formatter。
```

### 7.5 remember_step

`remember_step` 只做：

```text
memory.observe(request)
ctx.memory_context = memory.build_context(request)
```

不得做：

```text
LLM 压缩
Skill 选择
玩家画像
pinned facts
跨局查询
```

### 7.6 compress_memory_step

新增：

```text
agent/decision/steps/compress_memory.py
```

签名：

```python
async def compress_memory_step(
    ctx: AgentContext,
    memory: AgentMemory,
    model: ModelAdapter,
    *,
    max_recent_closed_segments: int = 4,
    max_retries: int = 2,
) -> AgentContext:
    ...
```

执行逻辑：

```text
如果 closed_segments 数量 <= 4:
  不调用 LLM。

如果 closed_segments 数量 > 4:
  取最旧且未 compression_failed 的 closed segment。
  用当前 decision model 调 LLM 压缩。
  JSON 合法则写入 compressed_segment_summaries，并从 closed_segments 移除。
  失败则 retry_count += 1，当前决策继续。
  retry_count >= 2 后标记 compression_failed，保留完整 segment。
```

压缩 prompt 约束：

```text
只能总结输入事件。
输入事件是该玩家可见事件，可能含私有信息。
不得补充输入中没有的身份真相。
不确定内容写 unknowns。
必须输出 JSON。
```

输出 schema：

```json
{
  "segment_key": "day_speech:2",
  "summary": "...",
  "key_events": ["..."],
  "player_notes": {"3": "..."},
  "unknowns": ["..."]
}
```

### 7.7 AgentRuntime 顺序

更新：

```text
agent/api/runtime.py
```

顺序改为：

```python
ctx = remember_step(ctx, self.memory)
ctx = await compress_memory_step(ctx, self.memory, self.model)
ctx = select_skills_step(ctx, skill_root=self.skill_dir)
ctx = build_prompt_step(ctx)
ctx = await call_model_step(ctx, self.model)
ctx = parse_output_step(ctx)
ctx = enforce_policy_step(ctx)
```

注意：

```text
compress_memory_step 必须在 select_skills_step 前执行。
压缩使用同一个 model_id，模型榜评估端到端能力。
select_skills_step 不做语义检索。
select_skills_step 只按 role / phase / action_type 确定性路由。
每次最多注入 3 个 active skills。
只注入 runtime_body。
runtime_body 不包含 Examples / Deprecated Rules / Changelog / Provenance / Evaluation Notes。
runtime_body 不包含玩家号、game_id、run_id、seed、模型名、provider、A/B 细节。
```

当前代码事实：

```text
agent/knowledge/skills/loader.py::MarkdownSkill 只有 body，没有 status/runtime_body。
agent/knowledge/skills/router.py::format_skill_context() 现在注入完整 skill.body。
router 现在不限制最多 3 个，不识别 deprecated/system sections。
```

必须改造：

```text
MarkdownSkill 增加 status / runtime_body / system_sections metadata。
loader 解析 runtime sections 和 system sections。
router 只选择 status=active。
format_skill_context 只渲染 runtime_body。
selector 超过 3 个时按 priority / promotion 时间排序。
runtime forbidden-content scanner 不只在 Applier 后跑，也要在加载 skill 时防御性校验。
```

### 7.8 AgentContext 与 DecisionRecord

`AgentContext` 增加：

```text
compression_errors: list[str]
compressed_segments_added: list[str]
```

`DecisionRecord` 可选增加或复用现有字段：

```text
memory_summary:
  compressed_segments_added
  open_segment_key
  recent_closed_segment_keys
  compression_errors
```

如果 `DecisionRecord` schema 暂不扩列，先塞入已有 `memory_summary` JSON/list，后续再独立字段化。

### 7.9 Prompt 改造

更新：

```text
agent/knowledge/prompts/base.py
```

短期记忆渲染顺序：

```text
1. 更早阶段摘要 compressed_segment_summaries
2. 最近完整阶段 recent_closed_segments
3. 当前阶段 open_segment
```

删除或停止渲染：

```text
pinned_facts
player_models
self_commitments
field_notes
rolling_summary
```

当前局势仍来自 `request.observation`，不是 memory 自己推断。

### 7.10 测试

新增：

```text
tests/test_agent_memory_segments.py
tests/test_compress_memory_step.py
```

覆盖：

```text
同 phase_group/day 的事件进入同一个 open segment。
phase_group 变化时旧 segment closed。
当前 open segment 不会被压缩。
最近 4 个 closed segments 保留完整。
第 5 个 closed segment 触发 LLM 压缩。
压缩失败不阻塞 ActionResponse。
压缩失败最多重试 2 次。
村民视角压缩不会出现狼人私密事件。
预言家视角可以保留自己的查验。
```

### 7.11 验收

```text
AgentRuntime 固定 7 步。
运行时 prompt 中没有 Pattern/Episodic。
prompt 中包含 open segment + 最近 4 个 closed segments + 更早摘要。
长局不会因为压缩失败中断。
```

---

## 8. Phase 4: 统一评测落库

### 8.1 目标

三条路线共享同一套评测产物：

```text
evaluations
decision_reviews
counterfactuals
reports
review.json
```

学习事实仍只由 `learning_eligible=true` 写入。

### 8.2 新增服务

建议新增：

```text
agent/learning/review/service.py
agent/learning/review/metrics.py
agent/learning/review/judgments.py
agent/learning/review/scorer.py
```

提供：

```python
def build_structured_review(
    *,
    game_id: str,
    events: list[dict],
    decisions: list[dict],
    player_roles: dict[int, str],
    winner: str,
) -> StructuredReviewResult:
    ...

def persist_structured_review(
    conn,
    result: StructuredReviewResult,
) -> None:
    ...
```

内部统一调用：

```text
MetricExtractor / GameEvaluator
LLM structured JudgmentEvaluator
Deterministic Scorer
GameReviewer
ReportGenerator
```

硬边界：

```text
GameEvaluator 可以编排程序指标和 LLM structured judgments。
LLM 不允许直接写最终分数。
Scorer 负责把程序指标 + validated judgments 合成 role_score。
ReportGenerator 只组织展示文本，不重新计算评分。
EvidencePipeline 只能读取 ReviewService 结构化结果，不能绕过它读原始日志抽经验。
generate_enhanced_review 降级为 legacy，不再作为主 review chain。
```

评测器配置：

```text
formal mode 使用固定 evaluator model/config。
同一 leaderboard snapshot 必须同 evaluator_config_hash。
dev mode 可以允许 evaluator override，但必须标记 dev，不能 promotion/rankable。
evaluator_config 变化且影响结构化评分时必须 bump scoring_version 或新 snapshot namespace。
被测 gameplay model 不能影响 evaluator prompt/config。
```

评分维度：

```text
speech_score
vote_score
skill_score
logic_score
team_score
risk_penalty
role_score = weighted_base_score - risk_penalty
```

无技能角色的 `skill_score` 是 `not_applicable`，允许权重重归一化；missing/failed judgment 不允许静默重归一化。

当前代码事实：

```text
agent/learning/review/evaluator.py 当前输出:
  information_score
  cooperation_score
  overall_score

agent/learning/review/report.py::generate_enhanced_review 当前也输出:
  information_score
  cooperation_score
  total_score
  role_weighted_score
```

必须改造：

```text
formal scoring_v1 不再使用 information_score/cooperation_score/overall_score 作为权威字段。
information_score 的职责拆入 logic_score 或 team_score 的结构化 judgment。
cooperation_score 的职责收敛为 team_score。
overall_score / total_score / role_weighted_score 降级为 legacy/debug 或映射到 role_score 后停止新写。
storage/battle/evaluation_repo.py 和 storage/schema.py 同步新字段。
```

### 8.3 调用点

1. `ui/backend/game_runner.py`

```text
build_review() 改为调用 build_structured_review。
成功后写 review.json。
如果 db_path 可用，同时写 evaluations / decision_reviews / counterfactuals / reports。
```

2. `agent/learning/evolution/games.py`

```text
_run_single_game 结束后，如果 enable_review:
  调用统一评测服务。
  产出 per-game review metrics。
  benchmark 和 evolution 都可写评测事实。
```

3. `agent/runner/evolution_runner.py`

```text
training 和 A/B 都可以写评测事实。
training 后续 evidence 使用评测结果作为原料。
A/B 只使用评测结果做 promote/reject，不写 learning facts。
```

### 8.4 数据映射

`GameEvaluation` -> `evaluations`：

```text
player_seat
role
speech_score
vote_score
skill_score
logic_score
team_score
risk_penalty
role_score
score_completeness
role_sample_status
role_sample_invalid_reason
ruleset_version
scoring_version
evaluator_config_hash
evaluation_status
review_status
report_status
```

`LLM judgment` -> `llm_judgments`：

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

`DecisionReview` -> `decision_reviews`：

```text
decision_id
player_seat
day
phase
action_type
quality
reason
alternative_action
```

`Counterfactual` -> `counterfactuals`：

```text
decision_id
what_if
likely_outcome
confidence
```

`GameReport` -> `reports`：

```text
summary JSON
```

### 8.5 测试

新增：

```text
tests/test_review_service.py
```

覆盖：

```text
一局完整 events + decisions 能写入 evaluations。
关键 decision review 能写入 decision_reviews。
counterfactuals 能写入 counterfactuals。
review.json 和 reports.summary 结构一致。
ordinary_game 写评测事实但不写学习事实。
```

### 8.6 验收

```text
普通单局复盘 UI 仍能读取 review。
SQLite 中能查到该局 evaluations / decision_reviews / counterfactuals / reports。
自进化 evidence 查询不因为评测落库而扩大来源。
```

---

## 9. Phase 5: Evaluation Batch Runner

### 9.1 目标

新增明确的批量评测入口，用于比较：

```text
model_id
单角色 role/version_id
```

第一阶段不比较：

```text
Agent 配置
temperature
thinking_enabled
provider/base_url
pipeline 版本
memory 策略
```

### 9.2 新增模块

建议新增：

```text
agent/evaluation/config.py
agent/evaluation/runner.py
agent/evaluation/fairness.py
agent/evaluation/metrics.py
agent/evaluation/leaderboard.py
ui/backend/evaluation_routes.py
```

### 9.3 EvaluationBatchConfig

定义：

```python
@dataclass
class EvaluationBatchConfig:
    batch_id: str
    comparison_group_id: str | None
    comparison_type: Literal["model_id", "role_version"]
    mode: Literal["dev", "formal"] = "dev"
    evaluation_set_id: str
    seed_set_id: str
    model_id: str
    model_config_hash: str
    game_count: int
    max_days: int = 20
    player_count: int = 12
    ruleset_version: str = "werewolf_12p_v1"
    temperature: float = 1.0
    target_role: str | None = None
    target_version_id: str | None = None
    role_version_config: dict[str, str] = field(default_factory=dict)
```

约束：

```text
temperature 固定 1.0。
thinking_enabled 不入参。
一局内所有 AI 使用同一个 model_id。
run_type 固定 evaluation_batch。
learning_eligible 固定 false。
rankable 由后端计算，禁止请求传入。
```

### 9.4 公平性校验

`agent/evaluation/fairness.py`：

```text
validate_model_comparison(batches)
validate_role_version_comparison(batches)
```

模型比较要求：

```text
同 evaluation_set_id
同 seed_set_id
同 game_count
同 max_days
同 player_count
同 ruleset_version
同 role_version_config
只改变 model_config_hash / model_id
```

单角色版本比较要求：

```text
同 model_id
同 model_config_hash
同 evaluation_set_id
同 seed_set_id
同 game_count
同 max_days
同 player_count
同 ruleset_version
其他角色版本相同
只改变 target_role 的 version_id
```

不满足公平性：

```text
batch 可保存，但 rankable=false。
不能进入归因 leaderboard。
```

rankable 后端计算条件：

```text
run_type = evaluation_batch
mode = formal
paired_seed = true
game_count >= 20
valid_sample_rate >= 0.8
比较维度合法
配置 hash 满足公平约束
```

### 9.5 Runner 实现

`agent/evaluation/runner.py`：

```text
复用 engine + AgentRuntime + GamePersistence。
每局调用统一评测服务。
每局 run_type=evaluation_batch。
每局 learning_eligible=false。
产物写 runs/evaluation_batches/{batch_id}/games/game_XXX。
summary 写 runs/evaluation_batches/{batch_id}/summary.json。
正式榜单以 DB 为权威，runs artifacts 只作为 debug/export/cache。
```

可以复用 `agent/learning/evolution/games.py` 的部分逻辑，但建议不要继续扩大 `SelfPlayConfig` 的职责。

第一阶段允许内部调用现有 `run_selfplay()`，前提是：

```text
显式传 run_type=evaluation_batch。
删除或忽略 enable_mid_memory。
由 run_policy.learning_eligible=false 阻止学习写入。
强制 enable_long_term_consolidation=false。
强制 temperature=1.0。
```

### 9.6 API

新增：

```text
POST /api/evaluation-batches
GET  /api/evaluation-batches
GET  /api/evaluation-batches/{batch_id}
GET  /api/evaluation-batches/{batch_id}/games
GET  /api/evaluation-batches/{batch_id}/summary
```

请求第一版只支持两种模式：

```json
{
  "comparison_type": "model_id",
  "mode": "formal",
  "evaluation_set_id": "model_eval_v1_20",
  "seed_set_id": "model_eval_v1_20",
  "model_id": "qwen",
  "game_count": 20
}
```

```json
{
  "comparison_type": "role_version",
  "mode": "formal",
  "evaluation_set_id": "role_eval_v1_20",
  "seed_set_id": "role_eval_v1_20",
  "model_id": "qwen",
  "target_role": "witch",
  "target_version_id": "witch_v2",
  "role_version_config": {
    "witch": "witch_v2",
    "seer": "baseline",
    "werewolf": "baseline"
  },
  "game_count": 20
}
```

### 9.7 测试

新增：

```text
tests/test_evaluation_batch_config.py
tests/test_evaluation_fairness.py
tests/test_evaluation_runner.py
```

覆盖：

```text
模型 batch 只改变 model_id / model_config_hash 才 rankable。
角色版本 batch 只改变目标角色版本才 rankable。
evaluation_batch 不写 experience_candidates。
summary 包含 role_score、role category scores、risk_penalty、data_sufficient、rankable reason。
```

### 9.8 验收

```text
同 evaluation_set/seed_set 跑两个 model_config_hash，能得到两个 batch summary。
同 evaluation_set/seed_set 跑同一角色两个 version_id，能得到两个 batch summary。
非公平 batch 不进入 leaderboard。
```

---

## 10. Phase 6: Benchmark Leaderboard

### 10.1 目标

做两张第一阶段 benchmark 榜：

```text
model leaderboard
single-role version leaderboard
```

自进化 A/B promotion summary 单独保留，不和 benchmark leaderboard 混用。

### 10.2 新表

建议不要重载旧 `leaderboard` 表，新增：

```text
evaluation_batches
benchmark_leaderboard
```

`evaluation_batches`：

```text
id TEXT PRIMARY KEY
comparison_group_id TEXT
comparison_type TEXT
model_id TEXT
target_role TEXT
target_version_id TEXT
role_version_config TEXT
game_count INTEGER
evaluation_set_id TEXT
seed_set_id TEXT
max_days INTEGER
player_count INTEGER
ruleset_version TEXT
rankable INTEGER DEFAULT 0
summary TEXT
started_at TEXT
finished_at TEXT
```

`benchmark_leaderboard`：

```text
id TEXT PRIMARY KEY
scope TEXT                         -- model | role_version
subject_id TEXT                    -- model_id 或 role:version_id
model_id TEXT
model_config_hash TEXT
target_role TEXT
target_version_id TEXT
comparison_group_id TEXT
evaluation_set_id TEXT
seed_set_id TEXT
ruleset_version TEXT
scoring_version TEXT
evaluator_config_hash TEXT
games_played INTEGER
valid_game_rate REAL
strength_score REAL
avg_role_score REAL
by_role_category_scores TEXT
avg_speech_score REAL
avg_vote_score REAL
avg_skill_score REAL
avg_logic_score REAL
avg_team_score REAL
risk_penalty REAL
fallback_rate REAL
llm_error_rate REAL
policy_adjusted_rate REAL
good_side_win_rate REAL
wolf_side_win_rate REAL
target_side_win_rate REAL
rankable INTEGER DEFAULT 0
data_sufficient INTEGER DEFAULT 0
summary TEXT
updated_at TEXT
```

### 10.3 模型强度计算

`agent/evaluation/metrics.py`：

```text
role_score = weighted_base_score - risk_penalty

weighted_base_score =
  0.25 * speech_score
+ 0.25 * vote_score
+ 0.20 * skill_score
+ 0.20 * logic_score
+ 0.10 * team_score

model_strength_score =
  equal_weight_average(role_category_scores)
```

规则：

```text
formal + paired_seed + games_played >= 20 才 data_sufficient=true。
valid_game_rate >= 0.8。
同一 snapshot 必须同 evaluation_set_id / seed_set_id / ruleset_version / scoring_version / evaluator_config_hash。
类别内样本平均，类别间等权。
胜率只辅助展示。
```

### 10.4 单角色版本强度计算

```text
role_version_strength_score = target_role_score
delta_vs_baseline = target_role_score - baseline_target_role_score
```

规则：

```text
同 evaluation_set_id / seed_set_id / ruleset_version / scoring_version / evaluator_config_hash。
同 gameplay model_config_hash。
同 other_role_version_config_hash。
只替换 target_role_version_id。
必须包含 baseline run 作为参照，否则 snapshot rankable=false。
target_role_score_delta >= 0.05 才显示“显著更强”。
其他角色指标只作为 safety gate。
```

### 10.5 API

新增：

```text
GET /api/leaderboards/models
GET /api/leaderboards/role-versions
GET /api/leaderboards/comparison-groups/{comparison_group_id}
```

保留：

```text
GET /api/leaderboards
```

第一阶段策略：

```text
旧 /api/leaderboards 不作为新榜单权威入口。
新 UI/API 使用 /models 和 /role-versions。
旧数据全清，不做旧 leaderboard 兼容聚合。
```

### 10.6 UI 第一阶段

如果本轮包含前端改造：

```text
Logs / Evolution 页面先不混入 benchmark 榜。
新增或预留 Evaluation 页面。
展示模型榜、单角色版本榜、comparison_group 详情。
```

如果不做前端：

```text
先保证 API + JSON summary 完整。
前端单独排期。
```

### 10.7 测试

新增：

```text
tests/test_benchmark_leaderboard.py
tests/test_evaluation_metrics.py
```

覆盖：

```text
role_score 公式。
model leaderboard 角色类别等权聚合。
role-version leaderboard 只看 target_role_score。
games < 20 时 data_sufficient=false。
valid_game_rate < 0.8 时 rankable=false。
同 comparison_group 下能计算 delta。
```

### 10.8 验收

```text
模型榜能区分不同 model_id / model_config_hash。
单角色版本榜能区分同一 target_role 的不同 version_id。
不公平 batch 不进入归因排名。
evolution_ab 不进入 benchmark leaderboard。
```

---

## 11. Phase 7: 自进化学习链路隔离

### 11.1 目标

保证自进化只从 `evolution_training` 学习，A/B 只用于验证。

### 11.2 训练局

改造：

```text
agent/learning/evolution/pipeline.py
agent/learning/evolution/games.py
agent/runner/evolution_runner.py
```

训练阶段必须传：

```text
run_type=evolution_training
learning_eligible=true
leaderboard_scope=evolution_training
promote_eligible=false
```

允许：

```text
ReviewService completed
run_evidence_pipeline
save_experience_candidates 到 evolution.db
positive_pattern_candidate / anti_pattern_candidate / correction_candidate
```

禁止：

```text
mid_memory 新写入或新读取
Pattern 新写入或新读取
Episodic 新写入或新读取
普通对局 / evaluation_batch / A-B / imported_mistake_case 作为经验来源
```

学习器配置：

```text
formal EvidencePipeline 使用固定 evidence_config_hash。
formal Consolidation 使用固定 consolidation_config_hash。
evolution_round / candidate_package / promotion_decision 必须记录 learning_pipeline_version。
learning_pipeline_version 变化后建议新 evolution experiment namespace。
gameplay model 不负责写 skill；skill 由 evidence/consolidation/applier 链生成。
```

### 11.3 A/B 验证局

A/B baseline：

```text
run_type=evolution_ab_baseline
learning_eligible=false
leaderboard_scope=evolution_ab
promote_eligible=false
```

A/B candidate：

```text
run_type=evolution_ab_candidate
learning_eligible=false
leaderboard_scope=evolution_ab
promote_eligible=true only through paired A/B summary
```

禁止：

```text
run_evidence_pipeline
save_experience_candidates
pattern update
episodic write
situational_records / decision_outcomes write
```

### 11.4 查询防线

所有用于 candidate 生成的查询必须带过滤：

```text
learning_eligible = 1
run_type = 'evolution_training'
```

涉及：

```text
storage/evolution/experience_repo.py
storage/evolution/rejected_repo.py
agent/learning/evolution/consolidation.py
agent/learning/evolution/pipeline.py
```

旧数据策略：

```text
旧数据全清。
新查询不做 unknown run_type 兼容。
不写 migration/backfill。
```

### 11.5 Promotion Gate

`agent/learning/evolution/battle.py` 的 `_is_significant_improvement()` 改为使用 spec 中晋升条件：

```text
minimum_pairs >= 20
valid_game_rate >= 0.8

target_role_score_delta >= +0.05
或者 win_rate_delta >= +0.10

fallback_rate_delta <= +0.03
policy_adjusted_rate_delta <= +0.05
non_target_role_score_delta >= -0.03
```

阈值配置化：

```text
agent/learning/evolution/config.py
```

### 11.6 Registry / Branch / Round 状态机

新增或改造：

```text
agent/learning/evolution/registry.py
storage/registry/schema.py
storage/registry/repo.py
agent/learning/evolution/rounds.py
```

Role version 规则：

```text
role_version_id 全局唯一、不可变。
内容变化必须生成新 version。
candidate A/B 前冻结 skill_package_hash。
A/B 通过后 status candidate -> promoted，不新建 baseline duplicate。
baseline 只是 role_current_baseline 指针。
baseline 更新写 role_baseline_history。
```

状态：

```text
role_version.status = candidate | promoted | rejected | invalid | deprecated
第一阶段不自动产生 deprecated。
current baseline 必须指向 promoted。
多个 promoted 历史版本可以并存。
baseline_history.reason 可预留 admin_override 枚举。
第一阶段代码禁止写 admin_override。
不提供人工切 baseline / rollback API。
```

Branch：

```text
formal evolution experiment 创建 evolution_branch_id。
同一 branch 内 generation 从 parent.generation + 1 递增。
parent_version_id 单父节点。
换 trained_gameplay_model 或 start_from_empty=true 时新建 branch。
同一 role 同时只允许一个 formal round running。
promotion 前校验 current baseline 仍等于 parent_version_id。
promotion 成功后，同 role 其他 active formal branches 全部 stale。
```

Round 状态机：

```text
created
training_running
training_completed
review_completed
candidates_generated
proposal_generated
ab_running
ab_completed
promoted
rejected
completed_no_proposal
failed
stale
```

终态：

```text
promoted
rejected
completed_no_proposal
failed
stale
```

A/B 数据不足：

```text
round failed
candidate package invalid
不写 rejected_proposals
```

A/B 完整但提升不足或 safety gate 失败：

```text
candidate package rejected
proposal 写 rejected_proposals
baseline 不变
如果无法归因到单条 proposal，则包内所有 proposal 写入 rejected_proposals。
rejection_scope=package_level_uncertain。
confidence=low。
```

### 11.7 Experience / Proposal / Skill Applier

`run_evidence_pipeline` 是第一阶段唯一 `experience_candidates` 生成器。

当前代码事实：

```text
agent/learning/pipeline.py::run_evidence_pipeline(game_dir, ...)
  直接读取 archive.json / agent_decisions.jsonl / game_events.jsonl / meta.json。

这和 ReviewService 是 EvidencePipeline 唯一上游的 spec 不一致。
```

必须改造：

```text
新增 EvidencePipeline 输入模型:
  game_id
  run_id
  run_type
  mode
  learning_eligible
  ReviewService structured result
  review_item_ids / judgment_ids

run_evidence_pipeline 第一阶段可以保留 artifact debug/export 输出，
但正式 candidate 生成必须从 ReviewService result 构造输入。
如果临时仍读取 artifact，必须通过 artifact_game_id 与 wolf.db game_id 对齐，并标记为过渡实现。
```

Candidate 准入：

```text
run_type=evolution_training
learning_eligible=true
至少 2 个不同 source_game_id
candidate_type in positive_pattern_candidate | anti_pattern_candidate | correction_candidate
confidence >= 0.7
必须绑定 role 和 phase/action
```

mode 规则：

```text
mode=dev:
  可以写 debug experience_candidates / proposals。
  不能 promotion。
  不能写 rejected_proposals。
  formal consolidation 默认不读取。

mode=formal:
  可以进入正式 consolidation。
  可以进入 A/B promotion。
  A/B 数据充分且失败时可以写 rejected_proposals。
```

Consolidation 只读取：

```text
experience_candidates
current active skills
rejected_proposals as guardrail
```

当前代码事实：

```text
agent/learning/evolution/consolidation.py::consolidate_for_role()
  仍扫描 run_dir/games/*/mid_memory/*.json。
  默认 db_path = DEFAULT_PATHS.data_dir / "wolf.db"。
  同时读取 mid_memory 和 SQLite experience_candidates。
```

必须改造：

```text
删除 formal consolidation 的 mid_memory 扫描。
db_path 默认改为 DEFAULT_PATHS.data_dir / "evolution.db" 或显式 EvolutionRepository。
formal consolidation 只从 evolution.db 读取 mode=formal 的 experience_candidates。
dev consolidation 可以读 mode=dev，但不能 promotion。
```

guardrail 规则：

```text
rejected_proposals 优先级高于 Deprecated Rules。
rejected_proposals 不进入 runtime prompt。
Deprecated Rules 不进入 runtime prompt。
命中 rejected_proposals 的相似 proposal 默认不生成。
命中 Deprecated Rules 但未命中 rejected_proposals 的策略，未来只能按 revival_candidate 机制重新挑战；第一阶段不实现自动 revival。
```

Proposal 规则：

```text
每轮最多 3 个 proposals。
每个 proposal 只影响一个 skill 文件。
每个 proposal 只表达一个 behavior change。
禁止跨角色泛化。
默认禁止跨阶段泛化，除非 phase_general=true 且有多阶段证据。
证据冲突则 conflicted，不出 proposal。
already_covered 不出 proposal。
```

Skill Applier 允许：

```text
create_skill
append_rule
rewrite_section
deprecate_rule
```

Skill Applier 禁止：

```text
人工 skill 导入/编辑路径
修改 existing skill frontmatter
修改 Deprecated Rules / Changelog / Provenance / Evaluation Notes
向 runtime sections 写玩家号、game_id、run_id、seed、模型名、provider、A/B 细节
超过 active skill 上限时 create_skill
```

Skill 上限：

```text
max_active_skills_per_role = 8
max_selected_skills_per_decision = 3
runtime_body_soft_limit = 1800 chars
runtime_body_hard_limit = 2400 chars
skill_file_total_soft_limit = 6000 chars
超过 soft 优先 rewrite_section 压缩。
超过 hard 拒绝 append_rule。
```

Runtime sections：

```text
Strategy
Heuristics
Decision Rules
Risk Boundaries
```

System sections：

```text
Examples
Deprecated Rules
Changelog
Provenance
Evaluation Notes
```

Applier 后必须执行：

```text
frontmatter validator
runtime forbidden-content scanner
section classifier
runtime_body length validator
skill_package_hash recompute
registry dirty check
```

### 11.8 测试

新增：

```text
tests/test_evolution_learning_boundaries.py
tests/test_evolution_ab_no_learning.py
```

覆盖：

```text
evolution_training 写 experience。
evolution_ab_baseline 不写 experience。
evolution_ab_candidate 不写 experience。
ordinary/evaluation_batch/evolution_ab 不写 experience。
全清后不存在 unknown 旧 experience；新查询不做旧数据兼容。
A/B summary 可以触发 promote/reject，但不能成为下一轮 learning evidence。
```

### 11.9 验收

```text
自进化 candidate 生成只读取 evolution_training。
A/B 结果只进入 battle_summary / version history。
普通 bad case 和 evaluation batch bad case 不会影响 skill proposal。
```

---

## 12. Phase 8: 普通对局复盘增强但不学习

### 12.1 目标

普通对局继续作为演示和复盘入口，能输出多维评分、关键决策复盘、反事实和结构化报告，但不产生任何经验。

### 12.2 改造点

```text
ui/backend/game_runner.py
ui/backend/battle/game_routes.py
ui/frontend/src/pages/LogsPage.vue
ui/frontend/src/composables/useGameHistory.js
```

后端：

```text
GET /api/games/{game_id}/review 读取 reports/evaluations/decision_reviews/counterfactuals。
review.json 只作为 debug/export/cache，DB review facts 是权威。
```

前端：

```text
继续展示 player_scores / turning_points / counterfactuals / timeline。
以后端结构化 review API 为准。
```

### 12.3 禁止项

```text
普通对局不写 evolution evidence。
普通对局不写 patterns。
普通对局不写 episodic memory。
普通对局不进 model leaderboard。
普通对局不进 role-version leaderboard。
```

### 12.4 TODO 记录

在 spec 或 plan TODO 中保留：

```text
imported_mistake_case / 失误案例库
```

不实现：

```text
导入外部错误局
expected_mistakes schema
复盘命中率回归测试
失误案例 UI
```

### 12.5 验收

```text
跑一局普通 UI 对局。
完成后有 review.json。
DB 中有评测事实。
evolution.db 中没有该 game_id 的学习事实。
```

---

## 13. Phase 9: 清理旧概念和文档同步

### 13.1 清理代码

完成主路径后清理：

```text
AgentRuntime docstring 中的旧 pipeline。
architecture_v2.md 中 inject_memory_step 的旧描述。
docs/ideas.md 中已过期的 Pattern/Episodic runtime injection 状态。
tests 中对 rolling_summary / pinned_facts / player_models 的旧断言。
```

### 13.2 保留但降级

以下模块可以保留，但从 runtime 主路径移除：

```text
agent/decision/steps/inject_memory.py
agent/learning/providers.py
agent/core/episodic_memory.py
storage/evolution/pattern_repo.py
```

定位：

```text
legacy/debug
后续实验
```

不是：

```text
运行时 prompt 输入
普通对局学习源
benchmark 学习源
```

### 13.3 文档更新

更新：

```text
docs/superpowers/specs/2026-06-04-global-architecture.md
docs/architecture_v2.md
README.md 如有相关入口说明
```

同步说明：

```text
三路线边界
固定 7 步 pipeline
运行时长期知识只来自 Skill
evaluation_batch leaderboard 只比较 model_id 和单角色 role/version_id
```

---

## 14. 建议实施顺序

推荐按以下 PR / 提交切分：

### PR 1: RunPolicy 与学习写入闸门

范围：

```text
agent/common/run_policy.py
agent/game_run/service.py
agent/game_run/models.py
storage/runtime.py
storage/experience_store.py
storage/schema.py
storage/evolution/schema.py
ui/backend/game_runner.py
agent/runner/battle_runner.py
agent/learning/evolution/games.py
agent/runner/evolution_runner.py
tests/test_run_policy.py
tests/test_learning_boundaries.py
```

交付：

```text
GameRunService 成为唯一 run_id/game_id 创建入口。
所有 game 都有 run_type。
非 learning_eligible 不写 experience。
ordinary/battle 不再写 episodic/pattern。
```

### PR 1.5: 全清与 Registry Bootstrap

范围：

```text
storage/registry/schema.py
storage/registry/repo.py
engine/rulesets/*
agent/learning/evolution/registry.py
scripts/bootstrap_registry.py
tests/test_registry_bootstrap.py
```

交付：

```text
全清后从 werewolf_12p_v1 创建每个具体角色的空 baseline。
不从旧 handwritten skills 初始化。
普通对局必须锁定具体 role_version_id 和 skill_package_hash。
hash dirty 时中断，不自动回滚。
```

### PR 2: Runtime 移除 cross-game injection

范围：

```text
agent/api/runtime.py
agent/core/context.py
agent/decision/steps/inject_memory.py
agent/decision/steps/build_prompt.py
agent/knowledge/prompts/base.py
tests/test_agent.py
```

交付：

```text
AgentRuntime 不再读取 evolution.db。
prompt 不再包含经验记忆注入。
```

### PR 3: Segment Memory + compress_memory_step

范围：

```text
agent/core/memory.py
agent/core/memory_segments.py
agent/decision/steps/compress_memory.py
agent/api/runtime.py
agent/knowledge/skills/loader.py
agent/knowledge/skills/router.py
agent/decision/steps/select_skills.py
agent/knowledge/prompts/base.py
tests/test_agent_memory_segments.py
tests/test_compress_memory_step.py
tests/test_skill_runtime_sections.py
```

交付：

```text
固定 7 步 pipeline。
open segment + recent 4 closed + compressed summaries 生效。
压缩失败不阻塞。
```

### PR 4: 统一评测服务与落库

范围：

```text
agent/learning/review/service.py
agent/learning/review/metrics.py
agent/learning/review/judgments.py
agent/learning/review/scorer.py
ui/backend/game_runner.py
agent/learning/evolution/games.py
storage/battle/*.py
tests/test_review_service.py
```

交付：

```text
普通/批量/evolution 都能写评测事实。
LLM judgment 结构化落库。
Scorer 合成 role_score，ReportGenerator 不重算评分。
学习事实仍严格隔离。
```

### PR 5: Evaluation Batch 后端

范围：

```text
agent/evaluation/*.py
ui/backend/evaluation_routes.py
ui/backend/app.py
tests/test_evaluation_*.py
```

交付：

```text
支持 model_id batch。
支持 single-role version batch。
支持 comparison_group_id。
```

### PR 6: Benchmark Leaderboard

范围：

```text
storage/schema.py
storage/battle/benchmark_repo.py
agent/evaluation/metrics.py
agent/evaluation/leaderboard.py
ui/backend/battle/leaderboard_routes.py
tests/test_benchmark_leaderboard.py
```

交付：

```text
模型榜。
单角色版本榜。
leaderboard snapshots。
seed_set/evaluation_set/ruleset/scoring/evaluator hash 公平约束。
同组公平对比 delta。
```

### PR 7: Evolution A/B Gate 收口

范围：

```text
agent/learning/evolution/battle.py
agent/learning/evolution/pipeline.py
agent/learning/evolution/consolidation.py
agent/learning/evolution/applier.py
agent/learning/evolution/rounds.py
storage/evolution/*.py
tests/test_evolution_learning_boundaries.py
```

交付：

```text
自进化只读取 evolution_training。
A/B 只验证不学习。
promote/reject 使用 paired A/B summary。
experience_candidates -> proposals -> candidate package -> A/B -> baseline pointer。
rejected_proposals 只作 guardrail。
```

### PR 8: UI 与文档收尾

范围：

```text
ui/frontend/src/pages/*
ui/frontend/src/composables/*
docs/*
README.md
```

交付：

```text
普通复盘继续可用。
Evaluation leaderboard 有入口或 API 已准备。
旧文档不再描述 runtime injection。
```

---

## 15. 回归测试清单

后端：

```text
uv run pytest tests/test_run_policy.py
uv run pytest tests/test_learning_boundaries.py
uv run pytest tests/test_agent.py
uv run pytest tests/test_agent_memory_segments.py
uv run pytest tests/test_compress_memory_step.py
uv run pytest tests/test_review_service.py
uv run pytest tests/test_evaluation_fairness.py
uv run pytest tests/test_benchmark_leaderboard.py
uv run pytest tests/test_evolution_learning_boundaries.py
uv run pytest tests/test_role_evolution
```

前端如有改动：

```text
npm run build
```

手动烟测：

```text
1. 启动普通对局，结束后打开复盘。
2. 跑 2 个小样本 model evaluation batch，确认不会写 learning facts。
3. 跑 2 个小样本 role-version evaluation batch，确认 fairness metadata 正确。
4. 跑 1 次 evolution training 小样本，确认能写 experience。
5. 跑 1 次 evolution A/B 小样本，确认不写 experience，只写 battle summary。
```

---

## 16. 风险与处理

### 16.1 AgentMemory 重写风险高

风险：

```text
大量旧测试依赖 rolling_summary / pinned_facts / field_notes。
```

处理：

```text
先让 prompt formatter 忽略旧字段。
新 segment tests 稳定后再删除旧字段断言。
```

### 16.2 LLM 压缩增加延迟

风险：

```text
closed_segments 超过 4 时，每次可能多一次 LLM 调用。
```

处理：

```text
只压缩最旧一个 segment。
失败不阻塞。
后续再做 token/字符预算器和小模型 summarizer。
```

### 16.3 旧 selfplay 职责混乱

风险：

```text
SelfPlayConfig 既被 UI selfplay 用，也被 evolution training/A/B 用。
```

处理：

```text
第一步加 run_type 和 run_policy 强制闸门。
第二步新增 agent/evaluation/runner.py，逐步把 benchmark 从 SelfPlayConfig 中分离。
```

### 16.4 全清后误连旧路径

风险：

```text
代码仍可能从旧 artifacts、旧 Pattern/Episodic 表、旧 handwritten skills 或 runs 目录读取数据。
```

处理：

```text
重构前全清 data/wolf.db、data/evolution.db、data/registry/*、runs/*。
新查询只信任 run_type='evolution_training' AND learning_eligible=1 AND mode='formal'。
runtime 禁止 fallback 到 repo handwritten skills。
Consolidation 禁止读取 Pattern/Episodic/mid_memory。
```

### 16.5 Leaderboard 表语义冲突

风险：

```text
现有 leaderboard 表和新 benchmark leaderboard 混用会导致 UI/排序含义混乱。
```

处理：

```text
新增 benchmark_leaderboard。
旧 leaderboard 不作为新正式榜单权威。
```

---

## 17. 第一阶段完成定义

必须全部满足：

```text
1. 普通对局:
   - 能生成 review.json 和结构化复盘。
   - 不写 evolution evidence / patterns / episodic。

2. Evaluation batch:
   - 能批量比较 model_id。
   - 能批量比较单角色 role/version_id。
   - 公平性校验生效。
   - 能生成 model leaderboard 和 single-role version leaderboard。
   - 不写学习事实。

3. Self-evolution:
   - evolution_training 是唯一默认学习来源。
   - evolution_ab_baseline / evolution_ab_candidate 不学习。
   - promote/reject 只基于 paired A/B summary。

4. Agent runtime:
   - 固定 7 步 pipeline。
   - 无 Pattern/Episodic runtime injection。
   - prompt 使用 segment window + LLM compressed summaries + Markdown skills。
   - 压缩摘要不跨局复用，不进入 evidence。
```

---

## 18. 第二阶段 TODO

以下明确不在本次第一阶段实现：

```text
imported_mistake_case / 失误案例库
expected_mistakes schema
复盘系统命中率 leaderboard
token / 字符预算器
pinned_facts
player_models
self_commitments
单独 summarizer model
thinking_enabled 对比
temperature 对比
Agent 配置榜
Prompt pipeline 榜
Memory 策略榜
```

第二阶段可以单独写 spec：

```text
1. 失误案例库
2. Prompt 预算器与 pinned_facts
3. 复盘质量评测
4. 更细粒度模型能力诊断
```

---

## 19. Spec 对照检查清单

本节用于确认本 plan 已对齐两份 spec。实现时每项都应能对应到代码、schema 或测试。

### 19.1 三路线边界

```text
ordinary_game:
  baseline only
  review/report only
  no learning
  no benchmark leaderboard

evaluation_batch:
  benchmark only
  model_id/model_config_hash 或 single-role version
  no learning
  rankable 由后端计算

evolution_training:
  唯一正式学习来源
  ReviewService -> EvidencePipeline -> experience_candidates

evolution_ab:
  paired validation only
  no experience_candidates
  no skill_proposals
  only promotion/rejection decision
```

### 19.2 Runtime / Memory

```text
固定 7 步 pipeline。
不做 Pattern/Episodic runtime injection。
运行时不读 evolution.db。
短期记忆只保留 current visible state、open segment、recent 4 closed segments、compressed summaries。
LLM 压缩只基于 player-view events。
压缩摘要不跨局复用，不进入 evidence。
select_skills_step 确定性路由，不做语义检索。
prompt 只注入 runtime_body。
```

### 19.3 Skill / Registry

```text
registry 独立于 wolf.db/evolution.db。
全清后从 werewolf_12p_v1 bootstrap 空 baseline。
不从旧 handwritten skills 初始化。
role_version_id 不可变。
baseline 是 current pointer。
ordinary_game 创建时锁定具体 role_version_id。
hash dirty 中断，不自动回滚。
runtime sections 禁止玩家号、game_id、run_id、seed、模型名、provider、A/B 细节。
system sections 可记录 provenance，但不进 prompt。
```

### 19.4 Review / Scoring / Leaderboard

```text
ReviewService 是报告、Leaderboard、EvidencePipeline 的唯一评测上游。
LLM judgment 结构化落库。
LLM 不直接给最终分。
deterministic scorer 合成 role_score。
ReportGenerator 不重新计算评分。
leaderboard 写 snapshot。
同 snapshot 不混 ruleset_version、scoring_version、evaluator_config_hash、evaluation_set_id。
模型榜按角色类别等权聚合。
角色版本榜只看 target_role_score，其他角色只做 safety gate。
```

### 19.5 Seed / Ruleset / Mode

```text
第一阶段固定 ruleset_version=werewolf_12p_v1。
ruleset provider 属于引擎层。
seed_set 存 wolf.db 且不可变。
training / A-B / leaderboard seed sets 互不重叠。
dev 可调试但不能 rankable/promotion/rejected_proposals。
formal + paired + >=20 + valid rate 达标才可进入正式结论。
```

### 19.6 Self-evolution

```text
run_evidence_pipeline 是第一阶段唯一 experience_candidates 生成器。
Consolidation 只读 experience_candidates + active skills + rejected_proposals。
不读 ReviewService tables / Pattern / Episodic / runtime summaries / mid_memory。
每轮最多 3 proposals。
每个 proposal 只影响一个 skill 文件和一个 behavior change。
禁止跨角色泛化。
A/B 数据不足不是 rejected。
A/B 数据充分但提升不足或 safety gate 失败才写 rejected_proposals。
rejected_proposals 是 guardrail，不进入 runtime。
```

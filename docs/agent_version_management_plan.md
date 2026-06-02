# Agent 策略版本管理与版本对战设计

## 1. 目标

本设计的目标是为 AI 狼人杀 Agent 层补齐一套可复现、可比较、可回滚的策略版本管理机制，并用版本对战验证自进化是否真的带来能力提升。

这里的版本管理不是管理整个代码仓库，而是管理 Agent 的策略状态。代码仍由 Git 管理，Agent 版本系统只负责记录一次实验中真正影响 Agent 决策表现的策略资产。

最终要解决四个问题：

1. 策略从哪里来。
2. 策略改了什么。
3. 策略是否真的变强。
4. 策略结果能否复现。

推荐答辩表述：

> 我们版本化的不是项目代码，而是 Agent 策略状态。每个版本包含 Markdown Skills、Prompt、长期记忆、模型配置和推理参数。系统通过 selfplay 产生对局，经 review、experience、dream 生成策略修改建议，再形成新的 AgentVersion。随后用固定 seed 的 version battle 与历史版本对战，只有多维指标显著提升的版本才会晋级。

## 2. 版本管理的对象

一个 Agent 策略版本可以定义为：

```text
AgentVersion =
  Skills
  + Prompts
  + Long Memory
  + Model Config
  + Runtime Feature Flags
  + Belief / ToT / GoT 参数
  + 版本元数据
```

各对象的版本化优先级如下：

| 对象                            | 是否必须版本化 | 原因                                                                                                                                       |
| ----------------------------- | ------: | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `skills/`                     |      必须 | 当前策略主体，Dream Agent 和经验沉淀主要修改这里。                                                                                                          |
| `agent/prompts/`              |     视情况 | 只版本化仍包含策略性文本的 prompt 模板；纯运行时渲染模板由 Git commit 记录即可。                                                                                       |
| long memory snapshot          |      必须 | 自进化后的长期经验资产，版本内保存为 `agent_versions/<name>/memory/` 快照；来源可以是当前 validated 主线 `data/long_memory/`，也可以是本轮 `runs/<run_id>/memory_candidate/`。 |
| 模型配置                          |      必须 | 模型名、temperature、max tokens 会影响公平比较。                                                                                                      |
| ToT / GoT / Belief 参数         |      必须 | 是否启用深度推理、图推理、概率更新策略会显著影响结果。                                                                                                              |
| Agent Runtime 代码              |   不建议复制 | Runtime 是基础设施，使用 Git commit 记录即可。                                                                                                        |
| 对局日志                          | 不属于版本本体 | 是评测产物，应该挂在 run / battle 结果下面。                                                                                                            |
| Dream Report / Skill Proposal | 不属于版本本体 | 是版本生成依据，需要在 manifest 中引用。                                                                                                                |

因此版本管理的核心对象是：

```text
策略版本，不是项目版本。
```

## 3. 推荐目录结构

新增两个顶层目录：

```text
agent_versions/
  baseline/
    manifest.json
    skills/
    prompts/
    memory/

  dream_v1/
    manifest.json
    skills/
    prompts/
    memory/

  dream_v2/
    manifest.json
    skills/
    prompts/
    memory/

runs/
  version_battles/
    battle_20260527_001/
      config.json
      leaderboard.json
      leaderboard.md
      result.json
      baseline/
        game_001/
        game_002/
      dream_v1/
        game_001/
        game_002/
```

当前根目录 `skills/` 作为开发中的 working copy：

```text
skills/                  当前正在调试的策略
agent_versions/baseline/ 固化后的可复现版本
agent_versions/dream_v1/ 第一次进化后的策略版本
```

不要让长期评测直接依赖不断变化的 `skills/`。否则旧实验无法复现。正确做法是先把 working copy 固化成一个 `agent_versions/<name>/`，再用该版本参与评测。

## 4. Manifest 设计

每个 AgentVersion 必须包含一个 `manifest.json`。它是版本的索引、配置和可追溯记录。

示例：

```json
{
  "version": "dream_v1",
  "display_name": "Dream V1",
  "description": "基于 baseline 自博弈 20 局后生成的第一版策略",
  "created_at": "2026-05-27T14:00:00+08:00",
  "base_version": "baseline",
  "status": "candidate",

  "runtime": {
    "git_commit": "484f90a",
    "agent_runtime": "agent_v2",
    "belief_policy": "weighted_evidence_v2",
    "tot_enabled": true,
    "got_enabled": true,
    "got_trigger_policy": "sparse_high_conflict"
  },

  "evolution": {
    "per_game_dream_enabled": false,
    "batch_dream_enabled": true,
    "skill_proposal_policy": {
      "auto_apply": false,
      "min_confidence": 0.75,
      "min_evidence_cards": 3,
      "require_human_review": true
    }
  },

  "model": {
    "provider": "volcengine",
    "model": "doubao-seed-2.0-pro",
    "temperature": 0.7,
    "max_tokens": 2048
  },

  "paths": {
    "skills": "./skills",
    "prompts": "./prompts",
    "memory": "./memory"
  },

  "training_source": {
    "selfplay_run_id": "selfplay_20260527_001",
    "source_games": 20,
    "experience_cards": [
      "data/experiences/werewolf/cards.jsonl",
      "data/experiences/witch/cards.jsonl"
    ],
    "dream_reports": [
      "data/dreams/werewolf/dream_xxx.json",
      "data/dreams/witch/dream_xxx.json"
    ],
    "skill_proposals": [
      "data/skill_proposals/werewolf/proposal_xxx.json"
    ]
  },

  "evaluation": {
    "last_battle_id": null,
    "promoted_from": null,
    "rejected_reason": null
  },

  "notes": [
    "增强狼人悍跳策略",
    "女巫毒药策略改为更保守",
    "村民投票更依赖票型和站边"
  ]
}
```

关键字段说明：

| 字段 | 作用 |
|---|---|
| `version` | 稳定版本名，用于加载和对战配置。 |
| `base_version` | 当前版本基于哪个旧版本演化。 |
| `status` | 版本状态，区分草稿、候选、验证通过、拒绝。 |
| `runtime.git_commit` | 记录当时使用的代码版本，保证可复现。 |
| `runtime.belief_policy` | 记录 Belief 更新算法版本。 |
| `runtime.tot_enabled` | 记录是否启用 ToT 深度决策。 |
| `runtime.got_enabled` | 记录是否启用 GoT 图推理。 |
| `runtime.got_trigger_policy` | 记录 GoT 触发策略，例如仅在高冲突关键决策启用。 |
| `evolution` | 记录版本进化相关配置，例如 per-game dream 是否关闭、batch dream 是否启用、proposal 是否允许自动应用。 |
| `model` | 记录模型和采样参数，避免不公平比较。 |
| `paths` | 记录该版本实际加载的 skills、prompts、memory。 |
| `training_source` | 记录版本如何产生，便于审计。 |
| `evaluation` | 记录最近一次版本对战和晋级/拒绝原因。 |

## 4.1 GoT 在版本中的定位

GoT 属于 Agent 策略版本的一部分，但不应该替代所有普通决策。它的定位是高风险关键决策增强器。

当前推荐的推理层级是：

```text
普通决策：
  Prompt + Skill + Memory + Belief

关键决策：
  ToT 多候选比较

高冲突关键决策：
  GoT 证据图 / 假设图 / 冲突图
```

GoT 适合的动作包括：

1. 白天投票：`exile_vote` / `pk_vote`。
2. 女巫用药：`witch_act`。
3. 猎人开枪：`hunter_shoot`。
4. 狼人夜刀：`werewolf_kill`。
5. 预言家查验：`seer_check`。
6. 白狼王自爆：`white_wolf_explode`。

GoT 的触发不建议全量开启。推荐稀疏触发：

```text
metadata.enable_got = true
metadata.high_conflict = true
metadata.reasoning_mode = "got"
或 belief top 3 嫌疑接近且均较高
```

GoT 输出应被完整归档：

```json
{
  "got_enabled": true,
  "got_evidence_nodes": [
    {
      "node_id": "e1",
      "kind": "speech",
      "summary": "P8 怀疑 P3",
      "source": "public_log",
      "reliability": 0.6
    }
  ],
  "got_hypotheses": [
    {
      "hypothesis_id": "h1",
      "claim": "P3 是狼，P9 可能跟狼队节奏",
      "supporting_evidence": ["e1"],
      "conflicting_evidence": [],
      "expected_action": {
        "choice": "vote",
        "target": 3
      },
      "confidence": 0.66
    }
  ],
  "got_judge_reason": "h1 支持证据更多且反证较少"
}
```

版本对战时必须记录 GoT 是否启用、触发次数和效果。否则无法判断新版本提升是来自 skill 变强、belief 变强，还是只是因为更多关键节点使用了更重的推理。

MVP 阶段不强求直接计算 GoT 的收益增量。因为 GoT 触发次数通常较少，早期样本量不足，`got_value_delta` 容易误导。第一版只要求记录：

1. `got_trigger_count`。
2. `got_usage_rate`。
3. `got_failure_count`。
4. 每次 GoT 的 evidence / hypothesis / judge reason。

等积累足够样本后，再引入 `got_success_rate` 和 `got_value_delta`。

## 5. 版本状态机

建议每个版本有明确状态：

```text
draft       草稿，刚生成，尚未进入正式评测
candidate   候选版本，可以参与版本对战
validated   已通过版本对战，表现优于基线
rejected    表现下降或不稳定，保留但不晋级
archived    历史版本，不再参与常规对战
```

状态流转：

```text
draft
  ↓
candidate
  ↓
validated

candidate
  ↓
rejected

validated / rejected
  ↓
archived
```

晋级规则不建议只看胜率。推荐第一版规则：

```text
如果 candidate 相比 base_version：
- 平均 review score 提升 >= 5%
- bad case count 不增加
- fallback rate 不增加
- policy_adjusted_rate 不增加
- 胜率下降 < 10 个百分点（MVP 阶段用百分比阈值；正式评测改用 permutation test，要求 candidate 相比 base 没有显著退化，同时 review score / bad case 等主指标满足提升阈值）

则标记为 validated。
否则标记为 rejected，并写入 rejected_reason。
```

## 6. 版本生成流程

需要新增一个版本生成能力：

```text
create_agent_version(
  name="dream_v1",
  base="baseline",
  source_skill_dir="skills",
  source_prompt_dir="agent/prompts",
  source_memory_dir="agent_versions/baseline/memory 或 runs/<run_id>/memory_candidate",
  notes="..."
)
```

流程：

```text
1. 创建 agent_versions/dream_v1/
2. 复制 skills/
3. 按需复制 agent/prompts/
4. 复制 base version 的 memory 快照，或复制本轮 selfplay 生成的 `runs/<run_id>/memory_candidate/`
5. 读取当前 git commit
6. 写 manifest.json
7. 校验 manifest 中的路径存在
8. 校验该版本可被 AgentRuntime / selfplay 加载
```

注意事项：

1. 不要直接修改 `agent_versions/baseline/`。
2. Dream Agent 生成的修改建议应先应用到 candidate 版本。
3. 只有 candidate 通过版本对战后，才标记为 validated。
4. rejected 版本不要删除，要保留失败原因和评测产物。

推荐生成链路：

```text
baseline
  ↓
create candidate version
  ↓
apply reviewed proposals to candidate
  ↓
跑 version battle
  ↓
promote candidate to validated / reject
```

### 6.1 长期记忆版本化策略

长期记忆必须以快照形式进入版本，不能让多个版本共享同一个可变目录。

推荐规则：

1. 创建新版本时，从 `base_version` 复制一份 memory 快照。
2. 新版本 selfplay 产生的新 long memory 只合并到 candidate 版本。
3. baseline / validated 版本不允许被后续实验覆盖。
4. manifest 记录 memory 来源和合并记录。
5. rejected 版本保留自己的 memory 快照，便于复盘失败原因。

示例：

```text
agent_versions/
  baseline/
    memory/
      werewolf.json
      witch.json

  dream_v1_candidate/
    memory/
      werewolf.json   基于 baseline 复制后合并本轮经验
      witch.json
```

不要在 manifest 里只引用 `data/long_memory/` 的共享路径。共享路径适合作为工作区输出，不适合作为可复现版本资产。

### 6.2 Prompt 与 Skill 的权限边界

Prompt 和 Skill 都会影响 Agent 决策，但修改权限应该不同。

| 对象 | 修改来源 | 自动应用策略 | 原因 |
|---|---|---|---|
| `skills/` | Dream Agent proposal、人工调优 | 可应用到 candidate，但必须记录 proposal id | Skill 是策略知识，适合小步迭代。 |
| `prompts/` | 主要人工调优 | 默认不自动应用 | Prompt 影响全局行为，风险比 skill 更高。 |
| `memory/` | selfplay + consolidation | 可自动生成 candidate 快照 | Memory 是经验资产，但必须和版本绑定。 |

Dream Agent 可以对 prompt 提出建议，但不应直接修改 prompt 模板。Prompt 变更需要在 manifest 中单独记录：

```json
{
  "prompt_changes": [
    {
      "file": "agent_versions/dream_v1/prompts/base.md",
      "reason": "强化 private_reasoning 与 public_text 的隔离",
      "source": "manual_review",
      "risk": "可能改变所有角色输出风格"
    }
  ]
}
```

### 6.3 Skill Proposal 自动应用策略

MVP 阶段不建议默认自动应用 Dream Agent 生成的 proposal。

推荐配置：

```json
{
  "skill_proposal_policy": {
    "auto_apply": false,
    "min_confidence": 0.75,
    "min_evidence_cards": 3,
    "require_human_review": true
  }
}
```

流程：

```text
Dream Agent 生成 proposal
  ↓
写入 data/skill_proposals/
  ↓
人工或规则审核
  ↓
应用到 candidate skills/
  ↓
跑 version battle
  ↓
promote / reject
```

只有在多次验证 proposal 质量稳定后，才考虑打开 `auto_apply=true`。即使自动应用，也必须只应用到 candidate 版本，不能直接改 baseline 或 validated 版本。

### 6.4 apply_skill_proposals() 接口改造

当前 `apply_skill_proposals()` 直接修改根目录 `skills/`。版本管理要求它只改 candidate 版本的 skills。

接口变更：

```python
# 当前
def apply_skill_proposals(
    proposals,
    *,
    skill_root: Path | str | None = None,
    patch_dir: Path | str | None = None,
    ...
): ...

# 改为
def apply_skill_proposals(
    proposals,
    *,
    target_skill_root: Path,                  # 必须显式传入，只写 candidate
    audit_skill_root: Path | None = None,     # 用于查重/对比，不写入
    patch_dir: Path | None = None,
): ...
```

调用时：

```python
# 创建 candidate 版本后
candidate_dir = create_agent_version(name="dream_v1_candidate", base="baseline")
apply_skill_proposals(
    proposals,
    target_skill_root=candidate_dir / "skills",       # 只改 candidate
    audit_skill_root=base_version_dir / "skills",     # base version 用于查重/对比
)
```

这样 baseline 的 skills 永远不会被自动修改。

## 7. 版本对战模式

版本对战用于回答：

```text
新策略版本是否比旧策略版本更强？
```

推荐分两个阶段实现。

### 7.1 整队版本对战

整队版本对战是第一阶段优先实现的模式。

含义：

```text
baseline 全员跑同一批 seed
dream_v1 全员跑同一批 seed
比较两个版本在相同局面分布下的表现
```

示例配置：

```json
{
  "battle_id": "battle_20260527_001",
  "mode": "team_vs_seed",
  "versions": ["baseline", "dream_v1"],
  "games_per_version": 20,
  "seed_start": 1000,
  "same_role_assignment": true,
  "metrics": [
    "win_rate",
    "avg_review_score",
    "vote_accuracy",
    "skill_accuracy",
    "fallback_rate",
    "policy_adjusted_rate",
    "bad_case_count"
  ]
}
```

优点：

1. 实现简单。
2. 和现有 selfplay / version_battle 兼容。
3. 适合证明整个 Agent Team 是否进步。

缺点：

1. 不是同场直接对抗。
2. 狼人杀的胜率受阵营分配影响，必须固定 seed 并跑足够多局。

### 7.2 混编阵营对战

混编阵营对战是第二阶段实现的增强模式。

含义：

```text
狼人阵营使用 dream_v1，好人阵营使用 baseline
然后阵营互换：
狼人阵营使用 baseline，好人阵营使用 dream_v1
```

示例：

```text
Round A:
  wolves: dream_v1
  villagers: baseline

Round B:
  wolves: baseline
  villagers: dream_v1
```

优点：

1. 更像真实对抗。
2. 能区分某个版本到底是狼人策略变强，还是好人策略变强。
3. 答辩说服力更强。

缺点：

1. 实现复杂。
2. 需要按阵营和角色注入不同版本配置。
3. 需要更严格的公平性控制。

建议先完成整队版本对战，再实现混编阵营对战。

## 8. 公平性要求

版本对战的核心是公平。否则 leaderboard 没有可信度。

必须保证：

1. 使用同一批 seed。
2. 使用同一套角色配置。
3. 使用同一套座位和身份分配。
4. 使用同一个规则引擎版本。
5. 使用同一个模型配置，除非测试目标就是模型差异。
6. 使用同一套 ToT / GoT 触发策略，除非测试目标就是推理策略差异。
7. 每个版本跑足够多局，建议至少 20 局。
8. 每局输出完整日志、决策归档和 review 报告。

如果做混编对战，还要保证：

1. 新版本当狼人跑 N 局。
2. 新版本当好人跑 N 局。
3. 阵营互换后使用同一批 seed。
4. 座位顺序必须轮换，不能让某个版本固定坐优势位置。
5. 同一 seed 下至少做阵营互换和座位镜像。
6. 指标按阵营、角色、座位、全局四个层次统计。

座位公平性很重要。狼人杀中发言顺序、相邻座位、警上/警下位置都会影响策略效果。如果新版本总是坐某些位置，对战结果会有偏。混编模式应记录每个版本在每个座位上的表现。

## 9. 指标设计

版本对战不能只看胜率。狼人杀有随机性，单纯胜率波动很大。

推荐指标：

| 指标 | 说明 |
|---|---|
| `win_rate` | 阵营胜率，最直观但波动较大。 |
| `avg_review_score` | 复盘综合评分，衡量整体决策质量。 |
| `vote_accuracy` | 投票准确率，衡量好人找狼和狼人带票能力。 |
| `skill_accuracy` | 技能准确率，衡量预言家、女巫、猎人的关键技能质量。 |
| `avg_speech_score` | 发言评分，衡量逻辑性、身份一致性和博弈效果。 |
| `fallback_rate` | LLM 输出失败或兜底次数，越低越稳定。 |
| `policy_adjusted_rate` | 输出非法后被规则修正的比例，越低越好。 |
| `bad_case_count` | 明显失误数量，越低越好。 |
| `avg_survival_days` | 平均存活天数，衡量生存策略稳定性。 |
| `turning_point_quality` | 关键转折点决策质量，需要从 enhanced review 报告中提取。 |
| `tot_usage_rate` | ToT 使用比例，用于分析推理成本和关键决策覆盖率。 |
| `got_usage_rate` | GoT 使用比例，用于确认是否只在高冲突节点稀疏启用。 |
| `got_trigger_count` | GoT 触发次数，MVP 阶段优先记录。 |
| `got_failure_count` | GoT 失败回退次数，MVP 阶段优先记录。 |
| `got_success_rate` | GoT 成功产出合法决策的比例，样本足够后再纳入主指标。 |
| `got_value_delta` | GoT 决策相对普通/ToT 决策的复盘评分差异，增强阶段再做。 |

Leaderboard 综合分可以先使用：

```text
final_score =
  0.30 * win_rate_score
+ 0.25 * review_score
+ 0.15 * vote_accuracy
+ 0.15 * skill_accuracy
+ 0.10 * stability_score
+ 0.05 * bad_case_score
```

其中：

```text
stability_score = 1 - normalized(fallback_rate + policy_adjusted_rate)
bad_case_score = 1 - normalized(bad_case_count)
```

后续可以根据实验效果调整权重。

### 9.1 统计显著性

20 局适合作为 smoke test，但不足以证明版本显著变强。狼人杀方差很大，尤其是 9-12 人局，少量局数下胜率波动明显。

推荐分两级：

```text
MVP 验证：
  每版本 20 局
  目标是发现明显退化、检查流程是否跑通

正式结论：
  每版本 50+ 局
  输出均值、置信区间、显著性判断
```

后续可以加入：

1. Bootstrap 置信区间：估计 win rate / review score 的不确定性。
2. Permutation test：判断两个版本的分数差异是否可能来自随机波动。
3. 分层统计：按角色、阵营、座位分别看提升是否稳定。

晋级规则应优先使用多指标稳定提升，而不是单局胜负或少量胜率差异。

## 10. 自进化闭环

版本管理是自进化 Agent 的验证层。完整闭环如下：

```text
1. baseline 跑 selfplay（版本冻结，关闭 per-game dream / skill proposal / auto apply）
2. 生成 game logs / decision archives
3. review 做多维评测
4. experience cards 提取经验
5. long memory consolidation 生成 run 级 memory_candidate
6. batch-level Dream Agent 基于多局经验反思
7. 生成版本级 skill proposals
8. 创建 candidate version
9. 人工审核或规则审核后应用 proposal 到 candidate
10. 跑 version battle
11. 如果新版本显著提升，promote 为正式版本
12. 如果下降，标记 rejected
```

简化成链路：

```text
Selfplay
  → Review
  → Experience
  → Memory Candidate
  → Batch Dream
  → Skill Proposal
  → AgentVersion
  → Version Battle
  → Promote / Reject
```

版本自进化流程中的 selfplay run 必须保持 AgentVersion 冻结：

```python
SelfPlayConfig(
    enable_dream=False,
    enable_skill_proposals=False,
    auto_apply_skill_proposals=False,
)
```

per-game Dream 可以作为调试功能保留，但不能在版本对战或版本进化的同一轮 selfplay 中修改 skill，否则 N 局不再属于同一个版本，评测结果不可复现。

其中：

| 环节 | 当前项目对应模块 |
|---|---|
| Selfplay | `agent/evaluation/selfplay.py` |
| Review | `agent/evaluation/review.py`, `review_enhanced.py` |
| Experience | `agent/cognition/experience.py` |
| Long Memory | `agent/cognition/long_memory.py` |
| Dream | `agent/cognition/dream.py` |
| Skill Proposal | `agent/cognition/skill_evolution.py` |
| Skill 载体 | `skills/` |
| Version Battle | `agent/evaluation/version_battle.py` |
| Leaderboard | `agent/evaluation/leaderboard.py` |

## 11. 实现阶段规划

### 阶段零：前置依赖

在开始版本管理之前，需要先补齐两个基础设施：

1. **持久化长期记忆存储**。当前 `long_memory.py` 的聚合结果只写到 per-game 目录，没有跨游戏的持久化存储。需要新增两类输出：`runs/<run_id>/memory_candidate/{role}.json` 作为本轮 selfplay 的候选记忆，`data/long_memory/{role}.json` 作为当前 validated 主线记忆。selfplay 后只写 `memory_candidate`；只有 candidate 被 promote/validated 后，才允许同步到 `data/long_memory/`。
2. **Leaderboard 指标扩展**。当前 `LeaderboardEntry` 缺少 `bad_case_count`、`turning_point_quality`、`tot_usage_rate`、`got_trigger_count`、`got_failure_count` 等字段。需要先扩展数据结构和聚合逻辑，Phase 2 的版本对战才能输出完整 leaderboard。
3. **Leaderboard 接入 enhanced review 数据**。当前 `aggregate_summaries()` 只读平铺的 summary dict，`Counterfactual`、`TurningPoint`、`DecisionMistake` 全部丢失。需要在 selfplay 输出中将 enhanced review 的关键数据（mistake_count、counterfactual_count、turning_point_count、各维度 score）写入 summary.json，让 leaderboard 能聚合。
4. **反事实推演覆盖扩展**。当前 `_generate_counterfactuals()` 只覆盖 `MISTAKE_POISONED_GOOD` 和 `MISTAKE_SHOT_GOOD` 两种失误。需要扩展到更多失误类型：投票投错人（好人投好人）、预言家查验优先级错误、狼人刀中队友、守卫连续守同一人等。

验收标准：

1. selfplay 完成后，`runs/<run_id>/memory_candidate/{role}.json` 存在且包含本轮聚合数据。
2. `LeaderboardEntry` 包含文档第 9 节列出的所有指标字段。
3. `aggregate_summaries()` 能正确计算新增指标。
4. summary.json 包含 enhanced review 的关键数据（mistake_count、counterfactual_count、turning_point_count）。
5. 反事实推演至少覆盖 5 种失误类型。

### 阶段一：版本目录与 Manifest

目标：能固化一个 Agent 策略版本。

要做：

1. 新增 `agent/evaluation/agent_version.py` 或 `agent/versioning/manifest.py`。
2. 定义 `AgentVersionManifest`。
3. 实现 `load_agent_version(name)`。
4. 实现 `create_agent_version(...)`。
5. 版本创建时复制 `skills/`、按需复制 `agent/prompts/`、并复制长期记忆快照。
6. 版本创建时记录当前 git commit。
7. 校验 manifest 路径。

验收标准：

1. 能创建 `agent_versions/baseline/`。
2. 能创建 `agent_versions/dream_v1/`。
3. `manifest.json` 完整记录 paths、model、runtime、base_version。
4. `version_battle` 可以读取版本名，而不是手写 `skill_dir`。

### 阶段二：整队版本对战

目标：同一批 seed 比较多个版本。

要做：

1. 扩展 `VersionSpec`，支持 `version_name` 或 `manifest_path`。
2. 加载 manifest 后自动设置 `skill_dir`、model 配置、feature flags。
3. 加载 manifest 后自动设置 ToT / GoT 触发策略。
4. 每个版本使用同一批 seed。
5. 每局保存 game log、decision archive、review report。
6. 输出 `leaderboard.json` 和 `leaderboard.md`。

验收标准：

1. baseline 和 dream_v1 各跑 20 局。
2. 输出可读 leaderboard。
3. Leaderboard 包含胜率、review score、投票准确率、技能准确率、fallback rate。
4. Leaderboard 包含 ToT / GoT 使用率、GoT 触发次数和失败次数。
5. 每个版本结果可追溯到 manifest。
6. Leaderboard 支持 per-role 聚合：能查看某个版本作为 Seer、Werewolf、Witch 等角色的分别表现。

### 阶段三：晋级 / 拒绝机制

目标：新版本必须通过评测才能成为正式版本。

要做：

1. 定义 promotion rule。
2. version battle 后自动比较 candidate 和 base。
3. 满足规则则更新状态为 `validated`。
4. 不满足则更新状态为 `rejected` 并写原因。
5. 输出 `battle_result.json`。
6. 支持 smoke test 和正式评测两种阈值。

验收标准：

1. 提升版本被标记为 `validated`。
2. 下降版本被标记为 `rejected`。
3. rejected 版本保留原因和对战报告。
4. 晋级过程可审计。
5. 即使 candidate 是人工创建，也能走统一 promote / reject 流程。
6. 支持版本回滚：`rollback_version(target)` 将当前 validated 版本降级为 archived，恢复目标版本为 validated。manifest 记录回滚来源和原因。

### 阶段四：自动生成候选版本

目标：Dream / Skill Proposal 能生成新版本。

要做：

1. 从 base version 复制出 candidate version。
2. 默认只把 proposal 写入 candidate 的审核记录，不自动应用。
3. 支持人工审核后应用 proposal。
4. 可选支持 `auto_apply_skill_proposals=false/true`。
5. 把 proposal id 写入 manifest。
6. 把 dream report 路径写入 manifest。
7. candidate 默认状态为 `candidate`。

验收标准：

1. selfplay 后能生成 `dream_v1_candidate`。
2. candidate 有完整 manifest。
3. 修改过的 skill 可以追溯到 proposal。
4. 原 baseline 不被修改。
5. 未通过版本对战前，candidate 不会被标记为 validated。

### 阶段五：混编阵营对战

目标：验证版本在直接对抗中的相对强弱。

要做：

1. 支持按阵营指定版本。
2. 支持按角色指定版本。
3. 支持狼人阵营和好人阵营互换。
4. 支持座位轮换和座位镜像。
5. 指标按阵营、角色、座位、版本聚合。

验收标准：

1. 能跑 `wolves=dream_v1, villagers=baseline`。
2. 能跑 `wolves=baseline, villagers=dream_v1`。
3. 输出阵营维度胜率。
4. 输出座位维度统计。
5. 能看出某版本是狼人更强还是好人更强。

## 12. 和现有代码的衔接

当前项目已经具备部分基础：

1. `SelfPlayConfig.skill_dir` 已支持指定不同 skill 目录。
2. `VersionSpec.skill_dir` 已支持不同版本的 skill 对战。
3. `skills/` 已经是根目录 Markdown 策略资产。
4. `dream.py` 能生成反思报告。
5. `skill_evolution.py` 能生成 proposal 并可选应用到 skill。
6. `leaderboard.py` 已有基本排行榜能力。
7. `got.py` 已提供高冲突关键决策的证据图 / 假设图推理。

需要补齐的是：

1. `agent_versions/` 目录规范。
2. `manifest.json` 数据结构。
3. 版本创建工具。
4. 从 manifest 加载版本配置。
5. 晋级/拒绝流程。
6. candidate 版本生成。
7. 混编阵营对战。
8. Leaderboard 增加 ToT / GoT 使用率和 GoT 价值分析。

### 12.1 VersionSpec 与 manifest.json 的过渡

当前 `VersionSpec` 是轻量数据结构：

```python
@dataclass
class VersionSpec:
    name: str
    skill_dir: Path | None = None
    model_name: str | None = None
    temperature: float | None = None
    notes: str = ""
```

过渡方案：`VersionSpec` 从 `manifest.json` 自动生成。新增 `version_spec_from_manifest(manifest_path)` 函数，读取 manifest 后填充 `VersionSpec` 的所有字段，并附加 runtime flags（tot_enabled、got_enabled 等）。

`run_version_battle()` 的接口改为同时支持两种方式：

```python
# 方式一：传版本名（自动加载 manifest）
await run_version_battle(versions=["baseline", "dream_v1"])

# 方式二：传 VersionSpec（向后兼容）
await run_version_battle(version_specs=[spec1, spec2])
```

内部优先使用版本名 → 加载 manifest → 生成 VersionSpec。

## 13. 风险与取舍

### 13.1 不要把所有内容都复制成版本

Runtime 代码不建议复制到 `agent_versions/`。否则目录会很重，也容易产生代码分叉。Runtime 变化使用 Git commit 记录即可。

### 13.2 不要直接改正式版本

Dream Agent 的修改建议只能应用到 candidate 版本。否则 baseline 被污染，无法复现。

### 13.3 不要只看胜率

狼人杀胜率波动大，少量局数下尤其明显。必须结合 review score、bad case、fallback rate 等指标。

### 13.4 不要让版本对战依赖 working copy

`skills/` 是开发态目录。正式 version battle 应该依赖 `agent_versions/<name>/skills`。

### 13.5 不要让 Agent 自己直接无审计改 skill

Dream Agent 负责提出建议，系统负责应用、记录和验证。自动应用也必须记录 proposal id 和 patch record。

### 13.6 不要全量开启 GoT

GoT 的成本和延迟高于普通 LLM 和 ToT。它应该用于高冲突关键决策，而不是每一次发言或简单行动。版本对战时必须记录 GoT 触发率，否则新版本可能只是因为调用了更多昂贵推理而看起来更强。

### 13.7 不要过早全自动进化

Dream Agent 生成的 proposal 即使置信度高，也可能产生看起来合理但实战有害的修改。MVP 阶段应保留人工审核，或者至少把自动应用限制在 candidate 版本，并强制经过 version battle 验证。

### 13.8 不要用 20 局给出强结论

20 局只能说明系统能跑通和是否有明显退化。正式答辩如果要证明胜率提升，建议提供更多局数，或者至少说明当前结果是 smoke test，并补充 review score、bad case、fallback rate 等更稳定指标。

## 14. 最小可行实现

如果时间有限，优先实现 MVP：

```text
0. memory_candidate + data/long_memory 主线持久化，以及 Leaderboard 指标扩展（前置依赖）
1. agent_versions/<name>/manifest.json
2. create_agent_version
3. VersionSpec 从 manifest 加载 + 支持 version_name
4. 固定 seed 整队版本对战
5. leaderboard 输出多维指标（含 GoT 触发率）
6. manifest 记录 ToT / GoT 开关和触发策略
7. promote / reject 流程支持人工创建的 candidate
```

MVP 不必立刻实现：

1. 混编阵营对战。
2. 自动生成并自动应用 skill proposal。
3. 复杂版本状态机。
4. GoT value delta。
5. Prompt 自动修改。

但 manifest 结构要预留这些字段，避免后面大改。

## 15. 总结

版本管理系统的定位是自进化 Agent 的验证基础设施。

它不直接让 Agent 变强，但它决定了系统能否证明 Agent 变强：

```text
没有版本管理：
  策略改了，但不知道改了什么；
  胜率变了，但不知道是不是随机波动；
  实验跑完了，但无法复现。

有版本管理：
  每次策略变化都有版本；
  每个版本都能追溯来源；
  每次提升都能通过固定 seed 对战验证；
  每次失败都能保留 bad case 和拒绝原因。
```

一句话总结：

```text
版本管理解决“策略从哪里来、改了什么、是否真的变强、能否复现”的问题。
```


## 16. 架构决策记录（Grill Session 2026-05-27）

以下是设计评审中对齐的 10 项架构决策。

### 16.1 Prompt 与 Skill 的边界

决策：策略性内容进 skill，运行时结构留 Python。

具体归属：

| 内容 | 归属 | 原因 |
|---|---|---|
| 角色人设 persona | `skills/<role>/persona.md` | 策略表达，版本化价值高 |
| 通用身份约束 | `skills/common/system_identity.md` | 稳定、可版本化 |
| 推理表达约束 | `skills/common/reasoning_contract.md` | 安全/格式要求 |
| 输出格式 schema | `skills/common/output_schema.md` | 已是 skill |
| 游戏规则 | `skills/common/game_rules.md` | 已是通用 skill |
| action_instruction 短句 | 留 Python | 更像动作合法性约束，不是策略 |
| build_request_prompt 插值 | 留 Python | 运行时数据装配 |
| format_field_notes | 留 Python | 数据转换逻辑 |

Python prompt 层负责：拼运行时状态、memory/belief、candidates、action instruction 硬约束、JSON 输出兜底格式。

Skill 层负责：通用身份边界、表达约束、游戏规则、输出 schema、角色人设、角色策略。

### 16.2 Skill 元数据扩展

在 YAML front-matter 中新增两个字段：

```yaml
category: foundation | strategy    # 用于展示和审计
evolvable: true | false            # 控制 Dream 自动应用权限
```

规则：

| 类型 | evolvable | 自动应用 |
|---|---|---|
| 策略 skill | true | 允许 |
| 基础 skill | false | 不允许，只进审核 |
| 未声明 | 默认 false | 保守 |

基础 skill 包括：`system_identity.md`、`reasoning_contract.md`、`game_rules.md`、`output_schema.md`、各角色 `persona.md`。

策略 skill 包括：`fake_seer.md`、`deep_wolf.md`、`poison.md`、`check_priority.md` 等局部策略文件。

`apply_skill_proposals()` 检查目标 skill 的 `evolvable` 字段，`false` 的 proposal 写入审核队列，不自动应用。

### 16.3 applicable_actions 语义

决策：`applicable_actions` 为空 = 该角色始终注入。

```yaml
# persona.md - 始终注入
name: werewolf_persona
scope: role
role: werewolf
# 无 applicable_actions

# fake_seer.md - 仅匹配 action 注入
name: werewolf_fake_seer
scope: role
role: werewolf
applicable_actions:
  - sheriff_run
  - sheriff_speak
  - speak
```

loader 改动：解析 front-matter 时，如果无 `applicable_actions`，设为空列表。`select_skills()` 中，空列表匹配所有 action。

### 16.4 Skill 隔离机制

决策：per-runtime skill_dir + per-root skill cache。

```python
_SKILL_CACHE: dict[Path, SkillIndex] = {}

@dataclass
class SkillIndex:
    common: list[MarkdownSkill]
    by_role: dict[Role, list[MarkdownSkill]]

def _get_skill_index(skill_root: Path | None = None) -> SkillIndex:
    root = (skill_root or DEFAULT_SKILL_ROOT).resolve()
    if root not in _SKILL_CACHE:
        _SKILL_CACHE[root] = _load_skill_index(root)
    return _SKILL_CACHE[root]
```

`AgentRuntime.__init__` 接收 `skill_dir`，`skill_router_node(ctx, skill_dir=self.skill_dir)` 传入 root。

`configure_skill_root()` 保留作为默认配置和测试辅助，不作为版本对战隔离机制。

适用范围：

| 阶段 | 方案 |
|---|---|
| 整队版本对战 | per-runtime skill_dir（同一进程顺序跑） |
| 混编阵营对战 | per-agent skill_dir（同一局内不同 Agent 不同版本） |

### 16.5 版本加载职责分离

决策：`run_selfplay()` 不感知 manifest，版本加载由 `version_battle.py` 负责。

```text
version_name
  -> load_agent_version_manifest()
  -> VersionSpec
  -> SelfPlayConfig
  -> create_agents(skill_dir=...)
  -> AgentRuntime(skill_dir=...)
  -> skill_router_node(ctx, skill_dir=...)
```

模块职责：

| 模块 | 职责 |
|---|---|
| `agent/versioning/manifest.py` | 读取、校验、保存 AgentVersionManifest |
| `agent/evaluation/version_battle.py` | 从 manifest 构建 VersionSpec 和 SelfPlayConfig |
| `agent/evaluation/selfplay.py` | 只执行 selfplay，不理解 manifest |
| `agent/runtime/agent.py` | 根据 skill_dir 创建 runtime |
| `agent/skill_system/router.py` | 根据 skill_root 加载对应 skills |

manifest 中的路径相对于 manifest 文件自身解析：

```python
def resolve_manifest_path(manifest_path: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return manifest_path.parent / path
```

### 16.6 Dream 分层

决策：per-game Dream 保留但默认关闭；版本自进化主链路使用 batch-level Dream。

| 类型 | 保留 | 默认 | 作用 |
|---|---|---|---|
| per-game Dream | 保留 | 关闭 | 调试单局、观察反思质量 |
| batch-level Dream | 必须 | 开启于进化流程 | 聚合多局经验，生成版本级 proposal |

版本管理流程中 selfplay 必须关闭 per-game Dream：

```python
SelfPlayConfig(
    enable_dream=False,
    enable_skill_proposals=False,
    auto_apply_skill_proposals=False,
)
```

### 16.7 版本冻结约束

决策：一个 selfplay run 内，AgentVersion 必须冻结。

Dream 和 proposal 只能写后处理产物，不能影响本轮后续对局。否则 N 局不再是同一个版本，评测结果不可复现。

### 16.8 Long Memory 三层模型

| 层级 | 路径 | 含义 | 可写 |
|---|---|---|---|
| 工作区 | `data/long_memory/` | 当前 validated 主线记忆 | 仅 validated 版本可更新 |
| 版本 | `agent_versions/<name>/memory/` | 版本只读快照 | 创建后不可修改 |
| 候选 | `runs/<run_id>/memory_candidate/` | 本次 selfplay 后的候选记忆 | 可写 |

MVP 流程：

1. 从 base_version.memory 复制 run_base_memory
2. selfplay N 局，版本冻结
3. 生成 new experience cards
4. 根据本轮 cards 生成 memory_candidate
5. batch-level Dream 使用 memory_candidate
6. create candidate version 时复制 memory_candidate
7. candidate validated 后可选择同步到 data/long_memory/
8. candidate rejected：保留 memory，不污染 data/long_memory/

增强方向：base memory + new cards 增量合并、加权衰减、去重、置信度更新。

### 16.9 Promote/Reject 自动化

决策：`version_battle.py` 自动判断 promote/reject，不需要人工确认。

```python
@dataclass
class PromotionVerdict:
    promoted: bool
    reasons: list[str]
    metrics: dict[str, float]
```

晋级规则：

- review score 提升 >= 5%
- bad case count 不增加
- fallback rate 不增加
- policy_adjusted_rate 不增加
- 胜率下降 < 10 个百分点；正式评测改用 permutation test，要求 candidate 相比 base 没有显著退化

manifest 更新为 `validated` 或 `rejected`，记录 verdict 详情。

### 16.10 模块职责总览

| 模块 | 职责 |
|---|---|
| `agent/versioning/manifest.py` | 读取、校验、保存 AgentVersionManifest |
| `agent/evaluation/version_battle.py` | 从 manifest 构建配置、跑对战、判断 promote/reject |
| `agent/evaluation/selfplay.py` | 执行 selfplay，归档、复盘、经验卡 |
| `agent/evaluation/leaderboard.py` | 聚合指标、排序、输出 |
| `agent/cognition/dream.py` | 单角色反思能力 |
| `agent/cognition/skill_evolution.py` | proposal 生成/审核/应用 |
| `agent/cognition/long_memory.py` | 长期记忆聚合 |
| `agent/runtime/agent.py` | 根据 skill_dir 创建 runtime |
| `agent/skill_system/router.py` | 根据 skill_root 加载 skills |

新增模块：

| 模块 | 职责 |
|---|---|
| `agent/versioning/version_evolution.py` | 批量 Dream + 创建 candidate version |

# Langfuse 接入执行文档

状态：执行计划版
日期：2026-06-10
范围：`app/services/observability.py`、`app/services/chain.py`、`app/graphs/*`、`app/lib/score.py`、benchmark/evolution 存储与测试

## 1. 结论

当前系统已经具备 Langfuse 接入基础，不需要重做观测架构。

推荐路线：**PostgreSQL 继续作为权威数据源，Langfuse 作为 LLM 调用观测、评测可视化、人工标注和数据集实验面板**。

第一阶段不要全局接 LangChain callback，也不要把 Langfuse 逻辑散落到每个业务节点。现有仓库已经把 LLM 调用集中在 `app/services/chain.py`，因此最稳妥的接法是：

- `app/services/observability.py` 继续作为唯一 Langfuse SDK 适配层。
- `app/services/chain.py` 继续作为 generation observation 入口。
- game/eval/evolve/review 只负责传业务 metadata 和写 score。
- 所有 Langfuse 调用保持 fail-open，不能影响游戏、评测、进化、持久化主流程。

## 2. 目标

本次接入要解决四类问题：

- 追踪每次 LLM 决策、judge、consolidate、apply 的输入摘要、输出摘要、模型、耗时、重试和异常。
- 把游戏、评测、进化产生的关键指标写入 Langfuse Scores，便于按模型、角色、版本、seed set、评测集筛选。
- 把固定 benchmark/seed set 同步成 Langfuse Datasets，用于后续离线实验和回归对比。
- 为 Prompt Management 留出 adapter，先让非核心 prompt 可由 Langfuse 管理，失败时回退本地 prompt。

## 3. 非目标

本计划不做以下事项：

- 不把 Langfuse 变成评分权威源；评分仍以 PostgreSQL 和 `app.lib.score` 为准。
- 不让 Langfuse 服务可用性影响主流程。
- 不默认上传完整 prompt、私密推理、原始输出。
- 不在第一阶段迁移所有 prompt 到 Langfuse Prompt Management。
- 不把 12 个 AI 玩家映射为真实 Langfuse user；`player_id`、`role` 放 metadata 即可。
- 不替代现有 UI 的历史、评测、进化页面。

## 4. 当前基础

已存在内容：

- 依赖：`pyproject.toml` 已包含 `langfuse>=4.6.1`。
- 环境变量：`.env.example` 和 `README.md` 已包含 `LANGFUSE_*` 配置，默认关闭。
- SDK 适配：`app/services/observability.py` 已有 `langfuse_enabled()`、`get_langfuse_client()`、`langfuse_context()`、`observe_llm_call()`、`score_current_trace()`、`flush_langfuse()`。
- LLM 调用边界：`app/services/chain.py` 是 app 层唯一 LLM 调用文件。
- 业务 trace/score 契约测试：
  - `tests/test_langfuse_observability.py`
  - `tests/test_langfuse_review_observability.py`
  - `tests/test_langfuse_eval_observability.py`
  - `tests/test_langfuse_evolve_observability.py`

关键业务入口：

| 入口 | 文件 | 用途 |
|---|---|---|
| LLM SDK 创建 | `app/services/llm.py` | 创建 ChatOpenAI 客户端、重试、熔断、超时 |
| LLM 调用观测 | `app/services/chain.py` | generation observation、stage/model/metadata |
| Langfuse SDK 适配 | `app/services/observability.py` | trace/context/score/flush |
| 单局 trace | `app/graphs/subgraphs/game/nodes.py` | `game_loop_node` 建 game trace |
| 决策 metadata | `app/graphs/subgraphs/agent/nodes.py` | `_decision_langfuse_metadata` |
| eval trace/score | `app/graphs/subgraphs/eval/nodes.py` | eval batch context 和 score |
| evolve trace/score | `app/graphs/subgraphs/evolve/nodes.py` | evolution run context 和 score |
| review judge score | `app/graphs/shared/nodes/review.py` | decision judge score |

## 5. 目标架构

### 5.1 数据边界

PostgreSQL 是权威数据源：

- `wolf.games`
- `wolf.decisions`
- `wolf.game_events`
- `wolf.evaluations`
- `wolf.llm_judgments`
- `wolf.evaluation_batches`
- `wolf.benchmark_leaderboard`
- `evolution.evolution_runs`
- `evolution.experience_candidates`
- `registry.role_versions`

Langfuse 是观测和实验视图：

- Traces：单局游戏、单次 eval batch、单次 evolve run。
- Observations：LLM generation、业务 chain/span。
- Scores：胜负、评分、judge、质量指标、进化门禁。
- Datasets：benchmark spec、seed set、精选经验样本。
- Human Annotation：异常局、低分决策、进化候选样本。
- Prompt Management：非核心 prompt 先试点。

### 5.2 ID 映射

| Langfuse 对象 | 推荐 ID/字段 | 来源 |
|---|---|---|
| game trace id | `create_trace_id(seed=game_id)` | `game_id` |
| game session id | `source_run_id`，没有则 `game_id` | eval/evolve/play 状态 |
| eval trace id | `create_trace_id(seed=batch_id)` | `batch_id` |
| eval session id | `batch_id` | `evaluation_batches` |
| evolve trace id | `create_trace_id(seed=f"evolve:{run_id}")` | `run_id` |
| evolve session id | `run_id` | `evolution_runs` |
| observation name | `llm.{stage}` | `decision/compress/consolidate/apply/evidence/decision_judge` |
| dataset name | `evaluation_set_id` | benchmark spec |
| dataset item id | `{evaluation_set_id}:{seed_set_id}:{seed}` | benchmark seed |

### 5.3 Metadata 标准

所有 trace metadata 尽量使用稳定、低基数、可筛选字段：

```json
{
  "run_type": "ordinary_game | evaluation_batch | evolution_training | evolution_ab_candidate",
  "mode": "dev | formal",
  "game_id": "string",
  "source_run_id": "string",
  "seed": 123,
  "model_id": "string",
  "model_config_hash": "string",
  "target_role": "seer",
  "target_version_id": "string",
  "evaluation_set_id": "role-baseline-v1@v1",
  "seed_set_id": "fixed-seeds-v1",
  "comparison_group_id": "string",
  "comparison_type": "model | role_version"
}
```

单次 LLM generation metadata：

```json
{
  "stage": "decision",
  "model": "string",
  "game_id": "string",
  "source_run_id": "string",
  "player_id": 7,
  "role": "seer",
  "action_type": "seer_check",
  "phase": "night",
  "day": 2,
  "candidate_count": 3,
  "retry_count": 0,
  "selected_skills": ["skill-name"],
  "skill_count": 1,
  "expected_schema_version": "1.0",
  "observed_schema_version": "1.0",
  "elapsed_ms": 1240,
  "attempts": 1
}
```

### 5.4 Score 命名

保留现有命名族，不混用中文名：

| Metric family | Score names |
|---|---|
| game | `winner`、`finished`、`terminal_status` |
| decision quality | `decision_quality.decision_count`、`decision_quality.fallback_rate`、`decision_quality.llm_error_rate`、`decision_quality.policy_adjusted_rate`、`decision_quality.invalid_response_rate`、`decision_quality.default_action_rate` |
| review judge | `review.decision_judge_average_score`、`review.decision_judge_judged`、`review.decision_judge_failed`、`review.decision_judge_status`、`review.decision_judge_bad_count`、`review.decision_judge_good_count` |
| eval | `eval.avg_role_score`、`eval.strength_score`、`eval.valid_game_rate`、`eval.fallback_rate`、`eval.llm_error_rate`、`eval.policy_adjusted_rate`、`eval.villagers_win_rate`、`eval.werewolves_win_rate`、`eval.rankable` |
| evolve | `evolve.recommendation`、`evolve.status`、`evolve.candidate_win_rate`、`evolve.baseline_win_rate`、`evolve.win_rate_delta`、`evolve.significant`、`evolve.promote_allowed`、`evolve.proposal_min_quality` |
| player | `player.role_score`、`player.speech_score`、`player.vote_score`、`player.skill_score`、`player.logic_score`、`player.team_score`、`player.risk_penalty` |

## 6. 分阶段执行

## Phase 0：基线确认

目标：确认现有接入稳定、测试覆盖可作为后续保护网。

任务：

- 运行 Langfuse 相关单测。
- 确认真实 `.env` 不会在测试中触发网络请求。
- 确认 `LANGFUSE_TRACING_ENABLED=false` 时所有 helper 都是 no-op。
- 确认 `LANGFUSE_CAPTURE_INPUT_OUTPUT=false` 是默认推荐值。

建议命令：

```powershell
uv run pytest tests/test_langfuse_observability.py tests/test_langfuse_review_observability.py tests/test_langfuse_eval_observability.py tests/test_langfuse_evolve_observability.py
```

验收：

- 测试通过。
- 不需要真实 Langfuse 服务。
- 不打印或提交 `.env` 中的密钥。

## Phase 1：补强 SDK 适配层

目标：让 `observability.py` 成为稳定、完整、可测试的 Langfuse facade。

文件范围：

- `app/services/observability.py`
- `tests/test_langfuse_observability.py`
- `.env.example`
- `README.md`

任务：

- 新增 `score_trace(trace_id, name, value, ...)` 或等价 helper，用于在非 current trace 上写 score。
- 新增 `get_current_trace_id()`、`get_trace_url(trace_id)` helper，便于 UI 或日志关联。
- 新增 SDK masking 配置，复用 `app.util.redaction.redact`。
- 保持 `LANGFUSE_CAPTURE_INPUT_OUTPUT=false` 作为推荐值。
- 记录 `environment`、`release`、`sample_rate` 的初始化参数测试。
- 所有 helper 捕获异常并降级为 no-op。

验收：

- tracing 关闭时不 import/construct Langfuse SDK。
- tracing 开启但初始化失败时业务代码不中断。
- `score_trace` 能被 fake client 捕获参数。
- README 明确自部署、密钥、采样、输入输出捕获策略。

## Phase 2：修正 trace 归属和 usage

目标：让所有 LLM generation 和 review score 进入正确 trace，并补齐 token/usage。

文件范围：

- `app/services/chain.py`
- `app/graphs/subgraphs/game/nodes.py`
- `app/graphs/shared/nodes/review.py`
- `tests/test_langfuse_observability.py`
- `tests/test_langfuse_review_observability.py`

任务：

- 从 LLM 返回对象中提取 token usage：
  - `usage_metadata`
  - `response_metadata.token_usage`
  - `llm_output.token_usage`
- 将 usage 写入 observation metadata，条件允许时写入 Langfuse generation usage 字段。
- 在 `game_loop_node` 关闭 trace 后，review 阶段仍能把 judge score 写回同一 `langfuse_trace_id`。
- play graph 需要保留并向 review 传递 `langfuse_trace_id`。
- 对 LLM 异常 observation 设置 `level=ERROR` 和 redacted status message。

验收：

- 单局游戏 trace 下能看到 `llm.decision`、`llm.decision_judge`。
- review judge score 写在对应 game trace，而不是丢在空 current trace。
- fake tests 覆盖 usage metadata 和异常 observation。

## Phase 3：完善业务 Scores

目标：让 Langfuse 的 Scores 面板可以回答“哪个模型/角色/版本/评测集表现更好”。

文件范围：

- `app/graphs/subgraphs/game/nodes.py`
- `app/graphs/subgraphs/eval/nodes.py`
- `app/graphs/shared/nodes/review.py`
- `app/lib/score.py`
- `tests/test_langfuse_eval_observability.py`
- `tests/test_langfuse_review_observability.py`

任务：

- 给 game trace 写 player-level scores：
  - `player.role_score`
  - `player.speech_score`
  - `player.vote_score`
  - `player.skill_score`
  - `player.logic_score`
  - `player.team_score`
  - `player.risk_penalty`
- score metadata 包含 `game_id`、`player_id`、`role`、`winner`、`source_run_id`。
- eval batch trace 继续写聚合 score，并补充：
  - `eval.data_sufficient`
  - `eval.low_error_rate`
  - `eval.leaderboard_accepted`
  - `eval.rankable_reason` 作为 categorical 或 metadata。
- review judge score 关联 `llm_judgment_ids`，metadata 包含 `judgment_count`。

验收：

- eval trace 可按 `target_role`、`target_version_id`、`evaluation_set_id` 过滤。
- score 写入失败不影响评测持久化。
- 与 PostgreSQL 中 `evaluation_batches`、`benchmark_leaderboard` 的结果一致。

## Phase 4：同步 Benchmark Datasets

目标：把固定 benchmark 和 seed set 同步成 Langfuse Datasets，为离线实验做准备。

文件范围：

- 新增 `app/tools/sync_langfuse_datasets.py`
- `app/lib/benchmark_spec.py`
- `tests/test_langfuse_dataset_sync.py`
- `README.md`

任务：

- 读取内置 benchmark：
  - `app/resources/benchmarks/*.json`
  - `app/resources/benchmark_seed_sets/*.json`
- Langfuse dataset name 使用 `evaluation_set_id`。
- dataset item input 包含：
  - `seed`
  - `max_days`
  - `target_role`
  - `role_version_config`
  - `model_runtime`
  - `ruleset_version`
- expected output 只放稳定目标：
  - `rankable` 规则
  - `primary_metric`
  - `expected_direction`
  - baseline subject 信息
- 工具默认 dry-run，需要 `--apply` 才写入 Langfuse。
- 已存在 item 时幂等跳过或更新 metadata，不制造重复 item。

建议命令：

```powershell
uv run python -m app.tools.sync_langfuse_datasets --dry-run
uv run python -m app.tools.sync_langfuse_datasets --apply
```

验收：

- dry-run 不触网或不写入。
- apply 模式能创建/更新 dataset 和 items。
- 无 Langfuse 配置时清晰提示并退出 0 或可预期错误码。
- 同步结果可由 `evaluation_set_id` 和 `seed_set_id` 精确定位。

## Phase 5：实验回归

目标：让固定 benchmark 运行结果可以在 Langfuse Experiments 中横向比较。

文件范围：

- 新增或扩展 benchmark runner 工具
- `app/run.py`
- `app/graphs/subgraphs/eval/nodes.py`
- `tests/test_langfuse_eval_observability.py`

任务：

- 运行 eval batch 时可选传入 `langfuse_dataset_name` 和 `experiment_name`。
- 每个 dataset item 对应一局或一组 paired seed。
- 实验分数仍从 `app.lib.score` 聚合而来。
- PostgreSQL leaderboard 仍为最终发布依据。

验收：

- 同一 benchmark 可比较不同 `model_config_hash` 或 `target_version_id`。
- Langfuse experiment 和 PostgreSQL batch 通过 `batch_id` 互相跳转。
- Langfuse 不可用时 benchmark 仍能完整运行并入库。

### Phase 5A：当前下一阶段执行包

目标：把已经同步到 Langfuse 的 Dataset 真正接入当前 benchmark/eval 运行链路，让每次评测既保留 PostgreSQL 权威结果，也能在 Langfuse Experiments 中复盘和横向比较。

本阶段优先解决三件事：

- eval/benchmark 启动时可选绑定 `langfuse_dataset_name`、`langfuse_experiment_name`、`langfuse_run_name`。
- 每个 seed 或 paired seed 在 Langfuse 中能关联到对应 dataset item、game trace、eval batch trace 和 score。
- 后端结果中返回 `langfuse_trace_id`、`langfuse_trace_url`、`langfuse_experiment_url` 或等价 deep link，方便从本地 UI 跳到 Langfuse 排查。

推荐数据流：

```text
benchmark spec / seed set
  -> sync_langfuse_datasets
  -> Langfuse Dataset
  -> run_evaluation(langfuse_dataset_name, experiment_name)
  -> game traces + eval batch trace + Langfuse scores
  -> PostgreSQL leaderboard remains authoritative
```

建议接口扩展：

```python
run_evaluation(
    ...,
    langfuse_dataset_name: str | None = None,
    langfuse_experiment_name: str | None = None,
    langfuse_run_name: str | None = None,
)
```

或者在已有 benchmark launcher/config 中增加同名可选字段，避免破坏现有调用方。

任务拆分：

| Worker | 范围 | 文件 |
|---|---|---|
| A：Eval 参数透传 | 给 eval/benchmark 入口增加 Langfuse dataset/experiment 可选参数 | `app/run.py`、eval/benchmark launcher |
| B：Dataset item 关联 | 按 `evaluation_set_id:seed_set_id:seed` 找 dataset item，写入 trace metadata | `app/graphs/subgraphs/eval/nodes.py`、`app/graphs/subgraphs/game/nodes.py` |
| C：Experiment score | 把 eval 聚合分数和 game/player score 关联到 dataset run | `app/services/observability.py`、`app/graphs/subgraphs/eval/nodes.py` |
| D：链接返回/UI 准备 | 后端输出 Langfuse trace/experiment URL，不强依赖前端改造 | API schema、eval result serializer |

实现原则：

- 不改变现有 benchmark 排名口径；`app.lib.score` 和 PostgreSQL leaderboard 仍是发布依据。
- Langfuse dataset/experiment 参数为空时，当前 eval 行为完全不变。
- Langfuse 不可用、dataset 不存在、item 缺失时只记录 warning/no-op，不阻塞评测。
- dataset item id 必须沿用 `{evaluation_set_id}:{seed_set_id}:{seed}`，避免后续数据重复。
- 单局 game trace metadata 至少补充 `langfuse_dataset_name`、`langfuse_dataset_item_id`、`experiment_name`、`batch_id`。
- eval batch trace metadata 至少补充 `evaluation_set_id`、`seed_set_id`、`target_role`、`target_version_id`、`model_config_hash`。

验收：

- 不传 Langfuse 参数时，现有 eval/benchmark 测试全部通过。
- 传入 dataset/experiment 参数时，fake Langfuse 能捕获 dataset item 关联、trace id、score 和 URL。
- 同一 benchmark 可在 Langfuse 中比较不同 `model_config_hash` 或 `target_version_id`。
- 任一 Langfuse 写入失败不影响 game/eval 持久化。
- PostgreSQL 中的 `evaluation_batches`、`benchmark_leaderboard` 与 Langfuse score 来源一致。

### Phase 5B：真实联调验收包

目标：把 Phase 5A 的代码链路变成可重复执行的验收流程，确认真实或本地 Langfuse 环境中 Dataset、Experiment、Trace、Score、URL 能闭环，同时保留离线 dry-run 能力。

本阶段优先解决四件事：

- 提供一个不打印密钥、不默认触网的验收工具，汇总 Langfuse 配置状态、dataset sync plan、benchmark result linkage 和缺口。
- 用真实 Langfuse 环境时，可以按步骤执行 dataset sync、启动 benchmark、检查 dataset run item、trace URL、experiment URL 和 score。
- 将验收报告输出为稳定 JSON，便于 CI 或人工记录，不把 Langfuse 作为权威数据源。
- 明确失败分级：配置缺失、dataset item 缺失、trace 未绑定、score 未写入都只作为验收失败或 warning，不影响 benchmark 主流程。

建议命令：

```powershell
uv run python -m app.tools.sync_langfuse_datasets --dry-run
uv run python -m app.tools.verify_langfuse_experiments --dry-run
uv run python -m app.tools.sync_langfuse_datasets --apply
uv run python -m app.tools.verify_langfuse_experiments --from-report runs/evaluation_batches/<batch_id>/report.json
```

验收清单：

- `.env` 中 `LANGFUSE_TRACING_ENABLED=true`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL` 齐全；验收输出只能显示布尔状态，不能打印密钥。
- `sync_langfuse_datasets --dry-run` 中每个 item id 都等于 `{evaluation_set_id}:{seed_set_id}:{seed}`。
- benchmark batch detail/report 中至少能看到：
  - `langfuse.dataset_names`
  - `langfuse.experiment_names`
  - `langfuse.run_names`
  - `trace_count`
  - `dataset_run_count`
  - `dataset_run_item_count`
  - `trace_urls` / `experiment_urls`
- 每个有 `langfuse_dataset_item_id` 的 game record 都能反查到本地 `game_id`、`batch_id`、`result_batch_id`、`seed`。
- Langfuse 不可用、dataset item 缺失、SDK 内部 API 变化时，验收工具返回清晰 warning/error，业务运行不抛异常。

文件范围：

- `app/tools/verify_langfuse_experiments.py`
- `tests/test_langfuse_experiment_verification.py`
- 必要时补充 README 的运行手册，但不修改核心业务路径。

Definition of Done：

- dry-run 测试不访问网络。
- fake payload 能验证 dataset item id、trace/run/item URL、score linkage 的缺口。
- 真实环境步骤可以人工执行并产出 JSON 验收报告。
- 验收报告可以直接附到 benchmark release 或回归记录中。

## Phase 6：Prompt Management 试点

目标：先把低风险 prompt 接到 Langfuse Prompt Management，验证版本治理。

文件范围：

- 新增 `app/services/prompt_registry.py`
- `app/services/prompt.py`
- `app/lib/decision_judge.py`
- `app/lib/evolve.py`
- `tests/test_prompt_registry.py`

试点顺序：

1. `decision_judge`
2. `evidence`
3. `consolidate`
4. `apply`
5. 最后才考虑核心 `decision`

任务：

- 提供 `get_prompt(name, label="production", fallback=local_prompt)`。
- Langfuse 不可用、prompt 不存在、compile 失败时使用本地 prompt。
- 返回 prompt resolution metadata：
  - `prompt_name`
  - `prompt_label`
  - `prompt_version`
  - `prompt_source`
  - `prompt_fallback_used`
- prompt metadata 写入 generation：
  - `prompt_name`
  - `prompt_version`
  - `prompt_label`
- 本地 schema 校验仍保留，不能因为 prompt 外置而绕过。

执行顺序：

1. 新增 `app/services/prompt_registry.py`，只作为 Langfuse Prompt Management facade，不让业务代码直接碰 Langfuse SDK。
2. `get_prompt()` 默认返回本地 fallback；只有 tracing 配置完整且 Langfuse prompt 可用时才返回远端 prompt。
3. 先把 `decision_judge`、`evidence` 的 chain metadata 接上 prompt resolution metadata；不改变 messages 内容时，功能行为必须完全一致。
4. 若需要远端 prompt 改写 messages，先只允许显式开关，例如 `LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true`；默认仍只记录 metadata。
5. 核心 `decision` prompt 继续保持本地，不进入本阶段。

Prompt fallback 规则：

- Langfuse disabled：使用 fallback，`prompt_source=local`，`prompt_fallback_used=true`。
- client 初始化失败：使用 fallback，记录 `prompt_error_type`。
- prompt 不存在或 label 不存在：使用 fallback，记录 `prompt_error_type=not_found` 或等价诊断。
- compile 失败：使用 fallback，不能污染业务 messages。
- 返回 prompt metadata 时，只进 observation metadata，不把完整 prompt 文本写入 Langfuse metadata。

验收：

- 没有 Langfuse 配置时所有 prompt 行为与当前一致。
- Langfuse prompt 版本可在 observation 中追踪。
- prompt 输出 schema 不合法时仍走当前错误处理和降级逻辑。
- `decision_judge`、`evidence` 两条低风险链路有 fake registry 测试覆盖。
- `LANGFUSE_CAPTURE_INPUT_OUTPUT=false` 时仍不上传完整 prompt/input/output。

## Phase 7：人工标注闭环

目标：把最值得人看的一小部分样本送入 Langfuse Human Annotation。

候选样本：

- LLM error 或 fallback 率高的局。
- decision judge 低分决策。
- policy adjustment 频繁的 action type。
- evolution 中 promotion gate 边界样本。
- benchmark 中 candidate/baseline 差异最大的 paired seeds。

任务：

- 定义 annotation queue 的导出工具。
- metadata 包含 PostgreSQL 主键和 UI deep link。
- 人工标注只作为训练和复盘输入，不直接覆盖正式 leaderboard。
- 先导出本地 JSON queue，不直接写 Langfuse annotation API。
- 每个 queue item 包含：
  - `annotation_id`
  - `source`
  - `priority`
  - `reason`
  - `game_id`
  - `batch_id`
  - `result_batch_id`
  - `seed`
  - `langfuse_trace_id`
  - `langfuse_trace_url`
  - `langfuse_experiment_url`
  - `local_url`
  - `metadata`
- 候选筛选要去重，同一 trace/game/decision 只进入一次高优先队列。
- 不导出完整 private reasoning、完整 prompt、完整原始输出；只导出短摘要和可回查 ID。

优先级规则：

| 优先级 | 样本 |
|---|---|
| P0 | benchmark problem game、LLM error、game failed、decision judge 极低分 |
| P1 | fallback/policy adjustment 高、leaderboard gate 边界失败 |
| P2 | candidate/baseline 差异大的 paired seed、evolution promotion gate 边界 |

文件范围：

- `app/tools/export_langfuse_annotation_queue.py`
- `tests/test_langfuse_annotation_export.py`

验收：

- 可以从 Langfuse trace 找回本地 game/review/evolution 详情。
- 标注结果有明确回流位置，例如 `llm_judgments`、`decision_reviews` 或后续 experience candidates。
- annotation queue dry-run 不触网。
- 导出的 queue item 不包含敏感长文本字段。
- 输出可作为后续 Human Annotation API 写入工具的输入。

## 7. 并行拆分建议

可以分 4 个 agent/分支并行推进，写范围保持隔离：

| Worker | 范围 | 文件 |
|---|---|---|
| A：SDK 适配 | observability facade、env、README、基础测试 | `app/services/observability.py`、`tests/test_langfuse_observability.py`、`.env.example`、`README.md` |
| B：Trace/Usage | LLM generation usage、review trace 归属 | `app/services/chain.py`、`app/graphs/subgraphs/game/nodes.py`、`app/graphs/shared/nodes/review.py` |
| C：Scores | player/eval/evolve score 完整性 | `app/graphs/subgraphs/eval/nodes.py`、`app/graphs/subgraphs/evolve/nodes.py`、`app/lib/score.py` |
| D：Datasets/Prompts | dataset sync 工具、prompt registry 试点 | `app/tools/*`、`app/services/prompt_registry.py`、`app/lib/benchmark_spec.py` |

集成顺序：

1. 先合 A。
2. 再合 B。
3. C 可在 A 后并行合。
4. D 等 A 稳定后合。

## 8. 配置策略

推荐 `.env`：

```dotenv
LANGFUSE_TRACING_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=http://127.0.0.1:3000
LANGFUSE_ENVIRONMENT=local
LANGFUSE_RELEASE=
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_INPUT_OUTPUT=false
```

生产建议：

- `LANGFUSE_TRACING_ENABLED=true`
- `LANGFUSE_CAPTURE_INPUT_OUTPUT=false`
- `LANGFUSE_SAMPLE_RATE=0.1` 起步，排查时临时提高。
- 只有在确认脱敏有效后，才允许对 dev 环境开启 raw input/output。
- `LANGFUSE_RELEASE` 使用 git sha 或部署版本。
- `LANGFUSE_ENVIRONMENT` 使用 `local/dev/staging/prod`。

## 9. 隐私和安全

必须遵守：

- 不上传 `.env`、API key、数据库连接串。
- 默认不上传完整 prompt 和 raw output。
- private reasoning、完整事件日志、玩家私密视角需要 redaction。
- metadata 保留结构化摘要，不放长文本。
- Langfuse 写入失败只能记录 debug/warning，不能抛到业务层。

建议脱敏点：

- `observe_llm_call(input=...)`
- `update_observation(output=...)`
- `metadata["message_summary"]`
- prompt management compile 后的变量输入
- dataset item 中的 game archive 摘要

## 10. 测试矩阵

最低测试集：

```powershell
uv run pytest tests/test_langfuse_observability.py
uv run pytest tests/test_langfuse_review_observability.py
uv run pytest tests/test_langfuse_eval_observability.py
uv run pytest tests/test_langfuse_evolve_observability.py
```

涉及业务后补充：

```powershell
uv run pytest tests/test_eval_pipeline.py
uv run pytest tests/test_evolve_consolidate_apply.py
uv run pytest tests/test_storage_runtime_replay.py
uv run pytest tests/test_api_contracts.py
```

验收规则：

- 所有 Langfuse 测试必须使用 fake SDK/fake observability，不访问真实网络。
- tracing disabled、missing keys、SDK init failed 三种情况都必须覆盖。
- 所有 score 写入必须有失败不影响业务的测试。
- dataset sync 工具必须有 dry-run 测试。

## 11. 风险和控制

| 风险 | 控制 |
|---|---|
| Langfuse 服务不可用影响游戏 | 所有调用 fail-open；测试覆盖异常路径 |
| 上传敏感 prompt/私密推理 | 默认 `LANGFUSE_CAPTURE_INPUT_OUTPUT=false`；接入 SDK mask |
| trace 过多、成本过高 | 采样；prod 先 10%；只同步精选 dataset |
| score 和 PostgreSQL 不一致 | PostgreSQL 为权威；Langfuse score 只从同一聚合结果派生 |
| Prompt Management 改坏核心决策 | 先接 judge/evidence；所有 prompt 有本地 fallback |
| 多 agent 并行冲突 | 按文件范围拆分；先合 observability facade |

## 12. Definition of Done

第一轮接入完成标准：

- `LANGFUSE_TRACING_ENABLED=false` 时系统行为与当前完全一致。
- tracing 开启时，单局游戏能看到 game trace 和 `llm.decision` generation。
- eval batch 能看到 `eval.batch` trace 和核心 eval scores。
- evolve run 能看到 `evolve.run` trace 和 promotion/gate scores。
- review judge score 能写回对应 game trace。
- Langfuse 不可用时游戏、评测、进化、review 均不失败。
- 文档、env 示例、测试全部更新。

第二轮完成标准：

- benchmark spec/seed set 可同步到 Langfuse Dataset。
- eval batch 可选关联 dataset/experiment。
- Prompt Management 至少完成 `decision_judge` 试点并保留 fallback。

## 13. 推荐下一步

Phase 5A 已完成后，下一轮按下面顺序推进：

1. **Phase 5B：真实联调验收包**
   - 新增 `verify_langfuse_experiments` dry-run 验收工具。
   - 用 fake payload 锁定 dataset item、trace、dataset run、experiment URL 的验收 contract。
   - 在本地 Langfuse 环境手动执行 dataset sync + benchmark + verification，产出 JSON 报告。
2. **Phase 6：Prompt Management 试点**
   - 新增 `prompt_registry` facade。
   - 先让 `decision_judge`、`evidence` 记录 prompt metadata，并保留本地 fallback。
   - 默认不改 core decision prompt，不上传完整 prompt/input/output。
3. **Phase 7：人工标注闭环**
   - 新增 annotation queue dry-run export。
   - 从 problem games、低分 judge、fallback/LLM error、promotion gate 边界样本中筛选。
   - 输出只包含短摘要、ID、deep link 和 metadata，为后续 Human Annotation API 写入做准备。

这三步完成后，Langfuse 的定位会从“可观测实验面板”扩展为“可验收、可追踪 prompt 版本、可承接人工标注闭环”的辅助系统；PostgreSQL、`app.lib.score` 和正式 leaderboard 仍保持权威地位。

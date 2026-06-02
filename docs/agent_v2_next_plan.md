# Agent V2 下一阶段实现计划

本文档记录 `agent` 下一阶段的实现计划。目标不是重新设计整套系统，而是在当前已经实现的 Agent v2 基础上，继续补齐评分标准里最有价值的 Agent 层能力。

当前优先级判断：

1. 先提升单 Agent 决策质量。
2. 再做可验证的策略迭代。
3. 最后补展示、文档和演示材料。

本阶段仍然保持一个原则：Agent 层兼容现有规则层，不修改狼人杀引擎的核心回合流程。

## 1. 当前基础

当前 `agent` 已经具备以下能力：

- 图式 runtime：观察、记忆、信念、skill 路由、prompt、模型调用、解析、policy 修正、日志归档拆成独立节点。
- Markdown skill：规则、输出格式、角色策略都以 markdown skill 注入。
- 信息隔离：Agent 只从规则层给自己的 observation 构造上下文。
- 短期记忆：局内结构化现场笔记和玩家画像。
- 中期经验：从完整对局中提取按角色划分的经验卡片。
- 长期记忆：从多局经验卡片中聚合角色长期策略提示。
- 复盘评测：能生成玩家评分、失误定位、转折点和 skill 维度统计。
- 自博弈与 leaderboard：能跑多局 selfplay，并对不同版本做对比。
- skill 版本对战：支持指定不同 `skill_dir` 跑固定 seed 的 A/B 测试。

因此下一阶段不再优先补基础框架，而是围绕“更会玩”和“能证明更会玩”继续推进。

## 2. 阶段目标

下一阶段要形成一条更完整的 Agent 调优闭环：

```text
关键决策强推理
  -> 生成更高质量行动
  -> 对局归档
  -> 复盘定位问题
  -> 生成 skill 修改建议
  -> 产生候选 skill 版本
  -> 多版本固定 seed 对战
  -> leaderboard 验证效果
```

这个闭环对应评分标准中的三个核心方向：

- 单 Agent 能力：通过 ToT / 多候选决策提升关键行动质量。
- 多 Agent 系统设计：通过 skill、记忆、上下文、归档和评测形成可调优系统。
- 进阶课题：更接近“评测 + 复盘”或“自进化 Agent”。

## 3. P1：ToT / 多候选关键决策

### 3.1 目标

为高影响动作引入多候选推理，让 Agent 不再只生成一个决策，而是先生成多个候选方案，再通过评审器选择最优方案。

这部分直接服务“单 Agent 能力 20%”：

- Prompt 设计更精细。
- 决策推理链路更可追溯。
- 不同角色在关键动作上的策略差异更明显。
- 可以统计 ToT 是否提高 review score。

### 3.2 启用范围

ToT 不应该用于所有动作，否则 token 成本过高，收益也不明显。

建议第一版只在以下动作启用：

- 白天投票。
- 女巫救人 / 毒人。
- 预言家查验。
- 狼人夜刀。
- 猎人开枪。
- 白狼王自爆。
- 警长竞选相关关键发言。

普通发言可以暂时不启用，除非后续发现发言质量是主要短板。

### 3.3 设计方案

新增模块：

```text
agent/
  reasoning/
    __init__.py
    tot.py
```

核心数据结构：

```python
@dataclass
class ToTCandidate:
    candidate_id: str
    action: dict[str, Any]
    public_text: str
    private_reasoning: str
    expected_gain: str
    risk: str


@dataclass
class ToTResult:
    enabled: bool
    candidates: list[ToTCandidate]
    selected_id: str | None
    judge_reason: str
    final_action: ActionResponse | None
```

运行流程：

```text
prompt_node 构造普通 prompt
  -> llm_node 判断当前 action 是否需要 ToT
  -> 如果不需要，保持当前流程
  -> 如果需要，调用 ToT prompt 生成候选方案
  -> judge prompt 对候选方案评分
  -> 选出 final_action
  -> parse_node / policy_node 继续做合法性校验
  -> archive 记录 candidates 和 judge_reason
```

### 3.4 Prompt 要点

候选生成 prompt 需要明确要求：

- 至少生成 3 个不同策略方向。
- 每个候选必须包含行动、公开话术、私有推理、预期收益和风险。
- 不允许使用 observation 中不存在的私有信息。
- 狼人可以欺骗，好人不能假装知道未获得的信息。
- 输出必须是 JSON，方便解析。

评审 prompt 需要按维度打分：

- 规则合法性。
- 当前轮次收益。
- 长期身份收益。
- 信息暴露风险。
- 阵营胜率贡献。
- 与角色 skill 的一致性。

### 3.5 验收标准

- 关键 action 能启用 ToT。
- 普通 action 不启用 ToT。
- ToT 输出解析失败时仍能 fallback 到原有单决策流程。
- policy 仍然能修正非法目标。
- archive 中能看到候选方案和评审理由。
- 单元测试覆盖启用、禁用、解析失败、非法动作修正。

## 4. P2：Skill 进化建议

### 4.1 目标

让复盘报告不只停留在“这局哪里错了”，而是能输出“应该如何修改 markdown skill”。

第一版不直接覆盖正式 skill，而是生成候选修改建议，人工确认后再应用。这样可以避免自动改坏策略。

### 4.2 输入

输入来源：

- `review.json`：玩家评分、失误、转折点。
- `experience cards`：每个角色的关键经验。
- `long memory`：跨局沉淀出的长期策略。
- 当前 `skills/**/*.md`：已有策略内容。

### 4.3 输出

建议输出目录：

```text
data/skill_suggestions/
  run_001/
    werewolf.md
    seer.md
    witch.md
    hunter.md
    villager.md
    summary.json
```

每个角色建议包含：

- 发现的问题。
- 证据来源。
- 建议新增的 skill 规则。
- 建议删除或降权的旧规则。
- 预计影响。
- 风险。

示例：

```markdown
# Werewolf Skill Update Suggestions

## 问题

狼人首日悍跳后被快速识破，主要原因是发言没有提前解释查验动机。

## 建议新增

- 如果选择悍跳预言家，必须提前准备查验路径：为什么查这个人、后续准备验谁、如何回应真预言家对跳。
- 如果发言位靠后且前置位已有强预言家起跳，优先考虑隐狼或倒钩，而不是强行悍跳。

## 证据

- game_003：狼人 2 首日悍跳失败，review score 42。
- game_006：狼人 5 悍跳但缺少查验链，第二天被票出。
```

### 4.4 验收标准

- 能从复盘和经验卡片生成按角色分组的 skill 修改建议。
- 建议中包含证据，不是泛泛而谈。
- 不直接覆盖正式 `skills`。
- 可以把建议复制成一个新 `skill_dir` 用于版本对战。

## 5. P3：候选 Skill 版本生成

### 5.1 目标

在 skill 建议基础上，自动生成候选版本目录，方便直接跑 A/B 对战。

目录结构：

```text
data/skill_versions/
  baseline/
  evolved_001/
  evolved_002/
```

其中：

- `baseline/` 是当前正式 skills 的拷贝。
- `evolved_001/` 是应用建议后的候选版本。
- 每个版本有 `VERSION.md` 记录来源、修改点和生成时间。

### 5.2 应用方式

第一版采用保守策略：

- 只追加新建议，不删除旧内容。
- 新增内容放在文件末尾的 `## Learned Strategy Notes` 区块。
- 每条建议带来源 game id 或 run id。
- 如果同一条建议重复出现，合并而不是重复追加。

### 5.3 验收标准

- 能生成完整可用的 `skill_dir`。
- `SelfPlayConfig(skill_dir=...)` 可以直接加载该目录。
- 版本目录中有变更说明。
- 不修改正式 skill 目录。

## 6. P4：版本对战验证

### 6.1 目标

使用已经实现的 `version_battle`，验证新策略是否真的提升表现。

对战对象：

- `baseline`：当前正式 skill。
- `evolved_001`：应用复盘建议后的 skill。
- `tot_enabled`：启用 ToT 的 agent。
- `tot_plus_evolved`：启用 ToT 且使用进化 skill 的 agent。

### 6.2 固定变量

为了让对比有意义，需要固定：

- 相同规则配置。
- 相同模型。
- 相同 temperature。
- 相同 seed 范围。
- 相同局数。

### 6.3 指标

Leaderboard 至少包含：

- 总胜率。
- 好人胜率。
- 狼人胜率。
- 平均 review score。
- fallback rate。
- 平均局长。
- 非法动作修正次数。
- 关键失误数量。

### 6.4 验收标准

- 能一键跑多个版本。
- 每个版本使用同一批 seed。
- 输出 `leaderboard.json` 和 `leaderboard.md`。
- 能看出版本之间的差异。
- 如果新版本变差，也要保留结果，作为 bad case。

## 7. P5：文档与演示材料

### 7.1 目标

把 Agent 层能力讲清楚，让评委能快速理解项目亮点。

需要补充：

- Agent 决策链路图。
- 信息隔离说明。
- skill 注入规则。
- 短期 / 中期 / 长期记忆说明。
- ToT 多候选决策示例。
- 复盘报告示例。
- skill 进化示例。
- leaderboard 对比结果。

### 7.2 推荐演示路径

答辩时可以按下面顺序展示：

```text
1. 打开一局完整对局日志
2. 展示某个关键投票前 Agent 看到了什么
3. 展示注入的 role skill 和长期记忆
4. 展示 ToT 生成的 3 个候选方案
5. 展示 judge 为什么选最终方案
6. 展示赛后 review 如何定位失误
7. 展示该失误如何生成 skill 修改建议
8. 展示 baseline vs evolved leaderboard
```

这条线能把“Agent 调优”和“多智能体系统设计”串起来。

## 8. 推荐实现顺序

### Phase 1：ToT 最小可用版

实现内容：

- 新增 `reasoning/tot.py`。
- 定义 ToT 数据结构。
- 在 runtime 中为关键 action 启用 ToT。
- archive 记录候选和评审。
- 补测试。

验收：

- 全量测试通过。
- 至少一个关键 action 能走 ToT。
- ToT 失败不影响游戏继续。

### Phase 2：Skill 建议生成

实现内容：

- 新增 `skill_evolution.py`。
- 从 review / experience / long memory 生成建议。
- 输出 markdown 和 json。

验收：

- 能按角色输出建议。
- 建议有证据链。
- 不修改正式 skill。

### Phase 3：Skill 版本生成

实现内容：

- 新增候选 skill_dir 生成工具。
- 把建议追加到 `Learned Strategy Notes`。
- 生成 `VERSION.md`。

验收：

- 新 skill_dir 可被 `configure_skill_root()` 加载。
- 能用 `SelfPlayConfig(skill_dir=...)` 跑局。

### Phase 4：A/B 验证

实现内容：

- 用 `version_battle` 对比 baseline / evolved / tot。
- 输出 leaderboard。
- 记录显著 bad case。

验收：

- 至少跑一组固定 seeds。
- 结果能用于答辩展示。

### Phase 5：文档收尾

实现内容：

- 更新 `docs/agent_v2_design.md`。
- 增加一份演示说明。
- 记录当前已实现能力和未实现能力。

验收：

- 文档能对应代码。
- 评委可以按文档复现实验。

## 9. 风险与取舍

### 9.1 ToT 成本

ToT 会增加 token 成本和延迟。因此只在关键 action 启用，不在所有发言里启用。

### 9.2 自动改 skill 的风险

自动覆盖正式 skill 风险较高。第一版只生成候选版本，正式采用前需要通过版本对战验证。

### 9.3 胜率波动

狼人杀本身随机性很强，少量局数不能证明策略稳定提升。至少需要固定 seed 对比，最好每个版本 20 局以上。

### 9.4 过拟合

如果 skill 只针对少数 bad case 修改，可能会对其他局势变差。解决方式是：

- 建议保留证据。
- 版本对战覆盖多个 seed。
- leaderboard 同时看胜率、review score 和 fallback rate。

## 10. 当前最建议立刻做的任务

下一步最建议先实现：

```text
P1：ToT / 多候选关键决策
```

原因：

- 对评分中的“单 Agent 能力”提升最直接。
- 实现边界清晰，不需要动规则层。
- 能自然接入现有 archive / review / leaderboard。
- 后续 skill 进化和 A/B 验证都可以基于 ToT 结果继续扩展。

完成 ToT 后，项目的 Agent 层就能从“按 skill 单次决策”升级为“基于 skill、记忆和多候选评审的关键决策系统”。

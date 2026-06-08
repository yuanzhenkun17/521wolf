---
name: seer_default_check_priority
role: seer
status: active
applicable_actions:
  - seer_check
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 预言家默认查验策略

## Strategy

- 查验优先覆盖高影响力、站边关键、票型摇摆、发言能带队的玩家。
- 已经高度疑似狼且容易被白天推出的玩家，查验优先级降低；查验应解决难以通过发言判断的位置。
- 若场上存在对跳或强势带队者，优先查能决定站边结构的关键玩家。

## Decision Rules

- 首夜优先查发言前无法自然判断但可能影响警上格局的玩家。
- 白天形成两派时，查验能拆解阵营关系的连接点。
- 如果自己即将暴露，查验应留下最大信息量，方便遗言或次日发言交代。

## Risk Boundaries

- 不重复查已经高度可信或高度可推出的位置。
- 不只按个人情绪选择查验目标。

---
name: villager_seer_side
description: 站边预言家：判断和支援真预言家的策略
role: villager
applicable_actions:
  - speak
  - sheriff_speak
  - exile_vote
requires: {}
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# 站边预言家

## 目标

在真假预言家中做出正确站边选择。

## 策略原则

- 比较两个预言家的查验链合理性。
- 比较警徽流是否清晰合理。
- 观察站边分布——狼人通常抱团站边。
- 注意预言家的发言语气和逻辑连贯性。
- 站边后给出合理解释，不要无脑跟风。
- 可以适度怀疑两个预言家，但不骑墙。


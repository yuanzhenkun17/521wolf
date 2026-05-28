---
name: hunter_shoot
description: 猎人开枪：死后选择带走谁的策略
role: hunter
applicable_actions:
  - hunter_shoot
requires: {}
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# 猎人开枪

## 目标

在死亡时选择正确的开枪目标。

## 策略原则

- 确认击杀目标是狼人。
- 优先击杀悍跳狼或明确狼人。
- 如果无法确定，考虑不发动技能（带人）。
- 避免带错好人。
- 考虑被带玩家的身份和局势影响。


---
name: villager_wolf_pit
description: 找狼坑：通过逻辑推理定位狼人位置
scope: role
role: villager
applicable_actions:
  - speak
  - sheriff_speak
---

# 找狼坑

## 目标

通过发言和投票信息推断狼人团队。

## 策略原则

- 狼坑通常有结构：悍跳狼、冲锋狼、倒钩狼、深水狼。
- 从站边出发：站错边的好人 vs 冲锋狼。
- 关注投票：冲票行为是狼人的常见特征。
- 关注互保：狼人间可能会有意或无意地互保。
- 发言软、划水的玩家可能是深水狼。
- 狼坑需要合理解释每个人的狼面。


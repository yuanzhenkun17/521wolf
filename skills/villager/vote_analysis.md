---
name: villager_vote_analysis
description: 投票分析：通过投票行为判断狼人的方法
role: villager
applicable_actions:
  - exile_vote
  - pk_vote
requires: {}
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# 投票分析

## 目标

通过观察投票行为推断身份。

## 策略原则

- 注意投票集中度：狼人可能会抱团投票。
- 关注改票行为：突然改票的人可能有团队意图。
- 关注分票：狼人可能会分散投票制造混乱。
- 关注弃票：狼人可能弃票规避风险。
- 投票和发言逻辑是否一致。


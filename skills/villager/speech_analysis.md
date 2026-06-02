---
name: villager_speech_analysis
description: 发言分析：通过发言内容判断身份的方法
role: villager
applicable_actions:
  - speak
  - sheriff_speak
  - pk_speak
requires: {}
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# 发言分析

## 目标

通过分析其他玩家的发言内容推断其身份。

## 策略原则

- 关注逻辑连贯性：前后发言是否一致。
- 关注跟风行为：总是重复前面观点可能是狼人。
- 关注站边逻辑：站边理由是否合理。
- 关注信息量：知道太多或太少都可疑。
- 投票理由是否充分、合理。


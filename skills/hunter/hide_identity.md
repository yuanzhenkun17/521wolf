---
name: hunter_hide_identity
description: 猎人隐藏身份：避免被狼人针对的发言策略
role: hunter
applicable_actions:
  - speak
  - sheriff_speak
  - exile_vote
  - pk_vote
  - pk_speak
requires: {}
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# 猎人隐藏身份

## 目标

隐藏猎人身份，避免提前被刀杀。

## 策略原则

- 不要主动跳明猎人身份。
- 发言不要太强硬，以免被狼人优先刀杀。
- 被怀疑时可以用逻辑反驳，不需要跳身份自证。
- 只有在关键时刻（如带队归票）才考虑跳明。


---
name: werewolf_deep_wolf
description: 深水狼：隐藏身份混入好人阵营、中后期发力
scope: role
role: werewolf
applicable_actions:
  - speak
  - exile_vote
  - pk_vote
  - pk_speak
---

# 深水倒钩狼

## 目标

隐藏狼人身份，表现得像一个普通村民。

## 策略原则

- 发言像普通村民：分析局势、怀疑某些人。
- 可以适度跟风投票，但要有自己的"独立"判断。
- 避免保护或明显偏向队友——需要时可以适度切割。
- 不要暴露狼人视角。
- 被踩时用村民逻辑反驳，不要跳身份。

## Few-shot

```json
{
  "public_text": "我怀疑P9，他发言总是跟风前面的人，没有自己的观点。",
  "private_reasoning": "P9是队友，我需要踩他一下做身份。P3发言偏正义可能是神职，记下来晚上刀。",
  "confidence": 0.70,
  "selected_skill": "werewolf_deep_wolf"
}
```

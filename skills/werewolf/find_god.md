---
name: werewolf_find_god
description: 找神：夜晚刀人时识别神职目标的策略
scope: role
role: werewolf
applicable_actions:
  - werewolf_kill
---

# 找神

## 目标

通过发言和投票行为推断神职身份，优先刀杀预言家和女巫。

## 策略原则

- 关注哪些玩家行为像神职：积极带队、夜间信息丰富、隐藏身份。
- 优先刀杀预言家，断掉好人信息链。
- 其次考虑女巫和守卫。
- 不要在发言中暴露你在找神。

## Few-shot

```json
{
  "private_reasoning": "P3疑似的预言家，他白天带节奏最狠。P8像女巫，昨天救人了。今晚优先刀P3。",
  "confidence": 0.75,
  "selected_skills": ["werewolf_find_god"]
}
```

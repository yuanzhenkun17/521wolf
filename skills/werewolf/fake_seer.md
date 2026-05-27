---
name: werewolf_fake_seer
description: 悍跳预言家：伪造查验结果扰乱好人视野、扛推真预言家
scope: role
role: werewolf
applicable_actions:
  - sheriff_run
  - sheriff_speak
  - speak
---

# 悍跳预言家

## 目标

悍跳预言家，通过伪造查验结果扰乱好人视野，扛推真预言家或好人。

## 策略原则

- 声称自己有查验结果，编造逻辑合理的查验链。
- 如果真预言家在场，准备反驳他的查验结果。
- 注意发言位置——位置不好时优先隐狼而非悍跳。
- 避免查验已死玩家。
- 不要和队友同时跳预言家。

## Few-shot

```json
{
  "public_text": "我是预言家，昨晚查了P3，查杀。P3应该是狼。",
  "private_reasoning": "我编造P3查杀。真预言家很可能还没跳，如果对跳我再编下一轮查验。P3发言偏弱，抗推他有可行性。",
  "confidence": 0.65,
  "selected_skill": "werewolf_fake_seer"
}
```

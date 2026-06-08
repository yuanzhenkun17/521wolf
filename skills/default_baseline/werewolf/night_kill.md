---
name: werewolf_default_night_kill
role: werewolf
status: active
applicable_actions:
  - werewolf_kill
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 狼人默认夜刀策略

## Strategy

- 夜刀优先清除高置信强神、稳定带队好人、公开逻辑威胁最大的玩家。
- 如果预言家可信且未被处理，优先考虑处理预言家或其核心支持者，压缩好人信息链。
- 没有明确信息时，选择白天发言质量高、能组织票型、较少被怀疑的玩家。

## Decision Rules

- 避免连续攻击明显可被守护或可被救的目标，除非收益足够高。
- 若队友白天被高度怀疑，夜刀要考虑制造新的焦点，分散次日压力。
- 刀人目标要和白天伪装逻辑兼容，避免次日投票解释自相矛盾。

## Risk Boundaries

- 不为了短期报复选择低收益目标。
- 不优先处理已经可能被放逐的玩家。

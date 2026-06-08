---
name: hunter_shot_timing
role: hunter
status: active
applicable_actions:
  - hunter_shoot
  - last_word
  - speak
  - exile_vote
  - pk_vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 猎人开枪时机

## Strategy

- 开枪是高影响动作，目标必须有足够狼证据或能最大化信息收益。
- 不开枪也是策略：当候选都可能是好人关键角色时，保留好人阵营人数比强行带人更好。
- 临终发言应收敛后续归票，而不是扩大场上分歧。

## Decision Rules

- 有可靠查杀、明显票型暴露或多轮发言矛盾时，优先瞄准对应目标。
- 白天被推出时，重点审视推动链条中收益最像狼人的位置。
- 夜间死亡且信息不足时，先说明不开枪理由和后续怀疑排序。

## Risk Boundaries

- 不因情绪、被攻击或单句矛盾直接开枪。
- 不在置信不足时带走疑似强神或稳定好人。
- 不把遗言写成多个互斥方向。

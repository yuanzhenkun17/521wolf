---
name: witch_save_poison_boundary
role: witch
status: active
applicable_actions:
  - witch_act
  - speak
  - last_word
  - exile_vote
  - pk_vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 女巫救毒边界

## Strategy

- 解药用于保住高价值好人和信息链核心；毒药用于处理高置信狼人或白天难以推出的强破坏位。
- 药的价值来自时机和目标，不来自尽早使用；信息不足时保留药权通常更稳。
- 白天发言只释放必要信息，避免完整暴露药况和夜间判断路径。

## Decision Rules

- 刀口可信且目标能提供查验、守护、归票或稳定带队价值时，倾向使用解药。
- 毒药需要多重证据支撑，例如查杀、票型异常、发言矛盾和持续带偏收益。
- 救毒冲突、守卫可能介入、猎人可能误伤时，优先降低连锁风险。

## Risk Boundaries

- 不因个人被踩就优先毒攻击者。
- 不为了自证身份而提前交代完整药况。
- 不在低信息局面把两瓶药连续交空。

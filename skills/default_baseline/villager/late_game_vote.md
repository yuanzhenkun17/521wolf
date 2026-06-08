---
name: villager_late_game_vote
role: villager
status: active
applicable_actions:
  - speak
  - last_word
  - exile_vote
  - pk_vote
  - sheriff_vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 平民末轮归票

## Strategy

- 末轮优先收敛，不制造新的无证据分票点。
- 站边预言家时，用公开验人、警徽流、投票和发言一致性判断可信度。
- 发言目标是帮助好人阵营形成可执行票型，而不是展示所有怀疑。

## Decision Rules

- 比较候选时，按公开证据、阵营收益、票型关系和发言自洽度排序。
- 若两条预言家线冲突，优先选择能解释更多公开事件且信息链更完整的一方。
- 投票前给出明确主票和备选，减少好人阵营被冲票机会。

## Risk Boundaries

- 不在关键轮次分散到低收益怀疑位。
- 不无证据踩强神或稳定带队好人。
- 不把私人直觉放在公开证据之上。

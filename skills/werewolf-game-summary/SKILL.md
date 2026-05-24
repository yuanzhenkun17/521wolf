---
name: werewolf-game-summary
description: Use when summarizing a Werewolf game log, replay, or match record, especially when the user needs identities, daily speeches, vote patterns, exile outcomes, night actions, and the final winner.
---

# Werewolf Game Summary

## Purpose

Summarize a Werewolf game from engine logs into a clear chronological replay. Treat the log as the source of truth, and distinguish public speeches from private night actions and voting explanations.

## Inputs

Prefer structured logs when available:

- `logs/*.jsonl`: best for exact event type, actor, target, phase, payload
- `logs/*.txt`: best for readable Chinese messages and quoted speeches

If both exist, use `jsonl` for structure and `txt` for natural-language speech details.

## Required Output

Always include these sections:

1. **身份分配**
   - List players 1-12 and their roles.
   - Group by team when helpful: wolves, gods, villagers.

2. **逐日流程**
   - For each day/night, summarize in order.
   - Include night actions:
     - guard protection
     - werewolf kill votes and final target
     - seer checks and result
     - witch save/poison/no action
     - hunter shot timing and target, if any
     - sheriff badge transfer/destroy, if any
     - deaths and death causes
   - Include daytime content:
     - last words
     - regular `speak` speeches
     - white wolf explosion and immediate last word
     - important claims, accusations, standing sides, and contradictions

3. **票型与放逐**
   - For each `exile_vote` and `pk_vote`, list who voted for whom.
   - State ties, PK candidates, PK result, and final exiled player.
   - Note that `exile_vote` text is a voting reason, not necessarily normal round speech.
   - State immediate last word after exile.

4. **关键转折**
   - Highlight decisive events: white wolf explosion, seer death, witch medicine usage, hunter shot, wrong exile, wolf vote control, slaughter-side condition.

5. **最终结果**
   - Winner.
   - Why the game ended, using the engine win condition if visible.

## Interpretation Rules

- Do not invent speeches or actions. If a detail is missing, say "日志未记录".
- Distinguish these text types:
  - `speak`: normal daytime speech
  - `last_word`: death speech
  - `exile_vote` / `pk_vote`: vote reason
  - `werewolf_kill`, `guard_protect`, `seer_check`, `witch_act`, `hunter_shoot`: private action text or god-log action text
- Night action text is not public table speech unless the user explicitly asks for god-view reasoning.
- If a player reveals hidden information in their text, summarize it as "该 agent 发言中泄露/声称..." rather than treating it as valid public knowledge.
- When white wolf explodes, summarize: explosion target, target death, white wolf immediate last word, and skipped exile if present.
- When hunter dies:
  - Exile death: hunter has immediate last word, then chooses whether to shoot.
  - Werewolf night kill: hunter has last word at daybreak, then chooses whether to shoot.
  - Hunter-shot target has no last word.
  - Poisoned hunter cannot shoot.

## Suggested Format

```markdown
**身份**
1号：...

**第0天：警长竞选**
发言摘要：...
票型：...
结果：...

**第1夜**
守卫：...
狼人：...
预言家：...
女巫：...
死亡：...

**第1天**
遗言：...
发言摘要：
- 1号：...
- 2号：...
票型：...
放逐：...

**关键转折**
- ...

**最终结果**
胜利方：...
结束原因：...
```

## Quality Checklist

Before answering, verify:

- All 12 identities are accounted for.
- Every night has actions and death result.
- Every day has speech summary, vote pattern, and exile result when applicable.
- Last words are placed at the correct timing.
- Voting reasons are not confused with normal daytime speeches.
- Final winner and ending condition are explicit.

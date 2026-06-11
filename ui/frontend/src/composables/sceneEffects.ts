import type { Game } from '../types/game'

type LooseRecord = Record<string, any>
type NumericId = number | null

interface SceneEffect {
  id: string
  type: string
  actorId: NumericId
  targetId: number
  day: number
  sequence: number
  source: 'decision' | 'log'
}

const GUARD_ACTIONS = new Set(['guard_protect', 'guard'])
const WITCH_SAVE_ACTIONS = new Set(['witch_save', 'antidote'])
const WITCH_POISON_ACTIONS = new Set(['witch_poison', 'poison'])
const VOTE_OUT_TYPES = new Set(['exile', 'exile_vote_end', 'pk_vote_end'])
const NIGHT_OUTCOME_TYPES = new Set(['night_end', 'night_result', 'night_death', 'night_death_reveal', 'death_result'])
const PUBLIC_DEATH_TYPES = new Set([
  'night_result',
  'night_death',
  'night_death_reveal',
  'death_result',
  'death',
  'hunter_shoot',
  'hunter_shot',
  'shoot',
  'white_wolf_burst_kill',
  'white_wolf_burst_death',
  'white_wolf_explosion'
])
const VOTE_ACTIONS = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const PUBLIC_SKILL_KILL_ACTIONS = new Set([
  'hunter_shoot',
  'hunter_shot',
  'shoot',
  'white_wolf_burst',
  'white_wolf_explosion'
])

function isRecord(value: unknown): value is LooseRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function numericId(value: unknown): NumericId {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function rowType(row: LooseRecord = {}) {
  return String(row.type || row.event_type || row.action || row.action_type || row.kind || '').trim()
}

function targetId(row: LooseRecord = {}): NumericId {
  return numericId(
    row.target_id
    ?? row.target
    ?? row.selected_target
    ?? row.payload?.target_id
    ?? row.payload?.target
    ?? row.payload?.player_id
  )
}

function actorId(row: LooseRecord = {}): NumericId {
  return numericId(row.actor_id ?? row.player_id ?? row.actor ?? row.playerId)
}

function payloadOf(row: LooseRecord = {}): LooseRecord {
  return isRecord(row.payload) ? row.payload : {}
}

function rowChoice(row: LooseRecord = {}) {
  const payload = payloadOf(row)
  return String(
    payload.choice
    ?? payload.selected_choice
    ?? payload.selected_skill
    ?? row.choice
    ?? row.selected_choice
    ?? row.selected_skill
    ?? row.action_choice
    ?? ''
  ).trim().toLowerCase()
}

function isLegacyWhiteWolfExplodeKill(row: LooseRecord = {}) {
  if (rowType(row) !== 'white_wolf_explode') return false
  return ['explode', 'burst'].includes(rowChoice(row)) && Boolean(targetId(row))
}

function isPublicSkillKill(row: LooseRecord = {}) {
  return PUBLIC_SKILL_KILL_ACTIONS.has(rowType(row)) || isLegacyWhiteWolfExplodeKill(row)
}

function firstNumeric(row: LooseRecord = {}, keys: string[] = []): NumericId {
  const payload = payloadOf(row)
  for (const key of keys) {
    const id = numericId(payload[key] ?? row[key])
    if (id) return id
  }
  return null
}

function numericList(value: unknown): number[] {
  const source = Array.isArray(value) ? value : (value == null ? [] : [value])
  return source.map(numericId).filter(Boolean)
}

function payloadIds(row: LooseRecord = {}, keys: string[] = []): number[] {
  const payload = payloadOf(row)
  const ids: number[] = []
  const seen = new Set<number>()
  keys.forEach((key) => {
    numericList(payload[key] ?? row[key]).forEach((id) => {
      if (seen.has(id)) return
      seen.add(id)
      ids.push(id)
    })
  })
  return ids
}

function truthyFlag(value: unknown) {
  return value === true || value === 1 || value === '1' || String(value).toLowerCase() === 'true'
}

function deathCause(row: LooseRecord = {}) {
  return String(payloadOf(row).cause || row.cause || '').trim().toLowerCase()
}

function dayOf(row: LooseRecord = {}) {
  const day = Number(row.day)
  return Number.isFinite(day) && day > 0 ? day : 0
}

function sequenceOf(row: LooseRecord = {}, fallback = 0) {
  const sequence = Number(row.sequence ?? row.index ?? fallback)
  return Number.isFinite(sequence) ? sequence : fallback
}

function textOf(row: LooseRecord = {}) {
  return String(row.message || row.public_summary || row.public_text || row.text || row.content || '')
}

function effectId(kind: string, row: LooseRecord, target: NumericId | string, suffix: string | number = '') {
  return [
    kind,
    dayOf(row),
    row.phase || '',
    sequenceOf(row),
    actorId(row) || '',
    target || '',
    suffix
  ].join(':')
}

function nightOutcomeKey(kind: string, row: LooseRecord, target: NumericId | string) {
  return `${kind}:${dayOf(row)}:${target}`
}

function addEffect(effects: SceneEffect[], seen: Set<string>, effect: SceneEffect) {
  if (!effect?.type || !effect?.id) return
  if (effect.targetId != null && !numericId(effect.targetId)) return
  if (seen.has(effect.id)) return
  seen.add(effect.id)
  effects.push(effect)
}

function parseSeatIds(text = '') {
  const ids: number[] = []
  const seen = new Set<number>()
  const value = String(text || '')
  const patterns = [/(\d{1,2})\s*号/g, /P\s*(\d{1,2})\b/gi]
  patterns.forEach((pattern) => {
    let match
    while ((match = pattern.exec(value))) {
      const id = numericId(match[1])
      if (!id || id > 12 || seen.has(id)) continue
      seen.add(id)
      ids.push(id)
    }
  })
  return ids
}

function witchChoice(decision: LooseRecord = {}) {
  return String(
    decision.selected_skill
    ?? decision.selected_choice
    ?? decision.choice
    ?? decision.action_choice
    ?? ''
  ).trim()
}

function witchSaveTarget(decision: LooseRecord = {}): NumericId {
  return targetId(decision)
    ?? numericId(decision.metadata?.attacked_player)
    ?? numericId(decision.options?.attacked_player)
}

function nightKey(row: LooseRecord = {}) {
  return `${dayOf(row)}:night`
}

function groupNightDecisions(decisions: LooseRecord[] = []) {
  const groups = new Map<string, { saves: Array<{ row: LooseRecord; target: number }>; poisons: Array<{ row: LooseRecord; target: number }> }>()
  decisions.forEach((decision, index) => {
    const type = rowType(decision)
    const phase = String(decision.phase || '').trim()
    const nightSkill = GUARD_ACTIONS.has(type) || WITCH_SAVE_ACTIONS.has(type) || WITCH_POISON_ACTIONS.has(type) || type === 'witch_act'
    if (!phase && !nightSkill) return
    if (phase && phase !== 'night' && !nightSkill) return
    const key = nightKey(decision)
    const group = groups.get(key) || { saves: [], poisons: [] }
    const target = targetId(decision)
    const choice = witchChoice(decision)
    const row = { ...decision, sequence: decision.sequence ?? decision.index ?? index + 1 }
    if (WITCH_SAVE_ACTIONS.has(type) || (type === 'witch_act' && ['save', 'antidote'].includes(choice))) {
      const saveTarget = witchSaveTarget(decision)
      if (saveTarget) group.saves.push({ row, target: saveTarget })
    } else if (WITCH_POISON_ACTIONS.has(type) || (type === 'witch_act' && choice === 'poison')) {
      if (target) group.poisons.push({ row, target })
    }
    groups.set(key, group)
  })
  return groups
}

function buildPrivilegedNightEffects(decisions: LooseRecord[], effects: SceneEffect[], seen: Set<string>, preciseNightOutcomes: Set<string>) {
  const groups = groupNightDecisions(decisions)
  groups.forEach((group) => {
    group.saves.forEach(({ row, target }) => {
      addEffect(effects, seen, {
        id: effectId('witch_save', row, target),
        type: 'witch_save',
        actorId: actorId(row),
        targetId: target,
        day: dayOf(row),
        sequence: sequenceOf(row),
        source: 'decision'
      })
    })

    group.poisons.forEach(({ row, target }) => {
      preciseNightOutcomes.add(`${dayOf(row)}:${target}`)
      addEffect(effects, seen, {
        id: effectId('poison_kill', row, target),
        type: 'poison_kill',
        actorId: actorId(row),
        targetId: target,
        day: dayOf(row),
        sequence: sequenceOf(row),
        source: 'decision'
      })
    })
  })
}

function buildPrivilegedNightLogEffects(logs: LooseRecord[], effects: SceneEffect[], seen: Set<string>, preciseNightOutcomes: Set<string>) {
  const preciseLogOutcomes = new Set<string>()
  logs.forEach((log, index) => {
    const type = rowType(log)
    if (!NIGHT_OUTCOME_TYPES.has(type)) return
    const row = { ...log, sequence: log.sequence ?? log.index ?? index + 1 }
    const payload = payloadOf(log)
    const deferredDeathReveal = truthyFlag(payload.deferred_death_reveal ?? log.deferred_death_reveal)
    if (type === 'night_end' && deferredDeathReveal) return
    const killed = firstNumeric(log, ['killed_target', 'killedTarget', 'attacked_player', 'attackedPlayer'])
    const guardedTarget = firstNumeric(log, ['protected_target', 'protectedTarget', 'guarded_target', 'guardedTarget'])
    const poisoned = firstNumeric(log, ['poisoned_target', 'poisonedTarget', 'poison_target', 'poisonTarget'])
    const savedTarget = firstNumeric(log, ['saved_target', 'savedTarget', 'revived_target', 'revivedTarget', 'antidote_target', 'antidoteTarget'])
    const hasDeathList = Array.isArray(payload.deaths)
      || Array.isArray(log.deaths)
      || Array.isArray(payload.death_ids)
      || Array.isArray(log.death_ids)
      || Array.isArray(payload.dead_players)
      || Array.isArray(log.dead_players)
    const deaths = payloadIds(log, ['deaths', 'death_ids', 'dead_players'])
    const saved = truthyFlag(payload.saved ?? payload.used_antidote ?? payload.antidote_used)

    if (killed) {
      const guarded = guardedTarget === killed
      const died = deaths.includes(killed)
      if (hasDeathList && !died && !guarded && !saved) return
      const effectType = died ? 'wolf_kill' : guarded ? 'wolf_guarded' : saved ? 'wolf_saved' : 'wolf_kill'
      const key = nightOutcomeKey('attack', row, killed)
      if (!preciseNightOutcomes.has(`${dayOf(row)}:${killed}`) && !preciseLogOutcomes.has(key)) {
        preciseLogOutcomes.add(key)
        preciseNightOutcomes.add(`${dayOf(row)}:${killed}`)
        addEffect(effects, seen, {
          id: effectId(effectType, row, killed, 'payload'),
          type: effectType,
          actorId: actorId(log),
          targetId: killed,
          day: dayOf(row),
          sequence: sequenceOf(row),
          source: 'log'
        })
      }
    }

    if (poisoned) {
      const key = nightOutcomeKey('poison', row, poisoned)
      if (!preciseNightOutcomes.has(`${dayOf(row)}:${poisoned}`) && !preciseLogOutcomes.has(key)) {
        preciseLogOutcomes.add(key)
        preciseNightOutcomes.add(`${dayOf(row)}:${poisoned}`)
        addEffect(effects, seen, {
          id: effectId('poison_kill', row, poisoned, 'payload'),
          type: 'poison_kill',
          actorId: actorId(log),
          targetId: poisoned,
          day: dayOf(row),
          sequence: sequenceOf(row) + 0.02,
          source: 'log'
        })
      }
    }

    if (savedTarget && savedTarget !== killed) {
      const key = nightOutcomeKey('save', row, savedTarget)
      if (!preciseLogOutcomes.has(key)) {
        preciseLogOutcomes.add(key)
        addEffect(effects, seen, {
          id: effectId('witch_save', row, savedTarget, 'payload'),
          type: 'witch_save',
          actorId: actorId(log),
          targetId: savedTarget,
          day: dayOf(row),
          sequence: sequenceOf(row) + 0.01,
          source: 'log'
        })
      }
    }

    deaths.forEach((id, idIndex) => {
      if (preciseNightOutcomes.has(`${dayOf(row)}:${id}`)) return
      preciseNightOutcomes.add(`${dayOf(row)}:${id}`)
      addEffect(effects, seen, {
        id: effectId('night_death', row, id, `payload:${idIndex}`),
        type: 'night_death',
        actorId: actorId(log),
        targetId: id,
        day: dayOf(row),
        sequence: sequenceOf(row) + idIndex / 10,
        source: 'log'
      })
    })
  })
}

function buildPublicLogEffects(logs: LooseRecord[], effects: SceneEffect[], seen: Set<string>, preciseNightOutcomes: Set<string>) {
  logs.forEach((log, index) => {
    const type = rowType(log)
    const row = { ...log, sequence: log.sequence ?? log.index ?? index + 1 }
    const target = targetId(log)

    if (VOTE_OUT_TYPES.has(type) && target) {
      addEffect(effects, seen, {
        id: effectId('exile_out', row, target),
        type: 'exile_out',
        actorId: actorId(log),
        targetId: target,
        day: dayOf(log),
        sequence: sequenceOf(row),
        source: 'log'
      })
      return
    }

    if (!PUBLIC_DEATH_TYPES.has(type) && !isLegacyWhiteWolfExplodeKill(log)) return
    if (type === 'death' && ['exile', 'self_explode'].includes(deathCause(log))) return
    const targets = target ? [target] : parseSeatIds(textOf(log))
    targets.forEach((id, idIndex) => {
      if (preciseNightOutcomes.has(`${dayOf(log)}:${id}`)) return
      addEffect(effects, seen, {
        id: effectId('night_death', row, id, idIndex),
        type: 'night_death',
        actorId: actorId(log),
        targetId: id,
        day: dayOf(log),
        sequence: sequenceOf(row) + idIndex / 10,
        source: 'log'
      })
    })
  })
}

function buildPublicDecisionEffects(decisions: LooseRecord[], effects: SceneEffect[], seen: Set<string>, preciseNightOutcomes = new Set<string>()) {
  decisions.forEach((decision, index) => {
    const type = rowType(decision)
    const target = targetId(decision)
    if (!target) return
    const row = { ...decision, sequence: decision.sequence ?? decision.index ?? index + 1 }
    if (isPublicSkillKill(decision)) {
      if (preciseNightOutcomes.has(`${dayOf(decision)}:${target}`)) return
      preciseNightOutcomes.add(`${dayOf(decision)}:${target}`)
      addEffect(effects, seen, {
        id: effectId('night_death', row, target, 'skill'),
        type: 'night_death',
        actorId: actorId(decision),
        targetId: target,
        day: dayOf(decision),
        sequence: sequenceOf(row),
        source: 'decision'
      })
      return
    }
    // Vote totals already provide continuous visual feedback. Playing a large
    // flash for every ballot obscures the tally and feels like an action effect.
    if (VOTE_ACTIONS.has(type)) return
  })
}

export function buildSceneEffects(game: Game | null | undefined, { canSeeLog, isWatch = false, isReplayMode = false }: {
  canSeeLog?: (log: LooseRecord) => boolean
  isWatch?: boolean
  isReplayMode?: boolean
} = {}): SceneEffect[] {
  if (!game) return []
  const privileged = Boolean(isWatch || isReplayMode || game.winner)
  const allLogs = (Array.isArray(game.logs) ? game.logs : (Array.isArray(game.events) ? game.events : [])) as LooseRecord[]
  const visibleLogs = privileged || typeof canSeeLog !== 'function'
    ? allLogs
    : allLogs.filter((log) => canSeeLog(log))
  const allDecisions = (Array.isArray(game.decisions) ? game.decisions : []) as LooseRecord[]
  const effects: SceneEffect[] = []
  const seen = new Set<string>()
  const preciseNightOutcomes = new Set<string>()

  if (privileged) {
    buildPrivilegedNightLogEffects(allLogs, effects, seen, preciseNightOutcomes)
    buildPublicDecisionEffects(allDecisions, effects, seen, preciseNightOutcomes)
  } else {
    buildPublicDecisionEffects(
      allDecisions.filter((decision) => VOTE_ACTIONS.has(rowType(decision)) || isPublicSkillKill(decision)),
      effects,
      seen,
      preciseNightOutcomes
    )
  }
  buildPublicLogEffects(visibleLogs, effects, seen, preciseNightOutcomes)

  return effects.sort((a, b) => (a.day - b.day) || (a.sequence - b.sequence) || String(a.id).localeCompare(String(b.id)))
}

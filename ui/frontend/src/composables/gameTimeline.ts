type TimelineRecord = Record<string, unknown>

interface TimelinePlayer extends TimelineRecord {
  id?: unknown
  alive?: boolean
  is_sheriff?: boolean
}

const AUTHORITATIVE_DEATH_EVENTS = new Set([
  'death',
  'exile',
  'exile_vote_end',
  'pk_vote_end',
  'white_wolf_burst_kill',
  'white_wolf_burst_death',
  'white_wolf_explosion'
])
const FALLBACK_DEATH_EVENTS = new Set(['werewolf_kill', 'hunter_shoot'])
const NIGHT_OUTCOME_EVENTS = new Set(['night_end', 'night_result', 'night_death', 'night_death_reveal', 'death_result'])
const SHERIFF_RESULT_EVENTS = new Set(['sheriff_election_end', 'sheriff_result'])
const SHERIFF_TRANSFER_EVENTS = new Set(['sheriff_badge_transfer', 'sheriff_transfer'])
const SHERIFF_DESTROY_EVENTS = new Set(['sheriff_badge_destroy', 'sheriff_destroy'])

function isRecord(value: unknown): value is TimelineRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function recordOf(value: unknown): TimelineRecord {
  return isRecord(value) ? value : {}
}

function numericId(value: unknown): number | null {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function logType(row: unknown = {}): string {
  const data = recordOf(row)
  return String(data.type || data.event_type || data.action || data.action_type || data.kind || '')
}

function payloadOf(row: unknown = {}): TimelineRecord {
  const payload = recordOf(row).payload
  return isRecord(payload) ? payload : {}
}

function rowChoice(row: unknown = {}): string {
  const data = recordOf(row)
  const payload = payloadOf(row)
  return String(
    payload.choice
    ?? payload.selected_choice
    ?? payload.selected_skill
    ?? data.choice
    ?? data.selected_choice
    ?? data.selected_skill
    ?? data.action_choice
    ?? ''
  ).trim().toLowerCase()
}

function truthyFlag(value: unknown): boolean {
  return value === true || value === 1 || value === '1' || String(value).toLowerCase() === 'true'
}

function payloadIdList(row: unknown = {}, keys: string[] = []): number[] {
  const data = recordOf(row)
  const payload = payloadOf(row)
  const ids: number[] = []
  const seen = new Set<number>()
  keys.forEach((key) => {
    const raw = payload[key] ?? data[key]
    const values = Array.isArray(raw) ? raw : (raw == null ? [] : [raw])
    values.forEach((value) => {
      const candidate = isRecord(value) ? (value.id ?? value.player_id ?? value.seat) : value
      const id = numericId(candidate)
      if (!id || seen.has(id)) return
      seen.add(id)
      ids.push(id)
    })
  })
  return ids
}

function eventTargetId(row: unknown = {}): number | null {
  const data = recordOf(row)
  const payload = payloadOf(row)
  return numericId(
    data.target_id
    ?? data.target
    ?? data.selected_target
    ?? payload.target_id
    ?? payload.target
    ?? payload.player_id
  )
}

function isLegacyWhiteWolfExplodeKill(log: unknown = {}): boolean {
  if (logType(log) !== 'white_wolf_explode') return false
  return ['explode', 'burst'].includes(rowChoice(log)) && Boolean(eventTargetId(log))
}

function eventKillsPlayer(log: unknown = {}, hasAuthoritativeDeathEvents = true): boolean {
  const type = logType(log)
  if (isLegacyWhiteWolfExplodeKill(log)) return true
  if (AUTHORITATIVE_DEATH_EVENTS.has(type)) return true
  return !hasAuthoritativeDeathEvents && FALLBACK_DEATH_EVENTS.has(type)
}

function nightOutcomeDeathIds(log: unknown = {}): number[] {
  const data = recordOf(log)
  const type = logType(log)
  if (!NIGHT_OUTCOME_EVENTS.has(type)) return []
  const payload = payloadOf(log)
  const deferredDeathReveal = truthyFlag(payload.deferred_death_reveal ?? data.deferred_death_reveal)
  if (type === 'night_end' && deferredDeathReveal) return []

  if (
    Array.isArray(payload.deaths)
    || Array.isArray(data.deaths)
    || Array.isArray(payload.death_ids)
    || Array.isArray(data.death_ids)
    || Array.isArray(payload.dead_players)
    || Array.isArray(data.dead_players)
  ) {
    return payloadIdList(log, ['deaths', 'death_ids', 'dead_players'])
  }

  const ids: number[] = []
  const killed = numericId(payload.killed_target ?? payload.killedTarget ?? data.killed_target ?? data.killedTarget)
  const protectedTarget = numericId(payload.protected_target ?? payload.protectedTarget ?? data.protected_target ?? data.protectedTarget)
  const saved = truthyFlag(payload.saved ?? payload.used_antidote ?? payload.antidote_used ?? data.saved)
  if (killed && !saved && killed !== protectedTarget) ids.push(killed)

  const poisoned = numericId(payload.poisoned_target ?? payload.poisonedTarget ?? payload.poison_target ?? payload.poisonTarget ?? data.poisoned_target)
  if (poisoned && !ids.includes(poisoned)) ids.push(poisoned)

  const target = eventTargetId(log)
  if (target && type !== 'night_end' && !ids.includes(target)) ids.push(target)
  return ids
}

function deathTargetIds(log: unknown = {}, hasAuthoritativeDeathEvents = true): number[] {
  const data = recordOf(log)
  const ids = nightOutcomeDeathIds(log)
  if (eventKillsPlayer(log, hasAuthoritativeDeathEvents)) {
    const target = eventTargetId(log) || numericId(data.actor_id)
    if (target && !ids.includes(target)) ids.push(target)
  }
  return ids
}

function isSheriffLog(log: unknown = {}): boolean {
  const type = logType(log)
  return SHERIFF_RESULT_EVENTS.has(type) || SHERIFF_TRANSFER_EVENTS.has(type) || SHERIFF_DESTROY_EVENTS.has(type)
}

function sheriffIdAfterLog(log: unknown = {}, currentSheriffId: unknown = null): number | null {
  const data = recordOf(log)
  const type = logType(log)
  const payload = payloadOf(log)
  if (SHERIFF_RESULT_EVENTS.has(type)) {
    return numericId(payload.winner ?? data.target_id ?? data.actor_id) ?? numericId(currentSheriffId)
  }
  if (SHERIFF_TRANSFER_EVENTS.has(type)) {
    return eventTargetId(log) ?? numericId(currentSheriffId)
  }
  if (SHERIFF_DESTROY_EVENTS.has(type)) {
    return null
  }
  return numericId(currentSheriffId)
}

function applySheriffToPlayers<TPlayer extends TimelinePlayer>(players: TPlayer[] = [], sheriffId: unknown = null): TPlayer[] {
  const nextSheriffId = numericId(sheriffId)
  return (players || []).map((player) => ({
    ...player,
    is_sheriff: Boolean(nextSheriffId && Number(player.id) === nextSheriffId)
  }))
}

function applyLogToPlayers<TPlayer extends TimelinePlayer>(
  players: TPlayer[] = [],
  log: unknown,
  hasAuthoritativeDeathEvents = true
): TPlayer[] {
  let next = (players || []).map((player) => ({ ...player }))
  for (const targetId of deathTargetIds(log, hasAuthoritativeDeathEvents)) {
    const dead = next.find((player) => Number(player.id) === targetId)
    if (dead) dead.alive = false
  }
  if (isSheriffLog(log)) {
    const currentSheriffId = next.find((player) => player.is_sheriff)?.id ?? null
    next = applySheriffToPlayers(next, sheriffIdAfterLog(log, currentSheriffId))
  }
  return next
}

function applyLogsToPlayers<TPlayer extends TimelinePlayer>(
  players: TPlayer[] = [],
  logs: unknown[] = [],
  hasAuthoritativeDeathEvents = true
): TPlayer[] {
  return (logs || []).reduce<TPlayer[]>(
    (nextPlayers, log) => applyLogToPlayers(nextPlayers, log, hasAuthoritativeDeathEvents),
    players || []
  )
}

export {
  AUTHORITATIVE_DEATH_EVENTS,
  FALLBACK_DEATH_EVENTS,
  NIGHT_OUTCOME_EVENTS,
  applyLogToPlayers,
  applyLogsToPlayers,
  deathTargetIds,
  eventKillsPlayer,
  eventTargetId,
  isSheriffLog,
  logType,
  nightOutcomeDeathIds,
  numericId,
  sheriffIdAfterLog
}

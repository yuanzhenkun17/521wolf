// @ts-nocheck
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

function numericId(value) {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function logType(row = {}) {
  return String(row.type || row.event_type || row.action || row.action_type || row.kind || '')
}

function payloadOf(row = {}) {
  return row.payload && typeof row.payload === 'object' && !Array.isArray(row.payload) ? row.payload : {}
}

function rowChoice(row = {}) {
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

function truthyFlag(value) {
  return value === true || value === 1 || value === '1' || String(value).toLowerCase() === 'true'
}

function payloadIdList(row = {}, keys = []) {
  const payload = payloadOf(row)
  const ids = []
  const seen = new Set()
  keys.forEach((key) => {
    const raw = payload[key] ?? row[key]
    const values = Array.isArray(raw) ? raw : (raw == null ? [] : [raw])
    values.forEach((value) => {
      const id = numericId(typeof value === 'object' && value !== null ? (value.id ?? value.player_id ?? value.seat) : value)
      if (!id || seen.has(id)) return
      seen.add(id)
      ids.push(id)
    })
  })
  return ids
}

function eventTargetId(row = {}) {
  return numericId(
    row.target_id
    ?? row.target
    ?? row.selected_target
    ?? row.payload?.target_id
    ?? row.payload?.target
    ?? row.payload?.player_id
  )
}

function isLegacyWhiteWolfExplodeKill(log = {}) {
  if (logType(log) !== 'white_wolf_explode') return false
  return ['explode', 'burst'].includes(rowChoice(log)) && Boolean(eventTargetId(log))
}

function eventKillsPlayer(log = {}, hasAuthoritativeDeathEvents = true) {
  const type = logType(log)
  if (isLegacyWhiteWolfExplodeKill(log)) return true
  if (AUTHORITATIVE_DEATH_EVENTS.has(type)) return true
  return !hasAuthoritativeDeathEvents && FALLBACK_DEATH_EVENTS.has(type)
}

function nightOutcomeDeathIds(log = {}) {
  const type = logType(log)
  if (!NIGHT_OUTCOME_EVENTS.has(type)) return []
  const payload = payloadOf(log)
  const deferredDeathReveal = truthyFlag(payload.deferred_death_reveal ?? log.deferred_death_reveal)
  if (type === 'night_end' && deferredDeathReveal) return []

  if (
    Array.isArray(payload.deaths)
    || Array.isArray(log.deaths)
    || Array.isArray(payload.death_ids)
    || Array.isArray(log.death_ids)
    || Array.isArray(payload.dead_players)
    || Array.isArray(log.dead_players)
  ) {
    return payloadIdList(log, ['deaths', 'death_ids', 'dead_players'])
  }

  const ids = []
  const killed = numericId(payload.killed_target ?? payload.killedTarget ?? log.killed_target ?? log.killedTarget)
  const protectedTarget = numericId(payload.protected_target ?? payload.protectedTarget ?? log.protected_target ?? log.protectedTarget)
  const saved = truthyFlag(payload.saved ?? payload.used_antidote ?? payload.antidote_used ?? log.saved)
  if (killed && !saved && killed !== protectedTarget) ids.push(killed)

  const poisoned = numericId(payload.poisoned_target ?? payload.poisonedTarget ?? payload.poison_target ?? payload.poisonTarget ?? log.poisoned_target)
  if (poisoned && !ids.includes(poisoned)) ids.push(poisoned)

  const target = eventTargetId(log)
  if (target && type !== 'night_end' && !ids.includes(target)) ids.push(target)
  return ids
}

function deathTargetIds(log = {}, hasAuthoritativeDeathEvents = true) {
  const ids = nightOutcomeDeathIds(log)
  if (eventKillsPlayer(log, hasAuthoritativeDeathEvents)) {
    const target = eventTargetId(log) || numericId(log.actor_id)
    if (target && !ids.includes(target)) ids.push(target)
  }
  return ids
}

function isSheriffLog(log = {}) {
  const type = logType(log)
  return SHERIFF_RESULT_EVENTS.has(type) || SHERIFF_TRANSFER_EVENTS.has(type) || SHERIFF_DESTROY_EVENTS.has(type)
}

function sheriffIdAfterLog(log = {}, currentSheriffId = null) {
  const type = logType(log)
  const payload = payloadOf(log)
  if (SHERIFF_RESULT_EVENTS.has(type)) {
    return numericId(payload.winner ?? log.target_id ?? log.actor_id) ?? currentSheriffId
  }
  if (SHERIFF_TRANSFER_EVENTS.has(type)) {
    return eventTargetId(log) ?? currentSheriffId
  }
  if (SHERIFF_DESTROY_EVENTS.has(type)) {
    return null
  }
  return currentSheriffId
}

function applySheriffToPlayers(players = [], sheriffId = null) {
  const nextSheriffId = numericId(sheriffId)
  return (players || []).map((player) => ({
    ...player,
    is_sheriff: Boolean(nextSheriffId && Number(player.id) === nextSheriffId)
  }))
}

function applyLogToPlayers(players, log, hasAuthoritativeDeathEvents = true) {
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

function applyLogsToPlayers(players, logs = [], hasAuthoritativeDeathEvents = true) {
  return (logs || []).reduce(
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

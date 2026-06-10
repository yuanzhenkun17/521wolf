<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  displayActionLabel,
  displayChoiceLabel,
  displayDayLabel,
  displayPhaseLabel,
  displayRoleLabel,
  displaySkillDirLabel,
  displaySourceLabel,
  displayWinnerLabel,
  normalizeHistoryDisplayText
} from './historyDisplay.ts'

const props = defineProps({
  archive: { type: Object, default: null },
  game: { type: Object, default: null },
  formatJson: Function
})

const selectedPlayerFilter = ref('all')
const selectedPhaseFilter = ref('all')
const selectedSignalFilter = ref('all')

const ARCHIVE_KIND_LABELS = {
  game_trace_archive: '对局轨迹档案',
  role_evolution_game_archive: '自进化样本档案',
  selfplay_game_archive: '自博弈对局档案'
}

const archiveData = computed(() => {
  const raw = props.archive
  if (!raw || raw.error) return null
  return raw.data || raw
})

const archiveEvents = computed(() => asArray(archiveData.value?.events || archiveData.value?.logs))
const archiveDecisions = computed(() => asArray(archiveData.value?.decisions))
const archiveEventCount = computed(() => archiveData.value?.event_count ?? archiveEvents.value.length)
const archiveDecisionCount = computed(() => archiveData.value?.decision_count ?? archiveDecisions.value.length)
const archiveWinner = computed(() => archiveData.value?.winner ?? archiveData.value?.verdict)
const archiveErrorCount = computed(() => {
  if (archiveData.value?.error_count != null) return Number(archiveData.value.error_count) || 0
  return archiveDecisions.value.filter(decisionHasError).length
})
const archiveFallbackCount = computed(() => {
  if (archiveData.value?.fallback_count != null) return Number(archiveData.value.fallback_count) || 0
  return archiveDecisions.value.filter(decisionHasFallback).length
})

const archiveTitle = computed(() =>
  normalizeHistoryDisplayText(archiveData.value?.title || archiveData.value?.game_id || '对局档案')
)

const archiveKindLabel = computed(() => {
  const kind = archiveData.value?.kind
  const text = normalizeHistoryDisplayText(kind)
  return ARCHIVE_KIND_LABELS[kind] || (/[\u4e00-\u9fa5]/.test(text) ? text : '') || '对局档案'
})

const archiveModeLabel = computed(() => {
  const data = archiveData.value || {}
  if (data.kind === 'role_evolution_game_archive') {
    const rawPhase = data.phase || data.config?.phase
    const rawSide = data.side || data.config?.side
    const phase = hasDisplayValue(rawPhase) ? phaseLabel(rawPhase) : ''
    const side = hasDisplayValue(rawSide) ? displayWinnerLabel(rawSide) : ''
    return [phase, side].filter(Boolean).join(' / ') || '样本局'
  }
  if (data.replay_available === false) return '未绑定回放'
  if (data.verdict && !data.winner) return '轻量档案'
  if (data.review) return '含复盘证据'
  return '完整轨迹'
})

const archiveSummary = computed(() => {
  if (archiveData.value?.summary) return formatArchiveHighlight(archiveData.value.summary)
  const winner = displayWinnerLabel(archiveWinner.value)
  return `胜方 ${winner}；公开事件 ${archiveEventCount.value} 条；决策 ${archiveDecisionCount.value} 条。`
})

const archiveIdentityChips = computed(() => {
  const data = archiveData.value || {}
  const config = safeObject(data.config)
  return [
    { label: '对局', value: data.game_id || data.id || data.history_game_id },
    { label: '运行', value: data.run_id || data.source_run_id || config.run_id },
    { label: '样本', value: sampleLabel(data.phase || config.phase, data.side || config.side) },
    { label: '回放', value: data.history_game_id || (data.replay_available === false ? data.replay_unavailable_reason : '') }
  ]
    .filter((item) => hasDisplayValue(item.value))
    .map((item) => ({ ...item, value: shortValue(item.value, 44) }))
})

const archiveHighlights = computed(() => {
  const list = archiveData.value?.highlights
  if (Array.isArray(list) && list.length) return list.map(formatArchiveHighlight).filter(Boolean).slice(0, 5)
  return archiveEvents.value
    .map(formatArchiveHighlight)
    .filter(Boolean)
    .slice(0, 5)
})

const archiveDecisionSources = computed(() => {
  const sources = archiveData.value?.decision_sources
  let rows = []
  if (sources && typeof sources === 'object' && !Array.isArray(sources)) {
    rows = Object.entries(sources).map(([source, count]) => ({ source, count: Number(count) || 0 }))
  } else if (Array.isArray(sources)) {
    rows = sources.map((item) => ({
      source: item.source || item.name || item.key || 'unknown',
      count: Number(item.count ?? item.value ?? 0) || 0
    }))
  } else {
    const tally = {}
    archiveDecisions.value.forEach((decision) => {
      const src = decision.source || decision.decision_source || 'unknown'
      tally[src] = (tally[src] || 0) + 1
    })
    rows = Object.entries(tally).map(([source, count]) => ({ source, count }))
  }
  return rows.filter((item) => item.count > 0).sort((a, b) => b.count - a.count)
})

const sourceMixRows = computed(() => {
  const rows = archiveDecisionSources.value
  const total = rows.reduce((sum, item) => sum + item.count, 0) || archiveDecisionCount.value || 0
  return rows.map((item) => {
    const percent = total ? Math.round((item.count / total) * 100) : 0
    return {
      ...item,
      kind: sourceKind(item.source),
      label: sourceLabel(item.source),
      percent,
      width: `${Math.max(5, percent)}%`
    }
  })
})

const evidenceTimelineRows = computed(() => {
  const highlights = archiveHighlights.value.slice(0, 3).map((text, index) => ({
    key: `highlight-${index}`,
    badge: '摘要',
    title: `关键记录 ${index + 1}`,
    meta: archiveKindLabel.value,
    text,
    actor: '',
    target: '',
    tone: 'highlight'
  }))
  const eventRows = archiveEvents.value
    .map(normalizeEventEvidence)
    .filter((item) => item.title || item.text)
  const notable = eventRows.filter(isNotableEvidence)
  const selectedEvents = (notable.length ? notable : eventRows).slice(0, Math.max(4, 9 - highlights.length))
  return [...highlights, ...selectedEvents].slice(0, 9)
})

const allDecisionLedgerRows = computed(() =>
  archiveDecisions.value
    .map(normalizeDecisionLedger)
    .reverse()
)

const filteredDecisionLedgerRows = computed(() =>
  allDecisionLedgerRows.value.filter((row) => {
    const playerFilter = activePlayerFilter.value
    const phaseFilter = activePhaseFilter.value
    const signalFilter = selectedSignalFilter.value
    if (playerFilter !== 'all' && row.playerFilter !== playerFilter) return false
    if (phaseFilter !== 'all' && row.phaseFilter !== phaseFilter) return false
    if (signalFilter === 'fallback' && !row.hasFallback) return false
    if (signalFilter === 'error' && !row.hasError) return false
    if (signalFilter === 'clean' && (row.hasFallback || row.hasError)) return false
    return true
  })
)

const decisionLedgerRows = computed(() =>
  filteredDecisionLedgerRows.value.slice(0, 18)
)

const ledgerHiddenCount = computed(() =>
  Math.max(0, filteredDecisionLedgerRows.value.length - decisionLedgerRows.value.length)
)

const qualityFindings = computed(() => {
  const rows = []
  asArray(archiveData.value?.errors).forEach((item, index) => {
    rows.push(normalizeQualityFinding(item, 'error', `archive-error-${index}`))
  })
  archiveDecisions.value.forEach((decision, index) => {
    if (!decisionHasError(decision) && !decisionHasFallback(decision)) return
    rows.push(normalizeQualityFinding(decision, decisionHasError(decision) ? 'error' : 'warning', `decision-${index}`))
  })
  archiveEvents.value.forEach((event, index) => {
    if (!eventHasQualitySignal(event)) return
    rows.push(normalizeQualityFinding(event, eventHasError(event) ? 'error' : 'warning', `event-${index}`))
  })
  return rows.filter((item) => item.message || item.title).slice(0, 6)
})

const qualityTone = computed(() => {
  if (archiveErrorCount.value > 0 || qualityFindings.value.some((item) => item.tone === 'error')) return 'error'
  if (archiveFallbackCount.value > 0 || qualityFindings.value.length) return 'warning'
  return 'ok'
})

const qualityTitle = computed(() => {
  if (qualityTone.value === 'error') return '需要排查'
  if (qualityTone.value === 'warning') return '存在回退'
  return '无异常'
})

const archiveCompleteness = computed(() => {
  const data = archiveData.value || {}
  const checks = [
    archiveEventCount.value > 0,
    archiveDecisionCount.value > 0,
    archiveHighlights.value.length > 0,
    sourceMixRows.value.length > 0,
    hasDisplayValue(archiveWinner.value),
    Object.keys(safeObject(data.config)).length > 0,
    playerRows.value.length > 0
  ]
  const passed = checks.filter(Boolean).length
  return Math.round((passed / checks.length) * 100)
})

const auditBriefRows = computed(() => {
  const reviewTarget = qualityTone.value === 'error'
    ? '优先复查错误决策和失败事件。'
    : qualityTone.value === 'warning'
      ? '建议抽查回退来源最高的玩家和阶段。'
      : '可以直接进入关键事件和决策账本。'
  return [
    {
      label: '档案完整度',
      value: `${archiveCompleteness.value}%`,
      note: `事件、决策、来源、配置和玩家证据覆盖 ${archiveCompleteness.value}%。`,
      tone: archiveCompleteness.value >= 86 ? 'ok' : archiveCompleteness.value >= 58 ? 'warning' : 'error'
    },
    {
      label: '关键转折',
      value: archiveHighlights.value[0] || '暂无摘要',
      note: archiveHighlights.value[1] || archiveSummary.value,
      tone: 'event'
    },
    {
      label: '复查焦点',
      value: qualityTitle.value,
      note: reviewTarget,
      tone: qualityTone.value
    }
  ]
})

const archiveNavigationRows = computed(() => [
  { id: 'casefile-overview', label: '总览', count: `${archiveCompleteness.value}%` },
  { id: 'casefile-players', label: '玩家', count: playerRows.value.length || '无' },
  { id: 'casefile-evidence', label: '证据', count: evidenceTimelineRows.value.length },
  { id: 'casefile-decisions', label: '决策', count: filteredDecisionLedgerRows.value.length },
  { id: 'casefile-quality', label: '审计', count: archiveErrorCount.value + archiveFallbackCount.value },
  { id: 'casefile-config', label: '配置', count: archiveConfigRows.value.length }
])

const archiveKpis = computed(() => [
  { label: '公开事件', value: archiveEventCount.value, tone: 'event' },
  { label: '决策记录', value: archiveDecisionCount.value, tone: 'decision' },
  { label: '来源类型', value: sourceMixRows.value.length || 0, tone: 'source' },
  { label: '错误', value: archiveErrorCount.value, tone: archiveErrorCount.value ? 'error' : 'ok' },
  { label: '回退', value: archiveFallbackCount.value, tone: archiveFallbackCount.value ? 'warning' : 'ok' }
])

const playerRows = computed(() => {
  const data = archiveData.value || {}
  const game = props.game || {}
  const config = safeObject(data.config)
  const rawPlayers = asArray(data.players || game.players)
  const stats = new Map()
  const ensureStats = (id) => {
    const key = playerFilterKey(id)
    if (!key) return null
    if (!stats.has(key)) {
      stats.set(key, {
        decisionCount: 0,
        eventCount: 0,
        voteCount: 0,
        skillCount: 0,
        fallbackCount: 0,
        errorCount: 0,
        lastPhase: '',
        lastAction: ''
      })
    }
    return stats.get(key)
  }
  archiveDecisions.value.forEach((decision) => {
    const row = ensureStats(decision.actor_id ?? decision.player_id ?? decision.seat)
    if (!row) return
    row.decisionCount += 1
    if (/vote|投票/.test(String(decision.action || decision.action_type || ''))) row.voteCount += 1
    if (/guard|seer|witch|kill|shoot|protect|check|poison|save|守|查验|女巫|狼人|猎人/.test(String(decision.action || decision.action_type || ''))) row.skillCount += 1
    if (decisionHasFallback(decision)) row.fallbackCount += 1
    if (decisionHasError(decision)) row.errorCount += 1
    row.lastPhase = phaseLabel(decision.phase)
    row.lastAction = actionLabel(decision.action || decision.action_type)
  })
  archiveEvents.value.forEach((event) => {
    const row = ensureStats(event.actor_id ?? event.player_id ?? event.seat)
    if (!row) return
    row.eventCount += 1
  })
  const deadIds = derivedDeadPlayerIds.value
  const aliveIds = derivedAlivePlayerIds.value
  const sourceRows = rawPlayers.length ? rawPlayers : derivedPlayerRows.value
  return sourceRows
    .map((player, index) => {
      const id = player.id ?? player.player_id ?? player.seat ?? index + 1
      const filter = playerFilterKey(id)
      const rowStats = stats.get(filter) || {
        decisionCount: 0,
        eventCount: 0,
        voteCount: 0,
        skillCount: 0,
        fallbackCount: 0,
        errorCount: 0,
        lastPhase: '',
        lastAction: ''
      }
      const role = displayRoleLabel(player.role || player.role_hint)
      const normalizedId = normalizedPlayerId(id)
      const alive = player.alive == null
        ? (aliveIds.size ? aliveIds.has(normalizedId) : !deadIds.has(normalizedId))
        : Boolean(player.alive)
      return {
        key: filter || `player-${index}`,
        filter,
        id,
        seat: player.seat ?? player.player_seat ?? id,
        name: player.name || player.player_name || `${player.seat ?? id}号`,
        role,
        side: roleSide(role),
        alive,
        sheriff: normalizedPlayerId(data.sheriff_id ?? config.sheriff_id ?? props.game?.sheriff_id) === normalizedId,
        ...rowStats
      }
    })
    .sort((a, b) => Number(a.seat) - Number(b.seat))
})

const playerSideGroups = computed(() => {
  const groups = [
    { key: 'wolf', label: '狼人阵营', rows: [] },
    { key: 'good', label: '好人阵营', rows: [] },
    { key: 'unknown', label: '未明身份', rows: [] }
  ]
  const byKey = new Map(groups.map((group) => [group.key, group]))
  playerRows.value.forEach((player) => {
    const group = byKey.get(player.side) || byKey.get('unknown')
    group.rows.push(player)
  })
  return groups.map((group) => ({
    ...group,
    alive: group.rows.filter((player) => player.alive).length,
    dead: group.rows.filter((player) => !player.alive).length
  }))
})

const visiblePlayerSideGroups = computed(() =>
  playerSideGroups.value.filter((group) => group.rows.length)
)

const derivedDeadPlayerIds = computed(() => {
  const data = archiveData.value || {}
  const ids = idSet(data.dead_player_ids || data.dead_players)
  archiveEvents.value.forEach((event) => {
    const type = String(event.event_type || event.type || event.action || '').toLowerCase()
    const text = String(event.message || '').toLowerCase()
    if (!/(death|dead|exile|kill|poison|shot|死亡|出局|放逐|毒|枪|袭击)/.test(`${type} ${text}`)) return
    const target = Number(event.target_id ?? event.target)
    if (Number.isFinite(target) && target > 0) ids.add(normalizedPlayerId(target))
    const seats = String(event.message || '').match(/\d+/g) || []
    seats.forEach((seat) => {
      const id = Number(seat)
      if (Number.isFinite(id) && id > 0 && id <= 20) ids.add(normalizedPlayerId(id))
    })
  })
  return ids
})

const derivedAlivePlayerIds = computed(() =>
  idSet(archiveData.value?.alive_player_ids || archiveData.value?.alive_players)
)

const derivedPlayerRows = computed(() => {
  const ids = new Set<number>()
  archiveDecisions.value.forEach((decision) => {
    const id = Number(decision.actor_id ?? decision.player_id ?? decision.seat)
    if (Number.isFinite(id) && id > 0) ids.add(id)
  })
  archiveEvents.value.forEach((event) => {
    const id = Number(event.actor_id ?? event.player_id ?? event.seat)
    if (Number.isFinite(id) && id > 0) ids.add(id)
  })
  return [...ids].sort((a, b) => a - b).map((id) => ({ id, seat: id, role_hint: '' }))
})

const playerFilterOptions = computed(() => [
  { value: 'all', label: '全部玩家' },
  ...playerRows.value.map((player) => ({
    value: player.filter,
    label: `${player.seat}号 ${player.role || '未知'}`
  }))
])

const activePlayerFilter = computed(() =>
  playerFilterOptions.value.some((item) => item.value === selectedPlayerFilter.value)
    ? selectedPlayerFilter.value
    : 'all'
)

const archivePhaseRows = computed(() => {
  const map = new Map()
  const ensure = (day, phase) => {
    const normalizedPhase = phase || 'unknown'
    const key = `d${day ?? 'x'}-${normalizedPhase}`
    if (!map.has(key)) {
      map.set(key, {
        key,
        day,
        phase: normalizedPhase,
        label: [day != null ? dayLabel(day) : '对局', phaseLabel(normalizedPhase)].join(' · '),
        events: 0,
        decisions: 0,
        signals: 0
      })
    }
    return map.get(key)
  }
  archiveEvents.value.forEach((event) => {
    const row = ensure(event.day, event.phase || event.event_phase)
    row.events += 1
    if (eventHasQualitySignal(event)) row.signals += 1
  })
  archiveDecisions.value.forEach((decision) => {
    const row = ensure(decision.day, decision.phase)
    row.decisions += 1
    if (decisionHasError(decision) || decisionHasFallback(decision)) row.signals += 1
  })
  return [...map.values()]
    .sort((a, b) => historyPhaseSort(a) - historyPhaseSort(b))
    .slice(0, 16)
})

const phaseFilterOptions = computed(() => [
  { value: 'all', label: '全部阶段' },
  ...archivePhaseRows.value.map((row) => ({ value: row.key, label: row.label }))
])

const activePhaseFilter = computed(() =>
  phaseFilterOptions.value.some((item) => item.value === selectedPhaseFilter.value)
    ? selectedPhaseFilter.value
    : 'all'
)

const signalFilterOptions = [
  { value: 'all', label: '全部决策' },
  { value: 'fallback', label: '只看回退' },
  { value: 'error', label: '只看错误' },
  { value: 'clean', label: '只看正常' }
]

const ledgerFilterSummary = computed(() => {
  const player = playerFilterOptions.value.find((item) => item.value === activePlayerFilter.value)?.label || '全部玩家'
  const phase = phaseFilterOptions.value.find((item) => item.value === activePhaseFilter.value)?.label || '全部阶段'
  const signal = signalFilterOptions.find((item) => item.value === selectedSignalFilter.value)?.label || '全部决策'
  return [player, phase, signal].join(' · ')
})

const archiveConfigRows = computed(() => {
  const data = archiveData.value || {}
  const config = safeObject(data.config)
  const roleSkillDirs = safeObject(config.role_skill_dirs || data.role_skill_dirs)
  const roleVersions = safeObject(config.role_versions || data.role_versions)
  const samplePhase = data.phase || config.phase
  const sampleSide = data.side || config.side
  return [
    { label: '胜方', value: displayWinnerLabel(archiveWinner.value) },
    { label: '随机种子', value: data.seed ?? config.seed ?? '随机' },
    { label: '最大天数', value: config.max_days ?? data.max_days ?? '默认' },
    { label: '玩家数', value: config.player_count ?? data.player_count ?? '' },
    { label: '警长规则', value: config.enable_sheriff == null ? '' : (config.enable_sheriff ? '开启' : '关闭') },
    { label: '技能目录', value: displaySkillDirLabel(config.skill_dir || data.skill_dir) },
    { label: '角色覆盖', value: Object.values(roleSkillDirs).filter(Boolean).length ? `${Object.values(roleSkillDirs).filter(Boolean).length} 个` : '无' },
    { label: '角色版本', value: Object.values(roleVersions).filter(Boolean).length ? `${Object.values(roleVersions).filter(Boolean).length} 个` : '' },
    { label: '样本阶段', value: hasDisplayValue(samplePhase) ? phaseLabel(samplePhase) : '' },
    { label: '样本侧', value: hasDisplayValue(sampleSide) ? displayWinnerLabel(sampleSide) : '' },
    { label: '绑定回放', value: data.history_game_id || (data.replay_available === false ? '缺失' : '') }
  ].filter((item) => hasDisplayValue(item.value))
})

const roleEvidenceRows = computed(() => {
  const data = archiveData.value || {}
  const config = safeObject(data.config)
  const roleSkillDirs = safeObject(config.role_skill_dirs || data.role_skill_dirs)
  const roleVersions = safeObject(config.role_versions || data.role_versions)
  const rows = []
  Object.entries(roleSkillDirs).forEach(([role, dir]) => {
    if (!hasDisplayValue(dir)) return
    rows.push({
      key: `skill-${role}`,
      label: displayRoleLabel(role),
      meta: '技能',
      value: displaySkillDirLabel(dir)
    })
  })
  Object.entries(roleVersions).forEach(([role, version]) => {
    if (!hasDisplayValue(version)) return
    rows.push({
      key: `version-${role}`,
      label: displayRoleLabel(role),
      meta: '版本',
      value: displayValue('version', version)
    })
  })
  return rows.slice(0, 10)
})

const archiveExtraFields = computed(() => {
  const data = archiveData.value
  if (!data || typeof data !== 'object') return []
  const knownKeys = new Set([
    'kind', 'schema_version', 'game_id', 'id', 'title', 'summary', 'highlights',
    'seed', 'config', 'winner', 'events', 'logs', 'decisions', 'decision_count',
    'total_decisions', 'event_count', 'error_count', 'errors', 'fallback_count',
    'fallbacks', 'decision_sources', 'review', 'agent_name', 'name', 'data', 'error',
    'run_id', 'source_run_id', 'phase', 'side', 'history_game_id', 'replay_available',
    'replay_unavailable_reason', 'verdict', 'role_skill_dirs', 'role_versions',
    'players', 'public_players', 'roster', 'sheriff_id', 'alive_player_ids',
    'dead_player_ids', 'alive_players', 'dead_players', 'view_scope', 'player_count'
  ])
  return Object.entries(data)
    .filter(([key]) => !knownKeys.has(key))
    .map(([key, value]) => ({
      key,
      label: fieldLabel(key),
      value: displayValue(key, value)
    }))
    .slice(0, 10)
})

function asArray(value) {
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object') return Object.values(value)
  return []
}

function safeObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function hasDisplayValue(value) {
  return value !== null && value !== undefined && value !== ''
}

function shortValue(value, max = 80) {
  const text = normalizeHistoryDisplayText(value)
  return text.length > max ? `${text.slice(0, max - 1)}...` : text
}

function sampleLabel(phase, side) {
  const parts = [
    hasDisplayValue(phase) ? phaseLabel(phase) : '',
    hasDisplayValue(side) ? displayWinnerLabel(side) : ''
  ].filter(Boolean)
  return parts.join(' / ')
}

function playerFilterKey(value) {
  if (value == null || value === '') return ''
  return `p-${value}`
}

function normalizedPlayerId(value) {
  if (value == null || value === '') return ''
  const num = Number(value)
  return Number.isFinite(num) ? String(num) : String(value)
}

function idSet(value) {
  return new Set(asArray(value).map(normalizedPlayerId).filter(Boolean))
}

function roleSide(role = '') {
  const text = String(role || '')
  if (/狼/.test(text) || /werewolf|wolf/i.test(text)) return 'wolf'
  if (/未知|unknown/i.test(text)) return 'unknown'
  return 'good'
}

function historyPhaseSort(row) {
  const day = Number(row.day)
  const dayValue = Number.isFinite(day) ? day * 100 : 0
  const order = {
    setup: 1,
    game_init: 1,
    night: 10,
    night_start: 10,
    night_result: 19,
    sheriff: 20,
    sheriff_election: 20,
    sheriff_result: 29,
    speech: 40,
    day_speech: 40,
    vote: 60,
    exile_vote: 60,
    pk_vote: 62,
    sheriff_vote: 64,
    result: 90,
    ended: 99,
    finished: 99
  }
  return dayValue + (order[row.phase] || 50)
}

function winnerKind(winner = '') {
  const key = String(winner || '').toLowerCase()
  if (/(wolf|werewolves|狼人)/.test(key)) return 'werewolves'
  if (/(good|village|villager|town|human|好人|村民)/.test(key)) return 'villagers'
  if (/(draw|tie|平)/.test(key)) return 'draw'
  if (/(error|fail|异常)/.test(key)) return 'error'
  return 'unknown'
}

function sourceKind(source = '') {
  const key = String(source).toLowerCase()
  if (key.includes('policy') || key.includes('skip')) return 'policy'
  if (key === 'tot' || key.includes('tree') || key === 'got' || key.includes('graph')) return 'reasoning'
  if (key.includes('fallback') || key.includes('default')) return 'fallback'
  if (key.includes('error') || key.includes('invalid') || key.includes('fail')) return 'error'
  if (key.includes('human')) return 'human'
  if (key.includes('llm') || key.includes('model')) return 'llm'
  return 'other'
}

function sourceLabel(source) {
  return displaySourceLabel(source)
}

function phaseLabel(phase) {
  return displayPhaseLabel(phase)
}

function dayLabel(day) {
  return displayDayLabel(day)
}

function actionLabel(action) {
  return displayActionLabel(action)
}

function choiceLabel(choice) {
  if (!hasDisplayValue(choice)) return ''
  const key = String(choice || '').toLowerCase()
  if (['none', 'skip', 'pass', 'no_target'].includes(key)) return displayChoiceLabel(choice)
  return displayChoiceLabel(choice)
}

function actorLabel(item) {
  const name = item?.actor_name || item?.player_name || item?.name
  if (name) return normalizeHistoryDisplayText(name)
  const value = item?.actor_id ?? item?.player_id ?? item?.seat
  if (value == null || value === '') return '系统'
  return `${value}号`
}

function playerLabel(value) {
  if (value == null || value === '') return '系统'
  return `${value}号`
}

function targetLabel(item) {
  const named = item?.target_name || item?.selected_target_name
  if (named) {
    const text = normalizeHistoryDisplayText(named)
    if (/^(无目标|无|none|no target|no_target|未选择|跳过)$/i.test(text)) return ''
    return text
  }
  const value = item?.target_id ?? item?.selected_target ?? item?.target
  if (value == null || value === '' || value === 'none' || value === 'no_target') return ''
  return playerLabel(value)
}

function confidencePercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return Math.round(Math.max(0, Math.min(num > 1 ? num : num * 100, 100)))
}

function normalizeEventEvidence(event, index) {
  const action = event?.action || event?.action_type || event?.event_type || event?.type
  const actor = actorLabel(event)
  const target = targetLabel(event)
  const meta = [
    event?.day != null ? dayLabel(event.day) : '',
    event?.phase ? phaseLabel(event.phase) : '',
    event?.source ? sourceLabel(event.source) : ''
  ].filter(Boolean).join(' · ')
  return {
    key: event?.id || event?.sequence || `event-${index}`,
    badge: event?.sequence ? `#${event.sequence}` : '事件',
    title: actionLabel(action),
    meta,
    text: formatArchiveHighlight(event?.message || event?.summary || event?.public_summary || event?.reason || ''),
    actor: actor === '系统' ? '' : actor,
    target,
    tone: eventHasError(event) ? 'error' : eventHasQualitySignal(event) ? 'warning' : 'event'
  }
}

function isNotableEvidence(row) {
  const text = `${row.title} ${row.text} ${row.meta}`.toLowerCase()
  return /(night|vote|death|result|end|sheriff|kill|exile|poison|check|shoot|警|票|死亡|胜|放逐|查验|自爆|猎人|终局)/.test(text)
}

function normalizeDecisionLedger(decision, index) {
  const choice = choiceLabel(decision.selected_choice ?? decision.choice ?? decision.selected_skill)
  const target = targetLabel(decision)
  const source = decision.source || decision.decision_source || 'unknown'
  const actorId = decision.actor_id ?? decision.player_id ?? decision.seat
  const phase = decision.phase || 'unknown'
  const day = decision.day
  const hasError = decisionHasError(decision)
  const hasFallback = decisionHasFallback(decision)
  return {
    key: decision.id || decision.decision_id || `${decision.actor_id || decision.player_id || 'd'}-${index}`,
    day: day != null ? dayLabel(day) : '未记录',
    phase: phaseLabel(phase),
    playerFilter: playerFilterKey(actorId),
    phaseFilter: `d${day ?? 'x'}-${phase}`,
    hasError,
    hasFallback,
    actor: actorLabel(decision),
    action: actionLabel(decision.action || decision.action_type || decision.selected_action),
    choice,
    target,
    source,
    sourceKind: sourceKind(source),
    sourceLabel: sourceLabel(source),
    confidence: confidencePercent(decision.confidence),
    summary: formatArchiveHighlight(decision.public_summary || decision.summary || decision.reason || decision.private_reasoning || '')
  }
}

function decisionHasError(decision) {
  const source = sourceKind(decision?.source || decision?.decision_source)
  const action = String(decision?.action || decision?.action_type || '').toLowerCase()
  const text = [
    decision?.error,
    ...asArray(decision?.errors),
    decision?.message,
    decision?.reason,
    decision?.summary
  ].map((item) => typeof item === 'object' ? JSON.stringify(item) : String(item || '')).join(' ').toLowerCase()
  return source === 'error'
    || asArray(decision?.errors).length > 0
    || hasDisplayValue(decision?.error)
    || /(invalid|error|failed|timeout|parse|exception|异常|错误|失败|超时|解析)/.test(`${action} ${text}`)
}

function decisionHasFallback(decision) {
  const source = sourceKind(decision?.source || decision?.decision_source)
  const action = String(decision?.action || decision?.action_type || '').toLowerCase()
  const text = JSON.stringify(decision || {}).toLowerCase()
  return source === 'fallback'
    || /(fallback|default_action|policy_adjusted|policy_skipped|回退|默认|兜底)/.test(`${action} ${text}`)
}

function eventHasError(event) {
  const action = String(event?.action || event?.action_type || event?.event_type || event?.type || '').toLowerCase()
  const text = JSON.stringify(event || {}).toLowerCase()
  return /(invalid|error|failed|timeout|parse|exception|agent_error|llm_error|异常|错误|失败|超时|解析)/.test(`${action} ${text}`)
}

function eventHasQualitySignal(event) {
  const action = String(event?.action || event?.action_type || event?.event_type || event?.type || '').toLowerCase()
  const text = JSON.stringify(event || {}).toLowerCase()
  return eventHasError(event) || /(fallback|default_action|policy_adjusted|policy_skipped|回退|默认|兜底)/.test(`${action} ${text}`)
}

function normalizeQualityFinding(item, tone, key) {
  const action = item?.action || item?.action_type || item?.event_type || item?.type
  const title = normalizeHistoryDisplayText(item?.title || actionLabel(action) || (tone === 'error' ? '错误记录' : '回退记录'))
  const meta = [
    item?.day != null ? dayLabel(item.day) : '',
    item?.phase ? phaseLabel(item.phase) : '',
    actorLabel(item) !== '系统' ? actorLabel(item) : ''
  ].filter(Boolean).join(' · ')
  const errors = asArray(item?.errors).map(formatArchiveHighlight).filter(Boolean).join('；')
  const message = formatArchiveHighlight(item?.message || item?.error || errors || item?.summary || item?.public_summary || item?.reason || '')
  return {
    key,
    tone,
    title,
    meta,
    message
  }
}

function fieldLabel(key) {
  const map = {
    created_at: '创建时间',
    updated_at: '更新时间',
    started_at: '开始时间',
    finished_at: '结束时间',
    run_id: '运行编号',
    source_run_id: '来源运行',
    model: '模型',
    model_name: '模型',
    player_count: '玩家数',
    mode: '模式',
    status: '状态',
    source: '来源',
    source_type: '来源类型',
    action: '动作',
    action_type: '动作',
    phase: '阶段',
    day: '天数',
    duration: '耗时',
    duration_seconds: '耗时'
  }
  return map[key] || '扩展字段'
}

function displayValue(key, value) {
  if (value == null || value === '') return ''
  if (key === 'source') return sourceLabel(value)
  if (key === 'action' || key === 'action_type') return actionLabel(value)
  if (key === 'phase') return phaseLabel(value)
  if (key === 'winner') return displayWinnerLabel(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'object') {
    const text = normalizeHistoryDisplayText(JSON.stringify(value))
    return text.length > 120 ? `${text.slice(0, 117)}...` : text
  }
  const text = normalizeHistoryDisplayText(value)
  return text.length > 120 ? `${text.slice(0, 117)}...` : text
}

function formatArchiveHighlight(item) {
  if (item == null) return ''
  if (typeof item === 'object') {
    const actor = item.actor_id ?? item.player_id
    const action = actionLabel(item.action || item.action_type || item.event_type || item.type)
    const source = item.source ? ` · ${sourceLabel(item.source)}` : ''
    const target = targetLabel(item)
    const prefix = actor != null ? `${playerLabel(actor)} ${action}` : action
    const message = item.message || item.summary || item.public_summary || item.reason || ''
    return `${prefix}${target ? ` → ${target}` : ''}${source}${message ? `：${formatArchiveHighlight(message)}` : ''}`
  }
  return normalizeHistoryDisplayText(item)
}

function jsonText(value) {
  if (props.formatJson) return props.formatJson(value)
  return JSON.stringify(value, null, 2)
}

function scrollCasefileSection(id) {
  const target = typeof document !== 'undefined' ? document.getElementById(id) : null
  target?.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' })
}
</script>

<template>
  <section class="casefile-archive-panel" aria-label="对局档案">
    <template v-if="archiveData">
      <header class="casefile-dossier">
        <div class="casefile-heading">
          <small>{{ archiveKindLabel }}</small>
          <h3>{{ archiveTitle }}</h3>
          <p>{{ archiveSummary }}</p>
          <div v-if="archiveIdentityChips.length" class="casefile-chip-row" aria-label="档案索引">
            <span v-for="chip in archiveIdentityChips" :key="chip.label" class="casefile-chip">
              <small>{{ chip.label }}</small>
              <b :title="chip.value">{{ chip.value }}</b>
            </span>
          </div>
          <div class="casefile-kpi-grid casefile-kpi-grid--dossier" aria-label="档案指标">
            <article v-for="item in archiveKpis" :key="item.label" class="casefile-kpi-card" :data-tone="item.tone">
              <small>{{ item.label }}</small>
              <b>{{ item.value }}</b>
            </article>
          </div>
        </div>
        <div class="casefile-verdict" :data-side="winnerKind(archiveWinner)">
          <small>最终裁定</small>
          <b>{{ displayWinnerLabel(archiveWinner) }}</b>
          <span>{{ archiveModeLabel }}</span>
        </div>
      </header>

      <div class="casefile-command-strip" aria-label="档案工具条">
        <nav class="casefile-nav-list" aria-label="档案章节">
          <button
            v-for="item in archiveNavigationRows"
            :key="item.id"
            type="button"
            class="casefile-nav-button"
            @click="scrollCasefileSection(item.id)"
          >
            <span>{{ item.label }}</span>
            <b>{{ item.count }}</b>
          </button>
        </nav>
        <section class="casefile-filter-stack casefile-filter-stack--command" aria-label="账本筛选">
          <label class="casefile-filter-field">
            <span>玩家</span>
            <select v-model="selectedPlayerFilter" class="casefile-select">
              <option v-for="item in playerFilterOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>
          <label class="casefile-filter-field">
            <span>阶段</span>
            <select v-model="selectedPhaseFilter" class="casefile-select">
              <option v-for="item in phaseFilterOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>
          <label class="casefile-filter-field">
            <span>信号</span>
            <select v-model="selectedSignalFilter" class="casefile-select">
              <option v-for="item in signalFilterOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>
        </section>
      </div>

      <section v-if="archivePhaseRows.length" class="casefile-phase-strip casefile-phase-strip--horizontal" aria-label="阶段索引">
        <button
          v-for="item in archivePhaseRows"
          :key="item.key"
          type="button"
          class="casefile-phase-button"
          :class="{ active: activePhaseFilter === item.key }"
          @click="selectedPhaseFilter = item.key"
        >
          <span>{{ item.label }}</span>
          <b>{{ item.events }} 事 · {{ item.decisions }} 策</b>
          <em v-if="item.signals">{{ item.signals }} 个信号</em>
        </button>
      </section>

      <div class="casefile-workbench-grid">
        <main class="casefile-main-evidence">
          <section id="casefile-overview" class="casefile-section casefile-overview-section">
            <div class="casefile-audit-brief">
              <article v-for="item in auditBriefRows" :key="item.label" class="casefile-audit-card" :data-tone="item.tone">
                <small>{{ item.label }}</small>
                <b :title="String(item.value)">{{ item.value }}</b>
                <span>{{ item.note }}</span>
              </article>
            </div>
          </section>

          <section id="casefile-evidence" class="casefile-section casefile-section--timeline">
            <header class="casefile-section-header">
              <div>
                <h4>证据链</h4>
              </div>
              <span>{{ evidenceTimelineRows.length }} 条</span>
            </header>
            <ol v-if="evidenceTimelineRows.length" class="casefile-timeline-list">
              <li
                v-for="item in evidenceTimelineRows"
                :key="item.key"
                class="casefile-timeline-item"
                :data-tone="item.tone"
              >
                <span class="casefile-timeline-dot">{{ item.badge }}</span>
                <div class="casefile-timeline-body">
                  <header>
                    <b>{{ item.title }}</b>
                    <small v-if="item.meta">{{ item.meta }}</small>
                  </header>
                  <p>{{ item.text }}</p>
                  <em v-if="item.actor || item.target">
                    <template v-if="item.actor">{{ item.actor }}</template>
                    <template v-if="item.target"> → {{ item.target }}</template>
                  </em>
                </div>
              </li>
            </ol>
            <div v-else class="casefile-clean-state">
              <b>暂无证据链</b>
              <span>当前档案没有公开事件或摘要。</span>
            </div>
          </section>

          <section id="casefile-decisions" class="casefile-section casefile-ledger-section">
            <header class="casefile-section-header">
              <div>
                <h4>决策账本</h4>
                <small>{{ ledgerFilterSummary }}</small>
              </div>
              <span>
                显示 {{ decisionLedgerRows.length }} 条<template v-if="ledgerHiddenCount">，另有 {{ ledgerHiddenCount }} 条</template>
              </span>
            </header>
            <div v-if="decisionLedgerRows.length" class="casefile-ledger" role="table" aria-label="决策账本">
              <div class="casefile-ledger-head" role="row">
                <span>行动</span>
                <span>来源</span>
                <span>置信度</span>
                <span>摘要</span>
              </div>
              <article v-for="item in decisionLedgerRows" :key="item.key" class="casefile-ledger-row" role="row">
                <div class="casefile-ledger-action">
                  <b>
                    {{ item.actor }} {{ item.action }}
                    <template v-if="item.choice"> · {{ item.choice }}</template>
                    <template v-if="item.target"> → {{ item.target }}</template>
                  </b>
                  <small>{{ item.day }} · {{ item.phase }}</small>
                </div>
                <span class="casefile-source-badge" :data-kind="item.sourceKind">{{ item.sourceLabel }}</span>
                <span class="casefile-confidence">
                  <template v-if="item.confidence != null">{{ item.confidence }}%</template>
                  <template v-else>--</template>
                </span>
                <p>{{ item.summary || '没有公开摘要，详情见原始档案。' }}</p>
              </article>
            </div>
            <div v-else class="casefile-clean-state">
              <b>暂无匹配决策</b>
              <span>当前筛选条件下没有账本记录。</span>
            </div>
          </section>
        </main>

        <aside class="casefile-context-rail" aria-label="档案上下文">
          <section id="casefile-players" class="casefile-section casefile-player-section">
            <header class="casefile-section-header">
              <div>
                <h4>玩家矩阵</h4>
              </div>
              <span>{{ playerRows.length || '无' }}</span>
            </header>
            <div v-if="playerRows.length" class="casefile-player-matrix">
              <section
                v-for="group in visiblePlayerSideGroups"
                :key="group.key"
                class="casefile-player-group"
                :data-side="group.key"
              >
                <header>
                  <b>{{ group.label }}</b>
                  <span>{{ group.alive }} 存活 · {{ group.dead }} 出局</span>
                </header>
                <button
                  v-for="player in group.rows"
                  :key="player.key"
                  type="button"
                  class="casefile-player-card"
                  :class="{ active: activePlayerFilter === player.filter }"
                  :data-side="player.side"
                  :data-status="player.alive ? 'alive' : 'dead'"
                  @click="selectedPlayerFilter = player.filter"
                >
                  <span class="casefile-player-seat">
                    {{ player.seat }}号
                    <em v-if="player.sheriff">警长</em>
                  </span>
                  <b>{{ player.role || '未知' }}</b>
                  <small>{{ player.alive ? '存活' : '出局' }} · 决策 {{ player.decisionCount }} · 事件 {{ player.eventCount }}</small>
                  <i v-if="player.fallbackCount || player.errorCount">
                    回退 {{ player.fallbackCount }} · 错误 {{ player.errorCount }}
                  </i>
                  <i v-else-if="player.lastAction">
                    {{ player.lastPhase || '阶段' }} · {{ player.lastAction }}
                  </i>
                </button>
              </section>
            </div>
            <div v-else class="casefile-clean-state">
              <b>暂无玩家矩阵</b>
              <span>档案未暴露玩家列表，已保留事件和账本证据。</span>
            </div>
          </section>

          <section id="casefile-quality" class="casefile-section casefile-quality-panel" :data-tone="qualityTone">
            <header class="casefile-section-header">
              <div>
                <h4>运行质量</h4>
              </div>
              <span>{{ qualityTitle }}</span>
            </header>
            <div class="casefile-quality-summary" :data-tone="qualityTone">
              <b>{{ qualityTitle }}</b>
              <span>错误 {{ archiveErrorCount }}，回退 {{ archiveFallbackCount }}</span>
            </div>
            <div v-if="qualityFindings.length" class="casefile-quality-list">
              <article v-for="item in qualityFindings" :key="item.key" class="casefile-quality-item" :data-tone="item.tone">
                <header>
                  <b>{{ item.title }}</b>
                  <small v-if="item.meta">{{ item.meta }}</small>
                </header>
                <p>{{ item.message || '已记录异常信号，原始详情见原始数据。' }}</p>
              </article>
            </div>
            <div v-else class="casefile-clean-state">
              <b>没有发现错误或规则回退</b>
              <span>当前档案中的决策来源、事件和错误数组未暴露异常信号。</span>
            </div>
          </section>

          <section id="casefile-config" class="casefile-section casefile-config-section">
            <header class="casefile-section-header">
              <div>
                <h4>配置证据</h4>
              </div>
              <span>{{ archiveConfigRows.length }} 项</span>
            </header>
            <div v-if="sourceMixRows.length" class="casefile-source-list">
              <div v-for="item in sourceMixRows" :key="item.source" class="casefile-source-row">
                <span class="casefile-source-badge" :data-kind="item.kind">{{ item.label }}</span>
                <div class="casefile-source-track">
                  <div class="casefile-source-fill" :data-kind="item.kind" :style="{ width: item.width }"></div>
                </div>
                <b>{{ item.count }}<small>{{ item.percent }}%</small></b>
              </div>
            </div>
            <div class="casefile-config-grid">
              <span v-for="item in archiveConfigRows" :key="item.label" class="casefile-config-item">
                <small>{{ item.label }}</small>
                <b :title="String(item.value)">{{ item.value }}</b>
              </span>
            </div>
            <div v-if="roleEvidenceRows.length" class="casefile-role-evidence">
              <span v-for="item in roleEvidenceRows" :key="item.key">
                <small>{{ item.meta }} · {{ item.label }}</small>
                <b :title="item.value">{{ item.value }}</b>
              </span>
            </div>
          </section>
        </aside>
      </div>

      <details v-if="archiveExtraFields.length" class="casefile-extra-fields">
        <summary>补充字段</summary>
        <div>
          <span v-for="field in archiveExtraFields" :key="'field-' + field.key" class="casefile-extra-item">
            <small :title="field.key">{{ field.label }}</small>
            <b :title="field.value">{{ field.value }}</b>
          </span>
        </div>
      </details>

      <details class="casefile-raw-details">
        <summary>原始数据</summary>
        <pre>{{ jsonText(archive) }}</pre>
      </details>
    </template>

    <pre v-else class="casefile-raw">{{ jsonText(archive) }}</pre>
  </section>
</template>

<style scoped>
/* Current archive workbench: logbook warm-yellow surface without wood framing. */
.casefile-archive-panel {
  --case-ink: #3a1b08;
  --case-muted: rgba(59, 28, 9, 0.68);
  --case-soft: rgba(74, 37, 15, 0.54);
  --case-line: rgba(93, 48, 17, 0.15);
  --case-line-strong: rgba(93, 48, 17, 0.26);
  --case-surface: #f2dfae;
  --case-surface-soft: rgba(255, 239, 194, 0.58);
  --case-panel: rgba(255, 244, 217, 0.72);
  --case-green: #2f7a53;
  --case-teal: #2f6d73;
  --case-red: #a94135;
  --case-amber: #b87520;
  --case-shadow: 0 5px 13px rgba(74, 38, 15, 0.1);
  display: grid;
  gap: 13px;
  min-width: 0;
  padding: 18px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 8px;
  color: var(--case-ink);
  background:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    linear-gradient(180deg, rgba(250, 233, 186, 0.98), rgba(242, 223, 174, 0.96)),
    var(--case-surface);
  box-shadow: var(--case-shadow);
  isolation: isolate;
}

.casefile-dossier,
.casefile-command-strip,
.casefile-workbench-grid,
.casefile-main-evidence,
.casefile-context-rail,
.casefile-section,
.casefile-audit-brief,
.casefile-ledger,
.casefile-quality-summary,
.casefile-raw,
.casefile-raw-details pre {
  box-sizing: border-box;
}

.casefile-dossier::before,
.casefile-phase-button::before {
  display: none !important;
  content: none !important;
}

.casefile-dossier {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 220px);
  gap: 18px;
  align-items: start;
  min-width: 0;
  min-height: 0;
  overflow: visible;
  padding: 0 0 14px;
  border: 0;
  border-bottom: 1px solid var(--case-line-strong);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.casefile-heading {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 0;
}

.casefile-heading > small,
.casefile-section-header small,
.casefile-filter-field span {
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0;
}

.casefile-heading h3 {
  overflow-wrap: anywhere;
  margin: 0;
  color: var(--case-ink);
  font-size: 25px;
  font-weight: 900;
  line-height: 1.12;
}

.casefile-heading p {
  max-width: 820px;
  margin: 0;
  color: var(--case-muted);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.55;
}

.casefile-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px 14px;
  min-width: 0;
}

.casefile-chip {
  display: inline-flex;
  align-items: baseline;
  min-width: 0;
  gap: 5px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: var(--case-muted);
  background: transparent;
}

.casefile-chip small {
  flex: 0 0 auto;
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 780;
}

.casefile-chip b {
  min-width: 0;
  overflow: hidden;
  max-width: 260px;
  color: var(--case-ink);
  font-size: 11px;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-verdict {
  display: grid;
  align-content: start;
  justify-items: start;
  gap: 5px;
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: none;
}

.casefile-verdict small {
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 820;
}

.casefile-verdict b {
  overflow-wrap: anywhere;
  color: var(--case-teal);
  font-size: 19px;
  font-weight: 900;
  line-height: 1.15;
}

.casefile-verdict span {
  color: var(--case-muted);
  font-size: 12px;
  font-weight: 720;
}

.casefile-verdict[data-side="villagers"] b {
  color: var(--case-green);
}

.casefile-verdict[data-side="werewolves"] b,
.casefile-verdict[data-side="error"] b {
  color: var(--case-red);
}

.casefile-kpi-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  min-width: 0;
}

.casefile-kpi-grid--dossier {
  margin-top: 2px;
  padding: 0;
  border: 0;
  background: transparent;
}

.casefile-kpi-card {
  display: inline-grid;
  grid-template-columns: auto auto;
  gap: 5px;
  align-items: baseline;
  min-width: 0;
  min-height: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.casefile-kpi-card small {
  order: 2;
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 760;
}

.casefile-kpi-card b {
  order: 1;
  color: var(--case-ink);
  font-size: 17px;
  font-weight: 900;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.casefile-kpi-card[data-tone="ok"] b {
  color: var(--case-green);
}

.casefile-kpi-card[data-tone="warning"] b {
  color: var(--case-amber);
}

.casefile-kpi-card[data-tone="error"] b {
  color: var(--case-red);
}

.casefile-command-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(390px, 0.75fr);
  gap: 12px;
  align-items: center;
  min-width: 0;
  padding: 0 0 12px;
  border: 0;
  border-bottom: 1px solid var(--case-line);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.casefile-nav-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  border: 0;
}

.casefile-nav-button,
.casefile-phase-button,
.casefile-player-card {
  font: inherit;
}

.casefile-nav-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  min-height: 30px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--case-muted);
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.casefile-nav-button:hover,
.casefile-nav-button:focus-visible {
  border-color: rgba(93, 48, 17, 0.26);
  color: var(--case-teal);
  background: rgba(255, 244, 207, 0.62);
  outline: none;
}

.casefile-nav-button span {
  overflow: hidden;
  font-size: 12px;
  font-weight: 820;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-nav-button b {
  min-width: 0;
  padding: 0;
  color: var(--case-soft);
  background: transparent;
  font-size: 10px;
  font-weight: 820;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.casefile-filter-stack {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.casefile-filter-stack--command {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.casefile-filter-field {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.casefile-select {
  width: 100%;
  min-width: 0;
  height: 30px;
  padding: 0 28px 0 9px;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  color: var(--case-ink);
  background: rgba(255, 252, 245, 0.82);
  font-size: 12px;
  font-weight: 720;
  outline: none;
}

.casefile-select:focus {
  border-color: rgba(47, 109, 115, 0.42);
  box-shadow: 0 0 0 2px rgba(47, 109, 115, 0.1);
}

.casefile-phase-strip--horizontal {
  display: flex;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding: 0 0 11px;
  border: 0;
  border-bottom: 1px solid var(--case-line);
  background: transparent;
  scrollbar-width: thin;
}

.casefile-phase-strip--horizontal .casefile-phase-button {
  flex: 0 0 auto;
  display: grid;
  gap: 2px;
  min-width: 116px;
  min-height: 0;
  padding: 7px 9px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--case-muted);
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.casefile-phase-strip--horizontal .casefile-phase-button:hover,
.casefile-phase-strip--horizontal .casefile-phase-button:focus-visible,
.casefile-phase-strip--horizontal .casefile-phase-button.active {
  border-color: rgba(93, 48, 17, 0.26);
  color: var(--case-teal);
  background: rgba(255, 244, 207, 0.62);
  outline: none;
}

.casefile-phase-button span,
.casefile-phase-button b,
.casefile-phase-button em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-phase-button span {
  font-size: 11px;
  font-weight: 820;
}

.casefile-phase-button b,
.casefile-phase-button em {
  color: var(--case-soft);
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
}

.casefile-phase-button em {
  color: var(--case-red);
}

.casefile-workbench-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(294px, 326px);
  gap: 18px;
  align-items: start;
  min-width: 0;
}

.casefile-main-evidence,
.casefile-context-rail {
  display: grid;
  align-content: start;
  gap: 16px;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.casefile-main-evidence {
  padding: 14px;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255, 244, 217, 0.8), rgba(250, 233, 186, 0.58));
}

.casefile-context-rail {
  padding-left: 18px;
  border-left: 1px solid var(--case-line);
}

.casefile-section {
  display: grid;
  gap: 11px;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.casefile-section + .casefile-section {
  padding-top: 16px;
  border-top: 1px solid var(--case-line);
}

.casefile-section-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 0;
  border: 0;
}

.casefile-section-header div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.casefile-section-header h4 {
  margin: 0;
  color: var(--case-ink);
  font-size: 15px;
  font-weight: 880;
  line-height: 1.2;
}

.casefile-section-header > span {
  flex: 0 0 auto;
  color: var(--case-soft);
  font-size: 11px;
  font-weight: 760;
  white-space: nowrap;
}

.casefile-audit-brief {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  background: var(--case-surface-soft);
}

.casefile-audit-card {
  display: grid;
  gap: 6px;
  min-width: 0;
  min-height: 92px;
  padding: 12px;
  border: 0;
  border-left: 3px solid rgba(93, 48, 17, 0.18);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.casefile-audit-card + .casefile-audit-card {
  border-left-width: 1px;
}

.casefile-audit-card[data-tone="ok"] {
  border-left-color: var(--case-green);
}

.casefile-audit-card[data-tone="warning"] {
  border-left-color: var(--case-amber);
}

.casefile-audit-card[data-tone="error"] {
  border-left-color: var(--case-red);
}

.casefile-audit-card[data-tone="event"] {
  border-left-color: var(--case-teal);
}

.casefile-audit-card small {
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 780;
}

.casefile-audit-card b {
  display: -webkit-box;
  overflow: hidden;
  color: var(--case-ink);
  font-size: 14px;
  font-weight: 880;
  line-height: 1.28;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.casefile-audit-card[data-tone="ok"] b {
  color: var(--case-green);
}

.casefile-audit-card[data-tone="warning"] b {
  color: var(--case-amber);
}

.casefile-audit-card[data-tone="error"] b {
  color: var(--case-red);
}

.casefile-audit-card[data-tone="event"] b {
  color: var(--case-teal);
}

.casefile-audit-card span {
  display: -webkit-box;
  overflow: hidden;
  color: var(--case-muted);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.casefile-timeline-list {
  position: relative;
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.casefile-timeline-list::before {
  position: absolute;
  top: 8px;
  bottom: 18px;
  left: 15px;
  width: 1px;
  background: rgba(93, 48, 17, 0.16);
  content: "";
}

.casefile-timeline-item {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
}

.casefile-timeline-dot {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  align-self: start;
  width: 30px;
  height: 22px;
  margin-top: 2px;
  border: 1px solid var(--case-line);
  border-radius: 7px;
  color: var(--case-muted);
  background: rgba(255, 252, 245, 0.92);
  box-shadow: none;
  font-size: 10px;
  font-weight: 780;
  white-space: nowrap;
}

.casefile-timeline-item[data-tone="highlight"] .casefile-timeline-dot {
  color: var(--case-teal);
  border-color: rgba(47, 109, 115, 0.2);
  background: rgba(230, 244, 238, 0.54);
}

.casefile-timeline-item[data-tone="error"] .casefile-timeline-dot {
  color: var(--case-red);
  border-color: rgba(169, 65, 53, 0.2);
  background: rgba(255, 236, 228, 0.54);
}

.casefile-timeline-body {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 0 0 13px;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  background: transparent;
}

.casefile-timeline-item[data-tone="highlight"] .casefile-timeline-body {
  padding: 0 0 13px;
  border-left: 0;
  background: transparent;
}

.casefile-timeline-body header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.casefile-timeline-body b {
  min-width: 0;
  overflow: hidden;
  color: var(--case-ink);
  font-size: 13px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-timeline-body small {
  min-width: 0;
  overflow: hidden;
  color: var(--case-soft);
  font-size: 11px;
  font-weight: 660;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-timeline-body p,
.casefile-ledger-row p,
.casefile-quality-item p {
  min-width: 0;
  margin: 0;
  color: var(--case-muted);
  font-size: 12px;
  font-weight: 560;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.casefile-timeline-body em {
  color: var(--case-teal);
  font-size: 11px;
  font-style: normal;
  font-weight: 760;
}

.casefile-ledger {
  display: grid;
  overflow: hidden;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  background: var(--case-panel);
}

.casefile-ledger-head,
.casefile-ledger-row {
  display: grid;
  grid-template-columns: minmax(184px, 0.92fr) minmax(82px, 0.28fr) minmax(66px, 0.18fr) minmax(180px, 1fr);
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.casefile-ledger-head {
  padding: 8px 12px;
  color: var(--case-soft);
  background: rgba(93, 48, 17, 0.06);
  font-size: 10px;
  font-weight: 820;
}

.casefile-ledger-row {
  padding: 10px 12px;
  border-top: 1px solid rgba(93, 48, 17, 0.09);
  background: transparent;
}

.casefile-ledger-row:hover {
  background: rgba(255, 244, 207, 0.34);
}

.casefile-ledger-action {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.casefile-ledger-action b {
  min-width: 0;
  overflow: hidden;
  color: var(--case-ink);
  font-size: 13px;
  font-weight: 820;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-ledger-action small {
  min-width: 0;
  overflow: hidden;
  color: var(--case-soft);
  font-size: 11px;
  font-weight: 640;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-source-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: start;
  min-width: 0;
  max-width: 100%;
  padding: 3px 7px;
  border-radius: 999px;
  color: var(--case-muted);
  background: rgba(93, 48, 17, 0.08);
  font-size: 11px;
  font-weight: 760;
  line-height: 1.2;
  text-align: center;
}

.casefile-source-badge[data-kind="llm"],
.casefile-source-badge[data-kind="reasoning"] {
  color: var(--case-teal);
  background: rgba(47, 109, 115, 0.1);
}

.casefile-source-badge[data-kind="human"] {
  color: var(--case-green);
  background: rgba(47, 122, 83, 0.1);
}

.casefile-source-badge[data-kind="fallback"],
.casefile-source-badge[data-kind="policy"] {
  color: var(--case-amber);
  background: rgba(184, 117, 32, 0.12);
}

.casefile-source-badge[data-kind="error"] {
  color: var(--case-red);
  background: rgba(169, 65, 53, 0.1);
}

.casefile-confidence {
  color: var(--case-ink);
  font-size: 12px;
  font-weight: 820;
  font-variant-numeric: tabular-nums;
}

.casefile-player-matrix {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  min-width: 0;
}

.casefile-player-group {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.casefile-player-group > header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding-bottom: 4px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.12);
}

.casefile-player-group > header b {
  color: var(--case-ink);
  font-size: 12px;
  font-weight: 840;
}

.casefile-player-group > header span {
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 650;
}

.casefile-player-group[data-side="wolf"] > header b {
  color: var(--case-red);
}

.casefile-player-group[data-side="good"] > header b {
  color: var(--case-green);
}

.casefile-player-card {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  grid-template-areas:
    "seat role"
    "seat meta"
    "seat signal";
  gap: 2px 8px;
  min-width: 0;
  min-height: 54px;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-left: 3px solid var(--case-teal);
  border-radius: 8px;
  color: var(--case-ink);
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.casefile-player-card:hover,
.casefile-player-card:focus-visible,
.casefile-player-card.active {
  border-color: rgba(47, 109, 115, 0.18);
  border-left-color: var(--case-teal);
  background: rgba(230, 244, 238, 0.48);
  outline: none;
}

.casefile-player-card[data-side="wolf"] {
  border-left-color: var(--case-red);
}

.casefile-player-card[data-side="wolf"]:hover,
.casefile-player-card[data-side="wolf"]:focus-visible,
.casefile-player-card[data-side="wolf"].active {
  border-color: rgba(169, 65, 53, 0.18);
  border-left-color: var(--case-red);
  background: rgba(255, 236, 228, 0.48);
}

.casefile-player-card[data-side="unknown"] {
  border-left-color: rgba(93, 48, 17, 0.34);
}

.casefile-player-card[data-status="dead"] {
  opacity: 0.72;
  filter: saturate(0.82);
}

.casefile-player-seat {
  grid-area: seat;
  display: grid;
  align-content: center;
  justify-content: start;
  gap: 2px;
  min-width: 0;
  color: var(--case-ink);
  font-size: 15px;
  font-weight: 880;
}

.casefile-player-seat em {
  width: fit-content;
  padding: 1px 4px;
  border-radius: 999px;
  color: var(--case-amber);
  background: rgba(184, 117, 32, 0.12);
  font-size: 9px;
  font-style: normal;
  font-weight: 780;
}

.casefile-player-card b,
.casefile-player-card small,
.casefile-player-card i {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-player-card b {
  grid-area: role;
  color: var(--case-ink);
  font-size: 13px;
  font-weight: 850;
}

.casefile-player-card small {
  grid-area: meta;
}

.casefile-player-card i {
  grid-area: signal;
}

.casefile-player-card small,
.casefile-player-card i {
  color: var(--case-muted);
  font-size: 10px;
  font-style: normal;
  font-weight: 620;
}

.casefile-quality-summary {
  display: grid;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
  padding: 10px;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  background: var(--case-surface-soft);
  overflow: hidden;
}

.casefile-quality-summary b {
  color: var(--case-green);
  font-size: 15px;
  font-weight: 860;
}

.casefile-quality-summary[data-tone="warning"] b {
  color: var(--case-amber);
}

.casefile-quality-summary[data-tone="error"] b {
  color: var(--case-red);
}

.casefile-quality-summary span,
.casefile-clean-state span {
  min-width: 0;
  color: var(--case-muted);
  font-size: 12px;
  font-weight: 560;
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.casefile-quality-list {
  display: grid;
  gap: 7px;
  min-width: 0;
  max-width: 100%;
}

.casefile-quality-item {
  display: grid;
  gap: 5px;
  min-width: 0;
  max-width: 100%;
  padding: 8px 10px;
  border: 0;
  border-left: 3px solid var(--case-amber);
  border-radius: 8px;
  background: rgba(184, 117, 32, 0.08);
  overflow: hidden;
}

.casefile-quality-item[data-tone="error"] {
  border-left-color: var(--case-red);
  background: rgba(169, 65, 53, 0.08);
}

.casefile-quality-item header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.casefile-quality-item b {
  min-width: 0;
  overflow: hidden;
  color: var(--case-ink);
  font-size: 12px;
  font-weight: 820;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-quality-item small {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 640;
  overflow-wrap: anywhere;
  text-align: right;
  word-break: break-word;
}

.casefile-source-list {
  display: grid;
  gap: 8px;
}

.casefile-source-row {
  display: grid;
  grid-template-columns: minmax(72px, 94px) minmax(0, 1fr) 56px;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.casefile-source-track {
  overflow: hidden;
  min-width: 0;
  height: 7px;
  border-radius: 999px;
  background: rgba(93, 48, 17, 0.1);
}

.casefile-source-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--case-soft);
}

.casefile-source-fill[data-kind="llm"],
.casefile-source-fill[data-kind="reasoning"] {
  background: var(--case-teal);
}

.casefile-source-fill[data-kind="human"] {
  background: var(--case-green);
}

.casefile-source-fill[data-kind="fallback"],
.casefile-source-fill[data-kind="policy"] {
  background: var(--case-amber);
}

.casefile-source-fill[data-kind="error"] {
  background: var(--case-red);
}

.casefile-source-row > b {
  color: var(--case-ink);
  font-size: 12px;
  font-weight: 820;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.casefile-source-row > b small {
  display: block;
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 640;
}

.casefile-config-grid,
.casefile-role-evidence {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
  min-width: 0;
}

.casefile-config-item,
.casefile-role-evidence span,
.casefile-extra-item {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 7px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
}

.casefile-config-item small,
.casefile-role-evidence small,
.casefile-extra-item small {
  color: var(--case-soft);
  font-size: 10px;
  font-weight: 720;
}

.casefile-config-item b,
.casefile-role-evidence b,
.casefile-extra-item b {
  min-width: 0;
  overflow: hidden;
  color: var(--case-ink);
  font-size: 12px;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.casefile-clean-state {
  display: grid;
  gap: 5px;
  padding: 10px;
  border: 1px dashed var(--case-line-strong);
  border-radius: 8px;
  background: rgba(255, 252, 243, 0.58);
}

.casefile-clean-state b {
  color: var(--case-green);
  font-size: 13px;
  font-weight: 850;
}

.casefile-extra-fields,
.casefile-raw-details {
  min-width: 0;
  padding-top: 10px;
  border-top: 1px solid var(--case-line);
}

.casefile-extra-fields summary,
.casefile-raw-details summary {
  color: var(--case-teal);
  cursor: pointer;
  font-size: 12px;
  font-weight: 820;
}

.casefile-extra-fields > div {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 8px 12px;
  margin-top: 8px;
}

.casefile-raw,
.casefile-raw-details pre {
  max-height: 280px;
  min-width: 0;
  overflow: auto;
  margin: 0;
  padding: 10px;
  border: 1px solid var(--case-line);
  border-radius: 8px;
  color: var(--case-ink);
  background: rgba(255, 252, 243, 0.68);
  box-shadow: none;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.casefile-raw-details pre {
  margin-top: 8px;
}

@media (max-width: 1180px) {
  .casefile-command-strip {
    grid-template-columns: 1fr;
  }

  .casefile-workbench-grid {
    grid-template-columns: minmax(0, 1fr) minmax(260px, 0.78fr);
  }
}

@media (max-width: 920px) {
  .casefile-archive-panel {
    padding: 14px;
  }

  .casefile-dossier,
  .casefile-workbench-grid {
    grid-template-columns: 1fr;
  }

  .casefile-verdict {
    max-width: 320px;
  }

  .casefile-context-rail {
    padding-left: 0;
    border-left: 0;
  }

  .casefile-audit-brief {
    grid-template-columns: 1fr;
  }

  .casefile-audit-card + .casefile-audit-card {
    border-top: 1px solid var(--case-line);
    border-left-width: 3px;
  }
}

@media (max-width: 720px) {
  .casefile-heading h3 {
    font-size: 20px;
  }

  .casefile-filter-stack--command,
  .casefile-config-grid,
  .casefile-role-evidence {
    grid-template-columns: 1fr;
  }

  .casefile-filter-field {
    grid-template-columns: 1fr;
  }

  .casefile-ledger-head {
    display: none;
  }

  .casefile-ledger-row {
    grid-template-columns: 1fr;
    gap: 7px;
  }

  .casefile-ledger-row p {
    display: block;
  }

  .casefile-source-row {
    grid-template-columns: minmax(0, 1fr) 54px;
  }

  .casefile-source-row .casefile-source-badge {
    grid-column: 1 / -1;
  }
}

@media (max-width: 460px) {
  .casefile-archive-panel {
    padding: 12px;
  }

  .casefile-section-header {
    align-items: start;
    flex-direction: column;
    gap: 4px;
  }

  .casefile-nav-list,
  .casefile-phase-strip--horizontal {
    gap: 4px;
  }

  .casefile-nav-button {
    padding: 0 7px;
  }
}
</style>

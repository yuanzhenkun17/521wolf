import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createGameApi } from './gameApi.js'
import { normalizeGameSnapshot } from './gameSnapshot.js'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.js'
import { createNoticeAutoDismiss } from './noticeAutoDismiss.js'
import {
  displayDayLabel,
  displayPhaseLabel,
  normalizeHistoryDisplayText
} from '../components/history/historyDisplay.js'
import { isReturnableGame, writeViewHash } from './gameSession.js'
import {
  AUTHORITATIVE_DEATH_EVENTS,
  deathTargetIds,
  eventTargetId,
  sheriffIdAfterLog
} from './gameTimeline.js'

const HISTORY_PHASE_ALIASES = {
  result: 'night',
  sheriff_election: 'sheriff',
  day_speech: 'speech',
  pk_speak: 'speech',
  finished: 'ended'
}

const HISTORY_PHASE_ORDER = [
  'setup',
  'night',
  'sheriff',
  'sheriff_vote',
  'sheriff_result',
  'speech',
  'exile_vote',
  'pk_vote',
  'vote',
  'ended'
]

const HISTORY_PHASE_RANK = new Map(HISTORY_PHASE_ORDER.map((phase, index) => [phase, index]))
const SPEECH_EVENT_TYPES = new Set([
  'speech',
  'speak',
  'talk',
  'message',
  'chat',
  'statement',
  'discussion',
  'day_speech',
  'player_speech',
  'sheriff_speak',
  'sheriff_speech',
  'pk_speak',
  'pk_speech',
  'last_word'
])
const REPLAY_VOTE_PHASES = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const REPLAY_VOTE_ACTIONS = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const REPLAY_VOTE_RESULT_EVENTS = new Set([
  'exile',
  'exile_vote_end',
  'exile_vote_tie',
  'pk_vote_end',
  'sheriff_election_end',
  'sheriff_result',
  'sheriff_vote_tie'
])
const VOTE_PHASE_BY_TYPE = {
  vote: 'exile_vote',
  exile: 'exile_vote',
  exile_vote: 'exile_vote',
  exile_vote_start: 'exile_vote',
  exile_vote_end: 'exile_vote',
  exile_vote_tie: 'exile_vote',
  pk_vote: 'pk_vote',
  pk_vote_start: 'pk_vote',
  pk_vote_end: 'pk_vote',
  sheriff_vote: 'sheriff_vote',
  sheriff_vote_tie: 'sheriff_vote'
}
const REPLAY_SPEEDS = [0.5, 1, 2, 4]
const REPLAY_BASE_INTERVAL_MS = 900
const DEFAULT_HISTORY_PAGE_SIZE = 8
const DEFAULT_PHASE_LOG_LIMIT = 300
const DEFAULT_PHASE_DECISION_LIMIT = 200
const DEFAULT_REPLAY_LIMIT = 500
const EMPTY_HISTORY_COUNTS = { all: 0, normal: 0, benchmark: 0, evolution: 0 }
const HISTORY_WORKSPACE_TABS = new Set(['phase', 'review', 'archive'])

function deleteHistoryNoticeFromError(err) {
  const message = String(err?.message || err || '').trim()
  const lower = message.toLowerCase()
  if (lower.includes('benchmark game requires force delete')) {
    return {
      type: 'warning',
      message: '批量评测对局会作为评测证据保留，普通删除不会移除。'
    }
  }
  if (lower.includes('evolution game requires force delete')) {
    return {
      type: 'warning',
      message: '自进化样本局会作为训练/对战证据保留，普通删除不会移除。'
    }
  }
  if (lower.includes('game not found')) {
    return {
      type: 'warning',
      message: '对局已不存在，已刷新历史列表。'
    }
  }
  return {
    type: 'error',
    message: message || '删除对局失败。'
  }
}

function historyLoadNotice(type, message, fallback) {
  return {
    type,
    message: String(message || '').trim() || fallback
  }
}

function normalizeHistoryWorkspaceTab(value, fallback = 'phase') {
  const text = String(value || '').trim().toLowerCase()
  return HISTORY_WORKSPACE_TABS.has(text) ? text : fallback
}

function logsHash({ gameId = '', workspace = '' } = {}) {
  const query = new URLSearchParams()
  if (gameId) query.set('game_id', String(gameId))
  const tab = normalizeHistoryWorkspaceTab(workspace, '')
  if (tab && tab !== 'phase') query.set('workspace', tab)
  const queryString = query.toString()
  return queryString ? `#logs?${queryString}` : '#logs'
}

function writeLogsHash(options = {}) {
  if (typeof window === 'undefined') return
  window.location.hash = logsHash(options)
}

function normalizeHistoryPhase(phase = 'setup') {
  return HISTORY_PHASE_ALIASES[phase] || phase || 'setup'
}

function normalizeHistoryDay(day) {
  const value = Number(day)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function historyPageSortValue(page) {
  if (!page) return 0
  const phase = normalizeHistoryPhase(page.phase)
  const rank = HISTORY_PHASE_RANK.has(phase) ? HISTORY_PHASE_RANK.get(phase) : HISTORY_PHASE_ORDER.length
  return normalizeHistoryDay(page.day) * 100 + rank
}

function historyPageKey(day, phase) {
  return `day-${normalizeHistoryDay(day)}-${normalizeHistoryPhase(phase)}`
}

function parseHistoryPageKey(key = '') {
  const match = String(key || '').match(/^day-(\d+)-(.+)$/)
  if (!match) return null
  return {
    day: normalizeHistoryDay(match[1]),
    phase: normalizeHistoryPhase(match[2])
  }
}

function numericHistoryId(value) {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function actorId(row) {
  return numericHistoryId(row?.actor_id ?? row?.player_id ?? row?.actor ?? row?.playerId ?? row?.payload?.actor_id)
}

function rowType(row = {}) {
  return String(row.type || row.event_type || row.action || row.action_type || row.kind || '').trim()
}

function voteActionPhase(row) {
  return VOTE_PHASE_BY_TYPE[rowType(row)] || ''
}

function rowHistoryPhase(row = {}, fallback = 'setup') {
  const rawPhase = normalizeHistoryPhase(row?.phase ?? fallback)
  const votePhase = voteActionPhase(row)
  if (rawPhase === 'vote' && votePhase && votePhase !== 'sheriff_vote') return votePhase
  if ((row?.phase == null || row?.phase === '') && votePhase) return votePhase
  return rawPhase
}

function votePhaseMatches(row, pagePhase) {
  const actionPhase = voteActionPhase(row)
  if (!actionPhase) return false
  const rowPhase = rowHistoryPhase(row, pagePhase)
  if (rowPhase === pagePhase) return actionPhase === pagePhase || pagePhase === 'vote'
  if (rowPhase === 'vote' && pagePhase !== 'sheriff_vote') return actionPhase === pagePhase
  return false
}

function replayVotesForPage(rows = [], page = {}) {
  const currentDay = normalizeHistoryDay(page.day)
  const currentPhase = normalizeHistoryPhase(page.phase)
  return rows.reduce((votes, row, index) => {
    if (!votePhaseMatches(row, currentPhase)) return votes
    const rowDay = normalizeHistoryDay(row.day ?? currentDay)
    if (rowDay !== currentDay) return votes
    const voterId = actorId(row)
    const targetId = numericHistoryId(eventTargetId(row))
    if (!voterId || !targetId) return votes
    votes.push({ voterId, targetId, index })
    return votes
  }, [])
}

function tallyReplayVotes(votes = []) {
  const voteByActor = new Map()
  votes.forEach((vote) => {
    voteByActor.set(vote.voterId, vote)
  })

  const grouped = new Map()
  for (const vote of voteByActor.values()) {
    if (!grouped.has(vote.targetId)) grouped.set(vote.targetId, { target_id: vote.targetId, count: 0, voter_ids: [] })
    const row = grouped.get(vote.targetId)
    row.voter_ids.push(vote.voterId)
    row.count = row.voter_ids.length
  }
  return [...grouped.values()].sort((a, b) => b.count - a.count || a.target_id - b.target_id)
}

function hasReplayVoteResultLog(logs = [], page = {}) {
  const currentDay = normalizeHistoryDay(page.day)
  const currentPhase = normalizeHistoryPhase(page.phase)
  return logs.some((log) =>
    normalizeHistoryDay(log.day ?? currentDay) === currentDay
    && (rowHistoryPhase(log, currentPhase) === currentPhase || votePhaseMatches(log, currentPhase))
    && REPLAY_VOTE_RESULT_EVENTS.has(rowType(log))
  )
}

function buildReplayVoteTally(decisions = [], page = {}, logs = [], sourceLogs = logs) {
  const currentPhase = normalizeHistoryPhase(page.phase)
  if (!REPLAY_VOTE_PHASES.has(currentPhase)) return []

  const sourceHasStructuredVoteLogs = replayVotesForPage(sourceLogs, page).length > 0
  const votes = sourceHasStructuredVoteLogs
    ? replayVotesForPage(logs, page)
    : replayVotesForPage(decisions, page)
  return tallyReplayVotes(votes)
}

function historyGamePath(gameId) {
  return encodeURIComponent(String(gameId || ''))
}

function historyGameShellPath(gameId) {
  return `${historyGamePath(gameId)}?view=history-shell`
}

function historyGamePhasePath(gameId, page, pagination = {}) {
  const params = new URLSearchParams()
  params.set('day', String(normalizeHistoryDay(page?.day)))
  params.set('phase', normalizeHistoryPhase(page?.phase))
  params.set('log_offset', String(Math.max(0, Number(pagination.log_offset ?? 0) || 0)))
  params.set('log_limit', String(Math.max(1, Number(pagination.log_limit ?? DEFAULT_PHASE_LOG_LIMIT) || DEFAULT_PHASE_LOG_LIMIT)))
  params.set('decision_offset', String(Math.max(0, Number(pagination.decision_offset ?? 0) || 0)))
  params.set('decision_limit', String(Math.max(1, Number(pagination.decision_limit ?? DEFAULT_PHASE_DECISION_LIMIT) || DEFAULT_PHASE_DECISION_LIMIT)))
  return `${historyGamePath(gameId)}/phase?${params.toString()}`
}

function historyGameReplayPath(gameId, { cursor = 0, limit = DEFAULT_REPLAY_LIMIT } = {}) {
  const params = new URLSearchParams()
  params.set('cursor', String(Math.max(0, Number(cursor) || 0)))
  params.set('limit', String(Math.max(1, Number(limit) || DEFAULT_REPLAY_LIMIT)))
  return `${historyGamePath(gameId)}/replay?${params.toString()}`
}

function historyGameFlowDataPath(gameId) {
  return `${historyGamePath(gameId)}/flow-data`
}

function createPagination(limit) {
  return {
    total: 0,
    offset: 0,
    limit,
    returned: 0,
    has_more: false
  }
}

function paginationFromResponse(data, rows, { offset, limit }) {
  const raw = data?.pagination || {}
  const returned = Number(raw.returned ?? rows.length ?? 0)
  const total = Number(raw.total ?? (offset + returned))
  return {
    total: Number.isFinite(total) ? total : rows.length,
    offset: Number(raw.offset ?? offset) || 0,
    limit: raw.limit == null ? limit : Number(raw.limit),
    returned: Number.isFinite(returned) ? returned : rows.length,
    has_more: Boolean(raw.has_more)
  }
}

function historyCountsFromResponse(data, rows) {
  const raw = data?.counts || data?.facets?.source || {}
  return {
    ...EMPTY_HISTORY_COUNTS,
    ...Object.fromEntries(
      Object.entries(raw)
        .filter(([key]) => key)
        .map(([key, value]) => [key, Number(value) || 0])
    ),
    all: Number(raw.all ?? data?.pagination?.total ?? rows.length ?? 0) || 0
  }
}

function historyFacetsFromResponse(data, counts) {
  const raw = data?.facets && typeof data.facets === 'object' ? data.facets : {}
  return {
    ...raw,
    source: {
      ...counts,
      ...(raw.source && typeof raw.source === 'object' ? raw.source : {})
    }
  }
}

function mergeHistoryGames(existing, incoming) {
  const seen = new Set()
  return [...existing, ...incoming].filter((game) => {
    const key = String(game?.game_id || '')
    if (!key) return true
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function historyPageFromSummary(summary = {}, index = 0) {
  const parsed = parseHistoryPageKey(summary.key || summary.phase_key)
  const day = normalizeHistoryDay(summary.day ?? summary.day_number ?? parsed?.day ?? 1)
  const phase = normalizeHistoryPhase(summary.phase ?? summary.name ?? parsed?.phase ?? 'setup')
  const key = String(summary.key || summary.phase_key || historyPageKey(day, phase))
  return {
    ...summary,
    key,
    day,
    phase,
    title: summary.title || '',
    log_count: Number(summary.log_count ?? summary.logs_count ?? summary.event_count ?? summary.events_count ?? 0) || 0,
    decision_count: Number(summary.decision_count ?? summary.decisions_count ?? 0) || 0,
    index
  }
}

function historyPagesFromRows(logs = [], decisions = [], source = {}) {
  const map = new Map()
  const ensurePage = (day, phase) => {
    const normalizedDay = normalizeHistoryDay(day)
    const normalizedPhase = normalizeHistoryPhase(phase)
    const key = historyPageKey(normalizedDay, normalizedPhase)
    if (!map.has(key)) {
      map.set(key, {
        key,
        day: normalizedDay,
        phase: normalizedPhase,
        title: '',
        log_count: 0,
        decision_count: 0
      })
    }
    return map.get(key)
  }

  ensurePage(1, 'setup')
  logs.forEach((log) => {
    const page = ensurePage(log.day, rowHistoryPhase(log))
    page.log_count += 1
  })
  decisions.forEach((decision) => {
    const page = ensurePage(decision.day, rowHistoryPhase(decision))
    page.decision_count += 1
  })
  if (source?.winner) {
    const maxObservedDay = Math.max(
      1,
      ...logs.map((log) => normalizeHistoryDay(log.day)),
      ...decisions.map((decision) => normalizeHistoryDay(decision.day)),
      normalizeHistoryDay(source.day)
    )
    ensurePage(maxObservedDay, 'ended')
  }
  return [...map.values()]
    .sort((a, b) => historyPageSortValue(a) - historyPageSortValue(b) || String(a.key).localeCompare(String(b.key)))
    .map((page, index) => ({ ...page, index }))
}

function historyPagesFromShell(source = {}) {
  const explicitPages = source.phases || source.history_pages || source.phase_index || source.pages
  if (Array.isArray(explicitPages) && explicitPages.length) {
    return explicitPages
      .map(historyPageFromSummary)
      .sort((a, b) => historyPageSortValue(a) - historyPageSortValue(b) || String(a.key).localeCompare(String(b.key)))
      .map((page, index) => ({ ...page, index }))
  }
  const logs = Array.isArray(source.logs) ? source.logs : (Array.isArray(source.events) ? source.events : [])
  const decisions = Array.isArray(source.decisions) ? source.decisions : []
  return historyPagesFromRows(logs, decisions, source)
}

function historyPageTotals(pages = [], field) {
  return pages.reduce((total, page) => total + (Number(page?.[field]) || 0), 0)
}

function phaseDetailKey(page = {}) {
  return String(page.key || historyPageKey(page.day, page.phase))
}

function phaseRequestKey(gameId, page) {
  return `${gameId}:${phaseDetailKey(page)}`
}

function phaseFetchKey(gameId, page, pagination = {}) {
  return [
    phaseRequestKey(gameId, page),
    Number(pagination.log_offset ?? 0) || 0,
    Number(pagination.log_limit ?? DEFAULT_PHASE_LOG_LIMIT) || DEFAULT_PHASE_LOG_LIMIT,
    Number(pagination.decision_offset ?? 0) || 0,
    Number(pagination.decision_limit ?? DEFAULT_PHASE_DECISION_LIMIT) || DEFAULT_PHASE_DECISION_LIMIT
  ].join(':')
}

function phasePagePagination(raw = {}, rows = [], fallback = {}) {
  const returned = Number(raw.returned ?? rows.length ?? 0)
  const offset = Math.max(0, Number(raw.offset ?? fallback.offset ?? 0) || 0)
  const limit = Math.max(1, Number(raw.limit ?? fallback.limit ?? rows.length ?? 1) || 1)
  const total = Number(raw.total ?? fallback.total ?? (offset + returned))
  return {
    total: Number.isFinite(total) ? total : rows.length,
    offset,
    limit,
    returned: Number.isFinite(returned) ? returned : rows.length,
    has_more: Boolean(raw.has_more)
  }
}

function phasePaginationFromResponse(raw = {}, logs = [], decisions = {}, request = {}) {
  const pagination = raw?.pagination && typeof raw.pagination === 'object' ? raw.pagination : {}
  const logRows = Array.isArray(logs) ? logs : []
  const decisionRows = Array.isArray(decisions) ? decisions : []
  return {
    logs: phasePagePagination(pagination.logs, logRows, {
      offset: request.log_offset ?? 0,
      limit: request.log_limit ?? DEFAULT_PHASE_LOG_LIMIT,
      total: raw?.summary?.log_count
    }),
    decisions: phasePagePagination(pagination.decisions, decisionRows, {
      offset: request.decision_offset ?? 0,
      limit: request.decision_limit ?? DEFAULT_PHASE_DECISION_LIMIT,
      total: raw?.summary?.decision_count
    })
  }
}

function pageWithPhaseDetail(page, detail) {
  if (!detail) return { ...page, logs: page.logs || [], decisions: page.decisions || [], pagination: page.pagination || null, loaded: Boolean(page.loaded) }
  return {
    ...page,
    loaded: true,
    log_count: Number(page.log_count ?? detail.summary?.log_count ?? detail.pagination?.logs?.total ?? detail.logs.length) || detail.logs.length,
    decision_count: Number(page.decision_count ?? detail.summary?.decision_count ?? detail.pagination?.decisions?.total ?? detail.decisions.length) || detail.decisions.length,
    logs: detail.logs,
    decisions: detail.decisions,
    summary: detail.summary || page.summary || {},
    pagination: detail.pagination || page.pagination || null
  }
}

function historyPhaseDetailsObject(cache) {
  return Object.fromEntries([...cache.entries()])
}

function replayEventIdentity(row = {}) {
  const stable = row.id ?? row.event_id ?? row.idx ?? row.sequence
  if (stable != null) return String(stable)
  return [
    row.day ?? '',
    row.phase ?? '',
    row.event_type || row.type || row.action || '',
    row.actor_id ?? row.player_id ?? '',
    row.target_id ?? '',
    row.message || row.content || row.text || row.public_summary || ''
  ].join(':')
}

function replayDecisionIdentity(row = {}) {
  const stable = row.id ?? row.decision_id
  if (stable != null) return String(stable)
  return [
    row.day ?? '',
    row.phase ?? '',
    row.action || row.action_type || '',
    row.actor_id ?? row.player_id ?? '',
    row.target_id ?? row.selected_target ?? '',
    row.public_summary || row.reason || row.message || row.text || ''
  ].join(':')
}

function mergeReplayEvents(existingRows = [], chunkRows = [], cursor = null) {
  const base = Array.isArray(existingRows) ? [...existingRows] : []
  const rows = Array.isArray(chunkRows) ? chunkRows : []
  const offset = Number(cursor)
  if (Number.isFinite(offset) && offset >= 0) {
    rows.forEach((row, index) => {
      base[offset + index] = row
    })
  } else {
    base.push(...rows)
  }

  const seen = new Set()
  return base.filter(Boolean).filter((row) => {
    const key = replayEventIdentity(row)
    if (!key) return true
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function mergeReplayDecisions(existingRows = [], chunkRows = []) {
  const seen = new Set()
  return [...(Array.isArray(existingRows) ? existingRows : []), ...(Array.isArray(chunkRows) ? chunkRows : [])]
    .filter(Boolean)
    .filter((row) => {
      const key = replayDecisionIdentity(row)
      if (!key) return true
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function normalizeHistoryShell(raw = {}, cache = new Map()) {
  const pages = historyPagesFromShell(raw)
  const normalized = normalizeGameSnapshot({
    ...raw,
    logs: [],
    events: [],
    decisions: [],
    phases: pages,
    history_pages: pages
  }, { mode: 'watch' })
  const pagesWithCachedDetails = pages.map((page) => pageWithPhaseDetail(page, cache.get(page.key)))
  return {
    ...normalized,
    logs: [],
    events: [],
    decisions: [],
    event_count: Number(raw.event_count ?? raw.log_count ?? raw.events_count ?? historyPageTotals(pages, 'log_count')) || 0,
    decision_count: Number(raw.decision_count ?? raw.decisions_count ?? historyPageTotals(pages, 'decision_count')) || 0,
    phases: pagesWithCachedDetails,
    history_pages: pagesWithCachedDetails,
    __historyPages: pagesWithCachedDetails,
    __phaseDetails: historyPhaseDetailsObject(cache),
    __activePhaseKey: '',
    __detailView: raw.detail_view || raw.detailView || 'history-shell'
  }
}

function normalizePhaseDetail(raw = {}, page = {}, shell = {}, request = {}) {
  const logs = Array.isArray(raw.logs)
    ? raw.logs
    : (Array.isArray(raw.events) ? raw.events : [])
  const decisions = Array.isArray(raw.decisions) ? raw.decisions : []
  const normalized = normalizeGameSnapshot({
    ...shell,
    ...raw,
    game_id: raw.game_id || shell.game_id,
    players: raw.players || shell.players || [],
    day: raw.day ?? page.day,
    phase: raw.phase ?? page.phase,
    logs,
    events: logs,
    decisions
  }, { mode: 'watch' })
  const day = normalizeHistoryDay(raw.day ?? page.day)
  const phase = normalizeHistoryPhase(raw.phase ?? page.phase)
  return {
    key: String(raw.key || raw.phase_key || page.key || historyPageKey(day, phase)),
    day,
    phase,
    logs: normalized.logs || [],
    decisions: normalized.decisions || [],
    summary: raw.summary || {},
    pagination: phasePaginationFromResponse(raw, normalized.logs || [], normalized.decisions || [], request),
    loaded_at: Date.now()
  }
}

function useGameHistory(state, options = {}) {
  const { apiFetch } = options.apiFetch ? { apiFetch: options.apiFetch } : createGameApi(options.apiBase)
  let actionApi = options.actionApi || {}
  let sceneApi = options.sceneApi || {}
  let replayTimer = null
  let replayAdvancePending = false
  const logOpenRequests = createLatestOnlyTracker()
  const historySelectionRequests = createLatestOnlyTracker()
  const historyListRequests = createLatestOnlyTracker()
  const historyPhaseRequests = createLatestOnlyMap()
  const replayStartRequests = createLatestOnlyTracker()
  const replayCursorRequests = createLatestOnlyTracker()
  const replayRequests = createLatestOnlyMap()
  const flowDataRequests = createLatestOnlyMap()
  const archiveRequests = createLatestOnlyMap()
  const reviewRequests = createLatestOnlyMap()
  const phaseDetailCacheByGameId = new Map()
  const phaseDetailPromises = new Map()
  const replaySourceByGameId = new Map()
  const replaySourcePromises = new Map()
  const replayChunkPromises = new Map()
  const replayChunkRequestKeysByGameId = new Map()
  const replayCacheVersionsByGameId = new Map()
  const flowDataPromises = new Map()
  let historyListLoaded = false
  const historyPageSize = Math.max(1, Number(options.historyListLimit || DEFAULT_HISTORY_PAGE_SIZE))
  const historyPagination = ref(createPagination(historyPageSize))
  const historyLoadingMore = ref(false)
  const historySourceFilter = ref('all')
  const historyStatusFilter = ref('all')
  const historyCounts = ref({ ...EMPTY_HISTORY_COUNTS })
  const historyFacets = ref({ source: { ...EMPTY_HISTORY_COUNTS }, status: {} })
  const historyNotice = ref({ type: '', message: '' })
  const noticeAutoDismiss = createNoticeAutoDismiss(historyNotice, {
    enabled: options.installLifecycle !== false,
    onDismiss(notice) {
      if (notice.type !== 'error' && state.error.value === notice.message) state.error.value = ''
    }
  })
  const historyHasMore = computed(() => Boolean(historyPagination.value.has_more))
  const historyCurrentPage = computed(() => {
    const limit = Math.max(1, Number(historyPagination.value.limit || historyPageSize))
    const offset = Math.max(0, Number(historyPagination.value.offset || 0))
    return Math.max(1, Math.floor(offset / limit) + 1)
  })
  const historyTotalPages = computed(() => {
    const limit = Math.max(1, Number(historyPagination.value.limit || historyPageSize))
    const total = Math.max(0, Number(historyPagination.value.total || 0))
    return Math.max(1, Math.ceil(total / limit))
  })

  function setActionApi(api = {}) {
    actionApi = api || {}
  }

  function setSceneApi(api = {}) {
    sceneApi = api || {}
  }

  function clearHistoryNotice() {
    historyNotice.value = { type: '', message: '' }
  }

  function setReplayLoadError(err, fallback = '回放数据读取失败，请重试。') {
    const notice = historyLoadNotice('error', err?.message, fallback)
    historyNotice.value = notice
    state.error.value = notice.message
    return notice
  }

  function replayCacheVersion(gameId) {
    return Number(replayCacheVersionsByGameId.get(String(gameId || '')) || 0)
  }

  function bumpReplayCacheVersion(gameId) {
    const key = String(gameId || '')
    if (!key) return
    replayCacheVersionsByGameId.set(key, replayCacheVersion(key) + 1)
    const chunkKeys = replayChunkRequestKeysByGameId.get(key) || new Set()
    chunkKeys.forEach((chunkKey) => replayRequests.invalidate(chunkKey))
    replayChunkRequestKeysByGameId.delete(key)
    replaySourcePromises.delete(key)
    ;[...replayChunkPromises.keys()]
      .filter((chunkKey) => chunkKey.startsWith(`${key}:`))
      .forEach((chunkKey) => replayChunkPromises.delete(chunkKey))
  }

  function rememberReplayChunkRequest(gameId, chunkKey) {
    const key = String(gameId || '')
    if (!replayChunkRequestKeysByGameId.has(key)) replayChunkRequestKeysByGameId.set(key, new Set())
    replayChunkRequestKeysByGameId.get(key).add(chunkKey)
  }

  function phaseCacheForGame(gameId) {
    const key = String(gameId || '')
    if (!phaseDetailCacheByGameId.has(key)) phaseDetailCacheByGameId.set(key, new Map())
    return phaseDetailCacheByGameId.get(key)
  }

  function syncPhaseCacheState(gameId) {
    const key = String(gameId || '')
    if (!key) return
    state.phaseDetailByGameId.value = {
      ...state.phaseDetailByGameId.value,
      [key]: historyPhaseDetailsObject(phaseCacheForGame(key))
    }
  }

  function setPhaseLoading(requestKey, loading) {
    state.phaseLoadingByKey.value = {
      ...state.phaseLoadingByKey.value,
      [requestKey]: Boolean(loading)
    }
  }

  function setPhaseError(requestKey, message = '') {
    state.phaseErrorByKey.value = {
      ...state.phaseErrorByKey.value,
      [requestKey]: String(message || '')
    }
  }

  function selectedHistoryPages() {
    const source = state.selectedHistoryGame.value
    const pages = source?.__historyPages || source?.history_pages || source?.phases
    return Array.isArray(pages) ? pages : []
  }

  function findHistoryPageByKey(key) {
    const pages = selectedHistoryPages()
    const parsed = parseHistoryPageKey(key)
    return pages.find((page) => page.key === key)
      || (parsed ? pages.find((page) =>
        normalizeHistoryDay(page.day) === parsed.day
        && normalizeHistoryPhase(page.phase) === parsed.phase
      ) : null)
      || parsed
  }

  function applyHistoryGameView(gameId, activePageKey = state.selectedHistoryPageKey.value) {
    const key = String(gameId || '')
    const source = state.selectedHistoryGame.value
    if (!key || !source || String(source.game_id || '') !== key) return null

    const cache = phaseCacheForGame(key)
    const basePages = historyPagesFromShell({
      ...source,
      phases: source.__historyPages || source.history_pages || source.phases
    })
    const pages = basePages.map((page) => pageWithPhaseDetail(page, cache.get(page.key)))
    const activeKey = activePageKey || pages[0]?.key || ''
    const activeDetail = activeKey ? cache.get(activeKey) : null
    const activePage = pages.find((page) => page.key === activeKey)
    state.selectedHistoryGame.value = {
      ...source,
      logs: activeDetail?.logs || [],
      events: activeDetail?.logs || [],
      decisions: activeDetail?.decisions || [],
      day: activeDetail?.day ?? activePage?.day ?? source.day,
      phase: activeDetail?.phase ?? activePage?.phase ?? source.phase,
      sheriff_id: activePage?.sheriff_id ?? activePage?.state_after?.sheriff_id ?? source.sheriff_id,
      phases: pages,
      history_pages: pages,
      __historyPages: pages,
      __phaseDetails: historyPhaseDetailsObject(cache),
      __activePhaseKey: activeKey
    }
    state.selectedPhaseDetail.value = activeDetail || null
    syncPhaseCacheState(key)
    return state.selectedHistoryGame.value
  }

  async function fetchHistoryPhaseDetail(gameId, page, pagination = {}) {
    const key = phaseFetchKey(gameId, page, pagination)
    if (phaseDetailPromises.has(key)) return phaseDetailPromises.get(key)
    const promise = apiFetch(`/games/${historyGamePhasePath(gameId, page, pagination)}`)
      .finally(() => {
        phaseDetailPromises.delete(key)
      })
    phaseDetailPromises.set(key, promise)
    return promise
  }

  async function ensureHistoryPhaseDetail(gameId = state.selectedHistoryGameId.value, pageOrKey = state.selectedHistoryPageKey.value, { setLoading = false } = {}) {
    const key = String(gameId || '')
    if (!key) return null
    const page = typeof pageOrKey === 'string' ? findHistoryPageByKey(pageOrKey) : pageOrKey
    if (!page) return null
    const pageKey = phaseDetailKey(page)
    const cache = phaseCacheForGame(key)
    const cached = cache.get(pageKey)
    if (cached) {
      if (String(state.selectedHistoryGameId.value || '') === key) applyHistoryGameView(key, pageKey)
      return cached
    }

    const requestKey = phaseRequestKey(key, page)
    const token = historyPhaseRequests.next(requestKey)
    setPhaseLoading(requestKey, true)
    setPhaseError(requestKey, '')
    if (setLoading) state.historyLoading.value = true
    try {
      const initialPagination = {
        log_offset: 0,
        log_limit: DEFAULT_PHASE_LOG_LIMIT,
        decision_offset: 0,
        decision_limit: DEFAULT_PHASE_DECISION_LIMIT
      }
      const raw = await fetchHistoryPhaseDetail(key, page, initialPagination)
      if (!token.isLatest()) return null
      const shell = state.selectedHistoryGame.value?.game_id === key ? state.selectedHistoryGame.value : {}
      const detail = normalizePhaseDetail(raw, page, shell, initialPagination)
      cache.set(pageKey, detail)
      syncPhaseCacheState(key)
      if (
        String(state.selectedHistoryGameId.value || '') === key
        && String(state.selectedHistoryGame.value?.game_id || '') === key
      ) {
        const currentKey = state.selectedHistoryPageKey.value || pageKey
        if (currentKey === pageKey) applyHistoryGameView(key, pageKey)
        else applyHistoryGameView(key, currentKey)
      }
      return detail
    } catch (err) {
      if (
        token.isLatest()
        && String(state.selectedHistoryGameId.value || '') === key
        && (state.selectedHistoryPageKey.value || pageKey) === pageKey
      ) {
        const notice = historyLoadNotice('error', err?.message, '历史阶段详情读取失败，请重试。')
        historyNotice.value = notice
        state.error.value = notice.message
        setPhaseError(requestKey, notice.message)
      }
      return null
    } finally {
      if (token.isLatest()) setPhaseLoading(requestKey, false)
      if (
        setLoading
        && token.isLatest()
        && String(state.selectedHistoryGameId.value || '') === key
        && (state.selectedHistoryPageKey.value || pageKey) === pageKey
      ) {
        state.historyLoading.value = false
      }
    }
  }

  async function loadMoreHistoryPhaseDetail(gameId = state.selectedHistoryGameId.value, pageOrKey = state.selectedHistoryPageKey.value) {
    const key = String(gameId || '')
    if (!key) return null
    const page = typeof pageOrKey === 'string' ? findHistoryPageByKey(pageOrKey) : pageOrKey
    if (!page) return null
    const pageKey = phaseDetailKey(page)
    const cache = phaseCacheForGame(key)
    const cached = cache.get(pageKey)
    if (!cached) return ensureHistoryPhaseDetail(key, page, { setLoading: false })

    const logPage = cached.pagination?.logs || {}
    const decisionPage = cached.pagination?.decisions || {}
    const needsLogs = Boolean(logPage.has_more)
    const needsDecisions = Boolean(decisionPage.has_more)
    if (!needsLogs && !needsDecisions) return cached

    const requestPagination = {
      log_offset: needsLogs ? (Number(logPage.offset || 0) + Number(logPage.returned || cached.logs.length || 0)) : Number(logPage.offset || 0),
      log_limit: needsLogs ? Number(logPage.limit || DEFAULT_PHASE_LOG_LIMIT) : 1,
      decision_offset: needsDecisions ? (Number(decisionPage.offset || 0) + Number(decisionPage.returned || cached.decisions.length || 0)) : Number(decisionPage.offset || 0),
      decision_limit: needsDecisions ? Number(decisionPage.limit || DEFAULT_PHASE_DECISION_LIMIT) : 1
    }
    const requestKey = phaseFetchKey(key, page, requestPagination)
    const token = historyPhaseRequests.next(requestKey)
    setPhaseLoading(phaseRequestKey(key, page), true)
    setPhaseError(phaseRequestKey(key, page), '')
    try {
      const raw = await fetchHistoryPhaseDetail(key, page, requestPagination)
      if (!token.isLatest()) return null
      const shell = state.selectedHistoryGame.value?.game_id === key ? state.selectedHistoryGame.value : {}
      const nextDetail = normalizePhaseDetail(raw, page, shell, requestPagination)
      const merged = {
        ...cached,
        logs: needsLogs ? [...cached.logs, ...nextDetail.logs] : cached.logs,
        decisions: needsDecisions ? [...cached.decisions, ...nextDetail.decisions] : cached.decisions,
        summary: { ...cached.summary, ...nextDetail.summary },
        pagination: {
          logs: needsLogs ? nextDetail.pagination.logs : logPage,
          decisions: needsDecisions ? nextDetail.pagination.decisions : decisionPage
        },
        loaded_at: Date.now()
      }
      cache.set(pageKey, merged)
      syncPhaseCacheState(key)
      if (
        String(state.selectedHistoryGameId.value || '') === key
        && String(state.selectedHistoryGame.value?.game_id || '') === key
      ) {
        applyHistoryGameView(key, state.selectedHistoryPageKey.value || pageKey)
      }
      return merged
    } catch (err) {
      if (token.isLatest()) {
        const notice = historyLoadNotice('error', err?.message, '更多阶段记录读取失败，请重试。')
        historyNotice.value = notice
        state.error.value = notice.message
        setPhaseError(phaseRequestKey(key, page), notice.message)
      }
      return null
    } finally {
      if (token.isLatest()) setPhaseLoading(phaseRequestKey(key, page), false)
    }
  }

  function normalizeReplaySource(raw = {}, gameId = '', existing = null) {
    const payload = raw?.game || raw?.replay || raw?.data || raw
    const chunkLogs = Array.isArray(payload.logs) ? payload.logs : (Array.isArray(payload.events) ? payload.events : [])
    const existingLogs = replayEvents(existing)
    const existingDecisions = Array.isArray(existing?.decisions) ? existing.decisions : []
    const mergedLogs = existing
      ? mergeReplayEvents(existingLogs, chunkLogs, payload.cursor)
      : mergeReplayEvents([], chunkLogs, payload.cursor)
    const chunkDecisions = Array.isArray(payload.decisions) ? payload.decisions : []
    const mergedDecisions = existing
      ? mergeReplayDecisions(existingDecisions, chunkDecisions)
      : mergeReplayDecisions([], chunkDecisions)
    const eventTotal = Number(payload.event_count ?? payload.total ?? existing?.__replayEventTotal ?? mergedLogs.length)
    const safeLimit = Number(payload.limit ?? existing?.__replayLimit ?? DEFAULT_REPLAY_LIMIT) || DEFAULT_REPLAY_LIMIT
    const nextCursor = Number(payload.next_cursor ?? (Number(payload.cursor || 0) + chunkLogs.length))
    return normalizeGameSnapshot({
      ...(existing || {}),
      ...payload,
      game_id: payload.game_id || gameId,
      logs: mergedLogs,
      events: mergedLogs,
      decisions: mergedDecisions,
      event_count: Number.isFinite(eventTotal) ? eventTotal : mergedLogs.length,
      __replayEventTotal: Number.isFinite(eventTotal) ? eventTotal : mergedLogs.length,
      __replayCursor: Number(payload.cursor ?? existing?.__replayCursor ?? 0) || 0,
      __replayLimit: safeLimit,
      __replayNextCursor: Number.isFinite(nextCursor) ? nextCursor : mergedLogs.length,
      __replayHasMore: Boolean(payload.has_more),
      __replayLoaded: mergedLogs.length
    }, { mode: 'watch' })
  }

  async function loadReplayChunk(gameId, { cursor = 0, limit = DEFAULT_REPLAY_LIMIT, background = false } = {}) {
    const key = String(gameId || '')
    if (!key) return null
    const safeCursor = Math.max(0, Number(cursor) || 0)
    const safeLimit = Math.max(1, Number(limit) || DEFAULT_REPLAY_LIMIT)
    const chunkKey = `${key}:${safeCursor}:${safeLimit}`
    if (replayChunkPromises.has(chunkKey)) return replayChunkPromises.get(chunkKey)
    rememberReplayChunkRequest(key, chunkKey)
    const token = replayRequests.next(chunkKey)
    const cacheVersion = replayCacheVersion(key)
    state.replayLoadingByGameId.value = { ...state.replayLoadingByGameId.value, [key]: true }
    const promise = apiFetch(`/games/${historyGameReplayPath(key, { cursor: safeCursor, limit: safeLimit })}`)
      .then((raw) => {
        if (!token.isLatest() || replayCacheVersion(key) !== cacheVersion) return null
        const existing = replaySourceByGameId.get(key) || null
        const source = normalizeReplaySource(raw, key, existing)
        replaySourceByGameId.set(key, source)
        state.replayByGameId.value = { ...state.replayByGameId.value, [key]: source }
        return source
      })
      .catch((err) => {
        if (token.isLatest() && replayCacheVersion(key) === cacheVersion && !background) {
          const cached = state.replayByGameId.value[key]
          state.replayByGameId.value = {
            ...state.replayByGameId.value,
            [key]: cached && typeof cached === 'object'
              ? { ...cached, error: err?.message || 'replay unavailable' }
              : { error: err?.message || 'replay unavailable' }
          }
        }
        throw err
      })
      .finally(() => {
        if (replayChunkPromises.get(chunkKey) === promise) replayChunkPromises.delete(chunkKey)
        if (token.isLatest() && replayCacheVersion(key) === cacheVersion) {
          const stillLoading = [...replayChunkPromises.keys()].some((pendingKey) => pendingKey.startsWith(`${key}:`))
          if (!stillLoading) {
            state.replayLoadingByGameId.value = { ...state.replayLoadingByGameId.value, [key]: false }
          }
        }
      })
    replayChunkPromises.set(chunkKey, promise)
    return promise
  }

  async function loadReplaySource(gameId) {
    const key = String(gameId || '')
    if (!key) return null
    if (replaySourceByGameId.has(key)) return replaySourceByGameId.get(key)
    if (replaySourcePromises.has(key)) return replaySourcePromises.get(key)
    const promise = loadReplayChunk(key, { cursor: 0, limit: DEFAULT_REPLAY_LIMIT })
      .then((source) => {
        if (source?.__replayHasMore) {
          void loadReplayChunk(key, {
            cursor: source.__replayNextCursor,
            limit: source.__replayLimit || DEFAULT_REPLAY_LIMIT,
            background: true
          }).catch(() => {})
        }
        return source
      })
      .finally(() => {
        replaySourcePromises.delete(key)
      })
    replaySourcePromises.set(key, promise)
    return promise
  }

  function normalizeFlowData(raw = {}, gameId = '') {
    const payload = raw?.data || raw
    const normalized = normalizeGameSnapshot({
      ...payload,
      game_id: payload.game_id || gameId,
      logs: [],
      events: [],
      decisions: Array.isArray(payload.decisions) ? payload.decisions : [],
      players: payload.players || state.selectedHistoryGame.value?.players || []
    }, { mode: 'watch' })
    return {
      ...payload,
      game_id: normalized.game_id || gameId,
      detail_view: payload.detail_view || payload.detailView || 'flow-data',
      players: normalized.players || [],
      decisions: normalized.decisions || [],
      decision_count: Number(payload.decision_count ?? normalized.decisions?.length ?? 0) || 0
    }
  }

  async function loadFlowData(gameId = state.selectedHistoryGameId.value, { clearNotice = false } = {}) {
    const key = String(gameId || '')
    if (!key) return null
    const cached = state.flowDataByGameId.value[key]
    if (cached && !cached.error) return cached
    if (flowDataPromises.has(key)) return flowDataPromises.get(key)
    const token = flowDataRequests.next(key)
    state.flowLoadingByGameId.value = { ...state.flowLoadingByGameId.value, [key]: true }
    if (clearNotice) clearHistoryNotice()
    const promise = apiFetch(`/games/${historyGameFlowDataPath(key)}`)
      .then((raw) => {
        if (!token.isLatest()) return null
        const flowData = normalizeFlowData(raw, key)
        state.flowDataByGameId.value = { ...state.flowDataByGameId.value, [key]: flowData }
        return flowData
      })
      .catch((err) => {
        if (token.isLatest()) {
          const notice = historyLoadNotice('error', err?.message, '复盘图表数据读取失败，请重试。')
          state.flowDataByGameId.value = { ...state.flowDataByGameId.value, [key]: { error: notice.message } }
          historyNotice.value = notice
          state.error.value = notice.message
        }
        return null
      })
      .finally(() => {
        if (token.isLatest()) {
          state.flowLoadingByGameId.value = { ...state.flowLoadingByGameId.value, [key]: false }
        }
        flowDataPromises.delete(key)
      })
    flowDataPromises.set(key, promise)
    return promise
  }

  function replaySource() {
    const key = String(state.replaySourceGameId.value || state.selectedHistoryGame.value?.game_id || '')
    return (key ? replaySourceByGameId.get(key) : null) || state.selectedHistoryGame.value
  }

  function historyQuery(offset = 0) {
    const params = new URLSearchParams()
    params.set('limit', String(historyPageSize))
    params.set('offset', String(Math.max(0, offset || 0)))
    if (historySourceFilter.value && historySourceFilter.value !== 'all') {
      params.set('source', historySourceFilter.value)
    }
    if (historyStatusFilter.value && historyStatusFilter.value !== 'all') {
      params.set('status', historyStatusFilter.value)
    }
    return `?${params.toString()}`
  }

  async function fetchHistoryPage(offset = 0) {
    const data = await apiFetch(`/games${historyQuery(offset)}`)
    const rows = data.games ?? []
    const pagination = paginationFromResponse(data, rows, { offset, limit: historyPageSize })
    const counts = historyCountsFromResponse(data, rows)
    const facets = historyFacetsFromResponse(data, counts)
    return { rows, pagination, counts, facets }
  }

  function applyHistoryMetadata({ pagination, counts, facets }) {
    historyPagination.value = pagination
    historyCounts.value = counts
    historyFacets.value = facets
  }

  function historyPageOffset(page = 1) {
    const safePage = Math.max(1, Number(page) || 1)
    return (safePage - 1) * historyPageSize
  }

  function firstHistoryGameId() {
    return state.gameHistory.value[0]?.game_id || ''
  }

  function applyHistorySelection({ resetSelection = false } = {}) {
    if (resetSelection) {
      const firstGameId = firstHistoryGameId()
      state.selectedHistoryGameId.value = firstGameId
      if (state.selectedHistoryGame.value?.game_id !== firstGameId) {
        state.selectedHistoryGame.value = null
      }
      return
    }
    if (!state.selectedHistoryGameId.value && state.gameHistory.value.length) {
      state.selectedHistoryGameId.value = state.gameHistory.value[0].game_id
    }
  }

  async function refreshHistoryList({ silent = false, resetSelection = false, page = historyCurrentPage.value } = {}) {
    const token = historyListRequests.next()
    historyLoadingMore.value = false
    if (!silent) state.historyLoading.value = true
    try {
      const { rows, pagination, counts, facets } = await fetchHistoryPage(historyPageOffset(page))
      if (!token.isLatest()) return false
      state.gameHistory.value = rows
      historyListLoaded = true
      applyHistoryMetadata({ pagination, counts, facets })
      applyHistorySelection({ resetSelection })
      return true
    } catch (err) {
      if (token.isLatest() && !silent) {
        const notice = historyLoadNotice('error', err?.message, '历史对局读取失败，请确认后端服务正在运行。')
        historyNotice.value = notice
        state.error.value = notice.message
      }
      return false
    } finally {
      if (token.isLatest() && !silent) state.historyLoading.value = false
    }
  }

  async function loadMoreHistory() {
    if (historyLoadingMore.value || state.historyLoading.value || !historyPagination.value.has_more) return
    const token = historyListRequests.next()
    historyLoadingMore.value = true
    try {
      const nextOffset = historyPagination.value.offset + historyPagination.value.returned
      const { rows, pagination, counts, facets } = await fetchHistoryPage(nextOffset)
      if (!token.isLatest()) return
      state.gameHistory.value = mergeHistoryGames(state.gameHistory.value, rows)
      historyListLoaded = true
      applyHistoryMetadata({ pagination, counts, facets })
    } catch (err) {
      if (token.isLatest()) {
        const notice = historyLoadNotice('error', err?.message, '历史对局读取失败，请确认后端服务正在运行。')
        historyNotice.value = notice
        state.error.value = notice.message
      }
    } finally {
      if (token.isLatest()) historyLoadingMore.value = false
    }
  }

  async function goHistoryPage(page = 1, { resetSelection = true, silent = false, loadSelected = true } = {}) {
    clearHistoryNotice()
    const targetPage = Math.max(1, Math.min(Number(page) || 1, historyTotalPages.value))
    const applied = await refreshHistoryList({ silent, resetSelection, page: targetPage })
    if (!applied) return false
    const targetGameId = resetSelection ? state.selectedHistoryGameId.value : ''
    if (loadSelected && targetGameId) await selectHistoryGame(targetGameId)
    return true
  }

  async function setHistorySourceFilter(source = 'all') {
    const next = ['normal', 'benchmark', 'evolution'].includes(source) ? source : 'all'
    if (historySourceFilter.value === next) return
    historySourceFilter.value = next
    await goHistoryPage(1, { resetSelection: true })
  }

  async function setHistoryStatusFilter(status = 'all') {
    const next = String(status || '').trim().toLowerCase() || 'all'
    if (historyStatusFilter.value === next) return
    historyStatusFilter.value = next
    await goHistoryPage(1, { resetSelection: true })
  }

  function clearHistoryGameCaches(gameId) {
    const key = String(gameId || '')
    if (!key) return
    const archives = { ...state.archiveByGameId.value }
    const reviews = { ...state.reviewByGameId.value }
    delete archives[key]
    delete reviews[key]
    state.archiveByGameId.value = archives
    state.reviewByGameId.value = reviews
    phaseDetailCacheByGameId.delete(key)
    const phaseDetails = { ...state.phaseDetailByGameId.value }
    delete phaseDetails[key]
    state.phaseDetailByGameId.value = phaseDetails
    bumpReplayCacheVersion(key)
    replaySourceByGameId.delete(key)
    const replayRows = { ...state.replayByGameId.value }
    delete replayRows[key]
    state.replayByGameId.value = replayRows
    const replayLoading = { ...state.replayLoadingByGameId.value }
    delete replayLoading[key]
    state.replayLoadingByGameId.value = replayLoading
    const flowData = { ...state.flowDataByGameId.value }
    delete flowData[key]
    state.flowDataByGameId.value = flowData
    const flowLoading = { ...state.flowLoadingByGameId.value }
    delete flowLoading[key]
    state.flowLoadingByGameId.value = flowLoading
    flowDataRequests.invalidate(key)
  }

  async function deleteHistoryGame(gameOrId) {
    const rawId = typeof gameOrId === 'object' ? gameOrId?.game_id : gameOrId
    const gameId = rawId == null ? '' : String(rawId)
    if (!gameId) return false
    const wasSelected = String(state.selectedHistoryGameId.value || '') === gameId
    const pageBeforeDelete = historyCurrentPage.value
    historyListRequests.invalidate()
    state.historyLoading.value = true
    state.error.value = ''
    clearHistoryNotice()
    try {
      await apiFetch(`/games/${historyGamePath(gameId)}`, { method: 'DELETE' })
      clearHistoryGameCaches(gameId)
      if (wasSelected) {
        state.selectedHistoryGameId.value = ''
        state.selectedHistoryGame.value = null
        state.selectedHistoryPageKey.value = ''
      }

      let applied = await refreshHistoryList({ resetSelection: wasSelected, page: pageBeforeDelete })
      if (
        applied
        && !state.gameHistory.value.length
        && Number(historyPagination.value.total || 0) > 0
        && pageBeforeDelete > 1
      ) {
        applied = await refreshHistoryList({ resetSelection: wasSelected, page: pageBeforeDelete - 1 })
      }

      if (applied && wasSelected && state.selectedHistoryGameId.value) {
        await selectHistoryGame(state.selectedHistoryGameId.value)
      }
      if (applied) {
        historyNotice.value = { type: 'success', message: '对局已删除，历史列表已刷新。' }
      } else {
        historyNotice.value = { type: 'warning', message: '对局已删除，但历史列表刷新失败，请重新进入历史页。' }
        state.error.value = historyNotice.value.message
      }
      return applied
    } catch (err) {
      const notice = deleteHistoryNoticeFromError(err)
      historyNotice.value = notice
      state.error.value = notice.message
      if (notice.message.includes('已刷新')) {
        clearHistoryGameCaches(gameId)
        if (wasSelected) {
          state.selectedHistoryGameId.value = ''
          state.selectedHistoryGame.value = null
          state.selectedHistoryPageKey.value = ''
        }
        const applied = await refreshHistoryList({ resetSelection: wasSelected, page: pageBeforeDelete })
        if (!applied) {
          historyNotice.value = { type: 'warning', message: '对局已不存在，但历史列表刷新失败，请重新进入历史页。' }
          state.error.value = historyNotice.value.message
        }
      }
      return false
    } finally {
      state.historyLoading.value = false
    }
  }

  async function selectHistoryGame(gameId, { fromOpenPage = false } = {}) {
    if (!gameId) return
    if (!fromOpenPage) logOpenRequests.invalidate()
    replayStartRequests.invalidate()
    replayCursorRequests.invalidate()
    const token = historySelectionRequests.next()
    const key = String(gameId)
    clearHistoryNotice()
    state.selectedHistoryGameId.value = key
    state.historyPhase.value = 'all'
    state.selectedHistoryPageKey.value = ''
    state.selectedHistoryGame.value = null
    state.selectedHistoryShell.value = null
    state.selectedPhaseDetail.value = null
    state.historyLoading.value = true
    state.error.value = ''
    try {
      const gameData = await apiFetch(`/games/${historyGameShellPath(key)}`)
      if (!token.isLatest() || String(state.selectedHistoryGameId.value || '') !== key) return
      const shell = normalizeHistoryShell(gameData, phaseCacheForGame(key))
      state.selectedHistoryShell.value = shell
      state.selectedHistoryGame.value = shell
      syncPhaseCacheState(key)
      const defaultPage = shell.__historyPages?.[0] || null
      if (defaultPage) {
        state.selectedHistoryPageKey.value = defaultPage.key
        await ensureHistoryPhaseDetail(key, defaultPage)
      }
    } catch (err) {
      if (token.isLatest()) {
        const notice = historyLoadNotice('error', err?.message, '历史对局详情读取失败，请重试。')
        historyNotice.value = notice
        state.error.value = notice.message
      }
    } finally {
      if (token.isLatest() && String(state.selectedHistoryGameId.value || '') === key) state.historyLoading.value = false
    }
  }

  async function ensureHistoryList({ silent = false } = {}) {
    if (
      historyListLoaded
      || state.gameHistory.value.length
      || Number(historyPagination.value.total || 0) > 0
    ) {
      applyHistorySelection()
      return true
    }
    return refreshHistoryList({ silent })
  }

  async function openLogPage(gameId = null, { rememberOrigin = true, workspace = 'phase' } = {}) {
    const token = logOpenRequests.next()
    const targetGameId = gameId == null ? '' : String(gameId)
    const targetWorkspace = normalizeHistoryWorkspaceTab(workspace)
    clearHistoryNotice()
    state.returnToMatchAvailable.value = rememberOrigin && isReturnableGame(state.liveGame.value)
    state.currentView.value = 'logs'
    state.historyWorkspaceTab.value = targetWorkspace
    writeLogsHash({ gameId: targetGameId, workspace: targetWorkspace })
    const listReady = await ensureHistoryList()
    if (!token.isLatest() || !listReady) return
    const selectedGameId = targetGameId || String(state.selectedHistoryGameId.value || '')
    const loadedGameId = String(state.selectedHistoryGame.value?.game_id || '')
    if (selectedGameId && (targetGameId || loadedGameId !== selectedGameId)) {
      await selectHistoryGame(selectedGameId, { fromOpenPage: true })
    }
  }

  function openEvolutionPage({ rememberOrigin = true } = {}) {
    state.returnToMatchAvailable.value = rememberOrigin && isReturnableGame(state.liveGame.value)
    state.currentView.value = 'evolution'
    const hash = typeof window === 'undefined' ? '' : String(window.location.hash || '')
    if (hash.split('?')[0] === '#evolution') return
    writeViewHash('evolution')
  }

  function openBenchmarkPage({ rememberOrigin = true } = {}) {
    state.returnToMatchAvailable.value = rememberOrigin && isReturnableGame(state.liveGame.value)
    state.currentView.value = 'benchmark'
    const hash = typeof window === 'undefined' ? '' : String(window.location.hash || '')
    if (hash.split('?')[0] === '#benchmark') return
    writeViewHash('benchmark')
  }

  function hashRouteInfo() {
    const hash = typeof window === 'undefined' ? '' : String(window.location.hash || '')
    const [routeHash, queryString = ''] = hash.split('?')
    const params = new URLSearchParams(queryString)
    return {
      routeHash,
      gameId: params.get('game_id') || params.get('game') || '',
      workspace: normalizeHistoryWorkspaceTab(params.get('workspace') || params.get('tab') || '', '')
    }
  }

  function syncHashRoute({ rememberOrigin = false } = {}) {
    const route = hashRouteInfo()
    if (route.routeHash === '#logs') {
      if (route.workspace) state.historyWorkspaceTab.value = route.workspace
      if (
        state.currentView.value === 'logs' &&
        state.selectedHistoryGame.value &&
        (!route.gameId || String(state.selectedHistoryGameId.value || '') === route.gameId)
      ) return
      void openLogPage(route.gameId || null, { rememberOrigin, workspace: route.workspace || state.historyWorkspaceTab.value || 'phase' })
      return
    }
    if (route.routeHash === '#evolution') {
      openEvolutionPage({ rememberOrigin })
      return
    }
    if (route.routeHash === '#benchmark') {
      openBenchmarkPage({ rememberOrigin })
      return
    }
    if (route.routeHash === '#match' && isReturnableGame(state.liveGame.value)) {
      state.currentView.value = 'match'
      state.skipIntroGameId.value = state.liveGame.value.game_id
      return
    }
    if (route.routeHash === '#match' && state.isReplayMode.value && state.replayGame.value) {
      state.currentView.value = 'match'
      return
    }
    if (route.routeHash === '#match') {
      void actionApi.restoreStoredGame?.({ navigate: true, silent: true, start: true })
    }
  }

  function goLobby() {
    state.returnToMatchAvailable.value = isReturnableGame(state.liveGame.value)
    state.currentView.value = 'lobby'
    writeViewHash('lobby')
  }

  function backToMatch() {
    state.returnToMatchAvailable.value = false
    if (isReturnableGame(state.liveGame.value)) {
      state.currentView.value = 'match'
      state.skipIntroGameId.value = state.liveGame.value.game_id
      writeViewHash('match')
      if (!state.watchRunning.value) {
        state.watchRunning.value = false
        actionApi.startWatch?.()
      }
    } else {
      state.currentView.value = 'lobby'
      writeViewHash('lobby')
    }
  }

  function buildReplaySnapshot(source, page) {
    if (!source || !page) return null
    const selectedSort = historyPageSortValue(page)
    const logs = (source.logs ?? []).filter((log) =>
      historyPageSortValue({ day: log.day, phase: rowHistoryPhase(log) }) <= selectedSort
    )
    const decisions = (source.decisions ?? []).filter((decision) => {
      const decisionPage = {
        day: normalizeHistoryDay(decision.day || page.day),
        phase: rowHistoryPhase(decision, page.phase)
      }
      return historyPageSortValue(decisionPage) <= selectedSort
    })
    const players = (source.players ?? []).map((player) => ({ ...player, alive: true, is_sheriff: false }))
    let sheriffId = null
    let currentSpeakerId = null
    const playerById = (id) => players.find((player) => player.id === id)
    const hasAuthoritativeDeathEvents = logs.some((log) => AUTHORITATIVE_DEATH_EVENTS.has(log.event_type || log.type || ''))
    for (const log of logs) {
      const type = log.event_type || log.type || ''
      for (const targetId of deathTargetIds(log, hasAuthoritativeDeathEvents)) {
        const dead = playerById(targetId)
        if (dead) dead.alive = false
      }
      sheriffId = sheriffIdAfterLog(log, sheriffId)
      if (SPEECH_EVENT_TYPES.has(type)) currentSpeakerId = log.actor_id || currentSpeakerId
    }
    players.forEach((player) => { player.is_sheriff = player.id === sheriffId })
    return {
      ...source,
      players,
      logs,
      decisions,
      vote_tally: buildReplayVoteTally(decisions, page, logs, replayEvents(source)),
      day: page.day,
      phase: page.phase,
      current_speaker_id: currentSpeakerId,
      sheriff_id: sheriffId,
      winner: source.winner && ['ended', 'result'].includes(page.phase) ? source.winner : null,
      waiting_for: 'none'
    }
  }

  function replayEvents(source = replaySource()) {
    return source?.logs || source?.events || []
  }

  function replayTotalForSource(source = replaySource()) {
    const loaded = replayEvents(source).length
    const total = Number(source?.__replayEventTotal ?? source?.event_count ?? loaded)
    return Number.isFinite(total) ? Math.max(loaded, total) : loaded
  }

  async function ensureReplayCursorLoaded(cursor, sourceOverride = replaySource()) {
    let source = sourceOverride
    if (!source) return null
    const gameId = String(state.replaySourceGameId.value || source.game_id || state.selectedHistoryGameId.value || '')
    if (!gameId) return source
    const target = Math.max(0, Math.min(replayTotalForSource(source), Number(cursor) || 0))
    while (replayEvents(source).length < target && source.__replayHasMore) {
      const nextCursor = Number(source.__replayNextCursor ?? replayEvents(source).length)
      const nextLimit = Number(source.__replayLimit || DEFAULT_REPLAY_LIMIT)
      const nextSource = await loadReplayChunk(gameId, { cursor: nextCursor, limit: nextLimit })
      if (!nextSource || replayEvents(nextSource).length <= replayEvents(source).length) break
      source = nextSource
    }
    return source
  }

  async function ensureReplayPageLoaded(source, page) {
    if (!source || !page) return source
    const gameId = String(state.replaySourceGameId.value || source.game_id || state.selectedHistoryGameId.value || '')
    if (!gameId) return source
    const selectedSort = historyPageSortValue(page)
    let current = source
    while (
      current.__replayHasMore
      && replayEvents(current).length < replayTotalForSource(current)
      && !replayEvents(current).some((log) => historyPageSortValue({ day: log.day, phase: rowHistoryPhase(log) }) > selectedSort)
    ) {
      const nextCursor = Number(current.__replayNextCursor ?? replayEvents(current).length)
      const nextLimit = Number(current.__replayLimit || DEFAULT_REPLAY_LIMIT)
      const nextSource = await loadReplayChunk(gameId, { cursor: nextCursor, limit: nextLimit })
      if (!nextSource || replayEvents(nextSource).length <= replayEvents(current).length) break
      current = nextSource
    }
    return current
  }

  function replayPhaseLabel(phase) {
    const normalized = normalizeHistoryPhase(phase)
    return displayPhaseLabel(normalized)
  }

  function replayCursorForPage(source, page) {
    if (!source || !page) return 0
    const selectedSort = historyPageSortValue(page)
    return replayEvents(source).filter((log) =>
      historyPageSortValue({ day: log.day, phase: rowHistoryPhase(log) }) <= selectedSort
    ).length
  }

  function replayEventLabel(log, cursor, total) {
    if (!log || cursor <= 0) return total ? '准备开始' : '无事件'
    const day = normalizeHistoryDay(log.day)
    const phase = replayPhaseLabel(log.phase)
    const speaker = log.speaker && !['法官', '系统'].includes(log.speaker) ? `${log.speaker} · ` : ''
    const message = normalizeHistoryDisplayText(log.message || log.type || log.event_type || '事件').replace(/\s+/g, ' ').trim()
    const clipped = message.length > 42 ? `${message.slice(0, 42)}...` : message
    return `${displayDayLabel(day)} · ${phase} · ${speaker}${clipped}`
  }

  function decisionsForReplayCursor(source, shownLogs, cursorSort) {
    const allDecisions = source.decisions ?? []
    if (!shownLogs.length) return []
    const latest = shownLogs.at(-1)
    const latestDay = normalizeHistoryDay(latest.day)
    const latestPhase = rowHistoryPhase(latest)
    const samePhaseVoteResultsPublic = hasReplayVoteResultLog(shownLogs, { day: latestDay, phase: latestPhase })
    return allDecisions.filter((decision) => {
      const decisionPage = {
        day: normalizeHistoryDay(decision.day || latestDay),
        phase: rowHistoryPhase(decision, latestPhase)
      }
      const decisionSort = historyPageSortValue(decisionPage)
      if (decisionSort < cursorSort) return true
      if (decisionSort > cursorSort) return false
      return !REPLAY_VOTE_ACTIONS.has(rowType(decision)) || samePhaseVoteResultsPublic
    })
  }

  function buildReplaySnapshotByCursor(source, cursor = state.replayCursor.value) {
    if (!source) return null
    const events = replayEvents(source)
    const total = replayTotalForSource(source)
    const clamped = Math.max(0, Math.min(events.length, total, Number(cursor) || 0))
    const logs = events.slice(0, clamped)
    const latestLog = logs.at(-1) || {}
    const day = latestLog.day ?? source.day ?? 1
    const phase = rowHistoryPhase(latestLog, clamped >= total && source.winner ? 'ended' : 'setup')
    const cursorSort = historyPageSortValue({ day, phase })
    const decisions = decisionsForReplayCursor(source, logs, cursorSort)
    const voteTally = buildReplayVoteTally(decisions, { day, phase }, logs, events)
    const players = (source.players ?? []).map((player) => ({ ...player, alive: true, is_sheriff: false }))
    const playerById = (id) => players.find((player) => Number(player.id) === Number(id))
    const hasAuthoritativeDeathEvents = events.some((log) => AUTHORITATIVE_DEATH_EVENTS.has(log.event_type || log.type || ''))
    let sheriffId = null
    let currentSpeakerId = null

    for (const log of logs) {
      const type = log.event_type || log.type || ''
      for (const targetId of deathTargetIds(log, hasAuthoritativeDeathEvents)) {
        const dead = playerById(targetId)
        if (dead) dead.alive = false
      }
      sheriffId = sheriffIdAfterLog(log, sheriffId)
      if (SPEECH_EVENT_TYPES.has(type)) currentSpeakerId = log.actor_id || currentSpeakerId
    }

    const latestType = latestLog.event_type || latestLog.type || ''
    if (!SPEECH_EVENT_TYPES.has(latestType)) currentSpeakerId = null
    players.forEach((player) => { player.is_sheriff = Number(player.id) === Number(sheriffId) })
    const atEnd = total === 0 || clamped >= total
    return {
      ...source,
      players,
      logs,
      events: logs,
      decisions,
      vote_tally: voteTally,
      day,
      phase,
      current_speaker_id: currentSpeakerId,
      sheriff_id: sheriffId,
      winner: atEnd ? source.winner : null,
      status: atEnd && source.winner ? (source.status || 'completed') : 'replaying',
      waiting_for: 'none',
      pending_action: null,
      pending_human_action: null
    }
  }

  function stopReplayTimer() {
    if (replayTimer) {
      window.clearInterval(replayTimer)
      replayTimer = null
    }
    state.replayPlaying.value = false
  }

  function applyReplayCursor(cursor = state.replayCursor.value, sourceOverride = replaySource()) {
    const source = sourceOverride
    if (!source) return null
    const total = replayTotalForSource(source)
    const clamped = Math.max(0, Math.min(replayEvents(source).length, total, Number(cursor) || 0))
    const snapshot = buildReplaySnapshotByCursor(source, clamped)
    if (!snapshot) return null
    state.replayCursor.value = clamped
    state.replayTotal.value = total
    state.replayEventLabel.value = replayEventLabel(snapshot.logs.at(-1), clamped, total)
    state.replayPageKey.value = state.selectedHistoryPage?.value?.key || state.replayPageKey.value || ''
    state.replayGame.value = snapshot
    if (clamped >= total) stopReplayTimer()
    nextTick(() => sceneApi.scheduleSyncCouncilScene?.())
    return snapshot
  }

  async function applyReplayCursorLoaded(cursor = state.replayCursor.value, sourceOverride = replaySource(), token = null) {
    const source = await ensureReplayCursorLoaded(cursor, sourceOverride)
    if (token && !token.isLatest()) return null
    return applyReplayCursor(cursor, source)
  }

  function replayIntervalMs() {
    const speed = Number(state.replaySpeed.value) || 1
    return Math.max(120, Math.round(REPLAY_BASE_INTERVAL_MS / speed))
  }

  async function playReplay() {
    const source = replaySource()
    if (!state.isReplayMode.value || !source || typeof window === 'undefined') return
    const total = replayTotalForSource(source)
    const token = replayCursorRequests.next()
    if (state.replayCursor.value >= total) {
      try {
        await applyReplayCursorLoaded(0, source, token)
      } catch (err) {
        if (token.isLatest()) setReplayLoadError(err)
        return
      }
      if (!token.isLatest()) return
    }
    stopReplayTimer()
    state.replayPlaying.value = true
    replayTimer = window.setInterval(() => {
      const next = Math.min(state.replayTotal.value, state.replayCursor.value + 1)
      if (replayAdvancePending) return
      replayAdvancePending = true
      const advanceToken = replayCursorRequests.next()
      applyReplayCursorLoaded(next, replaySource(), advanceToken)
        .catch((err) => {
          if (advanceToken.isLatest()) {
            stopReplayTimer()
            setReplayLoadError(err)
          }
        })
        .finally(() => {
          replayAdvancePending = false
          if (state.replayCursor.value >= state.replayTotal.value) stopReplayTimer()
        })
    }, replayIntervalMs())
  }

  function pauseReplay() {
    replayCursorRequests.invalidate()
    stopReplayTimer()
  }

  function stepReplay(delta = 1) {
    stopReplayTimer()
    const token = replayCursorRequests.next()
    return applyReplayCursorLoaded(state.replayCursor.value + Number(delta || 0), replaySource(), token)
      .catch((err) => {
        if (token.isLatest()) setReplayLoadError(err)
        return null
      })
  }

  function seekReplay(cursor) {
    stopReplayTimer()
    const token = replayCursorRequests.next()
    return applyReplayCursorLoaded(cursor, replaySource(), token)
      .catch((err) => {
        if (token.isLatest()) setReplayLoadError(err)
        return null
      })
  }

  function setReplaySpeed(speed) {
    const number = Number(speed)
    state.replaySpeed.value = REPLAY_SPEEDS.includes(number) ? number : 1
    if (state.replayPlaying.value) playReplay()
  }

  function enterReplayAt(cursor = 0, sourceOverride = replaySource()) {
    const source = sourceOverride
    if (!source) return
    const gameId = source.game_id || state.selectedHistoryGame.value?.game_id || null
    if (gameId) replaySourceByGameId.set(String(gameId), source)
    actionApi.stopWatch?.()
    if (!state.isReplayMode.value) {
      state.lastLiveGame.value = isReturnableGame(state.liveGame.value) ? state.liveGame.value : null
    }
    state.isReplayMode.value = true
    state.replaySourceGameId.value = gameId
    state.replayTotal.value = replayTotalForSource(source)
    state.judgeBoardStarted.value = true
    state.roleAssignmentComplete.value = true
    applyReplayCursor(cursor, source)
    state.currentView.value = 'match'
    writeViewHash('match')
  }

  async function enterReplayPage(page = state.selectedHistoryPage.value) {
    const gameId = state.selectedHistoryGame.value?.game_id || state.selectedHistoryGameId.value
    const initialSource = await loadReplaySource(gameId)
    const source = await ensureReplayPageLoaded(initialSource, page)
    if (!source) return
    enterReplayAt(replayCursorForPage(source, page), source)
  }

  async function replayHistoryGame(gameItem = state.selectedHistoryGame.value) {
    const gameId = typeof gameItem === 'object' ? gameItem?.game_id : gameItem
    const key = String(gameId || '')
    if (!key) {
      const notice = { type: 'error', message: '回放源数据尚未载入，请稍后重试。' }
      historyNotice.value = notice
      state.error.value = notice.message
      return
    }
    const token = replayStartRequests.next()
    replayCursorRequests.invalidate()
    clearHistoryNotice()
    state.error.value = ''
    try {
      const source = await loadReplaySource(key)
      if (!token.isLatest()) return
      if (!source) throw new Error('replay source missing')
      enterReplayAt(0, source)
    } catch {
      if (token.isLatest()) {
        const notice = { type: 'error', message: '回放源数据尚未载入，请稍后重试。' }
        historyNotice.value = notice
        state.error.value = notice.message
      }
    }
  }

  function returnToHistoryFromReplay() {
    pauseReplay()
    state.currentView.value = 'logs'
    writeViewHash('logs')
    state.returnToMatchAvailable.value = false
  }

  function exitReplayMode() {
    if (!state.isReplayMode.value) return
    replayCursorRequests.invalidate()
    stopReplayTimer()
    state.isReplayMode.value = false
    state.replaySourceGameId.value = null
    state.replayPageKey.value = ''
    state.replayCursor.value = 0
    state.replayPlaying.value = false
    state.replayTotal.value = 0
    state.replayEventLabel.value = ''
    state.replayGame.value = null
    if (isReturnableGame(state.lastLiveGame.value) && !state.liveGame.value) state.liveGame.value = state.lastLiveGame.value
    const hasLiveGame = isReturnableGame(state.liveGame.value)
    state.currentView.value = hasLiveGame ? 'match' : 'lobby'
    if (hasLiveGame) state.skipIntroGameId.value = state.liveGame.value.game_id
    writeViewHash(hasLiveGame ? 'match' : 'lobby')
    state.returnToMatchAvailable.value = false
    if (hasLiveGame) {
      state.watchRunning.value = false
      actionApi.startWatch?.()
    }
  }

  async function loadArchive(gameId = state.selectedHistoryGameId.value, { silentSuccess = false, clearNotice = true } = {}) {
    if (!gameId || (state.archiveByGameId.value[gameId] && !state.archiveByGameId.value[gameId].error)) return
    const token = archiveRequests.next(gameId)
    state.archiveLoading.value = true
    if (clearNotice) clearHistoryNotice()
    try {
      const archive = await apiFetch(`/games/${historyGamePath(gameId)}/archive`)
      if (!token.isLatest()) return
      state.archiveByGameId.value = { ...state.archiveByGameId.value, [gameId]: archive }
      if (!silentSuccess) historyNotice.value = { type: 'success', message: '对局档案已载入。' }
    } catch (err) {
      if (token.isLatest()) {
        const notice = historyLoadNotice('error', err?.message, '对局档案读取失败，请重试。')
        state.archiveByGameId.value = { ...state.archiveByGameId.value, [gameId]: { error: notice.message } }
        historyNotice.value = notice
        state.error.value = notice.message
      }
    } finally {
      if (token.isLatest()) state.archiveLoading.value = false
    }
  }

  async function loadReview(gameId = state.selectedHistoryGameId.value, { silentSuccess = false, clearNotice = true } = {}) {
    if (!gameId || (state.reviewByGameId.value[gameId] && !state.reviewByGameId.value[gameId].error)) return
    const token = reviewRequests.next(gameId)
    state.reviewLoading.value = true
    if (clearNotice) clearHistoryNotice()
    try {
      const review = await apiFetch(`/games/${historyGamePath(gameId)}/review`)
      if (!token.isLatest()) return
      state.reviewByGameId.value = { ...state.reviewByGameId.value, [gameId]: review }
    } catch (err) {
      if (token.isLatest()) {
        const notice = historyLoadNotice('error', err?.message, '复盘报告读取失败，请重试。')
        state.reviewByGameId.value = { ...state.reviewByGameId.value, [gameId]: { error: notice.message } }
        historyNotice.value = notice
        state.error.value = notice.message
      }
    } finally {
      if (token.isLatest()) state.reviewLoading.value = false
    }
  }

  watch(
    () => state.selectedHistoryPageKey.value,
    (pageKey, previousKey) => {
      if (!pageKey || pageKey === previousKey) return
      const gameId = String(state.selectedHistoryGameId.value || '')
      if (!gameId || String(state.selectedHistoryGame.value?.game_id || '') !== gameId) return
      applyHistoryGameView(gameId, pageKey)
      void ensureHistoryPhaseDetail(gameId, pageKey, { setLoading: false })
    }
  )

  if (options.installLifecycle !== false) {
    const handleHashChange = () => syncHashRoute({ rememberOrigin: false })
    onMounted(() => {
      const hash = typeof window === 'undefined' ? '' : window.location.hash
      if (['#logs', '#evolution', '#benchmark', '#match'].includes(String(hash || '').split('?')[0])) {
        syncHashRoute({ rememberOrigin: false })
      } else if (options.prefetchHistoryOnMount === true) {
        refreshHistoryList({ silent: true })
      }
      if (typeof window !== 'undefined') window.addEventListener('hashchange', handleHashChange)
    })
    onBeforeUnmount(() => {
      stopReplayTimer()
      noticeAutoDismiss.dispose()
      if (typeof window !== 'undefined') window.removeEventListener('hashchange', handleHashChange)
    })
  }

  return {
    setActionApi,
    setSceneApi,
    historyPagination,
    historyLoadingMore,
    historySourceFilter,
    historyStatusFilter,
    historyCounts,
    historyFacets,
    historyNotice,
    historyHasMore,
    historyCurrentPage,
    historyTotalPages,
    refreshHistoryList,
    loadMoreHistory,
    loadMoreHistoryPhaseDetail,
    goHistoryPage,
    setHistorySourceFilter,
    setHistoryStatusFilter,
    deleteHistoryGame,
    selectHistoryGame,
    openLogPage,
    openEvolutionPage,
    openBenchmarkPage,
    syncHashRoute,
    goLobby,
    backToMatch,
    buildReplaySnapshot,
    buildReplaySnapshotByCursor,
    enterReplayAt,
    enterReplayPage,
    applyReplayCursor,
    playReplay,
    pauseReplay,
    stepReplay,
    seekReplay,
    setReplaySpeed,
    stopReplayTimer,
    replayHistoryGame,
    returnToHistoryFromReplay,
    exitReplayMode,
    loadArchive,
    loadReview,
    loadFlowData
  }
}

export { useGameHistory }

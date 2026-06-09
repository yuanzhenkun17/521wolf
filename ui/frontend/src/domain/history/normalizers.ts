import type { Pagination, UnknownRecord } from '../../types/api'
import type {
  HistoryGame,
  HistoryListResponse,
  HistoryPage,
  HistoryPhaseDetail,
  HistoryPhasePagination,
  HistoryWorkspaceTab,
  PhaseDetailQuery,
  ReplaySnapshot
} from '../../types/history'
import type { Decision, GameLog, GamePhase } from '../../types/game'
import { normalizeDecisionEntry, normalizeGameSnapshot, normalizeLogEntry, normalizePhase } from '../game/normalizers'
import { arrayOrEmpty, integerValue, isRecord, normalizePagination, objectOrEmpty, positiveInteger, stringValue } from '../common'

const HISTORY_PHASE_ALIASES: Record<string, GamePhase> = {
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
const HISTORY_WORKSPACE_TABS = new Set(['phase', 'review', 'archive'])
const EMPTY_HISTORY_COUNTS = { all: 0, normal: 0, benchmark: 0, evolution: 0 }
const DEFAULT_PHASE_LOG_LIMIT = 300
const DEFAULT_PHASE_DECISION_LIMIT = 200

export function normalizeHistoryWorkspaceTab(value: unknown, fallback: HistoryWorkspaceTab = 'phase'): HistoryWorkspaceTab {
  const text = stringValue(value).toLowerCase()
  return HISTORY_WORKSPACE_TABS.has(text) ? (text as HistoryWorkspaceTab) : fallback
}

export function normalizeHistoryPhase(phase: unknown = 'setup'): GamePhase {
  const text = stringValue(phase, 'setup')
  return HISTORY_PHASE_ALIASES[text] || normalizePhase(text)
}

export function normalizeHistoryDay(day: unknown): number {
  return positiveInteger(day, 1)
}

export function historyPageKey(day: unknown, phase: unknown): string {
  return `day-${normalizeHistoryDay(day)}-${normalizeHistoryPhase(phase)}`
}

export function parseHistoryPageKey(key: unknown): { day: number; phase: GamePhase } | null {
  const match = stringValue(key).match(/^day-(\d+)-(.+)$/)
  if (!match) return null
  return {
    day: normalizeHistoryDay(match[1]),
    phase: normalizeHistoryPhase(match[2])
  }
}

export function historyPageSortValue(page: Partial<HistoryPage> | null | undefined): number {
  if (!page) return 0
  const phase = normalizeHistoryPhase(page.phase)
  const rank = HISTORY_PHASE_RANK.has(phase) ? HISTORY_PHASE_RANK.get(phase) || 0 : HISTORY_PHASE_ORDER.length
  return normalizeHistoryDay(page.day) * 100 + rank
}

export function normalizeHistoryPageSummary(raw: unknown = {}, index = 0): HistoryPage {
  const summary = objectOrEmpty(raw)
  const parsed = parseHistoryPageKey(summary.key ?? summary.phase_key)
  const day = normalizeHistoryDay(summary.day ?? summary.day_number ?? parsed?.day ?? 1)
  const phase = normalizeHistoryPhase(summary.phase ?? summary.name ?? parsed?.phase ?? 'setup')
  const key = stringValue(summary.key ?? summary.phase_key, historyPageKey(day, phase))
  return {
    ...summary,
    key,
    day,
    phase,
    title: stringValue(summary.title),
    log_count: integerValue(summary.log_count ?? summary.logs_count ?? summary.event_count ?? summary.events_count, 0),
    decision_count: integerValue(summary.decision_count ?? summary.decisions_count, 0),
    index
  }
}

export function historyPagesFromRows(logs: GameLog[] = [], decisions: Decision[] = [], source: UnknownRecord = {}): HistoryPage[] {
  const map = new Map<string, HistoryPage>()
  const ensurePage = (day: unknown, phase: unknown): HistoryPage => {
    const normalizedDay = normalizeHistoryDay(day)
    const normalizedPhase = normalizeHistoryPhase(phase)
    const key = historyPageKey(normalizedDay, normalizedPhase)
    const existing = map.get(key)
    if (existing) return existing
    const page: HistoryPage = {
      key,
      day: normalizedDay,
      phase: normalizedPhase,
      title: '',
      log_count: 0,
      decision_count: 0,
      index: 0
    }
    map.set(key, page)
    return page
  }

  ensurePage(1, 'setup')
  logs.forEach((log) => {
    const page = ensurePage(log.day, log.phase)
    page.log_count += 1
  })
  decisions.forEach((decision) => {
    const page = ensurePage(decision.day, decision.phase)
    page.decision_count += 1
  })
  if (source.winner) {
    const days = [
      1,
      ...logs.map((log) => normalizeHistoryDay(log.day)),
      ...decisions.map((decision) => normalizeHistoryDay(decision.day)),
      normalizeHistoryDay(source.day)
    ]
    ensurePage(Math.max(...days), 'ended')
  }
  return [...map.values()]
    .sort((a, b) => historyPageSortValue(a) - historyPageSortValue(b) || a.key.localeCompare(b.key))
    .map((page, pageIndex) => ({ ...page, index: pageIndex }))
}

export function historyPagesFromShell(raw: unknown = {}): HistoryPage[] {
  const source = objectOrEmpty(raw)
  const explicitPages = source.phases ?? source.history_pages ?? source.phase_index ?? source.pages
  if (Array.isArray(explicitPages) && explicitPages.length) {
    return explicitPages
      .map(normalizeHistoryPageSummary)
      .sort((a, b) => historyPageSortValue(a) - historyPageSortValue(b) || a.key.localeCompare(b.key))
      .map((page, index) => ({ ...page, index }))
  }
  const logs = (Array.isArray(source.logs) ? source.logs : arrayOrEmpty(source.events)).map(normalizeLogEntry)
  const decisions = arrayOrEmpty(source.decisions).map((decision, index) => normalizeDecisionEntry(decision, index + 1))
  return historyPagesFromRows(logs, decisions, source)
}

function pageTotals(pages: HistoryPage[], field: 'log_count' | 'decision_count'): number {
  return pages.reduce((total, page) => total + integerValue(page[field], 0), 0)
}

function phasePagination(raw: unknown, rows: unknown[] = [], fallback: Partial<Pagination> = {}): Pagination {
  return normalizePagination(raw, rows, fallback)
}

export function normalizePhasePagination(raw: unknown = {}, logs: GameLog[] = [], decisions: Decision[] = [], request: Partial<PhaseDetailQuery> = {}): HistoryPhasePagination {
  const pagination = objectOrEmpty(objectOrEmpty(raw).pagination)
  const summary = objectOrEmpty(objectOrEmpty(raw).summary)
  return {
    logs: phasePagination(pagination.logs, logs, {
      offset: request.log_offset ?? 0,
      limit: request.log_limit ?? DEFAULT_PHASE_LOG_LIMIT,
      total: integerValue(summary.log_count, logs.length)
    }),
    decisions: phasePagination(pagination.decisions, decisions, {
      offset: request.decision_offset ?? 0,
      limit: request.decision_limit ?? DEFAULT_PHASE_DECISION_LIMIT,
      total: integerValue(summary.decision_count, decisions.length)
    })
  }
}

export function pageWithPhaseDetail(page: HistoryPage, detail: HistoryPhaseDetail | null | undefined): HistoryPage {
  if (!detail) {
    return {
      ...page,
      logs: page.logs || [],
      decisions: page.decisions || [],
      pagination: page.pagination || null,
      loaded: Boolean(page.loaded)
    }
  }
  return {
    ...page,
    loaded: true,
    log_count: integerValue(page.log_count ?? detail.summary?.log_count ?? detail.pagination.logs.total, detail.logs.length),
    decision_count: integerValue(page.decision_count ?? detail.summary?.decision_count ?? detail.pagination.decisions.total, detail.decisions.length),
    logs: detail.logs,
    decisions: detail.decisions,
    summary: detail.summary || page.summary || {},
    pagination: detail.pagination || page.pagination || null
  }
}

export function normalizeHistoryShell(raw: unknown = {}, cache: Map<string, HistoryPhaseDetail> = new Map()): HistoryGame | null {
  const source = objectOrEmpty(raw)
  const pages = historyPagesFromShell(source)
  const normalized = normalizeGameSnapshot(
    {
      ...source,
      logs: [],
      events: [],
      decisions: [],
      phases: pages,
      history_pages: pages
    },
    { mode: 'watch' }
  )
  if (!normalized) return null
  const pagesWithCachedDetails = pages.map((page) => pageWithPhaseDetail(page, cache.get(page.key)))
  return {
    ...normalized,
    logs: [],
    events: [],
    decisions: [],
    event_count: integerValue(source.event_count ?? source.log_count ?? source.events_count, pageTotals(pages, 'log_count')),
    decision_count: integerValue(source.decision_count ?? source.decisions_count, pageTotals(pages, 'decision_count')),
    phases: pagesWithCachedDetails,
    history_pages: pagesWithCachedDetails,
    __historyPages: pagesWithCachedDetails,
    __phaseDetails: Object.fromEntries(cache.entries()),
    __activePhaseKey: '',
    __detailView: stringValue(source.detail_view ?? source.detailView, 'history-shell')
  }
}

export function normalizePhaseDetail(raw: unknown = {}, page: Partial<HistoryPage> = {}, shell: Partial<HistoryGame> = {}, request: Partial<PhaseDetailQuery> = {}): HistoryPhaseDetail {
  const source = objectOrEmpty(raw)
  const logs = (Array.isArray(source.logs) ? source.logs : arrayOrEmpty(source.events)).map(normalizeLogEntry)
  const decisions = arrayOrEmpty(source.decisions).map((decision, index) => normalizeDecisionEntry(decision, index + 1))
  const normalized = normalizeGameSnapshot(
    {
      ...shell,
      ...source,
      game_id: source.game_id || shell.game_id,
      players: source.players || shell.players || [],
      day: source.day ?? page.day,
      phase: source.phase ?? page.phase,
      logs,
      events: logs,
      decisions
    },
    { mode: 'watch' }
  )
  const day = normalizeHistoryDay(source.day ?? page.day)
  const phase = normalizeHistoryPhase(source.phase ?? page.phase)
  return {
    key: stringValue(source.key ?? source.phase_key ?? page.key, historyPageKey(day, phase)),
    day,
    phase,
    logs: normalized?.logs || logs,
    decisions: normalized?.decisions || decisions,
    summary: objectOrEmpty(source.summary),
    pagination: normalizePhasePagination(source, normalized?.logs || logs, normalized?.decisions || decisions, request),
    loaded_at: Date.now()
  }
}

export function normalizeReplaySnapshot(raw: unknown = {}, gameId = '', existing: ReplaySnapshot | null = null): ReplaySnapshot | null {
  const source = objectOrEmpty(raw)
  const normalized = normalizeGameSnapshot(
    {
      ...(existing || {}),
      ...source,
      game_id: source.game_id || gameId || existing?.game_id,
      logs: Array.isArray(source.logs) ? source.logs : arrayOrEmpty(source.events),
      decisions: arrayOrEmpty(source.decisions)
    },
    { mode: 'replay' }
  )
  if (!normalized) return null
  const cursor = integerValue(source.cursor ?? source.offset, existing?.cursor ?? 0)
  const limit = integerValue(source.limit, existing?.limit ?? normalized.logs.length)
  const nextCursorRaw = source.next_cursor ?? source.nextCursor
  return {
    ...normalized,
    cursor,
    limit,
    next_cursor: nextCursorRaw == null ? null : integerValue(nextCursorRaw),
    has_more: Boolean(source.has_more ?? source.hasMore)
  }
}

export function normalizeHistoryListResponse(data: unknown, fallback: { offset?: number; limit?: number | null } = {}): HistoryListResponse {
  const source = objectOrEmpty(data)
  const rows = arrayOrEmpty(source.games)
    .map((row) => normalizeHistoryShell(row))
    .filter((row): row is HistoryGame => Boolean(row))
  const rawCounts = objectOrEmpty(source.counts ?? objectOrEmpty(source.facets).source)
  const counts = {
    ...EMPTY_HISTORY_COUNTS,
    ...Object.fromEntries(Object.entries(rawCounts).map(([key, value]) => [key, integerValue(value, 0)])),
    all: integerValue(rawCounts.all ?? objectOrEmpty(source.pagination).total, rows.length)
  }
  const rawFacets = objectOrEmpty(source.facets)
  return {
    games: rows,
    pagination: normalizePagination(source.pagination, rows, fallback),
    counts,
    facets: {
      ...rawFacets,
      source: {
        ...counts,
        ...(isRecord(rawFacets.source) ? rawFacets.source : {})
      }
    },
    raw: data
  }
}

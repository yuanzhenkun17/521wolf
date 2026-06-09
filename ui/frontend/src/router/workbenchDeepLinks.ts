import type { LocationQuery, RouteLocationNormalizedLoaded } from 'vue-router'
import { normalizeHistoryWorkspaceTab } from '../domain/history/normalizers'
import type { HistoryWorkspaceTab } from '../types/history'

type RouteLike = Pick<RouteLocationNormalizedLoaded, 'name' | 'path' | 'query' | 'hash'>
type QueryLike = LocationQuery | Record<string, unknown>

export interface HistoryDeepLinkTarget {
  routeHash: string
  gameId: string
  workspace: HistoryWorkspaceTab | ''
}

export interface EvolutionDeepLinkTarget {
  run_id: string
  gate_report_id: string
  proposal_id: string
  role: string
  version_id: string
  panel: string
  query: string
  status: 'pending'
  pending: string[]
  message: string
}

const benchmarkIdKeys = ['batch_id', 'batch', 'run_id', 'run', 'source_run_id']
const evolutionQueryKeys = [
  'run_id',
  'run',
  'source_run_id',
  'sourceRunId',
  'gate_report_id',
  'gate',
  'gateReportId',
  'proposal_id',
  'proposal',
  'proposalId',
  'role',
  'version_id',
  'version',
  'versionId'
]

function textValue(value: unknown): string {
  if (Array.isArray(value)) return textValue(value[0])
  return String(value ?? '').trim()
}

function firstTextValue(...values: unknown[]): string {
  return values.map(textValue).find(Boolean) || ''
}

function optionalHistoryWorkspaceTab(value: unknown): HistoryWorkspaceTab | '' {
  const text = textValue(value).toLowerCase()
  if (!text) return ''
  const tab = normalizeHistoryWorkspaceTab(text)
  return tab === text ? tab : ''
}

function routeName(route: Partial<RouteLike> = {}): string {
  return typeof route.name === 'string' ? route.name : String(route.name || '')
}

function isRouteFor(route: Partial<RouteLike> | null | undefined, name: string): boolean {
  if (!route) return false
  if (routeName(route) === name) return true
  return String(route.path || '').replace(/\/+$/, '') === (name === 'lobby' ? '' : `/${name}`)
}

function queryStringFromQuery(query: QueryLike = {}, knownKeys: string[] = []): string {
  const params = new URLSearchParams()
  const keys = [
    ...knownKeys.filter((key) => Object.prototype.hasOwnProperty.call(query, key)),
    ...Object.keys(query).filter((key) => !knownKeys.includes(key)).sort()
  ]

  keys.forEach((key) => {
    const value = query[key]
    const values = Array.isArray(value) ? value : [value]
    values.forEach((item) => {
      const text = textValue(item)
      if (text) params.append(key, text)
    })
  })

  return params.toString()
}

function queryFromHash(value = ''): { routeHash: string; query: URLSearchParams; queryString: string } {
  const text = String(value || '')
  const hashIndex = text.indexOf('#')
  const hash = hashIndex >= 0 ? text.slice(hashIndex) : text
  const [routeHash, queryString = ''] = hash.split('?')
  return {
    routeHash,
    query: new URLSearchParams(queryString),
    queryString
  }
}

export function evolutionDeepLinkPanel(target: Partial<EvolutionDeepLinkTarget> = {}): string {
  if (target.version_id) return 'versions'
  if (target.proposal_id || target.gate_report_id) return 'review'
  if (target.run_id) return 'runs'
  return ''
}

export function benchmarkBatchIdFromQuery(query: QueryLike = {}): string {
  return firstTextValue(...benchmarkIdKeys.map((key) => query[key]))
}

export function benchmarkBatchIdFromHash(value = ''): string {
  const { routeHash, query } = queryFromHash(value)
  if (routeHash !== '#benchmark') return ''
  return firstTextValue(...benchmarkIdKeys.map((key) => query.get(key)))
}

export function benchmarkBatchIdFromRoute(route: Partial<RouteLike> | null | undefined): string {
  if (!route) return ''
  const routeValue = isRouteFor(route, 'benchmark') ? benchmarkBatchIdFromQuery(route.query || {}) : ''
  return routeValue || benchmarkBatchIdFromHash(route.hash || '')
}

export function logsHash({ gameId = '', workspace = '' }: { gameId?: unknown; workspace?: unknown } = {}): string {
  const query = new URLSearchParams()
  if (gameId) query.set('game_id', String(gameId))
  const tab = optionalHistoryWorkspaceTab(workspace)
  if (tab && tab !== 'phase') query.set('workspace', tab)
  const queryString = query.toString()
  return queryString ? `#logs?${queryString}` : '#logs'
}

export function historyDeepLinkFromQuery(query: QueryLike = {}): HistoryDeepLinkTarget {
  return {
    routeHash: '#logs',
    gameId: firstTextValue(query.game_id, query.game),
    workspace: optionalHistoryWorkspaceTab(firstTextValue(query.workspace, query.tab))
  }
}

export function historyDeepLinkFromHash(value = ''): HistoryDeepLinkTarget {
  const { routeHash, query } = queryFromHash(value)
  return {
    routeHash,
    gameId: firstTextValue(query.get('game_id'), query.get('game')),
    workspace: optionalHistoryWorkspaceTab(query.get('workspace') || query.get('tab'))
  }
}

export function historyDeepLinkFromRoute(route: Partial<RouteLike> | null | undefined): HistoryDeepLinkTarget {
  if (!route) return historyDeepLinkFromHash('')
  if (isRouteFor(route, 'logs')) {
    const routeTarget = historyDeepLinkFromQuery(route.query || {})
    if (routeTarget.gameId || routeTarget.workspace || !route.hash) return routeTarget
  }
  const hashTarget = historyDeepLinkFromHash(route.hash || '')
  if (hashTarget.routeHash) return hashTarget
  return isRouteFor(route, 'logs') ? historyDeepLinkFromQuery(route.query || {}) : hashTarget
}

export function evolutionDeepLinkFromQuery(query: QueryLike = {}): EvolutionDeepLinkTarget | null {
  const target = {
    run_id: firstTextValue(query.run_id, query.run, query.source_run_id, query.sourceRunId),
    gate_report_id: firstTextValue(query.gate_report_id, query.gate, query.gateReportId),
    proposal_id: firstTextValue(query.proposal_id, query.proposal, query.proposalId),
    role: firstTextValue(query.role),
    version_id: firstTextValue(query.version_id, query.version, query.versionId)
  }
  if (!Object.values(target).some(Boolean)) return null
  const panel = evolutionDeepLinkPanel(target)
  return {
    ...target,
    panel,
    query: queryStringFromQuery(query, evolutionQueryKeys),
    status: 'pending',
    pending: [],
    message: panel ? '等待恢复定位链接目标。' : '等待恢复自进化定位链接。'
  }
}

export function evolutionDeepLinkFromHash(value = ''): EvolutionDeepLinkTarget | null {
  const { routeHash, query } = queryFromHash(value)
  if (routeHash !== '#evolution') return null
  return evolutionDeepLinkFromQuery(Object.fromEntries(query.entries()))
}

export function evolutionDeepLinkFromRoute(route: Partial<RouteLike> | null | undefined): EvolutionDeepLinkTarget | null {
  if (!route) return null
  if (isRouteFor(route, 'evolution')) {
    const routeTarget = evolutionDeepLinkFromQuery(route.query || {})
    if (routeTarget) return routeTarget
  }
  return evolutionDeepLinkFromHash(route.hash || '')
}

import type { RouteLocationNormalizedLoaded } from 'vue-router'
import type { AppView } from '../types/ui'

export const APP_VIEWS: AppView[] = ['lobby', 'match', 'logs', 'benchmark', 'evolution', 'tasks', 'settings']
const APP_VIEW_SET = new Set<string>(APP_VIEWS)

const VIEW_PATHS: Record<AppView, string> = {
  lobby: '/',
  match: '/match',
  logs: '/logs',
  benchmark: '/benchmark',
  evolution: '/evolution',
  tasks: '/tasks',
  settings: '/settings'
}

const VIEW_HASHES: Record<AppView, string> = {
  lobby: '',
  match: 'match',
  logs: 'logs',
  benchmark: 'benchmark',
  evolution: 'evolution',
  tasks: 'tasks',
  settings: 'settings'
}

const PATH_VIEWS = Object.fromEntries(
  Object.entries(VIEW_PATHS).map(([view, path]) => [path, view])
) as Record<string, AppView>

const HASH_VIEWS = Object.fromEntries(
  Object.entries(VIEW_HASHES).map(([view, hash]) => [`#${hash}`, view])
) as Record<string, AppView>

function normalizedPath(path = ''): string {
  return String(path || '').replace(/\/+$/, '') || '/'
}

export function appViewPath(view: AppView): string {
  return VIEW_PATHS[view] || '/'
}

export function isAppView(view: unknown): view is AppView {
  return typeof view === 'string' && APP_VIEW_SET.has(view)
}

export function appViewHash(view: AppView): string {
  return VIEW_HASHES[view] || ''
}

export function appViewFromPath(path = ''): AppView {
  return PATH_VIEWS[normalizedPath(path)] || 'lobby'
}

export function appViewFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'path'>): AppView {
  return appViewFromPath(route.path)
}

export function knownAppViewFromPath(path = ''): AppView | '' {
  if (!path) return ''
  return PATH_VIEWS[normalizedPath(path)] || ''
}

export function appViewFromRouteSource(
  route: Partial<Pick<RouteLocationNormalizedLoaded, 'name' | 'path' | 'hash'>> | null | undefined
): AppView | '' {
  if (!route) return ''

  const pathView = knownAppViewFromPath(route.path || '')
  if (pathView && pathView !== 'lobby') return pathView

  const routeName = typeof route.name === 'string' ? route.name : String(route.name || '')
  if (isAppView(routeName) && routeName !== 'lobby') return routeName

  const hashView = appViewFromLegacyHash(route.hash || '')
  if (hashView !== 'lobby') return hashView

  if (pathView === 'lobby' || routeName === 'lobby') return 'lobby'
  return ''
}

export function appViewFromLegacyHash(hash = globalThis.window?.location?.hash || ''): AppView {
  if (!hash) return 'lobby'
  const routeHash = String(hash || '').split('?')[0]
  return HASH_VIEWS[routeHash] || 'lobby'
}

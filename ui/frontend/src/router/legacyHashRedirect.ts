import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { AppView } from '../types/ui'

const ROUTE_TO_LEGACY_HASH: Record<string, AppView> = {
  '/': 'lobby',
  '/match': 'match',
  '/logs': 'logs',
  '/benchmark': 'benchmark',
  '/evolution': 'evolution'
}

const LEGACY_HASHES: Record<AppView, string> = {
  lobby: '',
  match: 'match',
  logs: 'logs',
  benchmark: 'benchmark',
  evolution: 'evolution'
}

export function appViewFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'path'>): AppView {
  return ROUTE_TO_LEGACY_HASH[route.path] || 'lobby'
}

export function legacyHashForView(view: AppView, search = ''): string {
  const hash = LEGACY_HASHES[view]
  if (!hash) return ''
  const query = search.replace(/^\?/, '')
  return query ? `#${hash}?${query}` : `#${hash}`
}

export function syncInitialRouteToLegacyHash(locationLike: Location = window.location): void {
  const path = locationLike.pathname.replace(/\/+$/, '') || '/'
  const view = ROUTE_TO_LEGACY_HASH[path]
  if (!view || locationLike.hash) return
  const nextHash = legacyHashForView(view, locationLike.search)
  if (!nextHash) return
  locationLike.hash = nextHash
}

export function installLegacyHashBridge(router: Router): void {
  router.afterEach((to) => {
    if (typeof window === 'undefined') return
    if (window.location.hash) return
    const nextHash = legacyHashForView(appViewFromRoute(to), window.location.search)
    if (nextHash) window.location.hash = nextHash
  })
}

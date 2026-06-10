import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { AppView } from '../types/ui'
import {
  appViewFromRoute as routeToAppView,
  appViewHash,
  knownAppViewFromPath
} from './appViews'

export function appViewFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'path'>): AppView {
  return routeToAppView(route)
}

export function legacyHashForView(view: AppView, search = ''): string {
  const hash = appViewHash(view)
  if (!hash) return ''
  const query = search.replace(/^\?/, '')
  return query ? `#${hash}?${query}` : `#${hash}`
}

function legacyHashMatchesView(view: AppView, hash = ''): boolean {
  const viewHash = appViewHash(view)
  if (!viewHash) return !hash
  return String(hash || '').split('?')[0] === `#${viewHash}`
}

function legacyHashForRouteView(view: AppView, search = '', hash = ''): string {
  const query = String(search || '').replace(/^\?/, '')
  if (!query && legacyHashMatchesView(view, hash)) return String(hash || '')
  return legacyHashForView(view, search)
}

function routeOwnedViewFromPath(path = ''): AppView | '' {
  const view = knownAppViewFromPath(path)
  return view && view !== 'lobby' ? view : ''
}

export function syncInitialRouteToLegacyHash(locationLike: Location = window.location): void {
  const view = routeOwnedViewFromPath(locationLike.pathname)
  if (!view) return
  const nextHash = legacyHashForRouteView(view, locationLike.search, locationLike.hash)
  if (!nextHash || locationLike.hash === nextHash) return
  locationLike.hash = nextHash
}

export function installLegacyHashBridge(router: Router): void {
  router.afterEach((to) => {
    if (typeof window === 'undefined') return
    const view = routeOwnedViewFromPath(to.path)
    if (!view) return
    const nextHash = legacyHashForRouteView(view, window.location.search, window.location.hash)
    if (nextHash && window.location.hash !== nextHash) window.location.hash = nextHash
  })
}

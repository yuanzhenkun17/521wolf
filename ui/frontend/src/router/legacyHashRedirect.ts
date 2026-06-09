import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { AppView } from '../types/ui'
import {
  appViewFromPath,
  appViewFromRoute as routeToAppView,
  appViewHash
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

export function syncInitialRouteToLegacyHash(locationLike: Location = window.location): void {
  const view = appViewFromPath(locationLike.pathname)
  if (locationLike.hash) return
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

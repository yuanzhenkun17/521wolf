import type { Component } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { installLegacyHashBridge, syncInitialRouteToLegacyHash } from './legacyHashRedirect'
import { registerLegacyViewRouter } from './legacyViewNavigation'

type PageModule = { default: Component }

const pageModules = import.meta.glob<PageModule>('../pages/*.vue')

function lazyPage(path: keyof typeof pageModules): () => Promise<Component> {
  return () => {
    const loadPage = pageModules[path]
    if (!loadPage) throw new Error(`Route page module not found: ${String(path)}`)
    return loadPage().then((module) => module.default)
  }
}

const LobbyPage = lazyPage('../pages/LobbyPage.vue')
const MatchPage = lazyPage('../pages/MatchPage.vue')
const LogsPage = lazyPage('../pages/LogsPage.vue')
const BenchmarkPage = lazyPage('../pages/BenchmarkPage.vue')
const EvolutionPage = lazyPage('../pages/EvolutionPage.vue')
const TasksPage = lazyPage('../pages/TasksPage.vue')
const SettingsPage = lazyPage('../pages/SettingsPage.vue')

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'lobby', component: LobbyPage },
  { path: '/match', name: 'match', component: MatchPage },
  { path: '/logs', name: 'logs', component: LogsPage },
  { path: '/benchmark', name: 'benchmark', component: BenchmarkPage },
  { path: '/evolution', name: 'evolution', component: EvolutionPage },
  { path: '/tasks', name: 'tasks', component: TasksPage },
  { path: '/settings', name: 'settings', component: SettingsPage }
]

if (typeof window !== 'undefined') {
  syncInitialRouteToLegacyHash()
}

export const router = createRouter({
  history: createWebHistory(),
  routes
})

registerLegacyViewRouter(router)
installLegacyHashBridge(router)

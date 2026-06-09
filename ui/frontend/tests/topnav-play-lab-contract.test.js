import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('TopNav exposes Play and Lab as primary work lines', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /const navItems = \[[\s\S]*key: 'lobby'[\s\S]*line: 'play'[\s\S]*lineLabel: 'Play'[\s\S]*event: 'go-lobby'/)
  assert.match(source, /key: 'logs'[\s\S]*line: 'play'[\s\S]*lineLabel: 'Play'[\s\S]*event: 'open-logs'/)
  assert.match(source, /key: 'benchmark'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-benchmark'/)
  assert.match(source, /key: 'evolution'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-evolution'/)
})

test('TopNav buttons show current page state without changing App routing events', () => {
  const source = readSource('../src/components/TopNav.vue')
  const appSource = readSource('../src/App.vue')

  assert.match(source, /function navItemAriaLabel\(item\)[\s\S]*\$\{item\.lineLabel\} 工作线：\$\{item\.label\}[\s\S]*当前页面/)
  assert.match(source, /import \{ useRoute \} from 'vue-router'/)
  assert.match(source, /import \{ useGameStore, useSessionStore \} from '\.\.\/stores'/)
  assert.match(source, /const routeActiveView = computed\(\(\) => \{/)
  assert.match(source, /const storeActiveView = computed\(\(\) => sessionStore\.currentView \|\| ''\)/)
  assert.match(source, /if \(routeActiveView\.value && routeActiveView\.value !== 'lobby'\) return routeActiveView\.value/)
  assert.match(source, /if \(storeActiveView\.value && storeActiveView\.value !== 'lobby'\) return storeActiveView\.value/)
  assert.match(source, /<nav v-if="variant !== 'match'" class="primary-nav" aria-label="主导航">/)
  assert.match(source, /class="nav-button"[\s\S]*:data-work-line="item\.line"[\s\S]*:aria-current="activeNavView === item\.key \? 'page' : undefined"[\s\S]*:aria-label="navItemAriaLabel\(item\)"/)
  assert.match(source, /<span class="nav-line">\{\{ item\.lineLabel \}\}<\/span>[\s\S]*<span class="nav-label">\{\{ item\.label \}\}<\/span>[\s\S]*<span v-if="activeNavView === item\.key" class="nav-state">当前<\/span>/)

  assert.match(appSource, /import \{ useRoute \} from 'vue-router'/)
  assert.match(appSource, /import \{ useAppRuntimeProps \} from '\.\/composables\/appRuntimeProps'/)
  assert.match(appSource, /import \{ appViewFromRoute \} from '\.\/router\/appViews'/)
  assert.match(appSource, /const route = useRoute\(\)/)
  assert.match(appSource, /\} = useAppRuntimeProps\(runtime\)/)
  assert.match(appSource, /const routeAppView = computed\(\(\) => appViewFromRoute\(route\)\)/)
  assert.match(appSource, /const activeAppView = computed\(\(\) => \{[\s\S]*route\.path === '\/'[\s\S]*runtimeCurrentView\.value !== 'lobby'[\s\S]*return runtimeCurrentView\.value[\s\S]*return routeAppView\.value \|\| runtimeCurrentView\.value[\s\S]*\}\)/)
  assert.match(appSource, /const inLogs = computed\(\(\) => activeAppView\.value === 'logs'\)/)
  assert.match(appSource, /const topNavActiveView = computed\(\(\) => readRuntime\('isReplayMode'\) \? 'logs' : activeAppView\.value\)/)

  assert.match(appSource, /@go-lobby="goLobby"/)
  assert.match(appSource, /@open-logs="openLogPage\(\)"/)
  assert.match(appSource, /@open-benchmark="openBenchmarkPage"/)
  assert.match(appSource, /@open-evolution="openEvolutionPage"/)
})

test('TopNav Play and Lab segment styling stays compact on mobile', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /\.topbar \.primary-nav button\[data-work-line="play"\]\s*\{[\s\S]*--nav-button-accent:\s*#ffb4a8/)
  assert.match(source, /\.topbar \.primary-nav button\[data-work-line="lab"\]\s*\{[\s\S]*--nav-button-accent:\s*#76c7a3/)
  assert.match(source, /\.topbar--lobby \.primary-nav button\[data-work-line="lab"\]\s*\{[\s\S]*color:\s*var\(--nav-button-accent\)/)
  assert.match(source, /\.topbar--lobby \.primary-nav button\[data-work-line="lab"\]:hover\s*\{[\s\S]*background:\s*rgba\(118,\s*199,\s*163,\s*0\.08\)/)
  assert.match(source, /\.topbar--lobby \.primary-nav button\[data-work-line="lab"\]\.active:hover\s*\{[\s\S]*background:\s*rgba\(118,\s*199,\s*163,\s*0\.08\)/)
  assert.match(source, /\.nav-line\s*\{[\s\S]*text-transform:\s*uppercase/)
  assert.match(source, /\.nav-label\s*\{[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/)
  assert.match(source, /\.nav-state\s*\{[\s\S]*position:\s*absolute[\s\S]*pointer-events:\s*none/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.topbar \.primary-nav button\s*\{[\s\S]*grid-template-rows:\s*9px 14px/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.nav-state\s*\{[\s\S]*width:\s*6px[\s\S]*font-size:\s*0/)
})

test('TopNav Play/Lab contract does not remove existing stream status badge contract', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /const streamStatusBadge = computed\(\(\) => \{/)
  assert.match(source, /class="active-session-pill"[\s\S]*:title="streamStatusBadge\.title"[\s\S]*:aria-label="streamStatusBadge\.ariaLabel"/)
  assert.match(source, /class="stream-status-badge"[\s\S]*:data-stream-status="streamStatusBadge\.status"[\s\S]*\{\{ streamStatusBadge\.label \}\}/)
})

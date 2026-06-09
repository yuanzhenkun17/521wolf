import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('TopNav exposes Play and Lab as primary work lines', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /const navItems = \[[\s\S]*key: 'lobby'[\s\S]*line: 'play'[\s\S]*lineLabel: 'Play'[\s\S]*event: 'go-lobby'/)
  assert.match(source, /key: 'logs'[\s\S]*line: 'play'[\s\S]*lineLabel: 'Play'[\s\S]*event: 'open-logs'/)
  assert.match(source, /key: 'evidence'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-evidence'/)
  assert.match(source, /key: 'benchmark'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-benchmark'/)
  assert.match(source, /key: 'evolution'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-evolution'/)
})

test('TopNav buttons show current page state without changing App routing events', () => {
  const source = readSource('../src/components/TopNav.vue')
  const appSource = readSource('../src/App.vue')

  assert.match(source, /function navItemAriaLabel\(item\)[\s\S]*\$\{item\.lineLabel\} 工作线：\$\{item\.label\}[\s\S]*当前页面/)
  assert.match(source, /<nav v-if="variant !== 'match'" class="primary-nav" aria-label="主导航">/)
  assert.match(source, /class="nav-button"[\s\S]*:data-work-line="item\.line"[\s\S]*:aria-current="activeView === item\.key \? 'page' : undefined"[\s\S]*:aria-label="navItemAriaLabel\(item\)"/)
  assert.match(source, /<span class="nav-line">\{\{ item\.lineLabel \}\}<\/span>[\s\S]*<span class="nav-label">\{\{ item\.label \}\}<\/span>[\s\S]*<span v-if="activeView === item\.key" class="nav-state">当前<\/span>/)

  assert.match(appSource, /@go-lobby="goLobby"/)
  assert.match(appSource, /@open-logs="openLogPage\(\)"/)
  assert.match(appSource, /@open-evidence="openEvidencePage\(\)"/)
  assert.match(appSource, /@open-benchmark="openBenchmarkPage"/)
  assert.match(appSource, /@open-evolution="openEvolutionPage"/)
})

test('TopNav Play and Lab segment styling stays compact on mobile', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /\.topbar \.primary-nav button\[data-work-line="play"\]\s*\{[\s\S]*--nav-button-accent:\s*#ffb4a8/)
  assert.match(source, /\.topbar \.primary-nav button\[data-work-line="lab"\]\s*\{[\s\S]*--nav-button-accent:\s*#76c7a3/)
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

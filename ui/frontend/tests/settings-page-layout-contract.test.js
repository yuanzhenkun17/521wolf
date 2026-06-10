import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('SettingsPage copies the task page workbench shell layout', () => {
  const source = readSource('../src/pages/SettingsPage.vue')

  assert.match(source, /class="settings-shell parchment-logbook"/)
  assert.match(source, /class="settings-command-bar"/)
  assert.match(source, /class="settings-detail-topbar"/)
  assert.match(source, /class="settings-control-rail"/)
  assert.match(source, /class="settings-main-pane"/)
  assert.match(source, /class="settings-context-rail"[\s\S]*data-settings-context-rail/)
  assert.match(source, /grid-template-areas:[\s\S]*"rail command context"[\s\S]*"rail topbar context"[\s\S]*"rail pane context"/)
  assert.match(source, /--settings-bg:\s*#f2dfae/)
  assert.match(source, /repeating-linear-gradient\(90deg,\s*rgba\(118,\s*71,\s*27,\s*0\.024\)/)
})

test('SettingsPage follows local secret safety rules', () => {
  const source = readSource('../src/pages/SettingsPage.vue')
  const service = readSource('../src/services/settingsApi.ts')

  assert.match(source, /autocomplete="off"/)
  assert.doesNotMatch(source, /localStorage\.(setItem|getItem)/)
  assert.match(service, /'X-Settings-Admin-Token'/)
  assert.doesNotMatch(service, /localStorage\.(setItem|getItem)/)
})

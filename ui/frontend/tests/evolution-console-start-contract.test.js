import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const consolePanel = readSource('../src/components/evolution/EvolutionConsolePanel.vue')
const page = readSource('../src/pages/EvolutionPage.vue')

test('Evolution console start area only exposes the current-role launch action', () => {
  assert.match(consolePanel, /class="evo-start-panel"/)
  assert.match(consolePanel, /<small>启动对象<\/small>/)
  assert.match(consolePanel, /\{\{ evo\.selectedRoleLabel\.value \|\| '当前角色' \}\}/)
  assert.match(consolePanel, /class="evo-action evo-start-action"/)
  assert.match(consolePanel, /@click="evo\.startSingle\(\)"/)
  assert.match(consolePanel, /启动当前角色/)

  assert.doesNotMatch(consolePanel, /class="evo-batch-role-grid"/)
  assert.doesNotMatch(consolePanel, /class="\['evo-role-toggle'/)
  assert.doesNotMatch(consolePanel, /@click="evo\.toggleBatchRole\(role\.key\)"/)
  assert.doesNotMatch(consolePanel, /@click="evo\.startBatch\(\)"/)
  assert.doesNotMatch(consolePanel, />\s*批量\s*</)
  assert.doesNotMatch(consolePanel, />\s*单角色\s*</)
})

test('Evolution console start layout has no leftover batch selector styles', () => {
  assert.match(page, /\.evo-form-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(3,\s*minmax\(140px,\s*1fr\)\) minmax\(180px,\s*0\.9fr\) minmax\(190px,\s*0\.95fr\)/)
  assert.match(page, /\.evo-start-panel\s*\{/)
  assert.match(page, /\.evo-start-action\s*\{/)
  assert.doesNotMatch(page, /\.evo-batch-role-grid\s*\{/)
  assert.doesNotMatch(page, /\.evo-role-toggle\s*\{/)
  assert.doesNotMatch(page, /\.evo-command-row\s*\{/)
})

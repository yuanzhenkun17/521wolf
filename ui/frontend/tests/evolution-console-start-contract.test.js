import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const consolePanel = readSource('../src/components/evolution/EvolutionConsolePanel.vue')
const page = readSource('../src/pages/EvolutionPage.vue')
const runsPanel = readSource('../src/components/evolution/EvolutionRunsPanel.vue')
const samplesPanel = readSource('../src/components/evolution/EvolutionSamplesPanel.vue')

test('Evolution console start area only exposes the current-role launch action', () => {
  assert.match(consolePanel, /class="evo-start-panel"/)
  assert.match(consolePanel, /class="evo-form-grid evo-console-grid"/)
  assert.match(consolePanel, /class="evo-console-fields"/)
  assert.match(consolePanel, /class="evo-console-actions"/)
  assert.match(consolePanel, /class="evo-run-actions"/)
  assert.doesNotMatch(consolePanel, /<small>启动对象<\/small>/)
  assert.doesNotMatch(consolePanel, /\{\{ evo\.selectedRoleLabel\.value \|\| '当前角色' \}\}/)
  assert.match(consolePanel, /class="evo-action evo-start-action"/)
  assert.match(consolePanel, /@click="evo\.startSingle\(\)"/)
  assert.match(consolePanel, />\s*启动\s*</)
  assert.match(consolePanel, /class="evo-action evo-action-promote"/)
  assert.match(consolePanel, /class="evo-action evo-action-reject"/)
  assert.match(consolePanel, /class="evo-action evo-action-terminate"/)
  assert.match(consolePanel, /class="evo-review-head-kpis"/)

  assert.doesNotMatch(consolePanel, /class="evo-batch-role-grid"/)
  assert.doesNotMatch(consolePanel, /class="\['evo-role-toggle'/)
  assert.doesNotMatch(consolePanel, /@click="evo\.toggleBatchRole\(role\.key\)"/)
  assert.doesNotMatch(consolePanel, /@click="evo\.startBatch\(\)"/)
  assert.doesNotMatch(consolePanel, />\s*批量\s*</)
  assert.doesNotMatch(consolePanel, />\s*单角色\s*</)
})

test('Evolution console start layout has no leftover batch selector styles', () => {
  assert.match(page, /\.evo-form-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(280px,\s*1fr\) minmax\(238px,\s*auto\)[\s\S]*"fields actions"[\s\S]*"gate actions"/)
  assert.match(page, /\.evo-console-fields\s*\{[\s\S]*grid-area:\s*fields[\s\S]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(page, /\.evo-runtime-gate\s*\{[\s\S]*grid-area:\s*gate[\s\S]*min-height:\s*58px/)
  assert.match(page, /\.evo-console-actions\s*\{[\s\S]*grid-area:\s*actions[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)[\s\S]*width:\s*238px/)
  assert.match(page, /\.evo-page \*:not\(svg\):not\(svg \*\)\s*\{[\s\S]*box-sizing:\s*border-box/)
  assert.match(page, /\.evo-context-rail\s*\{[\s\S]*max-width:\s*100%[\s\S]*border-left:\s*1px solid rgba\(93,\s*48,\s*17,\s*0\.2\);/)
  assert.match(page, /@media \(max-width: 960px\)[\s\S]*\.evo-context-rail\s*\{[\s\S]*border-left:\s*none;/)
  assert.match(page, /\.evo-context-head,\s*[\s\S]*\.evo-context-section\s*\{[\s\S]*max-width:\s*100%/)
  assert.match(page, /\.evo-start-panel\s*\{/)
  assert.match(page, /\.evo-start-action\s*\{/)
  assert.match(page, /@media \(max-width: 960px\)[\s\S]*\.evo-console-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)[\s\S]*"fields"[\s\S]*"gate"[\s\S]*"actions"/)
  assert.match(page, /\.evo-action-promote\s*\{/)
  assert.match(page, /\.evo-review-head-kpis\s*\{/)
  assert.match(page, /\.evo-progress-card,\s*[\s\S]*\.evo-config-grid span,[\s\S]*border-radius:\s*0/)
  assert.match(page, /\.evo-command-bar\s*\{[\s\S]*grid-template-columns:\s*188px minmax\(0, 1fr\) 78px[\s\S]*min-height:\s*57px[\s\S]*padding:\s*10px 0 12px/)
  assert.doesNotMatch(page, /\.evo-batch-role-grid\s*\{/)
  assert.doesNotMatch(page, /\.evo-role-toggle\s*\{/)
  assert.doesNotMatch(page, /\.evo-command-row\s*\{/)
})

test('Evolution paginated lists keep load-more affordance without loaded copy', () => {
  assert.match(runsPanel, /v-if="evo\.runHasMore\.value" class="evo-run-more"/)
  assert.match(runsPanel, /@click="evo\.loadMoreRuns\(\)"/)
  assert.doesNotMatch(runsPanel, /已载入/)
  assert.match(samplesPanel, /v-if="evo\.sampleGameHasMore\.value" class="evo-run-more"/)
  assert.match(samplesPanel, /@click="evo\.loadMoreSampleGames\(evo\.selectedGameBucket\.value\)"/)
  assert.doesNotMatch(samplesPanel, /已载入/)
})

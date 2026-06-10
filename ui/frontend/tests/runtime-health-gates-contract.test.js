import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('runtime health gates are consumed by all launch surfaces', () => {
  const lobby = read('../src/pages/LobbyPage.vue')
  const benchmarkPage = read('../src/pages/BenchmarkPage.vue')
  const benchmarkWorkbench = read('../src/composables/useEvaluationWorkbench.ts')
  const evolutionPage = read('../src/pages/EvolutionPage.vue')
  const evolutionWorkbench = read('../src/composables/useEvolutionWorkbench.ts')
  const evolutionConsole = read('../src/components/evolution/EvolutionConsolePanel.vue')

  assert.match(lobby, /runtimeHealthGateSummary\(props\.runtimeHealth,\s*'game_start'\)/)
  assert.match(lobby, /gameStartBlocked/)
  assert.match(lobby, /'lobby-runtime-gate'/)

  assert.match(benchmarkWorkbench, /runtimeHealthGateSummary\(runtimeHealth\.value,\s*'benchmark_start'\)/)
  assert.match(benchmarkWorkbench, /async function loadRuntimeHealth\(\)/)
  assert.match(benchmarkPage, /benchmark\.runtimeHealthGateBlocked\.value/)
  assert.match(benchmarkPage, /benchmarkRuntime\.loadRuntimeHealth/)

  assert.match(evolutionWorkbench, /runtimeHealthGateSummary\(runtimeHealth\.value,\s*'evolution_start'\)/)
  assert.match(evolutionWorkbench, /async function loadRuntimeHealth\(\)/)
  assert.match(evolutionPage, /evolutionRuntime\.loadRuntimeHealth/)
  assert.match(evolutionConsole, /class="evo-runtime-gate"/)
  assert.match(evolutionConsole, /evo\.runtimeHealthGateBlocked/)
})

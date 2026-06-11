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
  const benchmarkTargetSelector = read('../src/components/benchmark/BenchmarkTargetSelector.vue')
  const evolutionPage = read('../src/pages/EvolutionPage.vue')
  const evolutionWorkbench = read('../src/composables/useEvolutionWorkbench.ts')
  const evolutionConsole = read('../src/components/evolution/EvolutionConsolePanel.vue')

  assert.match(lobby, /runtimeHealthGateSummary\(props\.runtimeHealth,\s*'game_start'\)/)
  assert.match(lobby, /runtimeHealthPreflightStatusText\(modelProfilePreflight\.value,\s*'game_start'\)/)
  assert.match(lobby, /const gameStartGate = computed/)
  assert.match(lobby, /showGameStartGate/)
  assert.match(lobby, /'lobby-runtime-gate'/)
  assert.match(lobby, /runtimeHealthPayloadFromPreflight/)
  assert.match(lobby, /\/health\/preflight\?\$\{query\.toString\(\)\}/)
  assert.match(lobby, /model_profile_id/)
  assert.match(lobby, /\.lobby-model-panel small \{[\s\S]*overflow-wrap: anywhere;[\s\S]*white-space: normal;/)

  assert.match(benchmarkWorkbench, /runtimeHealthGateSummary\(effectiveRuntimeHealth\.value,\s*'benchmark_start'\)/)
  assert.match(benchmarkWorkbench, /async function loadRuntimeHealth\(\)/)
  assert.match(benchmarkWorkbench, /runtimeHealthPayloadFromPreflight/)
  assert.match(benchmarkWorkbench, /\/health\/preflight\?\$\{query\.toString\(\)\}/)
  assert.match(benchmarkWorkbench, /model_profile_id/)
  assert.match(benchmarkWorkbench, /benchmark_model_profile_invalid/)
  assert.match(benchmarkWorkbench, /评测模型 Profile 不可用/)
  assert.match(benchmarkWorkbench, /WEREWOLF_LLM_\* 环境变量锁定默认模型/)
  assert.match(benchmarkPage, /benchmark\.runtimeHealthGateBlocked\.value/)
  assert.match(benchmarkPage, /benchmarkRuntime\.loadRuntimeHealth/)
  assert.match(benchmarkPage, /selectedModelProfileLabel/)
  assert.match(benchmarkTargetSelector, /v-model\.trim="benchmark\.form\.value\.model_profile_id"/)
  assert.match(benchmarkTargetSelector, /benchmark\.loadModelProfiles\(\)/)
  assert.match(benchmarkTargetSelector, /runtimeHealthPreflightStatusText\(props\.benchmark\.modelProfilePreflight\.value,\s*'benchmark_start'\)/)
  assert.match(benchmarkTargetSelector, /\.target-warning \{[\s\S]*overflow-wrap: anywhere;/)

  assert.match(evolutionWorkbench, /runtimeHealthGateSummary\(effectiveRuntimeHealth\.value,\s*'evolution_start'\)/)
  assert.match(evolutionWorkbench, /async function loadRuntimeHealth\(\)/)
  assert.match(evolutionWorkbench, /runtimeHealthPayloadFromPreflight/)
  assert.match(evolutionWorkbench, /\/health\/preflight\?\$\{query\.toString\(\)\}/)
  assert.match(evolutionWorkbench, /model_profile_id/)
  assert.match(evolutionWorkbench, /evolution_model_profile_invalid/)
  assert.match(evolutionWorkbench, /自进化模型 Profile 不可用/)
  assert.match(evolutionWorkbench, /WEREWOLF_LLM_\* 环境变量锁定默认模型/)
  assert.match(evolutionPage, /evolutionRuntime\.loadRuntimeHealth/)
  assert.match(evolutionConsole, /class="evo-runtime-gate"/)
  assert.match(evolutionConsole, /evo\.runtimeHealthGateBlocked/)
  assert.match(evolutionConsole, /v-model="evo\.form\.value\.model_profile_id"/)
  assert.match(evolutionConsole, /runtimeHealthPreflightStatusText\(evo\.modelProfilePreflight\.value,\s*'evolution_start'\)/)
  assert.match(evolutionPage, /\.evo-console-field--model small \{[\s\S]*overflow-wrap: anywhere;[\s\S]*white-space: normal;/)
  assert.match(evolutionPage, /\.evo-runtime-gate strong,[\s\S]*\.evo-runtime-gate small \{[\s\S]*overflow-wrap: anywhere;[\s\S]*white-space: normal;/)
})

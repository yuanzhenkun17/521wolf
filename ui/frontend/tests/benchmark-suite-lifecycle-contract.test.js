import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function assertSfcCompiles(relativePath, id) {
  const filename = new URL(relativePath, import.meta.url).pathname
  const source = readSource(relativePath)
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [])
  compileScript(descriptor, { id })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id
  })
  assert.deepEqual(template.errors, [])
}

test('Benchmark suite lifecycle is normalized in the workbench composable', () => {
  const source = readSource('../src/composables/useEvaluationWorkbench.ts')

  assert.match(source, /const BENCHMARK_SUITE_LAUNCHABLE_STATUSES = new Set\(\['enabled', 'active'\]\)/)
  assert.match(source, /const benchmarkSeedSets = ref\(\[\]\)/)
  assert.match(source, /const seedSetRequests = createLatestOnlyTracker\(\)/)
  assert.match(source, /async function loadBenchmarkSeedSets\(\)/)
  assert.match(source, /apiFetch\('\/benchmark\/seed-sets'\)/)
  assert.match(source, /normalizeBenchmarkSeedRegistry/)
  assert.match(source, /await loadBenchmarkSeedSets\(\)/)
  assert.match(source, /normalizeBenchmarkSuite\(item, seedRegistryById\)/)
  assert.match(source, /deprecated:\s*'废弃'/)
  assert.match(source, /launch_disabled_reason: benchmarkSuiteLaunchDisabledReason\(raw, status, launchable\)/)
  assert.match(source, /const selectedBenchmarkSuiteLaunchDisabledReason = computed/)
  assert.match(source, /!selectedBenchmarkSuiteLaunchDisabledReason\.value/)
  assert.match(source, /benchmarkPlanError\.value = selectedBenchmarkSuiteLaunchDisabledReason\.value/)
  assert.match(source, /setNotice\('warning', message\)/)
  assert.match(source, /benchmarkSeedSets,/)
  assert.match(source, /loadBenchmarkSeedSets,/)
})

test('BenchmarkPage context renders selected suite lifecycle, seed, gates, metrics, and judge details', () => {
  const source = readSource('../src/pages/BenchmarkPage.vue')
  const railSource = readSource('../src/components/benchmark/BenchmarkSuiteRail.vue')

  assert.match(source, /const contextSuiteDetailRows = computed/)
  assert.match(source, /const contextSuiteSeedRows = computed/)
  assert.match(source, /const contextSuiteMetricRows = computed/)
  assert.match(source, /const contextSuiteJudgeRows = computed/)
  assert.match(source, /const contextGateRows = computed/)
  assert.match(source, /label: 'Config Hash'/)
  assert.match(source, /label: '种子集'/)
  assert.match(source, /label: '种子版本'/)
  assert.match(source, /label: '种子层级'/)
  assert.match(source, /label: '对象类型'/)
  assert.match(source, /label: '创建时间'/)
  assert.match(source, /label: '使用边界'/)
  assert.match(source, /label: '非重叠组'/)
  assert.match(source, /label: '不可变'/)
  assert.match(source, /label: 'Seed Hash'/)
  assert.match(source, /label: '重叠警告'/)
  assert.match(source, /主指标/)
  assert.match(source, /最少完成局/)
  assert.match(source, /裁判判定/)
  assert.match(source, /套件详情/)

  assert.doesNotMatch(railSource, /selectedSpecRows|selectedSeedRows|selectedMetricRows|selectedGateRows|selectedJudgeRows/)
})

test('BenchmarkPage exposes lifecycle status and launch disabled reason in the launch area', () => {
  const source = readSource('../src/pages/BenchmarkPage.vue')

  assert.match(source, /const launchDisabledReason = computed/)
  assert.match(source, /label: '生命周期'/)
  assert.match(source, /value: launchDisabledReason\.value \? '不可启动'/)
  assert.match(source, /:title="launchDisabledReason \|\| undefined"/)
  assert.match(source, /<div v-if="launchDisabledReason" class="bench-inline-warning">/)
})

test('suite lifecycle SFCs compile', () => {
  assertSfcCompiles('../src/components/benchmark/BenchmarkSuiteRail.vue', 'benchmark-suite-lifecycle-rail-test')
  assertSfcCompiles('../src/pages/BenchmarkPage.vue', 'benchmark-suite-lifecycle-page-test')
})

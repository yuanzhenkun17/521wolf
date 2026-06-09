import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
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
  const source = readSource('../src/composables/useEvaluationWorkbench.js')

  assert.match(source, /const BENCHMARK_SUITE_LAUNCHABLE_STATUSES = new Set\(\['enabled', 'active'\]\)/)
  assert.match(source, /deprecated:\s*'废弃'/)
  assert.match(source, /launch_disabled_reason: benchmarkSuiteLaunchDisabledReason\(raw, status, launchable\)/)
  assert.match(source, /const selectedBenchmarkSuiteLaunchDisabledReason = computed/)
  assert.match(source, /!selectedBenchmarkSuiteLaunchDisabledReason\.value/)
  assert.match(source, /benchmarkPlanError\.value = selectedBenchmarkSuiteLaunchDisabledReason\.value/)
  assert.match(source, /setNotice\('warning', message\)/)
})

test('BenchmarkSuiteRail renders selected suite spec, lifecycle, seed, gates, metrics, and judge details', () => {
  const source = readSource('../src/components/benchmark/BenchmarkSuiteRail.vue')

  assert.match(source, /const selectedSpecRows = computed/)
  assert.match(source, /label: 'Config Hash'/)
  assert.match(source, /const selectedSeedRows = computed/)
  assert.match(source, /label: '种子集'/)
  assert.match(source, /const selectedMetricRows = computed/)
  assert.match(source, /主指标/)
  assert.match(source, /const selectedGateRows = computed/)
  assert.match(source, /最少完成局/)
  assert.match(source, /const selectedJudgeRows = computed/)
  assert.match(source, /裁判配置/)
  assert.match(source, /selectedSuite\.launchDisabledReason/)
  assert.match(source, /{{ selectedSuite\.launchable \? '可启动' : '不可启动' }}/)
  assert.match(source, /套件详情/)
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

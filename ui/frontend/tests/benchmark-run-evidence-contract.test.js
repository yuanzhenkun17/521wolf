import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import { useEvaluationWorkbench } from '../src/composables/useEvaluationWorkbench.js'

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

async function flushPromises(count = 6) {
  for (let index = 0; index < count; index += 1) await Promise.resolve()
}

test('BenchmarkBatchRunsTable exposes run game status filtering and pagination evidence', () => {
  const source = readSource('../src/components/benchmark/BenchmarkBatchRunsTable.vue')

  assert.match(source, /const detailGames = computed\(\(\) => props\.benchmark\.benchmarkBatchGames\.value\)/)
  assert.match(source, /const detailPagination = computed\(\(\) => props\.benchmark\.benchmarkBatchGamePagination\.value \|\| \{\}\)/)
  assert.match(source, /const detailGamesLoading = computed\(\(\) => Boolean\(props\.benchmark\.benchmarkBatchGamesLoading\?\.value\)\)/)
  assert.match(source, /const loadedGameCount = computed\(\(\) => detailGames\.value\.length\)/)
  assert.match(source, /const hasMoreGames = computed\(\(\) => Boolean\(detailPagination\.value\.has_more\)\)/)
  assert.match(source, /const gameStatusOptions = \[/)
  for (const value of ['problem', 'all', 'failed', 'timeout', 'abnormal', 'completed']) {
    assert.match(source, new RegExp(`\\{ value: '${value}'`))
  }
  assert.match(source, /:value="benchmark\.benchmarkGameStatusFilter\.value"/)
  assert.match(source, /@change="benchmark\.setBenchmarkGameStatusFilter\(\$event\.target\.value\)"/)
  assert.match(source, /:value="benchmark\.benchmarkGameSeedFilter\.value"/)
  assert.match(source, /@change="setGameSeedFilter"/)
  assert.match(source, /@click="benchmark\.loadNextBenchmarkBatchGamesPage\(\)"/)
  assert.match(source, /已加载 \{\{ loadedGameCount \}\} \/ 共 \{\{ totalGameCount \}\} 条/)
  assert.doesNotMatch(source, /detailPagination\.returned \|\| detailGames\.length/)
  assert.match(source, /benchmark\.benchmarkDiagnosticKindFilter\.value/)
  assert.match(source, /benchmark\.benchmarkDiagnosticLevelFilter\.value/)
  assert.match(source, /benchmark\.benchmarkDiagnosticStatusFilter\.value/)
  assert.match(source, /benchmark\.benchmarkDiagnosticStageFilter\.value/)
  assert.match(source, /benchmark\.benchmarkDiagnosticSeedFilter\.value/)
  assert.match(source, /@change="setDiagnosticFilter\('kind', \$event\)"/)
  assert.match(source, /diagnosticReplayHash\(item\)/)
})

test('BenchmarkDiagnosticsExplorer links selected diagnostics to affected game ids', () => {
  const source = readSource('../src/components/benchmark/BenchmarkDiagnosticsExplorer.vue')

  assert.match(source, /const problemGames = computed\(\(\) => \{/)
  assert.match(source, /const id = String\(game\?\.game_id \|\| game\?\.id \|\| ''\)/)
  assert.match(source, /game\.diagnosticMatches \+= 1/)
  assert.match(source, /const selectedDiagnosticGames = computed\(\(\) => \{/)
  assert.match(source, /if \(diagnostic\.game_id\) ids\.add\(String\(diagnostic\.game_id\)\)/)
  assert.match(source, /diagnostic\.kind &&\s*item\.kind === diagnostic\.kind &&\s*item\.game_id/s)
  assert.match(source, /statusLabel: '未加载'/)
  assert.match(source, /function inspectSelectedGames\(\) \{/)
  assert.match(source, /props\.benchmark\.selectBenchmarkBatch\(diagnostic\.batch_id\)/)
  assert.match(source, /props\.benchmark\.setBenchmarkGameStatusFilter\('problem'\)/)
  assert.match(source, /props\.benchmark\.setBenchmarkGameSeedFilter\(seed\)/)
  assert.match(source, /<a v-if="game\.replayHash" class="diagnostic-replay-link" :href="game\.replayHash">/)
})

test('useEvaluationWorkbench requests filtered batch games and diagnostics pages', () => {
  const source = readSource('../src/composables/useEvaluationWorkbench.js')

  assert.match(source, /const benchmarkBatchGamePagination = ref\(\{ total: 0, offset: 0, limit: 20, returned: 0, has_more: false \}\)/)
  assert.match(source, /const benchmarkBatchDiagnosticsLoading = ref\(false\)/)
  assert.match(source, /const benchmarkGameStatusFilter = ref\('problem'\)/)
  assert.match(source, /const benchmarkGameSeedFilter = ref\(''\)/)
  assert.match(source, /const benchmarkDiagnosticKindFilter = ref\(''\)/)
  assert.match(source, /function gameStatusFilterQuery\(\) \{/)
  assert.match(source, /if \(!filter \|\| filter === 'all'\) return ''/)
  assert.match(source, /if \(filter === 'problem'\) return 'problem'/)
  assert.match(source, /if \(seedFilter\) query\.set\('seed', seedFilter\)/)
  assert.match(source, /query\.set\('limit', String\(limit\)\)/)
  assert.match(source, /query\.set\('offset', String\(offset\)\)/)
  assert.match(source, /function benchmarkBatchDiagnosticsPath\(batchId\) \{/)
  assert.match(source, /\['kind', benchmarkDiagnosticKindFilter\.value\]/)
  assert.match(source, /\['status', benchmarkDiagnosticStatusFilter\.value\]/)
  assert.match(source, /const gamesPath = benchmarkBatchGamesPath\(id\)/)
  assert.match(source, /benchmarkBatchGamePagination\.value = games\?\.pagination \|\| defaultBenchmarkGamePagination\(\)/)
  assert.match(source, /function setBenchmarkGameStatusFilter\(status\) \{/)
  assert.match(source, /void loadBenchmarkBatchGamesPage\(\{ offset: 0, append: false \}\)/)
  assert.match(source, /function setBenchmarkDiagnosticFilter\(name, value\) \{/)
  assert.match(source, /void loadBenchmarkBatchDiagnostics\(selectedBenchmarkBatchId\.value\)/)
})

test('useEvaluationWorkbench reloads and appends filtered run evidence pages', async () => {
  const requests = []
  const apiFetch = async (path) => {
    requests.push(String(path))
    if (path === '/benchmark/batch/run-evidence') {
      return {
        kind: 'benchmark_batch_detail',
        batch_id: 'run-evidence',
        status: 'completed',
        benchmark: { id: 'role-baseline-v1', version: 1, target_type: 'role_version' },
        results: [],
        game_summary: { total: 2, by_status: { failed: 1, timeout: 1 } },
        diagnostic_summary: { total: 1, by_kind: { game_failure: 1 } }
      }
    }
    if (path.startsWith('/benchmark/batch/run-evidence/diagnostics')) {
      const query = path.includes('?') ? new URLSearchParams(path.split('?')[1]) : new URLSearchParams()
      return {
        kind: 'benchmark_batch_diagnostics',
        batch_id: 'run-evidence',
        filters: {
          kind: query.get('kind'),
          seed: query.get('seed')
        },
        diagnostics: [{
          origin: 'game',
          kind: 'game_failure',
          level: 'warning',
          stage: 'game.persist',
          message: 'persist failed',
          game_id: 'run-game-001',
          seed: 260902
        }],
        summary: { total: 1, by_kind: { game_failure: 1 }, by_level: { warning: 1 } }
      }
    }
    if (path === '/benchmark/batch/run-evidence/report') {
      return { kind: 'benchmark_run_report', batch_id: 'run-evidence', summary: {}, results: [], games: [], diagnostics: [] }
    }
    if (path.startsWith('/benchmark/batch/run-evidence/games?')) {
      const query = new URLSearchParams(path.split('?')[1])
      const status = query.get('status') || 'all'
      const seed = query.get('seed') || ''
      const offset = Number(query.get('offset') || 0)
      const gameId = offset === 20 ? 'run-game-003' : (status === 'failed' ? 'run-game-001' : 'run-game-002')
      return {
        kind: 'benchmark_batch_games',
        batch_id: 'run-evidence',
        status,
        seed,
        games: [{
          game_id: gameId,
          status: status === 'failed' ? 'failed' : 'timeout',
          seed: seed || (status === 'failed' ? 260902 : 260903),
          diagnostic_count: 1,
          decision_count: 0,
          event_count: 0
        }],
        pagination: {
          total: 21,
          offset,
          limit: 20,
          returned: offset === 20 ? 1 : 20,
          has_more: offset !== 20
        }
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  const loaded = await workbench.loadBenchmarkBatchDetail('run-evidence')

  assert.equal(loaded, true)
  assert.equal(workbench.benchmarkGameStatusFilter.value, 'problem')
  assert.equal(workbench.benchmarkBatchGamePagination.value.has_more, true)
  assert.equal(
    requests.includes('/benchmark/batch/run-evidence/games?status=problem&limit=20&offset=0'),
    true
  )

  assert.equal(workbench.loadNextBenchmarkBatchGamesPage(), true)
  await flushPromises()
  assert.equal(workbench.benchmarkBatchGames.value.length, 2)
  assert.equal(workbench.benchmarkBatchGames.value[1].game_id, 'run-game-003')
  assert.equal(
    requests.includes('/benchmark/batch/run-evidence/games?status=problem&limit=20&offset=20'),
    true
  )

  workbench.setBenchmarkGameStatusFilter('failed')
  await flushPromises()

  assert.equal(workbench.benchmarkGameStatusFilter.value, 'failed')
  assert.equal(workbench.benchmarkBatchGames.value[0].game_id, 'run-game-001')
  assert.deepEqual(workbench.benchmarkBatchGamePagination.value, {
    total: 21,
    offset: 0,
    limit: 20,
    returned: 20,
    has_more: true
  })
  assert.equal(
    requests.includes('/benchmark/batch/run-evidence/games?status=failed&limit=20&offset=0'),
    true
  )

  workbench.setBenchmarkGameSeedFilter('260902')
  await flushPromises()

  assert.equal(workbench.benchmarkGameSeedFilter.value, '260902')
  assert.equal(
    requests.includes('/benchmark/batch/run-evidence/games?status=failed&seed=260902&limit=20&offset=0'),
    true
  )

  workbench.setBenchmarkDiagnosticFilter('kind', 'game_failure')
  await flushPromises()
  workbench.setBenchmarkDiagnosticFilter('seed', '260902')
  await flushPromises()

  assert.equal(workbench.benchmarkDiagnosticKindFilter.value, 'game_failure')
  assert.equal(workbench.benchmarkDiagnosticSeedFilter.value, '260902')
  assert.equal(
    requests.includes('/benchmark/batch/run-evidence/diagnostics?kind=game_failure'),
    true
  )
  assert.equal(
    requests.includes('/benchmark/batch/run-evidence/diagnostics?kind=game_failure&seed=260902'),
    true
  )
})

test('run evidence SFCs compile after contract assertions', () => {
  assertSfcCompiles('../src/components/benchmark/BenchmarkBatchRunsTable.vue', 'benchmark-run-table-evidence-test')
  assertSfcCompiles('../src/components/benchmark/BenchmarkDiagnosticsExplorer.vue', 'benchmark-diagnostics-evidence-test')
})

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'
import { ApiError } from '../src/composables/gameApi.ts'
import {
  formatApiErrorForDisplay,
  inlineNoticeForDisplay,
  normalizeDiagnostics,
  noticeErrorForPanel
} from '../src/composables/apiErrorDisplay.ts'

const apiErrorPanelSourceUrl = new URL('../src/components/ApiErrorPanel.vue', import.meta.url)

test('formatApiErrorForDisplay preserves domain code diagnostics and request id', () => {
  const error = new ApiError({
    status: 409,
    code: 'benchmark_target_version_not_allowed',
    message: 'Benchmark target version is not allowed.',
    detail: 'benchmark target version not allowed: seer/seer_shadow_v1 is release_stage=shadow',
    requestId: 'req-409',
    diagnostics: [{
      kind: 'benchmark_target_version_not_allowed',
      role: 'seer',
      version_id: 'seer_shadow_v1',
      release_stage: 'shadow',
      allowed_flow: 'benchmark_canary_or_baseline'
    }]
  })

  const view = formatApiErrorForDisplay(error, '评测启动失败')

  assert.equal(view.status, 409)
  assert.equal(view.code, 'benchmark_target_version_not_allowed')
  assert.equal(view.message, 'Benchmark target version is not allowed.')
  assert.equal(view.detail, 'benchmark target version not allowed: seer/seer_shadow_v1 is release_stage=shadow')
  assert.equal(view.requestId, 'req-409')
  assert.equal(view.hasDiagnostics, true)
  assert.deepEqual(view.diagnostics[0].meta, [
    'role=seer',
    'version=seer_shadow_v1',
    'release_stage=shadow',
    'allowed_flow=benchmark_canary_or_baseline'
  ])
})

test('normalizeDiagnostics formats validation and plain diagnostic rows', () => {
  const rows = normalizeDiagnostics([
    { type: 'greater_than_equal', loc: ['body', 'max_days'], msg: 'Input should be >= 1' },
    'backend offline'
  ])

  assert.equal(rows[0].label, 'greater_than_equal')
  assert.equal(rows[0].message, 'Input should be >= 1')
  assert.equal(rows[1].label, 'backend offline')
})

test('BenchmarkPage notice mapping sends error notices to the ApiErrorPanel path', () => {
  const error = new ApiError({
    status: 409,
    code: 'benchmark_target_version_not_allowed',
    message: 'shadow target cannot run benchmark',
    diagnostics: [{ kind: 'release_stage_not_allowed', role: 'seer', release_stage: 'shadow' }]
  })
  const notice = { type: 'error', message: '评测启动失败', error }

  assert.equal(inlineNoticeForDisplay(notice), null)
  assert.equal(noticeErrorForPanel(notice), error)
  assert.equal(formatApiErrorForDisplay(noticeErrorForPanel(notice), '评测操作失败').code, 'benchmark_target_version_not_allowed')

  const warning = { type: 'warning', message: '评测已启动，但列表刷新失败。' }
  assert.deepEqual(inlineNoticeForDisplay(warning), warning)
  assert.equal(noticeErrorForPanel(warning), null)
})

test('ApiErrorPanel exposes retry contract and BenchmarkPage wires it to refresh', () => {
  const panelSource = readFileSync(apiErrorPanelSourceUrl, 'utf8')
  const benchmarkSource = readFileSync(new URL('../src/pages/BenchmarkPage.vue', import.meta.url), 'utf8')

  assert.match(panelSource, /retryLabel:\s*\{\s*type:\s*String,\s*default:\s*''\s*\}/)
  assert.match(panelSource, /retryBusyLabel:\s*\{\s*type:\s*String,\s*default:\s*'重试中'\s*\}/)
  assert.match(panelSource, /retrying:\s*Boolean/)
  assert.match(panelSource, /retryDisabled:\s*Boolean/)
  assert.match(panelSource, /const emit = defineEmits\(\['retry'\]\)/)
  assert.match(panelSource, /function handleRetry\(\)[\s\S]*retryDisabled[\s\S]*retrying[\s\S]*emit\('retry'\)/)
  assert.match(panelSource, /class="api-error-panel__retry"[\s\S]*:disabled="retryDisabled \|\| retrying"[\s\S]*@click="handleRetry"/)

  assert.match(benchmarkSource, /function refresh\(\)[\s\S]*benchmark\.refreshAll\(\{ notify: true \}\)/)
  assert.match(benchmarkSource, /<ApiErrorPanel[\s\S]*v-if="benchErrorNotice"[\s\S]*retry-label="重试刷新"[\s\S]*retry-busy-label="刷新中"[\s\S]*:retrying="Boolean\(benchmark\.loading\.value\)"[\s\S]*:retry-disabled="Boolean\(benchmark\.loading\.value \|\| benchmark\.actionLoading\.value\)"[\s\S]*@retry="refresh"/)
})

test('Evolution and Logs error panels wire retry to existing refresh/reload paths', () => {
  const evolutionSource = readFileSync(new URL('../src/components/evolution/EvolutionWorkbenchShell.vue', import.meta.url), 'utf8')
  const logsSource = readFileSync(new URL('../src/pages/LogsPage.vue', import.meta.url), 'utf8')

  assert.match(evolutionSource, /const refreshRetrying = computed\(\(\) => Boolean\(runSummary\.value\.loading\)\)/)
  assert.match(evolutionSource, /const refreshRetryDisabled = computed\(\(\) => Boolean\(runSummary\.value\.loading \|\| runSummary\.value\.actionLoading\)\)/)
  assert.match(evolutionSource, /function retryRefresh\(\)[\s\S]*refreshRetryDisabled\.value[\s\S]*emit\('refresh'\)/)
  assert.match(evolutionSource, /<ApiErrorPanel[\s\S]*v-if="errorNotice"[\s\S]*class="evo-error-panel"[\s\S]*retry-label="重试刷新"[\s\S]*retry-busy-label="刷新中"[\s\S]*:retrying="refreshRetrying"[\s\S]*:retry-disabled="refreshRetryDisabled"[\s\S]*@retry="retryRefresh"/)

  assert.match(logsSource, /const detailRetrying = computed\(\(\) =>[\s\S]*props\.historyLoading[\s\S]*selectedPhaseLoading\.value[\s\S]*props\.archiveLoading[\s\S]*props\.reviewLoading[\s\S]*selectedFlowLoading\.value/)
  assert.match(logsSource, /const detailRetryAvailable = computed\(\(\) => \{[\s\S]*workspaceTab\.value === 'review'[\s\S]*props\.loadReview[\s\S]*workspaceTab\.value === 'archive'[\s\S]*props\.loadArchive[\s\S]*props\.loadMoreHistoryPhaseDetail/)
  assert.match(logsSource, /function retrySelectedDetail\(\)[\s\S]*detailRetryDisabled\.value[\s\S]*workspaceTab\.value === 'review'[\s\S]*loadSelectedReview\(\)[\s\S]*workspaceTab\.value === 'archive'[\s\S]*loadSelectedArchive\(\)[\s\S]*loadMoreSelectedPhase\(\)/)
  assert.match(logsSource, /<ApiErrorPanel[\s\S]*v-if="detailErrorNotice"[\s\S]*class="detail-error-panel"[\s\S]*retry-label="重试读取"[\s\S]*retry-busy-label="读取中"[\s\S]*:retrying="detailRetrying"[\s\S]*:retry-disabled="detailRetryDisabled"[\s\S]*@retry="retrySelectedDetail"/)
})

test('LogsPage and EvolutionWorkbenchShell notice mapping wraps string errors but keeps non-error banners inline', () => {
  const historyError = {
    type: 'error',
    message: '历史对局详情读取失败',
    status: 404,
    code: 'not_found',
    requestId: 'req-history-404',
    diagnostics: [{ kind: 'lookup_failed', game_id: 'missing-game' }]
  }
  const panelError = noticeErrorForPanel(historyError)
  const view = formatApiErrorForDisplay(panelError, '历史记录读取失败')

  assert.equal(inlineNoticeForDisplay(historyError), null)
  assert.equal(view.status, 404)
  assert.equal(view.code, 'not_found')
  assert.equal(view.requestId, 'req-history-404')
  assert.equal(view.hasDiagnostics, true)

  const evolutionSuccess = { type: 'success', message: '单角色进化已启动。' }
  assert.deepEqual(inlineNoticeForDisplay(evolutionSuccess), evolutionSuccess)
  assert.equal(noticeErrorForPanel(evolutionSuccess), null)
})

test('MatchPage notice mapping sends action errors to ApiErrorPanel and keeps non-errors as toast notices', () => {
  const actionError = {
    type: 'error',
    message: '提交行动失败',
    status: 409,
    code: 'match_action_invalid',
    request_id: 'req-match-409',
    diagnostics: [{
      kind: 'invalid_target',
      role: 'witch',
      seed: 260600,
      message: '目标已出局'
    }]
  }
  const panelError = noticeErrorForPanel(actionError)
  const view = formatApiErrorForDisplay({
    ...panelError,
    requestId: panelError.requestId || panelError.request_id
  }, '对局操作失败')

  assert.equal(inlineNoticeForDisplay(actionError), null)
  assert.equal(view.status, 409)
  assert.equal(view.code, 'match_action_invalid')
  assert.equal(view.requestId, 'req-match-409')
  assert.equal(view.hasDiagnostics, true)
  assert.equal(view.diagnostics[0].label, 'invalid_target')

  const success = { type: 'success', message: '发言已提交。' }
  const warning = { type: 'warning', message: '已返回大厅，但后台停止对局失败。' }
  const info = { type: 'info', message: '等待其他玩家行动。' }

  assert.deepEqual(inlineNoticeForDisplay(success), success)
  assert.deepEqual(inlineNoticeForDisplay(warning), warning)
  assert.deepEqual(inlineNoticeForDisplay(info), info)
  assert.equal(noticeErrorForPanel(success), null)
  assert.equal(noticeErrorForPanel(warning), null)
  assert.equal(noticeErrorForPanel(info), null)
})

test('MatchPage source wires error notices to ApiErrorPanel without reusing the lightweight toast', () => {
  const source = readFileSync(new URL('../src/pages/MatchPage.vue', import.meta.url), 'utf8')

  assert.match(source, /import ApiErrorPanel from '\.\.\/components\/ApiErrorPanel\.vue'/)
  assert.match(source, /import \{ inlineNoticeForDisplay, noticeErrorForPanel \} from '\.\.\/composables\/apiErrorDisplay\.ts'/)
  assert.match(source, /inlineMatchNotice = computed\(\(\) => inlineNoticeForDisplay\(props\.matchNotice\)\)/)
  assert.match(source, /matchErrorNotice = computed\(\(\) => matchPanelErrorForNotice\(props\.matchNotice\)\)/)
  assert.match(source, /<ApiErrorPanel[\s\S]*v-if="matchErrorNotice"[\s\S]*class="match-error-notice"[\s\S]*title="对局操作失败"/)
  assert.match(source, /<aside[\s\S]*v-if="matchNoticeMessage"[\s\S]*match-action-notice/)
  assert.match(source, /--match-safe-left/)
  assert.match(source, /--match-safe-right/)
  assert.match(source, /--match-error-bottom-clearance/)
  assert.equal(source.includes('.match-action-notice.error'), false)
})

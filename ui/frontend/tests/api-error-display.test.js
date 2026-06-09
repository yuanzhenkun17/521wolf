import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError } from '../src/composables/gameApi.js'
import {
  formatApiErrorForDisplay,
  inlineNoticeForDisplay,
  normalizeDiagnostics,
  noticeErrorForPanel
} from '../src/composables/apiErrorDisplay.js'

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

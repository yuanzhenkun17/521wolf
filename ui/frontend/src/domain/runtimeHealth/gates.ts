import type { RuntimeHealthGate, RuntimeHealthGateScope, RuntimeHealthGateSummary, RuntimeHealthPayload } from '../../types/health'

const SCOPE_BLOCKED_REASON: Record<string, string> = {
  game_start: '运行环境未就绪，不能开始游戏。',
  benchmark_start: '运行环境未就绪，不能启动评测。',
  evolution_start: '运行环境未就绪，不能启动进化任务。'
}

const BLOCKER_LABELS: Record<string, string> = {
  llm_config: '模型配置缺失',
  llm_connectivity: '模型连接不可用',
  task_queue: '任务队列不可用',
  task_worker: '任务 Worker 不可用',
  artifact_root: '产物目录不可写',
  health_gate_missing: '健康门禁缺失'
}

const WARNING_LABELS: Record<string, string> = {
  llm_config: '模型配置降级',
  llm_connectivity: '模型连接尚未探测',
  task_queue: '任务队列降级',
  task_worker: '任务 Worker 心跳异常',
  artifact_root: '产物目录状态未知'
}

const ACTION_LABELS: Record<string, string> = {
  'open settings and test the model connection': '打开设置页，测试模型连接。',
  'configure a model profile in settings': '在设置页配置模型 Profile。',
  'set settings_admin_enabled=true': '开启 SETTINGS_ADMIN_ENABLED=true 后再修改设置。'
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function stringItems(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item ?? '').trim()).filter(Boolean)
    : []
}

function labelItems(items: string[], labels: Record<string, string>): string[] {
  return items.map((item) => labels[item] || item)
}

function labelActionItems(items: string[]): string[] {
  return items.map((item) => {
    const key = item.replace(/\.$/, '').trim().toLowerCase()
    return ACTION_LABELS[key] || item
  })
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value != null && typeof value !== 'object') {
      const text = String(value).trim()
      if (text) return text
    }
  }
  return ''
}

export function runtimeHealthGate(payload: RuntimeHealthPayload | null | undefined, scope: RuntimeHealthGateScope): RuntimeHealthGate | null {
  const gates = asRecord(payload?.gates)
  const gate = asRecord(gates[scope])
  return Object.keys(gate).length ? gate as RuntimeHealthGate : null
}

export function runtimeHealthGateSummary(
  payload: RuntimeHealthPayload | null | undefined,
  scope: RuntimeHealthGateScope
): RuntimeHealthGateSummary {
  const gate = runtimeHealthGate(payload, scope)
  if (!gate) {
    return {
      scope,
      known: false,
      ready: true,
      status: 'unknown',
      blockers: [],
      warnings: [],
      actions: [],
      disabled: false,
      reason: '',
      warning: ''
    }
  }

  const blockers = stringItems(gate.blockers)
  const warnings = stringItems(gate.warnings)
  const actions = stringItems(gate.actions)
  const ready = gate.ready !== false
  const blockerLabels = labelItems(blockers, BLOCKER_LABELS)
  const warningLabels = labelItems(warnings, WARNING_LABELS)
  const actionLabels = labelActionItems(actions)
  const reason = ready
    ? ''
    : firstText(blockerLabels.join('、'), actionLabels[0], SCOPE_BLOCKED_REASON[scope], '运行环境未就绪。')
  const warning = ready && warningLabels.length
    ? `运行环境有降级项：${warningLabels.join('、')}。启动时会再次检查。`
    : ''

  return {
    scope,
    known: true,
    ready,
    status: String(gate.status || (ready ? 'ok' : 'error')),
    blockers,
    warnings,
    actions: actionLabels,
    disabled: !ready,
    reason,
    warning
  }
}

export function runtimeHealthPayloadFromPreflight(
  result: Record<string, unknown> | null | undefined,
  scope: RuntimeHealthGateScope
): RuntimeHealthPayload | null {
  if (!result || typeof result !== 'object') return null
  const gate = asRecord(result.gate)
  if (!Object.keys(gate).length) return null
  const checks = asRecord(result.checks)
  return {
    status: String(result.status || gate.status || (result.ready ? 'ok' : 'error')),
    ready: Boolean(result.ready),
    checks,
    gates: {
      [scope]: gate
    },
    actions: Array.isArray(result.actions) ? result.actions : (Array.isArray(gate.actions) ? gate.actions : [])
  }
}

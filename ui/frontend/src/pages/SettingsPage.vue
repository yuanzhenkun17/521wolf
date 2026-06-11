<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { createSettingsService } from '../services/settingsApi'
import type { RuntimeHealthProbeResult } from '../types/health'
import type { ModelProfile, ModelProfilePayload, SettingsAdminState, SettingsModelProfilesResponse, SettingsOpsAlert, SettingsOpsMetrics, SettingsStorageState, SettingsVariable } from '../types/settings'

type SettingsGroupKey = 'models' | 'variables' | 'benchmark' | 'evolution' | 'langfuse' | 'tts' | 'system'
type IntegrationDetailRow = {
  key: string
  label: string
  value: string
  detail: string
  severity: 'ok' | 'warning' | 'error' | 'unknown'
}
type OpsAlertRow = {
  key: string
  code: string
  label: string
  detail: string
  severity: 'ok' | 'warning' | 'error' | 'unknown'
}
type OpsMetricRow = {
  key: string
  label: string
  value: string
  detail: string
  severity: 'ok' | 'warning' | 'error' | 'unknown'
}

const DEFAULT_RUNTIME_PROBE_SCOPE = 'settings_model_test'
const DEFAULT_MODEL_PROBE_SCOPE = 'prompt_test'
const MODEL_SCOPE_GROUPS = new Set<SettingsGroupKey>(['benchmark', 'evolution'])
const HEALTH_GATE_BLOCKER_LABELS: Record<string, string> = {
  llm_config: '模型配置缺失',
  llm_connectivity: '模型连接不可用',
  task_queue: '任务队列不可用',
  task_worker: '任务 Worker 不可用',
  artifact_root: '产物目录不可写',
  health_gate_missing: '健康门禁缺失'
}
const HEALTH_GATE_WARNING_LABELS: Record<string, string> = {
  llm_config: '模型配置降级',
  llm_connectivity: '模型连接尚未探测',
  task_queue: '任务队列降级',
  task_worker: '任务 Worker 心跳异常',
  artifact_root: '产物目录状态未知'
}
const HEALTH_GATE_ACTION_LABELS: Record<string, string> = {
  'open settings and test the model connection': '在设置页测试模型连接。',
  'configure a model profile in settings': '在设置页配置模型 Profile。',
  'set settings_admin_enabled=true': '开启 SETTINGS_ADMIN_ENABLED=true。',
  'start the task worker and wait for a fresh heartbeat': '启动 task worker 并等待心跳恢复。',
  'verify the task artifact root exists and is writable': '确认任务产物目录存在且可写。'
}

const GROUPS: Array<{ key: SettingsGroupKey; label: string; caption: string }> = [
  { key: 'models', label: '模型', caption: 'Profiles' },
  { key: 'variables', label: '运行变量', caption: 'Runtime' },
  { key: 'benchmark', label: 'Benchmark', caption: '默认模型' },
  { key: 'evolution', label: 'Evolution', caption: '默认模型' },
  { key: 'langfuse', label: 'Langfuse', caption: '观测' },
  { key: 'tts', label: 'TTS', caption: '语音' },
  { key: 'system', label: '系统状态', caption: 'Health' }
]

const DEFAULT_FORM = {
  name: '',
  provider: 'openai_compatible',
  base_url: '',
  model: '',
  api_key: '',
  temperature: 0.4,
  timeout_seconds: 60,
  max_retries: 0,
  enabled: true,
  clear_api_key: false,
  default_scopes: {
    game_decision: false,
    judge: false,
    benchmark: false,
    evolution: false,
    prompt_test: false
  },
  capabilities: {
    chat: true,
    json_mode: false,
    tool_calling: false,
    streaming: false,
    vision: false
  }
}

const settingsService = createSettingsService()
const profiles = ref<ModelProfile[]>([])
const health = ref<Record<string, any>>({})
const opsMetrics = ref<SettingsOpsMetrics>({})
const admin = ref<SettingsAdminState>({ enabled: false, token_configured: false, write_available: false, storage: {} })
const scopes = ref<Array<{ key: string; label: string }>>([])
const providers = ref<string[]>(['openai_compatible', 'custom'])
const variables = ref<SettingsVariable[]>([])
const envLocks = ref<Record<string, unknown>>({})
const selectedProfileId = ref('')
const activeGroup = ref<SettingsGroupKey>('models')
const adminToken = ref('')
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const healthProbeTesting = ref(false)
const savingVariableKey = ref('')
const error = ref('')
const notice = ref('')
const refreshedAt = ref('')
const form = reactive({ ...DEFAULT_FORM })
const variableDrafts = reactive<Record<string, boolean | number | string>>({})
const selectedProfileFormSignature = ref('')

const selectedProfile = computed(() =>
  profiles.value.find((profile) => profile.profile_id === selectedProfileId.value) || null
)
const storageStates = computed<Record<string, SettingsStorageState>>(() => {
  const raw = admin.value.storage
  return raw && typeof raw === 'object' ? raw : {}
})
const storageRows = computed(() =>
  Object.entries(storageStates.value).map(([key, state]) => {
    const writable = storageWritable(state)
    const action = storageActionText(state)
    return {
      key,
      label: storageLabel(key),
      backend: storageBackendLabel(state),
      writable,
      severity: writable ? 'ok' : 'error',
      status: writable ? '可写' : '只读',
      hint: storageHint(state, action),
      action
    }
  })
)
const blockedStorageRows = computed(() => storageRows.value.filter((row) => !row.writable))
const canWrite = computed(() =>
  Boolean(admin.value.enabled && admin.value.token_configured && admin.value.write_available && adminToken.value.trim())
)
const enabledProfiles = computed(() => profiles.value.filter((profile) => profile.enabled))
const selectedProfileLastTestError = computed(() => profileTestError(selectedProfile.value))
const profileFormDirty = computed(() =>
  Boolean(selectedProfile.value && selectedProfileFormSignature.value && profileFormSignature() !== selectedProfileFormSignature.value)
)
const healthStatus = computed(() => String(health.value.status || 'unknown'))
const healthReady = computed(() => health.value.ready !== false)
const adminWriteStateLabel = computed(() => canWrite.value ? '可写' : '只读')
const adminWriteStatus = computed(() => {
  if (!admin.value.enabled) return '写入未开启'
  if (!admin.value.token_configured) return '令牌未配置'
  if (!admin.value.write_available) return '存储只读'
  if (!adminToken.value.trim()) return '等待令牌'
  return '已授权'
})
const healthChecks = computed(() => {
  const checks = health.value.checks && typeof health.value.checks === 'object' ? health.value.checks : {}
  return Object.entries(checks).map(([key, value]) => {
    const row = value && typeof value === 'object' ? value as Record<string, any> : {}
    return {
      key,
      label: checkLabel(key),
      status: String(row.status || 'unknown'),
      message: String(row.message || row.error?.message || ''),
      raw: row
    }
  })
})
const activeIntegrationChecks = computed(() =>
  healthChecks.value.filter((check) =>
    activeGroup.value === 'tts' ? check.key.includes('tts') : check.key.includes('langfuse')
  )
)
const activeIntegrationDetailRows = computed(() =>
  integrationDetailRows(activeGroup.value, activeIntegrationChecks.value)
)
const activeIntegrationGuidanceRows = computed(() =>
  integrationGuidanceRows(activeGroup.value, activeIntegrationChecks.value)
)
const gateRows = computed(() => {
  const gates = health.value.gates && typeof health.value.gates === 'object' ? health.value.gates : {}
  return Object.entries(gates).map(([key, value]) => {
    const row = value && typeof value === 'object' ? value as Record<string, any> : {}
    const ready = Boolean(row.ready)
    const blockers = gateIssueLabels(row.blockers, HEALTH_GATE_BLOCKER_LABELS)
    const warnings = gateIssueLabels(row.warnings, HEALTH_GATE_WARNING_LABELS)
    const actions = gateActionLabels(row.actions)
    const status = String(row.status || 'unknown')
    return {
      key,
      label: gateLabel(key),
      ready,
      status,
      blockers,
      warnings,
      actions,
      severity: ready ? (warnings.length ? 'warning' : 'ok') : 'error',
      summary: ready
        ? warnings.length ? `可启动，有 ${warnings.length} 个警告` : '可启动'
        : blockers.join(' / ') || '不可启动',
      detail: gateDetailText(ready, blockers, warnings, actions)
    }
  })
})
const opsAlertRows = computed<OpsAlertRow[]>(() =>
  textAlertRows(Array.isArray(opsMetrics.value.alerts) ? opsMetrics.value.alerts : [])
)
const opsBlockingAlertRows = computed(() => opsAlertRows.value.filter((alert) => alert.severity === 'error'))
const opsMetricRows = computed<OpsMetricRow[]>(() => buildOpsMetricRows(opsMetrics.value))
const profileBlockingIssues = computed(() => {
  const issues: string[] = []
  if (!form.name.trim()) issues.push('填写 Profile 名称。')
  if (!form.base_url.trim()) issues.push('填写模型 Base URL。')
  if (!form.model.trim()) issues.push('填写模型 ID。')
  return issues
})
const profileGuidanceRows = computed(() => {
  const rows: string[] = []
  if (!canWrite.value) rows.push(adminWriteHint())
  rows.push(...profileBlockingIssues.value)
  if (profileFormDirty.value) {
    rows.push('表单有未保存改动；保存后再测试连接，避免测试旧配置。')
  }
  if (selectedProfile.value && !selectedProfile.value.enabled) {
    rows.push('当前 Profile 已禁用，启动任务不会选用它。')
  }
  if (selectedProfileLastTestError.value) {
    rows.push(`上次测试失败：${selectedProfileLastTestError.value}`)
  }
  if (selectedProfile.value && ['error', 'stale', 'untested'].includes(String(selectedProfile.value.last_test_status || 'untested'))) {
    rows.push('保存后建议测试连接；启动入口会重新预检，失败才会阻断任务。')
  }
  if (form.clear_api_key && !form.api_key.trim()) {
    rows.push('清除 key 后需要重新填写 API key 才能用于启动。')
  }
  const lockedScopes = scopes.value
    .filter((scope) => Boolean(envLocks.value[scope.key]) && Boolean((form.default_scopes as Record<string, boolean>)[scope.key]))
    .map((scope) => scope.label)
  if (lockedScopes.length) rows.push(`${lockedScopes.join(' / ')} 被环境变量锁定，保存不会改变实际默认模型。`)
  return rows
})
const canSubmitProfile = computed(() => Boolean(canWrite.value && !saving.value && profileBlockingIssues.value.length === 0))
const canTestSelectedProfile = computed(() => Boolean(selectedProfile.value && canWrite.value && !testing.value && !profileFormDirty.value))
const profileTestButtonTitle = computed(() => {
  if (!selectedProfile.value) return '先选择模型 Profile。'
  if (profileFormDirty.value) return '表单有未保存改动，保存后才能测试连接。'
  return adminWriteHint()
})
const settingsMetaRows = computed(() => [
  { key: 'profiles', label: '模型', value: profiles.value.length || '0' },
  { key: 'enabled', label: '启用', value: enabledProfiles.value.length || '0' },
  { key: 'storage', label: '存储', value: blockedStorageRows.value.length ? '只读' : '可写' },
  { key: 'alerts', label: '告警', value: opsAlertRows.value.length || '0' },
  { key: 'ready', label: 'API', value: healthReady.value ? statusLabel(healthStatus.value) : '未就绪' },
  { key: 'selected', label: '选中', value: selectedProfile.value?.name || '新建' }
])
const settingsGuidanceRows = computed(() => {
  const rows: string[] = []
  if (!canWrite.value) rows.push(adminWriteHint())
  for (const storage of blockedStorageRows.value) {
    rows.push(`${storage.label}存储只读：${storage.hint}`)
  }
  const blockedGates = gateRows.value.filter((gate) => !gate.ready)
  if (blockedGates.length) {
    rows.push(`${blockedGates.map((gate) => gate.label).join('、')} 已阻断：${blockedGates.map((gate) => gate.summary).join('；')}。`)
  }
  if (opsBlockingAlertRows.value.length) {
    rows.push(`运行告警阻断：${opsBlockingAlertRows.value.map((alert) => alert.label).join('、')}。`)
  }
  const degradedAlerts = opsAlertRows.value.filter((alert) => alert.severity === 'warning')
  if (degradedAlerts.length) {
    rows.push(`运行降级：${degradedAlerts.map((alert) => alert.label).slice(0, 2).join('、')}。`)
  }
  const activeProfile = selectedProfile.value
  if (activeProfile && ['error', 'stale', 'untested'].includes(String(activeProfile.last_test_status || 'untested'))) {
    rows.push(`当前 Profile 状态为${statusLabel(activeProfile.last_test_status || 'untested')}，建议先测试连接。`)
  }
  if (['benchmark', 'evolution'].includes(activeGroup.value) && Boolean(envLocks.value[activeGroup.value])) {
    rows.push(`${activeGroupInfo.value.label} 默认模型由环境变量锁定，设置页只展示本地配置。`)
  }
  if (['benchmark', 'evolution'].includes(activeGroup.value) && inactiveScopedProfiles.value.length) {
    rows.push(`${inactiveScopedProfiles.value.length} 个默认 Profile 缺少启用状态或 API key，启动入口不会选用。`)
  }
  return rows.slice(0, 4)
})
const activeGroupInfo = computed(() => GROUPS.find((item) => item.key === activeGroup.value) || GROUPS[0])
const scopedProfileCandidates = computed(() => {
  const scope = activeGroup.value
  if (!['benchmark', 'evolution'].includes(scope)) return []
  return profiles.value.filter((profile) => Boolean(profile.default_scopes?.[scope]))
})
const scopedProfiles = computed(() =>
  scopedProfileCandidates.value.filter(profileCanLaunch)
)
const inactiveScopedProfiles = computed(() =>
  scopedProfileCandidates.value.filter((profile) => !profileCanLaunch(profile))
)

onMounted(() => {
  void refreshSettings()
})

async function refreshSettings() {
  loading.value = true
  error.value = ''
  try {
    const payload = await settingsService.listModelProfiles()
    applySettings(payload)
    refreshedAt.value = new Date().toISOString()
  } catch (err) {
    error.value = errorMessage(err, '设置读取失败')
  } finally {
    loading.value = false
  }
}

async function probeRuntimeModel() {
  healthProbeTesting.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await settingsService.probeRuntimeModel({
      scope: DEFAULT_RUNTIME_PROBE_SCOPE,
      model_scope: runtimeProbeModelScope(),
      model_profile_id: selectedProfileId.value || undefined
    }, adminToken.value)
    notice.value = runtimeProbeNotice(result)
    await refreshSettings()
  } catch (err) {
    error.value = errorMessage(err, '当前模型连接测试失败')
  } finally {
    healthProbeTesting.value = false
  }
}

function applySettings(payload: SettingsModelProfilesResponse) {
  profiles.value = Array.isArray(payload.profiles) ? payload.profiles : []
  health.value = payload.health || {}
  admin.value = {
    ...(payload.admin || { enabled: false, token_configured: false, write_available: false }),
    storage: payload.admin?.storage || payload.storage || {}
  }
  scopes.value = Array.isArray(payload.scopes) ? payload.scopes : []
  providers.value = Array.isArray(payload.providers) && payload.providers.length ? payload.providers : providers.value
  variables.value = Array.isArray(payload.variables) ? payload.variables : []
  opsMetrics.value = payload.ops_metrics || {}
  syncVariableDrafts(variables.value)
  envLocks.value = payload.env_locks || {}
  if (selectedProfileId.value && profiles.value.some((profile) => profile.profile_id === selectedProfileId.value)) {
    loadProfileToForm(selectedProfile.value)
    return
  }
  const first = profiles.value[0] || null
  if (first) selectProfile(first)
  else startNewProfile()
}

function selectGroup(group: SettingsGroupKey) {
  activeGroup.value = group
}

function selectProfile(profile: ModelProfile | null) {
  selectedProfileId.value = profile?.profile_id || ''
  loadProfileToForm(profile)
}

function startNewProfile() {
  selectedProfileId.value = ''
  Object.assign(form, JSON.parse(JSON.stringify(DEFAULT_FORM)))
  selectedProfileFormSignature.value = profileFormSignature()
}

function loadProfileToForm(profile: ModelProfile | null) {
  if (!profile) {
    startNewProfile()
    return
  }
  Object.assign(form, {
    name: profile.name || '',
    provider: profile.provider || 'openai_compatible',
    base_url: profile.base_url || '',
    model: profile.model || '',
    api_key: '',
    temperature: numberOrDefault(profile.temperature, 0.4),
    timeout_seconds: numberOrDefault(profile.timeout_seconds, 60),
    max_retries: numberOrDefault(profile.max_retries, 0),
    enabled: Boolean(profile.enabled),
    clear_api_key: false,
    default_scopes: { ...DEFAULT_FORM.default_scopes, ...(profile.default_scopes || {}) },
    capabilities: { ...DEFAULT_FORM.capabilities, ...(profile.capabilities || {}) }
  })
  selectedProfileFormSignature.value = profileFormSignature()
}

function buildPayload(): ModelProfilePayload {
  const payload: ModelProfilePayload = {
    name: form.name.trim(),
    provider: form.provider,
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    temperature: Number(form.temperature),
    timeout_seconds: Number(form.timeout_seconds),
    max_retries: Number(form.max_retries),
    enabled: Boolean(form.enabled),
    default_scopes: { ...form.default_scopes },
    capabilities: { ...form.capabilities }
  }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  if (form.clear_api_key) payload.clear_api_key = true
  return payload
}

async function saveProfile() {
  if (!canWrite.value) {
    notice.value = adminWriteHint()
    return
  }
  if (profileBlockingIssues.value.length) {
    notice.value = profileBlockingIssues.value[0]
    return
  }
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    if (selectedProfileId.value) {
      const response = await settingsService.updateModelProfile(selectedProfileId.value, buildPayload(), adminToken.value)
      upsertProfile(response.profile)
      selectProfile(response.profile)
      notice.value = '模型配置已保存。'
    } else {
      const response = await settingsService.createModelProfile(buildPayload(), adminToken.value)
      upsertProfile(response.profile)
      selectProfile(response.profile)
      notice.value = '模型 Profile 已创建。'
    }
  } catch (err) {
    error.value = errorMessage(err, '保存模型配置失败')
  } finally {
    saving.value = false
  }
}

async function testSelectedProfile() {
  if (!selectedProfileId.value || !canWrite.value) {
    notice.value = selectedProfileId.value ? adminWriteHint() : '先选择或创建模型 Profile。'
    return
  }
  if (profileFormDirty.value) {
    notice.value = '表单有未保存改动；请先保存，再测试连接。'
    return
  }
  testing.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await settingsService.testModelProfile(selectedProfileId.value, adminToken.value)
    notice.value = result.ok ? `连接正常，耗时 ${result.latency_ms}ms。` : result.error?.message || '连接失败。'
    await refreshSettings()
  } catch (err) {
    error.value = errorMessage(err, '模型连接测试失败')
  } finally {
    testing.value = false
  }
}

async function disableSelectedProfile() {
  if (!selectedProfileId.value || !canWrite.value) {
    notice.value = selectedProfileId.value ? adminWriteHint() : '先选择模型 Profile。'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const response = await settingsService.disableModelProfile(selectedProfileId.value, adminToken.value)
    upsertProfile(response.profile)
    selectProfile(response.profile)
    notice.value = '模型 Profile 已禁用。'
  } catch (err) {
    error.value = errorMessage(err, '禁用失败')
  } finally {
    saving.value = false
  }
}

async function deleteSelectedProfile() {
  if (!selectedProfileId.value || !canWrite.value) {
    notice.value = selectedProfileId.value ? adminWriteHint() : '先选择模型 Profile。'
    return
  }
  if (typeof window !== 'undefined' && !window.confirm('确认删除这个模型 Profile？已保存的 secret 也会删除。')) return
  saving.value = true
  error.value = ''
  try {
    await settingsService.deleteModelProfile(selectedProfileId.value, adminToken.value)
    profiles.value = profiles.value.filter((profile) => profile.profile_id !== selectedProfileId.value)
    startNewProfile()
    notice.value = '模型 Profile 已删除。'
  } catch (err) {
    error.value = errorMessage(err, '删除失败')
  } finally {
    saving.value = false
  }
}

async function saveRuntimeVariable(variable: SettingsVariable) {
  if (!canWrite.value) {
    notice.value = adminWriteHint()
    return
  }
  if (!variableCanEdit(variable)) {
    notice.value = variable.locked ? '该变量由环境变量锁定。' : '该变量不可在设置页修改。'
    return
  }
  savingVariableKey.value = variable.key
  error.value = ''
  notice.value = ''
  try {
    const response = await settingsService.updateRuntimeVariable(
      variable.key,
      { value: variablePayloadValue(variable) },
      adminToken.value
    )
    upsertVariable(response.variable)
    notice.value = `${variable.label} 已保存。`
    await refreshSettings()
  } catch (err) {
    error.value = errorMessage(err, '保存运行变量失败')
  } finally {
    savingVariableKey.value = ''
  }
}

function syncVariableDrafts(items: SettingsVariable[]) {
  for (const variable of items) {
    variableDrafts[variable.key] = variableInitialValue(variable)
  }
}

function upsertVariable(variable: SettingsVariable) {
  const index = variables.value.findIndex((item) => item.key === variable.key)
  if (index >= 0) variables.value.splice(index, 1, variable)
  else variables.value.push(variable)
  variableDrafts[variable.key] = variableInitialValue(variable)
}

function variableInitialValue(variable: SettingsVariable): boolean | number | string {
  if (variable.value_type === 'boolean') return Boolean(variable.raw_value)
  if (variable.value_type === 'integer' || variable.value_type === 'number') {
    const parsed = Number(variable.raw_value ?? variable.value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return String(variable.raw_value ?? variable.value ?? '')
}

function variablePayloadValue(variable: SettingsVariable): boolean | number | string {
  const draft = variableDrafts[variable.key]
  if (variable.value_type === 'boolean') return Boolean(draft)
  if (variable.value_type === 'integer') return Math.round(Number(draft))
  if (variable.value_type === 'number') return Number(draft)
  return String(draft ?? '')
}

function variableCanEdit(variable: SettingsVariable): boolean {
  return Boolean(canWrite.value && variable.editable && !variable.locked && !variable.secret)
}

function variableDirty(variable: SettingsVariable): boolean {
  return variablePayloadValue(variable) !== variableInitialValue(variable)
}

function upsertProfile(profile: ModelProfile) {
  const index = profiles.value.findIndex((item) => item.profile_id === profile.profile_id)
  if (index >= 0) profiles.value.splice(index, 1, profile)
  else profiles.value.unshift(profile)
}

function profileCanLaunch(profile: ModelProfile): boolean {
  return Boolean(profile.enabled && profile.has_api_key)
}

function profileTestError(profile: ModelProfile | null): string {
  const text = String(profile?.last_test_error || '').trim()
  return text || ''
}

function profileFormSignature(): string {
  return JSON.stringify({
    name: form.name.trim(),
    provider: String(form.provider || ''),
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    api_key_present: Boolean(form.api_key.trim()),
    temperature: Number(form.temperature),
    timeout_seconds: Number(form.timeout_seconds),
    max_retries: Number(form.max_retries),
    enabled: Boolean(form.enabled),
    clear_api_key: Boolean(form.clear_api_key),
    default_scopes: { ...form.default_scopes },
    capabilities: { ...form.capabilities }
  })
}

function numberOrDefault(value: unknown, fallback: number): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function formatDateTime(value: unknown): string {
  const text = String(value || '').trim()
  if (!text) return '未记录'
  const date = new Date(text)
  if (!Number.isFinite(date.getTime())) return text
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

function errorMessage(err: unknown, fallback: string): string {
  const source = err as { message?: string; code?: string; status?: number }
  const code = String(source?.code || '')
  if (code === 'settings_admin_required' || source?.status === 403) return `${fallback}：${adminWriteHint()}`
  if (code === 'settings_storage_unavailable') return `${fallback}：${storageBlockHint() || String(source?.message || '设置存储不可写。')}`
  if (code === 'settings_runtime_variable_locked') return `${fallback}：该变量由环境变量锁定，需修改服务端环境变量后重启。`
  if (code === 'runtime_not_ready') return `${fallback}：模型或任务运行门禁未通过，请查看系统状态。`
  return String(source?.message || fallback)
}

function adminWriteHint(): string {
  if (canWrite.value) return '管理员令牌已填写，可修改本地设置。'
  if (!admin.value.enabled) return '设置写入未开启：需要 SETTINGS_ADMIN_ENABLED=true。'
  if (!admin.value.token_configured) return '管理员令牌未配置：需要 SETTINGS_ADMIN_TOKEN。'
  const storageHint = storageBlockHint()
  if (storageHint) return storageHint
  if (!admin.value.write_available) return '设置存储未就绪，暂不能写入。'
  return '输入管理员令牌后才能修改本地模型配置。'
}

function storageBlockHint(): string {
  const row = blockedStorageRows.value[0]
  return row ? `${row.label}存储不可写：${row.hint}` : ''
}

function storageWritable(state: SettingsStorageState): boolean {
  return Boolean(state?.ready) && !Boolean(state?.read_only)
}

function storageLabel(key: string): string {
  return {
    model_profiles: '模型 Profile',
    runtime_variables: '运行变量'
  }[key] || key
}

function storageBackendLabel(state: SettingsStorageState): string {
  const backend = String(state?.backend || 'unknown')
  if (backend === 'postgres') return 'PostgreSQL'
  if (backend === 'local_file') return '本地文件'
  return backend
}

function storageActionText(state: SettingsStorageState): string {
  const actions = Array.isArray(state.actions) ? state.actions : []
  const text = actions.map((item) => String(item || '').trim()).find(Boolean) || ''
  if (!text) return ''
  const key = text.toLowerCase()
  if (key.includes('ui_model_profiles')) return '执行数据库迁移，创建 ui_model_profiles。'
  if (key.includes('ui_runtime_settings')) return '执行数据库迁移，创建 ui_runtime_settings。'
  if (key.includes('settings_secret_encryption_key')) return '配置 SETTINGS_SECRET_ENCRYPTION_KEY 后重启。'
  if (key.includes('postgresql connectivity')) return '检查 PostgreSQL 连接配置。'
  if (key.includes('schema permissions')) return '检查 PostgreSQL schema 权限。'
  return text
}

function storageHint(state: SettingsStorageState, action: string): string {
  const reason = String(state.reason || '')
  if (action) return action
  if (reason === 'missing_table') return '执行数据库迁移后刷新。'
  if (reason === 'secret_encryption_missing') return '配置 SETTINGS_SECRET_ENCRYPTION_KEY 后重启。'
  if (reason === 'connection_unavailable') return '检查 PostgreSQL 连接配置。'
  const message = String(state.message || '').trim()
  return message || '恢复设置存储后再写入。'
}

function integrationDetailRows(group: SettingsGroupKey, checks: Array<{ key: string; raw: Record<string, any> }>): IntegrationDetailRow[] {
  const raw = integrationPrimaryRaw(group, checks)
  if (!Object.keys(raw).length) return []
  return group === 'tts' ? ttsDetailRows(raw) : langfuseDetailRows(raw)
}

function integrationGuidanceRows(group: SettingsGroupKey, checks: Array<{ key: string; raw: Record<string, any> }>): string[] {
  const raw = integrationPrimaryRaw(group, checks)
  const rows: string[] = []
  if (!Object.keys(raw).length) return rows
  if (group === 'langfuse') {
    if (raw.enabled && raw.capture_input_output === false) {
      rows.push('Langfuse 输入/输出捕获已关闭；generation 的 Input/Output 会显示为空。')
    }
    const missing = textArray(raw.missing)
    if (missing.length) rows.push(`缺少配置：${missing.join('、')}。`)
    rows.push(...textArray(raw.warnings).map(langfuseWarningText))
  }
  rows.push(...textArray(raw.actions).map(integrationActionText))
  return Array.from(new Set(rows.filter(Boolean))).slice(0, 5)
}

function integrationPrimaryRaw(group: SettingsGroupKey, checks: Array<{ key: string; raw: Record<string, any> }>): Record<string, any> {
  const preferredKey = group === 'tts' ? 'tts_config' : 'langfuse_config'
  return checks.find((item) => item.key === preferredKey)?.raw || checks[0]?.raw || {}
}

function langfuseDetailRows(raw: Record<string, any>): IntegrationDetailRow[] {
  const enabled = Boolean(raw.enabled)
  const capture = raw.capture_input_output === true
  const rows: IntegrationDetailRow[] = [
    {
      key: 'enabled',
      label: 'Tracing',
      value: enabled ? '已启用' : '未启用',
      detail: enabled ? 'Langfuse tracing 已打开。' : '当前不会写入 Langfuse trace。',
      severity: enabled ? 'ok' : 'unknown'
    }
  ]
  if (raw.base_url) {
    rows.push({
      key: 'base_url',
      label: 'Base URL',
      value: String(raw.base_url),
      detail: String(raw.base_url),
      severity: 'ok'
    })
  }
  if (enabled) {
    rows.push({
      key: 'capture_input_output',
      label: '输入/输出',
      value: capture ? '已捕获' : '未捕获',
      detail: capture ? 'Langfuse 会显示 generation Input/Output。' : 'Input/Output 会为空；需要 LANGFUSE_CAPTURE_INPUT_OUTPUT=true。',
      severity: capture ? 'ok' : 'warning'
    })
    rows.push({
      key: 'sample_rate',
      label: '采样率',
      value: raw.sample_rate === null || raw.sample_rate === undefined ? '未显式配置' : String(raw.sample_rate),
      detail: '决定 trace 是否可能被采样丢弃。',
      severity: raw.sample_rate === null || raw.sample_rate === undefined ? 'warning' : 'ok'
    })
    rows.push({
      key: 'environment',
      label: 'Environment',
      value: raw.environment_configured ? '已配置' : '未配置',
      detail: '用于区分 dev/staging/prod 的 trace。',
      severity: raw.environment_configured ? 'ok' : 'warning'
    })
    rows.push({
      key: 'release',
      label: 'Release',
      value: raw.release_configured ? '已配置' : '未配置',
      detail: '用于把 trace 关联到部署版本。',
      severity: raw.release_configured ? 'ok' : 'warning'
    })
  }
  const missing = textArray(raw.missing)
  if (missing.length) {
    rows.push({
      key: 'missing',
      label: '缺失变量',
      value: `${missing.length} 项`,
      detail: missing.join('、'),
      severity: 'error'
    })
  }
  return rows
}

function ttsDetailRows(raw: Record<string, any>): IntegrationDetailRow[] {
  return [
    {
      key: 'provider',
      label: 'Provider',
      value: String(raw.provider || 'DashScope'),
      detail: String(raw.source || 'environment'),
      severity: statusSeverity(raw.status)
    },
    {
      key: 'model',
      label: '模型',
      value: String(raw.model || '未配置'),
      detail: `Voice：${String(raw.voice || '未配置')}`,
      severity: raw.model ? 'ok' : 'warning'
    },
    {
      key: 'sample_rate',
      label: '采样率',
      value: raw.sample_rate ? `${raw.sample_rate} Hz` : '未知',
      detail: `模式：${String(raw.mode || '未知')}`,
      severity: raw.sample_rate ? 'ok' : 'unknown'
    },
    {
      key: 'max_chars',
      label: '单次长度',
      value: raw.max_chars ? `${raw.max_chars} 字符` : '未限制',
      detail: raw.ws_url ? `WebSocket：${String(raw.ws_url)}` : '未提供 WebSocket 地址',
      severity: 'ok'
    }
  ]
}

function textAlertRows(alerts: SettingsOpsAlert[]): OpsAlertRow[] {
  return alerts.map((alert, index) => {
    const code = String(alert.code || `alert_${index}`)
    const severity = opsAlertSeverity(alert.severity)
    return {
      key: `${code}-${index}`,
      code,
      label: opsAlertLabel(code),
      detail: opsAlertDetail(alert),
      severity
    }
  })
}

function buildOpsMetricRows(payload: SettingsOpsMetrics): OpsMetricRow[] {
  if (!payload.kind && !payload.metrics && !payload.tasks) return []
  const metrics = recordObject(payload.metrics)
  const tasks = recordObject(payload.tasks)
  const runtime = recordObject(payload.runtime)
  const integrations = recordObject(payload.integrations)
  const release = recordObject(payload.release)
  const langfuse = recordObject(integrations.langfuse)
  const queueCounts = recordObject(tasks.queue_status_counts)
  const healthReady = payload.ready !== false
  const blockedGateCount = safeNumber(metrics.health_gate_blocked_count)
  const staleTaskCount = safeNumber(tasks.stale_running_count)
  const workerFresh = tasks.worker_fresh === true
  const artifactWritable = tasks.artifact_root_writable === true
  const activeGames = safeNumber(runtime.live_game_active_count)
  const activeBackground = safeNumber(runtime.background_active_count)
  const queued = safeNumber(queueCounts.queued)
  const running = safeNumber(queueCounts.running)
  const failed = safeNumber(queueCounts.failed)
  const interrupted = safeNumber(queueCounts.interrupted)

  return [
    {
      key: 'release',
      label: '部署版本',
      value: releaseValue(release),
      detail: releaseDetail(release),
      severity: release.configured ? 'ok' : 'warning'
    },
    {
      key: 'health_ready',
      label: 'API 就绪',
      value: healthReady ? '就绪' : '未就绪',
      detail: String(payload.summary || statusLabel(payload.status)),
      severity: healthReady ? statusSeverity(payload.status) : 'error'
    },
    {
      key: 'gates',
      label: '启动门禁',
      value: blockedGateCount ? `${blockedGateCount} 个阻断` : '全部通过',
      detail: blockedGateCount ? '至少一个启动入口被运行门禁阻断。' : '开始游戏、评测、进化门禁没有阻断项。',
      severity: blockedGateCount ? 'error' : 'ok'
    },
    {
      key: 'task_queue',
      label: '任务队列',
      value: `排队 ${queued} / 运行 ${running}`,
      detail: `失败 ${failed}，中断 ${interrupted}，陈旧运行 ${staleTaskCount}。`,
      severity: staleTaskCount > 0 ? 'error' : (failed + interrupted > 0 ? 'warning' : 'ok')
    },
    {
      key: 'task_worker',
      label: 'Task worker',
      value: workerFresh ? '心跳正常' : '心跳异常',
      detail: `已注册 worker ${safeNumber(tasks.worker_count)} 个。`,
      severity: workerFresh ? 'ok' : 'error'
    },
    {
      key: 'artifact_root',
      label: '产物写入',
      value: artifactWritable ? '可写' : '不可写',
      detail: artifactWritable ? '任务报告和产物可以落盘。' : 'Benchmark/Evolution 产物可能无法保存。',
      severity: artifactWritable ? 'ok' : 'error'
    },
    {
      key: 'runtime',
      label: '运行中任务',
      value: `游戏 ${activeGames} / 后台 ${activeBackground}`,
      detail: '用于判断当前系统是否有进行中的游戏、Benchmark 或 Evolution。',
      severity: activeBackground > 0 || activeGames > 0 ? 'warning' : 'ok'
    },
    {
      key: 'langfuse',
      label: 'Langfuse',
      value: langfuse.enabled ? '已启用' : '未启用',
      detail: langfuse.enabled && langfuse.capture_input_output === false
        ? 'Input/Output 捕获关闭，Langfuse 会显示空输入输出。'
        : `状态：${statusLabel(langfuse.status)}`,
      severity: langfuse.enabled && langfuse.capture_input_output === false ? 'warning' : statusSeverity(langfuse.status)
    }
  ]
}

function releaseValue(release: Record<string, any>): string {
  const name = String(release.release || '').trim()
  const sha = String(release.git_sha_short || '').trim()
  if (name && sha) return `${name} · ${sha}`
  return name || sha || '未配置'
}

function releaseDetail(release: Record<string, any>): string {
  const environment = String(release.environment || '').trim()
  const sha = String(release.git_sha || '').trim()
  const parts = [
    environment ? `环境 ${environment}` : '',
    sha ? `提交 ${sha}` : '',
  ].filter(Boolean)
  return parts.length ? parts.join('；') : '建议在部署环境配置 WOLF_APP_RELEASE 或 APP_GIT_SHA。'
}

function opsAlertSeverity(severity: unknown): OpsAlertRow['severity'] {
  const text = String(severity || '').toLowerCase()
  if (text === 'error') return 'error'
  if (text === 'degraded' || text === 'warning') return 'warning'
  if (text === 'ok') return 'ok'
  return 'unknown'
}

function opsAlertLabel(code: string): string {
  if (code === 'health_not_ready') return 'API 未就绪'
  if (code.startsWith('gate_blocked.')) return `${gateLabel(code.replace('gate_blocked.', ''))} 被阻断`
  if (code === 'task_queue.stale_running') return '任务队列有陈旧运行项'
  if (code === 'task_worker.not_fresh') return 'Task worker 心跳异常'
  if (code === 'artifact_root.not_writable') return '产物目录不可写'
  if (code === 'langfuse.config_error') return 'Langfuse 配置错误'
  if (code === 'langfuse.capture_input_output_disabled') return 'Langfuse 输入/输出捕获关闭'
  return code
}

function opsAlertDetail(alert: SettingsOpsAlert): string {
  const code = String(alert.code || '')
  const message = String(alert.message || '').trim()
  if (code === 'health_not_ready') return '部署或入口检查不能只看进程存活，需要先恢复 health ready。'
  if (code === 'task_worker.not_fresh') return '启动 worker 服务并等待心跳刷新，Benchmark/Evolution 会因此被阻断。'
  if (code === 'artifact_root.not_writable') return '检查任务产物目录权限，避免报告和回放产物写入失败。'
  if (code === 'langfuse.capture_input_output_disabled') return '设置 LANGFUSE_CAPTURE_INPUT_OUTPUT=true 并重启后，Langfuse 才会显示 Input/Output。'
  return message || '查看 health checks 和运行门禁获取恢复路径。'
}

function recordObject(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function safeNumber(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function statusSeverity(status: unknown): IntegrationDetailRow['severity'] {
  const text = String(status || '').toLowerCase()
  if (text === 'ok') return 'ok'
  if (text === 'degraded' || text === 'stale' || text === 'warning') return 'warning'
  if (text === 'error') return 'error'
  return 'unknown'
}

function langfuseWarningText(value: unknown): string {
  const text = String(value || '')
  if (text === 'capture_input_output_disabled') return '输入/输出捕获关闭：Langfuse generation Input/Output 会为空。'
  if (text === 'sample_rate_missing') return '未显式配置 LANGFUSE_SAMPLE_RATE，建议设置为 1 或合理采样率。'
  if (text === 'sample_rate_invalid') return 'LANGFUSE_SAMPLE_RATE 不是合法数字。'
  if (text === 'sample_rate_zero') return 'LANGFUSE_SAMPLE_RATE 为 0，trace 会被采样掉。'
  if (text === 'environment_missing') return '未配置 LANGFUSE_ENVIRONMENT，线上排查会缺少环境维度。'
  if (text === 'release_missing') return '未配置 LANGFUSE_RELEASE，trace 无法关联部署版本。'
  return text
}

function integrationActionText(value: unknown): string {
  const text = String(value || '').trim()
  const key = text.toLowerCase()
  if (!text) return ''
  if (key.includes('langfuse_capture_input_output=true')) return '设置 LANGFUSE_CAPTURE_INPUT_OUTPUT=true 并重启，Langfuse 才会显示 Input/Output。'
  if (key.includes('langfuse_public_key') || key.includes('langfuse_secret_key') || key.includes('langfuse_base_url')) return '配置 LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY、LANGFUSE_BASE_URL。'
  if (key.includes('langfuse_sample_rate') && key.includes('above 0')) return '设置 LANGFUSE_SAMPLE_RATE 大于 0，避免 trace 被采样掉。'
  if (key.includes('langfuse_sample_rate')) return '设置 LANGFUSE_SAMPLE_RATE 为 0 到 1 之间的数字。'
  if (key.includes('dashscope package')) return '安装 dashscope 依赖以启用 TTS。'
  if (key.includes('qwen_tts_realtime')) return '安装包含 qwen_tts_realtime 的 dashscope 版本。'
  if (key.includes('werewolf_tts_api_key')) return '配置 WEREWOLF_TTS_API_KEY 后重启。'
  return text
}

function runtimeProbeNotice(result: RuntimeHealthProbeResult): string {
  if (String(result.status || '').toLowerCase() === 'ok') {
    const latency = Number(result.latency_ms)
    return Number.isFinite(latency)
      ? `当前模型连接正常，耗时 ${latency}ms；相关启动门禁会使用这次结果。`
      : '当前模型连接正常；相关启动门禁会使用这次结果。'
  }
  return `${String(result.error?.message || result.message || '当前模型连接失败。')} 失败会阻断使用该模型的启动入口。`
}

function statusLabel(status: unknown): string {
  const text = String(status || '').toLowerCase()
  if (text === 'ok') return '正常'
  if (text === 'degraded') return '降级'
  if (text === 'error') return '错误'
  if (text === 'stale') return '需复测'
  if (text === 'untested') return '未测试'
  if (text === 'unknown') return '未知'
  if (text === 'immediate') return '立即生效'
  if (text === 'next_task') return '下次任务'
  if (text === 'requires_restart') return '需重启'
  if (text === 'env_locked') return '环境锁定'
  if (text === 'settings') return '本地设置'
  if (text === 'environment') return '环境变量'
  if (text === 'default') return '默认值'
  if (text === 'warning') return '警告'
  return String(status || '未知')
}

function checkLabel(key: string): string {
  return {
    postgresql: 'PostgreSQL',
    alembic: 'Alembic',
    registry_baseline: '角色基线',
    llm: 'LLM 启动',
    llm_config: '模型配置',
    llm_connectivity: '模型连接',
    langfuse_config: 'Langfuse 配置',
    tts_config: 'TTS 配置',
    task_queue: '任务队列',
    task_worker: 'Task worker',
    artifact_root: '产物目录'
  }[key] || key
}

function gateLabel(key: string): string {
  return {
    game_start: '开始游戏',
    benchmark_start: '启动 Benchmark',
    evolution_start: '启动 Evolution'
  }[key] || key
}

function gateIssueLabels(value: unknown, labels: Record<string, string>): string[] {
  return Array.isArray(value)
    ? value.map((item) => {
        const key = String(item || '').trim()
        return key ? labels[key] || checkLabel(key) : ''
      }).filter(Boolean)
    : []
}

function gateActionLabels(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => {
        const text = String(item || '').trim()
        const key = text.replace(/\.$/, '').trim().toLowerCase()
        return text ? HEALTH_GATE_ACTION_LABELS[key] || text : ''
      }).filter(Boolean)
    : []
}

function textArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item || '').trim()).filter(Boolean)
    : []
}

function gateDetailText(ready: boolean, blockers: string[], warnings: string[], actions: string[]): string {
  if (!ready) return actions[0] || blockers[0] || '需要先恢复运行环境。'
  if (warnings.length) return actions[0] || warnings[0] || '可启动，但建议先处理警告。'
  return '运行门禁通过。'
}

function runtimeProbeModelScope(): string {
  return MODEL_SCOPE_GROUPS.has(activeGroup.value) ? activeGroup.value : DEFAULT_MODEL_PROBE_SCOPE
}

function scopeText(profile: ModelProfile): string {
  const active = scopes.value
    .filter((scope) => Boolean(profile.default_scopes?.[scope.key]))
    .map((scope) => scope.label)
  return active.length ? active.join(' / ') : '未设默认'
}

function shortId(value: unknown): string {
  const text = String(value || '')
  return text.length > 24 ? `${text.slice(0, 24)}...` : text || '—'
}
</script>

<template>
  <section class="settings-page" data-test="settings-page" aria-label="设置控制台">
    <section class="settings-shell parchment-logbook">
      <aside class="settings-control-rail" aria-label="设置分组">
        <header class="settings-rail-header">
          <span>设置上下文</span>
          <strong>{{ activeGroupInfo.label }}</strong>
        </header>

        <div class="settings-filter-panel">
          <div class="settings-filter-head">
            <span class="settings-rail-label">设置分组</span>
            <p v-if="refreshedAt" class="settings-refresh-note">{{ formatDateTime(refreshedAt) }}</p>
          </div>
          <div class="settings-filter-list">
            <button
              v-for="group in GROUPS"
              :key="group.key"
              type="button"
              :data-group="group.key"
              :class="['settings-filter-chip', { selected: activeGroup === group.key }]"
              @click="selectGroup(group.key)"
            >
              <span>
                <b>{{ group.label }}</b>
                <small>{{ group.caption }}</small>
              </span>
              <em>{{ group.key === 'models' ? profiles.length : group.key === 'system' ? healthChecks.length : '·' }}</em>
            </button>
          </div>
        </div>
      </aside>

      <main class="settings-detail-panel">
        <header class="settings-command-bar">
          <div class="settings-command-title">
            <h2>设置控制台</h2>
          </div>
          <div class="settings-command-metrics" aria-label="设置状态条">
            <span v-for="item in settingsMetaRows" :key="item.key">
              <small>{{ item.label }}：</small>
              <b :title="String(item.value ?? '')">{{ item.value }}</b>
            </span>
          </div>
          <div class="settings-command-actions">
            <button type="button" class="settings-refresh-button" :disabled="healthProbeTesting || loading" @click="probeRuntimeModel">
              <span aria-hidden="true">&#9678;</span> {{ healthProbeTesting ? '测试中' : '测试' }}
            </button>
            <button type="button" class="settings-refresh-button" :disabled="loading" @click="refreshSettings">
              <span aria-hidden="true">&#8635;</span> {{ loading ? '刷新中' : '刷新' }}
            </button>
          </div>
        </header>

        <section class="settings-main-pane">
          <div class="settings-scroll">
            <div v-if="error" class="settings-warning">{{ error }}</div>
            <div v-if="notice" class="settings-notice">{{ notice }}</div>
            <div v-if="settingsGuidanceRows.length" class="settings-guidance" aria-label="设置恢复建议">
              <span v-for="row in settingsGuidanceRows" :key="row">{{ row }}</span>
            </div>

            <section v-if="activeGroup === 'models'" class="settings-card settings-profile-list" aria-label="模型 Profile 列表">
              <header>
                <div>
                  <small>模型 Profiles</small>
                  <h2>{{ profiles.length }} 个本地模型</h2>
                </div>
                <button type="button" class="settings-card-action" @click="startNewProfile">新建</button>
              </header>
              <div class="settings-profile-table">
                <button
                  v-for="profile in profiles"
                  :key="profile.profile_id"
                  type="button"
                  :class="['settings-profile-row', { selected: selectedProfileId === profile.profile_id }]"
                  :data-status="profile.last_test_status || 'untested'"
                  @click="selectProfile(profile)"
                >
                  <span class="settings-status-dot" aria-hidden="true"></span>
                  <span class="settings-main-cell">
                    <b :title="profile.name">{{ profile.name }}</b>
                    <small :title="profile.base_url">{{ profile.provider }} / {{ profile.model }}</small>
                  </span>
                  <span class="settings-scope-cell">
                    <b>{{ statusLabel(profile.last_test_status || 'untested') }}</b>
                    <small :class="{ error: Boolean(profileTestError(profile)) }">
                      {{ profileTestError(profile) || scopeText(profile) }}
                    </small>
                  </span>
                  <span class="settings-time-cell">
                    <b>{{ profile.enabled ? '启用' : '禁用' }}</b>
                    <small>{{ formatDateTime(profile.last_tested_at) }}</small>
                  </span>
                </button>
                <div v-if="!profiles.length && !loading" class="settings-empty">暂无模型 Profile。</div>
                <div v-if="loading" class="settings-empty">正在读取设置。</div>
              </div>
            </section>

            <section v-if="activeGroup === 'models'" class="settings-card settings-editor" aria-label="模型 Profile 表单">
              <header>
                <div>
                  <small>{{ selectedProfile ? '编辑 Profile' : '新建 Profile' }}</small>
                  <h2>{{ selectedProfile ? selectedProfile.name : '本地模型配置' }}</h2>
                </div>
                <b>{{ profileFormDirty ? '未保存' : adminWriteStateLabel }}</b>
              </header>
              <div v-if="profileGuidanceRows.length" class="settings-guardrail" aria-label="模型操作提示">
                <span v-for="row in profileGuidanceRows" :key="row">{{ row }}</span>
              </div>

              <div class="settings-form-grid">
                <label>
                  <small>名称</small>
                  <input v-model="form.name" :disabled="!canWrite" placeholder="Qwen Prod" />
                </label>
                <label>
                  <small>Provider</small>
                  <select v-model="form.provider" :disabled="!canWrite">
                    <option v-for="provider in providers" :key="provider" :value="provider">{{ provider }}</option>
                  </select>
                </label>
                <label class="wide">
                  <small>Base URL</small>
                  <input v-model="form.base_url" :disabled="!canWrite" placeholder="https://example.com/v1" />
                </label>
                <label>
                  <small>Model</small>
                  <input v-model="form.model" :disabled="!canWrite" placeholder="qwen-plus" />
                </label>
                <label>
                  <small>API key</small>
                  <input
                    v-model="form.api_key"
                    :disabled="!canWrite"
                    type="password"
                    autocomplete="off"
                    :placeholder="selectedProfile?.api_key_masked ? `已保存：${selectedProfile.api_key_masked}` : '保存后只留在服务端'"
                  />
                </label>
                <label>
                  <small>Temperature</small>
                  <input v-model.number="form.temperature" :disabled="!canWrite" type="number" min="0" max="2" step="0.1" />
                </label>
                <label>
                  <small>Timeout</small>
                  <input v-model.number="form.timeout_seconds" :disabled="!canWrite" type="number" min="1" max="600" step="1" />
                </label>
                <label>
                  <small>Max retries</small>
                  <input v-model.number="form.max_retries" :disabled="!canWrite" type="number" min="0" max="10" step="1" />
                </label>
              </div>

              <div class="settings-editor-options">
                <div class="settings-toggle-grid">
                  <label>
                    <input v-model="form.enabled" :disabled="!canWrite" type="checkbox" />
                    <span>启用 Profile</span>
                  </label>
                  <label>
                    <input v-model="form.clear_api_key" :disabled="!canWrite || !selectedProfile?.has_api_key" type="checkbox" />
                    <span>清除已保存 key</span>
                  </label>
                </div>

                <div class="settings-scope-grid">
                  <div>
                    <small>默认用途</small>
                    <label v-for="scope in scopes" :key="scope.key">
                      <input v-model="form.default_scopes[scope.key]" :disabled="!canWrite || Boolean(envLocks[scope.key])" type="checkbox" />
                      <span>{{ scope.label }}</span>
                    </label>
                  </div>
                  <div>
                    <small>Capabilities</small>
                    <label v-for="(_value, key) in form.capabilities" :key="key">
                      <input v-model="form.capabilities[key]" :disabled="!canWrite" type="checkbox" />
                      <span>{{ key }}</span>
                    </label>
                  </div>
                </div>
              </div>

              <footer class="settings-form-actions">
                <button type="button" class="settings-card-action primary" :disabled="!canSubmitProfile" :title="profileGuidanceRows[0] || ''" @click="saveProfile">
                  {{ saving ? '保存中' : selectedProfile ? '保存' : '创建' }}
                </button>
                <button type="button" class="settings-card-action" :disabled="!canTestSelectedProfile" :title="profileTestButtonTitle" @click="testSelectedProfile">
                  {{ testing ? '测试中' : '测试连接' }}
                </button>
                <button type="button" class="settings-card-action" :disabled="!selectedProfile || !canWrite" :title="selectedProfile ? adminWriteHint() : '先选择模型 Profile。'" @click="disableSelectedProfile">禁用</button>
                <button type="button" class="settings-card-action danger" :disabled="!selectedProfile || !canWrite" :title="selectedProfile ? adminWriteHint() : '先选择模型 Profile。'" @click="deleteSelectedProfile">删除</button>
              </footer>
            </section>

            <section v-if="activeGroup === 'variables'" class="settings-card" aria-label="运行变量">
              <header>
                <div>
                  <small>运行变量</small>
                  <h2>{{ variables.length }} 个变量</h2>
                </div>
                <b>{{ canWrite ? '可编辑' : '只读' }}</b>
              </header>
              <div class="settings-variable-list">
                <div v-for="variable in variables" :key="variable.key" class="settings-variable-row">
                  <span>
                    <b>{{ variable.label }}</b>
                    <small>{{ variable.locked ? '环境变量锁定：需改服务端环境变量后重启。' : variable.description || variable.key }}</small>
                  </span>
                  <label v-if="variable.value_type === 'boolean'" class="settings-variable-toggle">
                    <input
                      v-model="variableDrafts[variable.key]"
                      :disabled="!variableCanEdit(variable)"
                      type="checkbox"
                    />
                    <b>{{ variableDrafts[variable.key] ? '开启' : '关闭' }}</b>
                  </label>
                  <input
                    v-else-if="variable.value_type === 'integer' || variable.value_type === 'number'"
                    v-model.number="variableDrafts[variable.key]"
                    :disabled="!variableCanEdit(variable)"
                    :min="variable.minimum ?? undefined"
                    :max="variable.maximum ?? undefined"
                    class="settings-variable-input"
                    type="number"
                    step="1"
                  />
                  <em v-else>{{ variable.value }}</em>
                  <strong :title="variable.key">
                    {{ variable.locked ? '环境锁定' : statusLabel(variable.source || variable.state) }}
                    <small>{{ statusLabel(variable.state) }}</small>
                  </strong>
                  <button
                    type="button"
                    class="settings-card-action"
                    :disabled="!variableCanEdit(variable) || savingVariableKey === variable.key || !variableDirty(variable)"
                    @click="saveRuntimeVariable(variable)"
                  >
                    {{ savingVariableKey === variable.key ? '保存中' : '保存' }}
                  </button>
                </div>
                <div v-if="!variables.length" class="settings-empty">暂无运行变量。</div>
              </div>
            </section>

            <section v-if="['benchmark', 'evolution'].includes(activeGroup)" class="settings-card" aria-label="任务默认模型">
              <header>
                <div>
                  <small>{{ activeGroupInfo.label }}</small>
                  <h2>{{ scopedProfiles.length }} 个可用默认模型</h2>
                </div>
                <b>{{ Boolean(envLocks[activeGroup]) ? '环境锁定' : '可配置' }}</b>
              </header>
              <div v-if="inactiveScopedProfiles.length" class="settings-guardrail" aria-label="不可用默认模型">
                <span v-for="profile in inactiveScopedProfiles" :key="profile.profile_id">
                  {{ profile.name }} 未计入可用默认模型：{{ profile.enabled ? '缺少 API key' : '已禁用' }}
                </span>
              </div>
              <div class="settings-profile-table compact">
                <button
                  v-for="profile in scopedProfiles"
                  :key="profile.profile_id"
                  type="button"
                  class="settings-profile-row"
                  @click="selectProfile(profile); selectGroup('models')"
                >
                  <span class="settings-status-dot" aria-hidden="true"></span>
                  <span class="settings-main-cell">
                    <b>{{ profile.name }}</b>
                    <small>{{ profile.model }}</small>
                  </span>
                  <span class="settings-time-cell">
                    <b>{{ statusLabel(profile.last_test_status || 'untested') }}</b>
                    <small>{{ shortId(profile.model_config_hash) }}</small>
                  </span>
                </button>
                <div v-if="!scopedProfiles.length" class="settings-empty">还没有为 {{ activeGroupInfo.label }} 指定可用默认模型。</div>
              </div>
            </section>

            <section v-if="activeGroup === 'langfuse' || activeGroup === 'tts'" class="settings-card" aria-label="集成状态">
              <header>
                <div>
                  <small>{{ activeGroupInfo.label }}</small>
                  <h2>集成状态</h2>
                </div>
                <b>只读</b>
              </header>
              <div class="settings-health-grid">
                <div v-for="item in activeIntegrationChecks" :key="item.key" class="settings-health-row">
                  <span>
                    <b>{{ item.label }}</b>
                    <small>{{ item.message || '未提供详情' }}</small>
                  </span>
                  <em :data-status="item.status">{{ statusLabel(item.status) }}</em>
                </div>
                <div v-if="!activeIntegrationChecks.length" class="settings-empty">当前 health payload 暂未提供 {{ activeGroupInfo.label }} 检查。</div>
              </div>
              <div v-if="activeIntegrationDetailRows.length" class="settings-integration-grid" aria-label="集成配置详情">
                <div v-for="row in activeIntegrationDetailRows" :key="row.key" :data-status="row.severity">
                  <span>
                    <b>{{ row.label }}</b>
                    <small>{{ row.detail }}</small>
                  </span>
                  <em>{{ row.value }}</em>
                </div>
              </div>
              <div v-if="activeIntegrationGuidanceRows.length" class="settings-guardrail" aria-label="集成恢复建议">
                <span v-for="row in activeIntegrationGuidanceRows" :key="row">{{ row }}</span>
              </div>
            </section>

            <section v-if="activeGroup === 'system'" class="settings-card" aria-label="系统状态">
              <header>
                <div>
                  <small>系统状态</small>
                  <h2>{{ statusLabel(healthStatus) }}</h2>
                </div>
                <b>{{ healthReady ? 'ready' : 'not ready' }}</b>
              </header>
              <div class="settings-ops-grid" aria-label="运行快照">
                <div v-for="item in opsMetricRows" :key="item.key" class="settings-ops-row" :data-status="item.severity">
                  <span>
                    <b>{{ item.label }}</b>
                    <small>{{ item.detail }}</small>
                  </span>
                  <em>{{ item.value }}</em>
                </div>
              </div>
              <div v-if="opsAlertRows.length" class="settings-alert-grid" aria-label="运行告警">
                <div v-for="alert in opsAlertRows" :key="alert.key" class="settings-alert-row" :data-status="alert.severity">
                  <span>
                    <b>{{ alert.label }}</b>
                    <small>{{ alert.detail }}</small>
                  </span>
                  <em>{{ alert.severity === 'error' ? '阻断' : '降级' }}</em>
                </div>
              </div>
              <div v-else class="settings-context-empty">暂无运行告警。</div>
              <div class="settings-health-grid settings-health-grid--system">
                <div v-for="item in healthChecks" :key="item.key" class="settings-health-row">
                  <span>
                    <b>{{ item.label }}</b>
                    <small>{{ item.message || item.key }}</small>
                  </span>
                  <em :data-status="item.status">{{ statusLabel(item.status) }}</em>
                </div>
              </div>
            </section>
          </div>
        </section>
      </main>

      <aside class="settings-context-rail" aria-label="设置详情" data-settings-context-rail>
        <div class="settings-context-scroll">
          <header class="settings-context-head">
            <span>
              <small>当前分组</small>
              <strong>{{ activeGroupInfo.label }}</strong>
            </span>
            <b>{{ statusLabel(healthStatus) }}</b>
          </header>

          <section class="settings-context-section settings-admin-panel">
            <h3>管理员写入</h3>
            <p class="settings-context-empty">{{ adminWriteStatus }}：{{ adminWriteHint() }}</p>
            <div v-if="storageRows.length" class="settings-storage-list" aria-label="设置存储状态">
              <span v-for="row in storageRows" :key="row.key" :data-status="row.severity">
                <b>{{ row.label }}</b>
                <small>{{ row.backend }} · {{ row.status }}</small>
                <em>{{ row.hint }}</em>
              </span>
            </div>
            <label class="settings-admin-token">
              <small>Admin Token</small>
              <input v-model="adminToken" type="password" autocomplete="off" placeholder="只保存在当前页面内存" />
            </label>
          </section>

          <section class="settings-context-section settings-profile-context">
            <h3>当前 Profile</h3>
            <template v-if="selectedProfile">
              <div class="settings-context-run-id">
                <small>profile_id</small>
                <code>{{ selectedProfile.profile_id }}</code>
              </div>
              <div class="settings-context-kpis">
                <span>
                  <small>模型</small>
                  <b :title="selectedProfile.model">{{ selectedProfile.model }}</b>
                </span>
                <span>
                  <small>Key</small>
                  <b>{{ selectedProfile.api_key_masked || '未保存' }}</b>
                </span>
                <span>
                  <small>测试</small>
                  <b>{{ statusLabel(selectedProfile.last_test_status || 'untested') }}</b>
                </span>
                <span>
                  <small>Hash</small>
                  <b>{{ shortId(selectedProfile.model_config_hash) }}</b>
                </span>
              </div>
              <p class="settings-context-empty">
                {{ ['error', 'stale', 'untested'].includes(String(selectedProfile.last_test_status || 'untested')) ? '连接未确认时，启动入口会重新预检；预检失败才会阻断。' : '连接状态可用于启动门禁判断。' }}
              </p>
              <p v-if="selectedProfileLastTestError" class="settings-context-empty error">
                上次失败：{{ selectedProfileLastTestError }}
              </p>
              <p v-if="profileFormDirty" class="settings-context-empty warning">
                当前表单未保存；测试连接会先被禁用，避免误测旧配置。
              </p>
            </template>
            <p v-else class="settings-context-empty">正在编辑新 Profile。</p>
          </section>

          <section class="settings-context-section settings-gate-panel">
            <h3>运行门禁</h3>
            <div v-if="opsAlertRows.length" class="settings-alert-list" aria-label="运行告警摘要">
              <span v-for="alert in opsAlertRows.slice(0, 3)" :key="alert.key" :data-status="alert.severity">
                <b>{{ alert.label }}</b>
                <small>{{ alert.detail }}</small>
              </span>
            </div>
            <div class="settings-gate-list">
              <div v-for="gate in gateRows" :key="gate.key" class="settings-gate-item" :data-status="gate.severity">
                <div class="settings-gate-copy">
                  <b>{{ gate.label }}</b>
                  <small>{{ gate.summary }}；{{ gate.detail }}</small>
                </div>
              </div>
              <p v-if="!gateRows.length" class="settings-context-empty">暂无门禁项。</p>
            </div>
          </section>
        </div>
      </aside>
    </section>
  </section>
</template>

<style scoped>
.settings-page {
  --settings-bg: #f2dfae;
  --settings-bg-texture:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    var(--settings-bg);
  --settings-surface: rgba(255, 252, 245, 0.52);
  --settings-panel: rgba(255, 252, 245, 0.68);
  --settings-panel-solid: rgba(255, 250, 240, 0.76);
  --settings-border: rgba(139, 94, 52, 0.15);
  --settings-border-strong: rgba(90, 51, 25, 0.34);
  --settings-text: #3a2a18;
  --settings-muted: #8b6b4a;
  --settings-accent: #8b5e34;
  --settings-accent-strong: #5a3319;
  --settings-danger: #993026;
  --settings-input-bg: rgba(255, 255, 250, 0.58);
  --settings-input-border: rgba(139, 94, 52, 0.2);
  --settings-hover: rgba(139, 94, 52, 0.06);
  --settings-active-bg: rgba(139, 94, 52, 0.1);
  --settings-font: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif;
  position: fixed;
  z-index: 11;
  top: 72px;
  right: 0;
  bottom: 0;
  left: 0;
  margin: 0;
  overflow: hidden;
  color: var(--settings-text);
  font-family: var(--settings-font);
  background: transparent;
}

.settings-page *:not(svg):not(svg *) {
  box-sizing: border-box;
  font-family: var(--settings-font);
}

.settings-shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr) 292px;
  grid-template-rows: auto minmax(0, 1fr);
  grid-template-areas:
    "rail command context"
    "rail pane context";
  height: 100%;
  min-height: 0;
  overflow: hidden;
  column-gap: 18px;
  row-gap: 0;
  padding: 26px;
  background: var(--settings-bg-texture);
}

.settings-detail-panel {
  display: contents;
}

.settings-control-rail,
.settings-context-rail,
.settings-main-pane,
.settings-scroll,
.settings-context-scroll,
.settings-card,
.settings-profile-row {
  min-width: 0;
  min-height: 0;
}

.settings-control-rail {
  grid-area: rail;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  padding: 0 14px 0 0;
  border-right: 1px solid rgba(91, 47, 18, 0.2);
  background: transparent;
}

.settings-rail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--settings-border);
  background: transparent;
}

.settings-context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
}

.settings-rail-header span,
.settings-context-head small,
.settings-rail-label,
.settings-card small,
.settings-form-grid small,
.settings-scope-grid small,
.settings-admin-token small {
  color: var(--settings-muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
}

.settings-rail-header strong,
.settings-context-head strong {
  min-width: 0;
  overflow: hidden;
  margin-left: auto;
  color: var(--settings-accent);
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-context-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  padding: 0 0 2px;
}

.settings-context-kpis span,
.settings-gate-item {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.32);
}

.settings-context-kpis b,
.settings-gate-list b {
  min-width: 0;
  overflow: hidden;
  color: var(--settings-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-filter-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  min-height: 0;
  padding: 0;
}

.settings-filter-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  margin-bottom: 0;
}

.settings-refresh-note {
  margin: 0;
  color: rgba(80, 50, 24, 0.58);
  font-size: 11px;
  font-weight: 700;
}

.settings-filter-list {
  display: grid;
  grid-template-columns: 1fr;
  grid-auto-rows: max-content;
  gap: 7px;
  align-content: start;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.28) transparent;
}

.settings-filter-chip,
.settings-refresh-button,
.settings-card-action {
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.settings-filter-chip {
  --settings-filter-color: var(--settings-accent);
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  position: relative;
  width: 100%;
  min-height: 36px;
  padding: 0 10px 0 12px;
  background: rgba(255, 239, 194, 0.42);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  text-align: left;
}

.settings-filter-chip::before {
  content: "";
  width: 16px;
  height: 16px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 5px;
  background:
    radial-gradient(circle at 50% 50%, rgba(255, 252, 228, 0.92) 0 2px, transparent 2px),
    var(--settings-filter-color);
  box-shadow:
    inset 0 1px 0 rgba(255, 252, 228, 0.58),
    0 1px 2px rgba(93, 48, 17, 0.12);
}

.settings-filter-chip::after {
  content: "";
  position: absolute;
  top: 7px;
  bottom: 7px;
  left: 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--settings-filter-color);
  opacity: 0.62;
}

.settings-filter-chip[data-group="models"],
.settings-filter-chip[data-group="benchmark"],
.settings-filter-chip[data-group="evolution"] {
  --settings-filter-color: #6a7a2c;
}

.settings-filter-chip[data-group="variables"] {
  --settings-filter-color: #b9852f;
}

.settings-filter-chip[data-group="langfuse"] {
  --settings-filter-color: #7a6047;
}

.settings-filter-chip[data-group="tts"] {
  --settings-filter-color: #8b5e34;
}

.settings-filter-chip[data-group="system"] {
  --settings-filter-color: var(--settings-danger);
}

.settings-filter-chip span,
.settings-profile-row span,
.settings-variable-row span,
.settings-health-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-filter-chip b,
.settings-profile-row b,
.settings-variable-row b,
.settings-health-row b {
  overflow: hidden;
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-filter-chip small,
.settings-profile-row small,
.settings-variable-row small,
.settings-health-row small,
.settings-gate-list small {
  overflow: hidden;
  color: var(--settings-muted);
  font-size: 11px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-profile-row small.error {
  color: var(--settings-danger);
}

.settings-filter-chip em {
  min-width: max-content;
  color: currentColor;
  font-style: normal;
  font-size: 10px;
  font-weight: 750;
  opacity: 0.72;
  white-space: nowrap;
}

.settings-filter-chip:hover {
  border-color: rgba(90, 51, 25, 0.34);
  background: rgba(255, 245, 214, 0.62);
}

.settings-filter-chip.selected {
  border-color: rgba(93, 48, 17, 0.45);
  color: var(--settings-text);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.settings-command-bar {
  grid-area: command;
  display: grid;
  grid-template-columns: minmax(108px, 0.32fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 18px 20px 16px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background:
    linear-gradient(135deg, rgba(58, 42, 24, 0.96), rgba(90, 51, 25, 0.9)),
    repeating-linear-gradient(90deg, rgba(232, 196, 132, 0.08) 0 1px, transparent 1px 18px);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.1);
}

.settings-command-title h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #fff4d9;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-command-metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px 12px;
  min-width: 0;
  overflow: visible;
}

.settings-command-metrics span {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  flex: 0 0 auto;
  min-width: 0;
  max-width: none;
  overflow: visible;
}

.settings-command-metrics small {
  flex: 0 0 auto;
  color: rgba(232, 210, 170, 0.68);
  font-size: 12px;
  font-weight: 800;
}

.settings-command-metrics b {
  flex: 0 1 auto;
  min-width: 0;
  overflow: visible;
  color: #fff4d9;
  font-size: 14px;
  text-overflow: clip;
  white-space: nowrap;
}

.settings-command-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

.settings-refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 56px;
  height: 42px;
  padding: 0 10px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  background: rgba(255, 239, 194, 0.42);
  color: rgba(59, 28, 9, 0.78);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  font-size: 13px;
  font-weight: 800;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  white-space: nowrap;
}

.settings-refresh-button:hover {
  border-color: rgba(93, 48, 17, 0.32);
  color: var(--settings-text);
  background: rgba(255, 245, 214, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.82);
  transform: none;
}

.settings-main-pane {
  grid-area: pane;
  overflow: hidden;
  border: 1px solid var(--settings-border);
  border-radius: 0 0 8px 8px;
  background: rgba(255, 252, 245, 0.24);
}

.settings-scroll {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.settings-context-scroll {
  display: grid;
  align-content: start;
  gap: 10px;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.3) transparent;
}

.settings-scroll::-webkit-scrollbar,
.settings-context-scroll::-webkit-scrollbar {
  width: 6px;
}

.settings-scroll::-webkit-scrollbar-thumb,
.settings-context-scroll::-webkit-scrollbar-thumb {
  border-radius: 3px;
  background: rgba(139, 94, 52, 0.18);
}

.settings-card {
  display: grid;
  flex: 0 0 auto;
  align-content: start;
  gap: 12px;
  margin-bottom: 0;
  padding: 14px;
  border: 1px solid rgba(93, 48, 17, 0.16);
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.36), rgba(255, 239, 194, 0.18)),
    rgba(255, 252, 245, 0.24);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.48);
}

.settings-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  min-height: 38px;
  margin: -2px 0 0;
  padding: 0 0 10px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.14);
}

.settings-card h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-card > header > b,
.settings-context-head > b {
  flex: 0 0 auto;
  padding: 3px 8px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 239, 194, 0.38);
  color: rgba(74, 37, 15, 0.72);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.2;
}

.settings-card-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 0 10px;
  background: rgba(255, 239, 194, 0.42);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  font-size: 11px;
  font-weight: 900;
  white-space: nowrap;
}

.settings-card-action.primary {
  background: #e8c484;
  color: #2d1e10;
}

.settings-card-action.danger {
  color: var(--settings-danger);
}

.settings-card-action:disabled,
.settings-refresh-button:disabled,
.settings-form-grid input:disabled,
.settings-form-grid select:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.settings-profile-table,
.settings-variable-list,
.settings-health-grid {
  display: grid;
  gap: 7px;
}

.settings-profile-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) minmax(132px, 0.42fr) minmax(132px, 0.38fr);
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 54px;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.38);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.5);
  color: var(--settings-text);
  text-align: left;
  cursor: pointer;
}

.settings-profile-row:hover,
.settings-profile-row.selected {
  border-color: rgba(93, 48, 17, 0.26);
  background: rgba(255, 245, 214, 0.54);
}

.settings-profile-row.selected {
  border-color: rgba(93, 48, 17, 0.45);
  background: rgba(224, 184, 111, 0.36);
}

.settings-status-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: #8b6b4a;
}

.settings-profile-row[data-status="ok"] .settings-status-dot,
.settings-health-row em[data-status="ok"] {
  background: #68772b;
}

.settings-profile-row[data-status="error"] .settings-status-dot,
.settings-health-row em[data-status="error"] {
  background: #993026;
}

.settings-editor {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(240px, 280px);
  grid-template-areas:
    "head head"
    "guard guard"
    "form options"
    "actions actions";
  column-gap: 12px;
  row-gap: 12px;
  grid-auto-rows: auto;
  align-content: start;
  align-items: start;
  overflow: visible;
}

.settings-editor > header {
  grid-area: head;
}

.settings-editor .settings-guardrail {
  grid-area: guard;
}

.settings-editor .settings-form-grid {
  grid-area: form;
}

.settings-editor-options {
  display: grid;
  grid-area: options;
  align-self: start;
  align-content: start;
  gap: 10px;
  width: 100%;
  min-width: 0;
}

.settings-editor .settings-form-actions {
  grid-area: actions;
}

.settings-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 0;
}

.settings-form-grid label,
.settings-admin-token {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.settings-form-grid .wide {
  grid-column: 1 / -1;
}

.settings-form-grid input,
.settings-form-grid select,
.settings-admin-token input {
  width: 100%;
  min-width: 0;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--settings-input-border);
  border-radius: 0;
  background: var(--settings-input-bg);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.46);
  color: var(--settings-text);
  font-size: 13px;
  font-weight: 850;
  outline: none;
}

.settings-toggle-grid,
.settings-scope-grid {
  display: grid;
  align-self: start;
  gap: 8px;
  min-width: 0;
  padding: 0;
}

.settings-toggle-grid,
.settings-scope-grid > div {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.28), rgba(255, 239, 194, 0.14)),
    rgba(255, 252, 245, 0.24);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.46);
}

.settings-scope-grid {
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
}

.settings-scope-grid > div {
  display: grid;
  gap: 6px;
  align-content: start;
}

.settings-scope-grid small {
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
}

.settings-toggle-grid label,
.settings-scope-grid label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
  color: var(--settings-text);
  font-size: 12px;
  font-weight: 850;
}

.settings-toggle-grid input,
.settings-scope-grid input {
  width: 14px;
  height: 14px;
  accent-color: var(--settings-accent);
}

.settings-form-actions {
  display: flex;
  align-self: start;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  min-width: 0;
  padding: 10px 0 0;
  border-top: 1px solid rgba(93, 48, 17, 0.12);
}

.settings-variable-row,
.settings-health-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(112px, 0.24fr) minmax(116px, 0.22fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 56px;
  padding: 9px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.38);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.5);
}

.settings-health-grid--system {
  max-height: min(610px, calc(100dvh - 238px));
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.3) transparent;
}

.settings-health-grid--system::-webkit-scrollbar {
  width: 6px;
}

.settings-health-grid--system::-webkit-scrollbar-thumb {
  border-radius: 3px;
  background: rgba(139, 94, 52, 0.18);
}

.settings-health-row {
  grid-template-columns: minmax(0, 1fr) auto;
}

.settings-integration-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.settings-ops-grid,
.settings-alert-grid,
.settings-alert-list {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.settings-ops-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.settings-integration-grid > div {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  min-width: 0;
  min-height: 64px;
  padding: 9px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  background: rgba(255, 252, 245, 0.34);
}

.settings-ops-row,
.settings-alert-row,
.settings-alert-list span {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px;
  min-width: 0;
  min-height: 58px;
  padding: 9px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-left: 3px solid rgba(104, 119, 43, 0.68);
  background: rgba(255, 252, 245, 0.34);
}

.settings-alert-row,
.settings-alert-list span {
  min-height: 0;
  border-left-color: #b9852f;
  background: rgba(255, 239, 194, 0.32);
}

.settings-ops-row[data-status="warning"],
.settings-alert-row[data-status="warning"],
.settings-alert-list span[data-status="warning"] {
  border-left-color: #b9852f;
  background: rgba(255, 239, 194, 0.38);
}

.settings-ops-row[data-status="error"],
.settings-alert-row[data-status="error"],
.settings-alert-list span[data-status="error"] {
  border-left-color: var(--settings-danger);
  background: rgba(153, 48, 38, 0.07);
}

.settings-integration-grid > div[data-status="warning"] {
  border-color: rgba(185, 133, 47, 0.26);
  background: rgba(255, 239, 194, 0.36);
}

.settings-integration-grid > div[data-status="error"] {
  border-color: rgba(153, 48, 38, 0.22);
  background: rgba(153, 48, 38, 0.07);
}

.settings-integration-grid span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-ops-row span,
.settings-alert-row span,
.settings-alert-list span span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-integration-grid b,
.settings-integration-grid small,
.settings-integration-grid em,
.settings-ops-row b,
.settings-ops-row small,
.settings-ops-row em,
.settings-alert-row b,
.settings-alert-row small,
.settings-alert-row em,
.settings-alert-list b,
.settings-alert-list small {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-integration-grid b,
.settings-ops-row b,
.settings-alert-row b,
.settings-alert-list b {
  color: var(--settings-text);
  font-size: 12px;
  font-weight: 920;
}

.settings-integration-grid small,
.settings-ops-row small,
.settings-alert-row small,
.settings-alert-list small {
  color: var(--settings-muted);
  font-size: 11px;
  font-weight: 760;
  line-height: 1.35;
}

.settings-integration-grid em,
.settings-ops-row em,
.settings-alert-row em {
  justify-self: start;
  max-width: 100%;
  padding: 4px 7px;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--settings-accent-strong);
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  text-align: left;
  white-space: normal;
}

.settings-gate-grid {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.settings-gate-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(132px, 0.32fr);
  gap: 10px;
  align-items: center;
  min-height: 54px;
  padding: 9px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-left: 3px solid rgba(104, 119, 43, 0.68);
  background: rgba(255, 252, 245, 0.38);
}

.settings-gate-row[data-status="warning"] {
  border-left-color: #b9852f;
}

.settings-gate-row[data-status="error"] {
  border-left-color: var(--settings-danger);
}

.settings-gate-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-gate-row b {
  overflow: hidden;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-gate-row small {
  color: var(--settings-muted);
  font-size: 11px;
  font-weight: 760;
  line-height: 1.35;
}

.settings-variable-row em,
.settings-health-row em,
.settings-gate-row em {
  justify-self: end;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--settings-accent-strong);
  font-style: normal;
  font-size: 12px;
  font-weight: 800;
}

.settings-variable-row strong {
  display: grid;
  gap: 2px;
  justify-self: end;
  color: var(--settings-muted);
  font-size: 12px;
  text-align: right;
}

.settings-variable-row strong small {
  max-width: 118px;
}

.settings-variable-toggle {
  display: inline-flex;
  align-items: center;
  justify-self: end;
  gap: 8px;
  min-width: 104px;
  min-height: 34px;
  padding: 5px 9px;
  border: 1px solid rgba(139, 94, 52, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.4);
  color: var(--settings-accent-strong);
  font-size: 12px;
  font-weight: 900;
}

.settings-variable-toggle input {
  width: 16px;
  height: 16px;
  accent-color: var(--settings-accent);
}

.settings-variable-input {
  justify-self: end;
  width: min(128px, 100%);
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--settings-input-border);
  border-radius: 0;
  background: var(--settings-input-bg);
  color: var(--settings-text);
  font-size: 13px;
  font-weight: 800;
  outline: none;
}

.settings-variable-input:disabled,
.settings-variable-toggle input:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.settings-empty,
.settings-warning,
.settings-notice,
.settings-context-empty {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  padding: 10px;
  color: var(--settings-muted);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.45;
}

.settings-empty,
.settings-context-empty {
  border: 1px dashed rgba(93, 48, 17, 0.16);
  border-radius: 0;
  background: rgba(255, 242, 210, 0.34);
}

.settings-context-empty.error {
  border-color: rgba(153, 48, 38, 0.2);
  background: rgba(153, 48, 38, 0.07);
  color: var(--settings-danger);
}

.settings-context-empty.warning {
  border-color: rgba(185, 133, 47, 0.22);
  background: rgba(255, 239, 194, 0.38);
  color: var(--settings-accent-strong);
}

.settings-warning {
  margin-bottom: 0;
  border: 1px solid rgba(153, 48, 38, 0.22);
  border-radius: 0;
  background: rgba(153, 48, 38, 0.08);
  color: var(--settings-danger);
}

.settings-notice {
  margin-bottom: 0;
  border: 1px solid rgba(104, 119, 43, 0.2);
  border-radius: 0;
  background: rgba(104, 119, 43, 0.08);
  color: #4e5f22;
}

.settings-guidance,
.settings-guardrail {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid rgba(185, 133, 47, 0.22);
  background: rgba(255, 239, 194, 0.34);
}

.settings-guidance span,
.settings-guardrail span {
  position: relative;
  min-width: 0;
  padding-left: 14px;
  color: var(--settings-accent-strong);
  font-size: 12px;
  font-weight: 780;
  line-height: 1.42;
  overflow-wrap: anywhere;
}

.settings-guidance span::before,
.settings-guardrail span::before {
  content: "";
  position: absolute;
  top: 0.58em;
  left: 0;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #b9852f;
}

.settings-context-rail {
  grid-area: context;
  max-width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  padding-left: 16px;
  border-left: 1px solid rgba(93, 48, 17, 0.2);
  background: transparent;
}

.settings-context-head,
.settings-context-section {
  max-width: 100%;
  min-width: 0;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.28), rgba(255, 239, 194, 0.14)),
    rgba(255, 252, 245, 0.2);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.46);
}

.settings-context-section {
  position: relative;
  display: grid;
  gap: 8px;
  margin-bottom: 0;
  overflow: hidden;
  padding: 10px 11px 11px;
}

.settings-context-section::before {
  content: "";
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 3px;
  background: var(--settings-accent);
  opacity: 0.34;
}

.settings-admin-panel::before {
  background: #b9852f;
}

.settings-profile-context::before {
  background: #6a7a2c;
}

.settings-gate-panel::before {
  background: #7a6047;
}

.settings-context-section h3 {
  margin: 0;
  padding: 0 0 7px 7px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  color: #3b1c09;
  font-size: 13px;
  font-weight: 950;
}

.settings-admin-token {
  padding: 0;
}

.settings-admin-token input {
  height: 34px;
}

.settings-storage-list {
  display: grid;
  gap: 6px;
}

.settings-storage-list span {
  display: grid;
  grid-template-columns: minmax(0, 0.74fr) minmax(0, 0.8fr);
  gap: 3px 8px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  background: rgba(255, 252, 245, 0.26);
}

.settings-storage-list span[data-status="error"] {
  border-color: rgba(153, 48, 38, 0.2);
  background: rgba(153, 48, 38, 0.06);
}

.settings-storage-list b,
.settings-storage-list small,
.settings-storage-list em {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-storage-list b {
  color: var(--settings-text);
  font-size: 12px;
  font-weight: 900;
}

.settings-storage-list small {
  justify-self: end;
  color: var(--settings-muted);
  font-size: 11px;
  font-weight: 800;
  text-align: right;
}

.settings-storage-list em {
  grid-column: 1 / -1;
  color: var(--settings-accent-strong);
  font-size: 11px;
  font-style: normal;
  font-weight: 760;
  line-height: 1.35;
}

.settings-context-run-id {
  display: grid;
  gap: 6px;
  min-width: 0;
  margin: 0;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.28);
}

.settings-context-run-id small {
  color: var(--settings-muted);
  font-size: 11px;
  font-weight: 800;
}

.settings-context-run-id code {
  min-width: 0;
  overflow: hidden;
  overflow-wrap: anywhere;
  color: var(--settings-text);
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-gate-list {
  display: grid;
  gap: 8px;
  padding: 0;
}

.settings-context-kpis {
  gap: 0 10px;
}

.settings-context-kpis span {
  min-height: 0;
  padding: 7px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.settings-gate-item {
  gap: 0;
  min-height: 0;
  padding: 8px 9px 8px 11px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-left: 3px solid rgba(104, 119, 43, 0.68);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.3);
  box-shadow: none;
}

.settings-gate-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
  max-width: 100%;
}

.settings-gate-item[data-status="error"] {
  border-left-color: var(--settings-danger);
  background: rgba(153, 48, 38, 0.06);
}

.settings-gate-item[data-status="warning"] {
  border-left-color: #b9852f;
  background: rgba(255, 239, 194, 0.32);
}

.settings-gate-item[data-status="error"] b {
  color: var(--settings-danger);
}

.settings-gate-item[data-status="warning"] b {
  color: #7a6047;
}

.settings-gate-list small {
  display: block;
  overflow: visible;
  overflow-wrap: anywhere;
  text-overflow: clip;
  white-space: normal;
  word-break: normal;
  line-height: 1.38;
}

@media (max-width: 1120px) {
  .settings-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    margin: 0 12px 10px;
  }

  .settings-command-metrics,
  .settings-command-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .settings-shell,
  .settings-shell.parchment-logbook {
    grid-template-columns: 220px minmax(0, 1fr) 260px;
    column-gap: 14px;
  }

  .settings-editor {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "head"
      "guard"
      "form"
      "options"
      "actions";
  }

  .settings-editor .settings-form-grid,
  .settings-editor-options,
  .settings-editor .settings-form-actions {
    grid-column: auto;
    grid-row: auto;
  }

  .settings-editor-options {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-profile-row,
  .settings-variable-row,
  .settings-health-row {
    grid-template-columns: 12px minmax(0, 1fr);
  }

  .settings-health-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-integration-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-ops-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-variable-row strong,
  .settings-variable-input,
  .settings-variable-toggle,
  .settings-variable-row .settings-card-action,
  .settings-health-row em {
    justify-self: start;
  }
}

@media (max-width: 960px) {
  .settings-page {
    right: 18px;
    left: 18px;
    padding: 0 0 18px;
  }

  .settings-shell,
  .settings-shell.parchment-logbook {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto minmax(0, 1fr) auto;
    grid-template-areas:
      "command"
      "rail"
      "pane"
      "context";
    gap: 8px;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 16px;
  }

  .settings-command-bar {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
    gap: 10px;
    margin: 0 12px 8px;
    padding: 14px;
  }

  .settings-command-actions {
    grid-column: auto;
  }

  .settings-control-rail {
    grid-template-rows: auto auto;
    gap: 8px;
    padding: 0 0 8px;
    border-right: none;
    border-bottom: 1px solid var(--settings-border);
  }

  .settings-filter-list {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    overflow-y: hidden;
    padding-right: 0;
    scrollbar-width: none;
  }

  .settings-filter-list::-webkit-scrollbar {
    display: none;
  }

  .settings-filter-chip {
    flex: 0 0 176px;
  }

  .settings-main-pane {
    max-height: none;
    overflow: visible;
  }

  .settings-scroll {
    max-height: none;
    overflow: visible;
    padding: 12px;
  }

  .settings-editor-options {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-context-rail {
    padding: 8px 0 0;
    border-left: none;
    border-top: 1px solid var(--settings-border);
  }

  .settings-context-scroll {
    max-height: 420px;
    overflow-y: auto;
  }
}

@media (max-width: 640px) {
  .settings-page {
    right: 10px;
    left: 10px;
    padding-bottom: 10px;
  }

  .settings-shell,
  .settings-shell.parchment-logbook {
    gap: 10px;
    padding: 10px;
  }

  .settings-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "title action"
      "metrics metrics";
    gap: 6px;
    margin: 0 10px 8px;
    padding: 9px;
  }

  .settings-command-title {
    grid-area: title;
  }

  .settings-command-actions {
    grid-area: action;
    align-self: center;
    justify-content: end;
  }

  .settings-command-metrics {
    grid-area: metrics;
    gap: 12px;
    justify-content: flex-start;
  }

  .settings-command-title h2 {
    font-size: 18px;
  }

  .settings-refresh-button {
    width: auto;
    min-width: 64px;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
  }

  .settings-filter-chip {
    flex-basis: 152px;
  }

  .settings-scroll {
    padding: 10px;
  }

  .settings-form-grid,
  .settings-scope-grid,
  .settings-context-kpis {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (min-width: 961px) {
  .settings-shell,
  .settings-shell.parchment-logbook {
    grid-template-columns: 252px minmax(0, 1fr) 300px;
    column-gap: 8px;
    padding: 12px;
  }

  .settings-control-rail {
    gap: 10px;
    padding-right: 14px;
    border-right-color: rgba(93, 48, 17, 0.22);
  }

  .settings-rail-header {
    min-height: 57px;
    padding: 10px 0 12px;
    border-bottom-color: rgba(93, 48, 17, 0.2);
  }

  .settings-rail-header span {
    font-size: 22px;
    font-weight: 950;
  }

  .settings-rail-header strong {
    height: auto;
    padding: 0;
    border-radius: 0;
    background: transparent;
    color: var(--settings-muted);
    font-size: 13px;
  }

  .settings-filter-chip {
    height: 36px;
    padding: 0 11px;
  }

  .settings-command-bar {
    grid-template-columns: 188px minmax(0, 1fr) 124px;
    gap: 14px;
    min-height: 57px;
    padding: 10px 0 12px;
    border: 0;
    border-bottom: 1px solid rgba(93, 48, 17, 0.2);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .settings-command-title h2 {
    color: var(--settings-text);
    font-size: 22px;
    font-weight: 950;
  }

  .settings-command-metrics {
    gap: 6px 12px;
    justify-content: flex-end;
    width: 100%;
  }

  .settings-command-metrics span {
    flex: 0 0 auto;
    max-width: none;
  }

  .settings-command-metrics small {
    color: var(--settings-muted);
    font-size: 11px;
  }

  .settings-command-metrics b {
    color: var(--settings-text);
    font-size: 13px;
  }

  .settings-refresh-button {
    flex: 0 0 58px;
    min-width: 58px;
    height: 34px;
    padding: 0 8px;
    font-size: 12px;
  }

  .settings-main-pane {
    align-self: stretch;
    height: 100%;
    max-height: none;
    border: 0;
    border-radius: 0;
    background: transparent;
  }

  .settings-scroll {
    height: 100%;
    max-height: none;
    padding: 14px 0 12px;
  }
}
</style>

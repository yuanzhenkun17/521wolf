<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { createSettingsService } from '../services/settingsApi'
import type { ModelProfile, ModelProfilePayload, SettingsAdminState, SettingsModelProfilesResponse, SettingsVariable } from '../types/settings'

type SettingsGroupKey = 'models' | 'variables' | 'benchmark' | 'evolution' | 'langfuse' | 'tts' | 'system'

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
const admin = ref<SettingsAdminState>({ enabled: false, token_configured: false, write_available: false })
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
const savingVariableKey = ref('')
const error = ref('')
const notice = ref('')
const refreshedAt = ref('')
const form = reactive({ ...DEFAULT_FORM })
const variableDrafts = reactive<Record<string, boolean | number | string>>({})

const selectedProfile = computed(() =>
  profiles.value.find((profile) => profile.profile_id === selectedProfileId.value) || null
)
const canWrite = computed(() =>
  Boolean(admin.value.enabled && admin.value.token_configured && adminToken.value.trim())
)
const enabledProfiles = computed(() => profiles.value.filter((profile) => profile.enabled))
const healthStatus = computed(() => String(health.value.status || 'unknown'))
const healthReady = computed(() => health.value.ready !== false)
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
const gateRows = computed(() => {
  const gates = health.value.gates && typeof health.value.gates === 'object' ? health.value.gates : {}
  return Object.entries(gates).map(([key, value]) => {
    const row = value && typeof value === 'object' ? value as Record<string, any> : {}
    return {
      key,
      label: gateLabel(key),
      ready: Boolean(row.ready),
      status: String(row.status || 'unknown'),
      blockers: Array.isArray(row.blockers) ? row.blockers : [],
      warnings: Array.isArray(row.warnings) ? row.warnings : []
    }
  })
})
const settingsMetaRows = computed(() => [
  { key: 'profiles', label: '模型', value: profiles.value.length || '0' },
  { key: 'enabled', label: '启用', value: enabledProfiles.value.length || '0' },
  { key: 'ready', label: 'API', value: healthReady.value ? statusLabel(healthStatus.value) : '未就绪' },
  { key: 'selected', label: '选中', value: selectedProfile.value?.name || '新建' }
])
const activeGroupInfo = computed(() => GROUPS.find((item) => item.key === activeGroup.value) || GROUPS[0])
const scopedProfiles = computed(() => {
  const scope = activeGroup.value
  if (!['benchmark', 'evolution'].includes(scope)) return []
  return profiles.value.filter((profile) => Boolean(profile.default_scopes?.[scope]))
})

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

function applySettings(payload: SettingsModelProfilesResponse) {
  profiles.value = Array.isArray(payload.profiles) ? payload.profiles : []
  health.value = payload.health || {}
  admin.value = payload.admin || { enabled: false, token_configured: false, write_available: false }
  scopes.value = Array.isArray(payload.scopes) ? payload.scopes : []
  providers.value = Array.isArray(payload.providers) && payload.providers.length ? payload.providers : providers.value
  variables.value = Array.isArray(payload.variables) ? payload.variables : []
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
  const source = err as { message?: string }
  return String(source?.message || fallback)
}

function adminWriteHint(): string {
  if (!admin.value.enabled) return '设置写入未开启：需要 SETTINGS_ADMIN_ENABLED=true。'
  if (!admin.value.token_configured) return '管理员令牌未配置：需要 SETTINGS_ADMIN_TOKEN。'
  return '输入管理员令牌后才能修改本地模型配置。'
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

        <div class="settings-rail-summary" aria-label="设置概览">
          <span v-for="item in settingsMetaRows" :key="item.key">
            <small>{{ item.label }}</small>
            <b :title="String(item.value ?? '')">{{ item.value }}</b>
          </span>
        </div>

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
            <button type="button" class="settings-refresh-button" :disabled="loading" @click="refreshSettings">
              <span aria-hidden="true">&#8635;</span> {{ loading ? '刷新中' : '刷新' }}
            </button>
          </div>
        </header>

        <div class="settings-detail-topbar">
          <nav class="settings-nav detail-workspace-tabs" aria-label="设置视图">
            <button
              v-for="group in GROUPS"
              :key="group.key"
              type="button"
              :class="['settings-nav-tab', { active: activeGroup === group.key }]"
              @click="selectGroup(group.key)"
            >
              <span>{{ group.label }}</span>
            </button>
          </nav>
        </div>

        <section class="settings-main-pane">
          <div class="settings-scroll">
            <div v-if="error" class="settings-warning">{{ error }}</div>
            <div v-if="notice" class="settings-notice">{{ notice }}</div>

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
                    <small>{{ scopeText(profile) }}</small>
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
                <b>{{ canWrite ? '可写' : '只读' }}</b>
              </header>

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

              <footer class="settings-form-actions">
                <button type="button" class="settings-card-action primary" :disabled="saving || !canWrite" @click="saveProfile">
                  {{ saving ? '保存中' : selectedProfile ? '保存' : '创建' }}
                </button>
                <button type="button" class="settings-card-action" :disabled="testing || !selectedProfile || !canWrite" @click="testSelectedProfile">
                  {{ testing ? '测试中' : '测试连接' }}
                </button>
                <button type="button" class="settings-card-action" :disabled="!selectedProfile || !canWrite" @click="disableSelectedProfile">禁用</button>
                <button type="button" class="settings-card-action danger" :disabled="!selectedProfile || !canWrite" @click="deleteSelectedProfile">删除</button>
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
                    <small>{{ variable.description || variable.key }}</small>
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
                  <h2>{{ scopedProfiles.length }} 个默认模型</h2>
                </div>
                <b>{{ Boolean(envLocks[activeGroup]) ? '环境锁定' : '可配置' }}</b>
              </header>
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
                <div v-if="!scopedProfiles.length" class="settings-empty">还没有为 {{ activeGroupInfo.label }} 指定默认模型。</div>
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
                <div v-for="item in healthChecks.filter((check) => activeGroup === 'tts' ? check.key.includes('tts') : check.key.includes('langfuse'))" :key="item.key" class="settings-health-row">
                  <span>
                    <b>{{ item.label }}</b>
                    <small>{{ item.message || '未提供详情' }}</small>
                  </span>
                  <em :data-status="item.status">{{ statusLabel(item.status) }}</em>
                </div>
                <div class="settings-empty">当前 health payload 暂未提供更多 {{ activeGroupInfo.label }} 检查。</div>
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
              <div class="settings-health-grid">
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

          <section class="settings-context-section">
            <h3>管理员写入</h3>
            <p class="settings-context-empty">{{ adminWriteHint() }}</p>
            <label class="settings-admin-token">
              <small>Admin Token</small>
              <input v-model="adminToken" type="password" autocomplete="off" placeholder="只保存在当前页面内存" />
            </label>
          </section>

          <section class="settings-context-section">
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
            </template>
            <p v-else class="settings-context-empty">正在编辑新 Profile。</p>
          </section>

          <section class="settings-context-section">
            <h3>运行门禁</h3>
            <div class="settings-gate-list">
              <span v-for="gate in gateRows" :key="gate.key">
                <b>{{ gate.label }}</b>
                <small>{{ gate.ready ? '可启动' : gate.blockers.join(' / ') || '不可启动' }}</small>
              </span>
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
  grid-template-rows: auto auto minmax(0, 1fr);
  grid-template-areas:
    "rail command context"
    "rail topbar context"
    "rail pane context";
  height: 100%;
  min-height: 0;
  overflow: hidden;
  gap: 0 18px;
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
  overflow: hidden;
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: var(--settings-surface);
}

.settings-rail-header,
.settings-context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 16px 14px;
  border-bottom: 1px solid var(--settings-border);
  background: rgba(255, 252, 245, 0.34);
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
  color: var(--settings-accent-strong);
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-rail-summary,
.settings-context-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 14px;
}

.settings-rail-summary span,
.settings-context-kpis span,
.settings-gate-list span {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 9px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.32);
}

.settings-rail-summary b,
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
  padding: 2px 14px 14px;
}

.settings-filter-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 9px;
}

.settings-refresh-note {
  margin: 0;
  color: rgba(80, 50, 24, 0.58);
  font-size: 11px;
  font-weight: 700;
}

.settings-filter-list {
  display: grid;
  gap: 7px;
}

.settings-filter-chip,
.settings-nav-tab,
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 52px;
  padding: 9px 10px;
  background: rgba(255, 252, 245, 0.34);
  text-align: left;
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

.settings-filter-chip em {
  display: grid;
  min-width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--settings-accent-strong);
  font-style: normal;
  font-size: 12px;
  font-weight: 900;
}

.settings-filter-chip:hover,
.settings-filter-chip.selected,
.settings-nav-tab:hover,
.settings-nav-tab.active {
  border-color: rgba(90, 51, 25, 0.34);
  background: var(--settings-active-bg);
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
  justify-content: flex-end;
  gap: 12px;
  min-width: 0;
  overflow: hidden;
}

.settings-command-metrics span {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  flex: 0 0 92px;
  min-width: 0;
  max-width: 148px;
}

.settings-command-metrics small {
  flex: 0 0 auto;
  color: rgba(232, 210, 170, 0.68);
  font-size: 12px;
  font-weight: 800;
}

.settings-command-metrics b {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: #fff4d9;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 92px;
  height: 42px;
  padding: 0 15px;
  background: #e8c484;
  color: #2d1e10;
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}

.settings-detail-topbar {
  grid-area: topbar;
  min-width: 0;
  padding: 10px 16px;
  border-right: 1px solid var(--settings-border);
  border-bottom: 1px solid var(--settings-border);
  border-left: 1px solid var(--settings-border);
  background: rgba(255, 252, 245, 0.28);
}

.settings-nav {
  display: flex;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}

.settings-nav::-webkit-scrollbar {
  display: none;
}

.settings-nav-tab {
  flex: 0 0 auto;
  height: 34px;
  padding: 0 13px;
  background: rgba(255, 252, 245, 0.36);
  font-size: 13px;
  font-weight: 800;
}

.settings-main-pane {
  grid-area: pane;
  overflow: hidden;
  border-right: 1px solid var(--settings-border);
  border-bottom: 1px solid var(--settings-border);
  border-left: 1px solid var(--settings-border);
  border-radius: 0 0 8px 8px;
  background: rgba(255, 252, 245, 0.2);
}

.settings-scroll,
.settings-context-scroll {
  height: 100%;
  overflow: auto;
  padding: 16px;
}

.settings-card {
  margin-bottom: 14px;
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: var(--settings-panel);
  box-shadow: 0 8px 18px rgba(97, 58, 21, 0.08);
}

.settings-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 16px;
  border-bottom: 1px solid var(--settings-border);
}

.settings-card h2 {
  margin: 3px 0 0;
  color: var(--settings-accent-strong);
  font-size: 18px;
  line-height: 1.1;
}

.settings-card > header > b,
.settings-context-head > b {
  flex: 0 0 auto;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.09);
  color: var(--settings-accent-strong);
  font-size: 12px;
}

.settings-card-action {
  min-height: 34px;
  padding: 0 12px;
  background: rgba(255, 252, 245, 0.58);
  font-size: 12px;
  font-weight: 800;
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
  gap: 0;
}

.settings-profile-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) minmax(132px, 0.42fr) minmax(132px, 0.38fr);
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 64px;
  padding: 11px 15px;
  border: 0;
  border-bottom: 1px solid rgba(139, 94, 52, 0.1);
  background: transparent;
  color: var(--settings-text);
  text-align: left;
  cursor: pointer;
}

.settings-profile-row:hover,
.settings-profile-row.selected {
  background: var(--settings-hover);
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

.settings-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px;
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
  height: 38px;
  padding: 0 10px;
  border: 1px solid var(--settings-input-border);
  border-radius: 6px;
  background: var(--settings-input-bg);
  color: var(--settings-text);
  font-size: 13px;
  outline: none;
}

.settings-toggle-grid,
.settings-scope-grid {
  display: grid;
  gap: 10px;
  padding: 0 16px 16px;
}

.settings-scope-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.settings-toggle-grid label,
.settings-scope-grid label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  color: var(--settings-text);
  font-size: 13px;
  font-weight: 700;
}

.settings-form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 16px 16px;
}

.settings-variable-row,
.settings-health-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(112px, 0.24fr) minmax(116px, 0.22fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 56px;
  padding: 11px 15px;
  border-bottom: 1px solid rgba(139, 94, 52, 0.1);
}

.settings-variable-row em,
.settings-health-row em {
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
  border-radius: 999px;
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
  border-radius: 6px;
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
  margin: 0;
  padding: 14px 15px;
  color: var(--settings-muted);
  font-size: 13px;
  font-weight: 700;
}

.settings-warning {
  margin-bottom: 12px;
  border: 1px solid rgba(153, 48, 38, 0.22);
  border-radius: 7px;
  background: rgba(153, 48, 38, 0.08);
  color: var(--settings-danger);
}

.settings-notice {
  margin-bottom: 12px;
  border: 1px solid rgba(104, 119, 43, 0.2);
  border-radius: 7px;
  background: rgba(104, 119, 43, 0.08);
  color: #4e5f22;
}

.settings-context-rail {
  grid-area: context;
  overflow: hidden;
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: var(--settings-surface);
}

.settings-context-section {
  margin-bottom: 12px;
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.34);
}

.settings-context-section h3 {
  margin: 0;
  padding: 13px 14px 0;
  color: var(--settings-accent-strong);
  font-size: 15px;
}

.settings-admin-token {
  padding: 0 14px 14px;
}

.settings-context-run-id {
  display: grid;
  gap: 6px;
  margin: 12px 14px 0;
  padding: 10px;
  border-radius: 7px;
  background: rgba(45, 34, 24, 0.9);
}

.settings-context-run-id small {
  color: rgba(232, 210, 170, 0.72);
  font-size: 11px;
  font-weight: 800;
}

.settings-context-run-id code {
  overflow-wrap: anywhere;
  color: #fff4d9;
  font-size: 12px;
}

.settings-gate-list {
  display: grid;
  gap: 8px;
  padding: 14px;
}

@media (max-width: 1180px) {
  .settings-shell {
    grid-template-columns: 220px minmax(0, 1fr);
    grid-template-areas:
      "rail command"
      "rail topbar"
      "rail pane"
      "context context";
    overflow: auto;
  }

  .settings-context-rail {
    min-height: 320px;
  }
}

@media (max-width: 760px) {
  .settings-page {
    top: 64px;
  }

  .settings-shell {
    display: block;
    padding: 14px;
    overflow: auto;
  }

  .settings-control-rail,
  .settings-context-rail,
  .settings-command-bar,
  .settings-detail-topbar,
  .settings-main-pane {
    margin-bottom: 12px;
    border-radius: 8px;
  }

  .settings-command-bar,
  .settings-profile-row,
  .settings-variable-row,
  .settings-health-row,
  .settings-form-grid,
  .settings-scope-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-command-metrics {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>

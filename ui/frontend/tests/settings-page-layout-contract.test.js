import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('SettingsPage copies the task page workbench shell layout', () => {
  const source = readSource('../src/pages/SettingsPage.vue')

  assert.match(source, /class="settings-shell parchment-logbook"/)
  assert.match(source, /class="settings-command-bar"/)
  assert.match(source, /class="settings-control-rail"/)
  assert.match(source, /class="settings-main-pane"/)
  assert.match(source, /class="settings-context-rail"[\s\S]*data-settings-context-rail/)
  assert.match(source, /:data-group="group\.key"/)
  assert.match(source, /grid-template-areas:[\s\S]*"rail command context"[\s\S]*"rail pane context"/)
  assert.doesNotMatch(source, /class="settings-detail-topbar"/)
  assert.doesNotMatch(source, /class="settings-rail-summary"/)
  assert.match(source, /--settings-bg:\s*#f2dfae/)
  assert.match(source, /repeating-linear-gradient\(90deg,\s*rgba\(118,\s*71,\s*27,\s*0\.024\)/)
})

test('SettingsPage follows local secret safety rules', () => {
  const source = readSource('../src/pages/SettingsPage.vue')
  const service = readSource('../src/services/settingsApi.ts')

  assert.match(source, /autocomplete="off"/)
  assert.doesNotMatch(source, /localStorage\.(setItem|getItem)/)
  assert.match(service, /'X-Settings-Admin-Token'/)
  assert.match(service, /\/settings\/runtime-variables\/\$\{encodeURIComponent\(settingKey\)\}/)
  assert.match(source, /function saveRuntimeVariable\(variable: SettingsVariable\)/)
  assert.match(source, /variableCanEdit\(variable\)/)
  assert.match(source, /savingVariableKey === variable\.key/)
  assert.match(source, /function probeRuntimeModel\(\)/)
  assert.match(source, /settingsService\.probeRuntimeModel\(\{\s*scope: DEFAULT_RUNTIME_PROBE_SCOPE,[\s\S]*model_scope: runtimeProbeModelScope\(\),[\s\S]*model_profile_id: selectedProfileId\.value \|\| undefined[\s\S]*\}\)/)
  assert.match(source, /const DEFAULT_RUNTIME_PROBE_SCOPE = 'settings_model_test'/)
  assert.match(source, /const DEFAULT_MODEL_PROBE_SCOPE = 'prompt_test'/)
  assert.match(source, /function runtimeProbeModelScope\(\): string/)
  assert.match(source, /HEALTH_GATE_BLOCKER_LABELS[\s\S]*llm_connectivity: '模型连接不可用'/)
  assert.match(source, /HEALTH_GATE_ACTION_LABELS[\s\S]*open settings and test the model connection[\s\S]*在设置页测试模型连接/)
  assert.match(source, /function gateActionLabels\(value: unknown\): string\[\]/)
  assert.match(source, /function gateDetailText\(ready: boolean, blockers: string\[\], warnings: string\[\], actions: string\[\]\): string/)
  assert.match(source, /const profileBlockingIssues = computed/)
  assert.match(source, /const profileGuidanceRows = computed/)
  assert.match(source, /const settingsGuidanceRows = computed/)
  assert.match(source, /const canSubmitProfile = computed/)
  assert.match(source, /class="settings-guidance"/)
  assert.match(source, /class="settings-guardrail"/)
  assert.match(source, /class="settings-gate-grid"/)
  assert.match(source, /失败会阻断使用该模型的启动入口/)
  assert.match(source, /环境变量锁定：需改服务端环境变量后重启/)
  assert.doesNotMatch(source, /gate\.blockers\.join/)
  assert.match(source, /healthProbeTesting/)
  assert.match(source, /healthProbeTesting \? '测试中' : '测试'/)
  assert.match(service, /\/health\/probes\/llm/)
  assert.match(service, /probeRuntimeModel\(options: string \| SettingsRuntimeModelProbeOptions = DEFAULT_RUNTIME_PROBE_SCOPE, token = ''\)/)
  assert.match(service, /model_scope: queryText\(options\.model_scope\)/)
  assert.match(service, /model_profile_id: queryText\(options\.model_profile_id\)/)
  assert.match(service, /typeof options === 'string'/)
  assert.doesNotMatch(service, /localStorage\.(setItem|getItem)/)
})

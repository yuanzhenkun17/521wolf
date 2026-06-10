<script setup lang="ts">
import { computed } from 'vue'
import ApiErrorPanel from '../ApiErrorPanel.vue'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../../composables/apiErrorDisplay.ts'

interface EvolutionTab {
  key: string
  label: string
}

interface EvolutionRole {
  key: string
  label: string
  image?: string
  baselineShort?: string
}

interface EvolutionRunRow {
  role?: string
  displayRole?: string
  isActive?: boolean
  status?: string
  warningCount?: number
  errorCount?: number
}

const props = defineProps({
  title: { type: String, required: true },
  tabs: { type: Array, default: () => [] },
  activeTab: { type: String, required: true },
  roles: { type: Array, default: () => [] },
  runRows: { type: Array, default: () => [] },
  selectedRole: { type: String, default: '' },
  selectedRun: { type: Object, default: null },
  selectedRunSummary: { type: Object, default: null },
  selectedProposalReview: { type: Object, default: null },
  selectedGames: { type: Object, default: null },
  selectedCanPromote: { type: Boolean, default: false },
  selectedPromoteDisabledReason: { type: String, default: '' },
  selectedCanReject: { type: Boolean, default: false },
  selectedRejectDisabledReason: { type: String, default: '' },
  selectedCanTerminate: { type: Boolean, default: false },
  selectedTerminateDisabledReason: { type: String, default: '' },
  selectedRollbackDisabledReason: { type: String, default: '' },
  error: { type: [String, Object, Error], default: '' },
  notice: { type: Object, default: null }
})

const emit = defineEmits(['update:activeTab', 'refresh', 'select-role'])

const tabs = computed(() => props.tabs as EvolutionTab[])
const roles = computed(() => props.roles as EvolutionRole[])
const runRows = computed(() => props.runRows as EvolutionRunRow[])

const selectedRoleRow = computed(() =>
  roles.value.find((role) => role.key === props.selectedRole) || roles.value[0] || null
)

const activeTabLabel = computed(() =>
  tabs.value.find((tab) => tab.key === props.activeTab)?.label || '—'
)

const runSummary = computed(() => props.selectedRunSummary || {})
const selectedRun = computed(() => props.selectedRun || {})
const selectedReview = computed(() => props.selectedProposalReview || {})
const selectedGate = computed(() => selectedReview.value.gate || {})
const selectedTrustBundle = computed(() => selectedReview.value.trustBundle || selectedReview.value.trust_bundle || {})
const refreshRetrying = computed(() => Boolean(runSummary.value.loading))
const refreshRetryDisabled = computed(() => Boolean(runSummary.value.loading || runSummary.value.actionLoading))
const pageNotice = computed(() => {
  if (props.notice?.message) return props.notice
  if (props.error) return { type: 'error', message: errorMessage(props.error), error: props.error }
  return null
})
const inlineNotice = computed(() => inlineNoticeForDisplay(pageNotice.value))
const errorNotice = computed(() => noticeErrorForPanel(pageNotice.value))
const railCounts = computed(() => {
  const rows = runRows.value
  return {
    active: rows.filter((run) => Boolean(run?.isActive)).length,
    reviewing: rows.filter((run) => run?.status === 'reviewing').length,
    warning: rows.filter((run) => Number(run?.warningCount || 0) > 0 || Number(run?.errorCount || 0) > 0 || run?.status === 'failed').length
  }
})
const contextKpis = computed(() => [
  { key: 'role', label: '角色', value: runSummary.value.displayRole || selectedRoleRow.value?.label || '—' },
  { key: 'type', label: '类型', value: runSummary.value.entityLabel || '—' },
  { key: 'training', label: '训练', value: runSummary.value.trainingProgressLabel || '等待' },
  { key: 'battle', label: '对战', value: runSummary.value.battleProgressLabel || '等待' },
  { key: 'baseline', label: '基线', value: runSummary.value.parentShort || selectedRoleRow.value?.baselineShort || '—', code: true },
  { key: 'candidate', label: '候选', value: runSummary.value.candidateShort || '—', code: true }
])
const contextGateLabel = computed(() =>
  selectedGate.value.decisionLabel ||
  selectedGate.value.releaseLabel ||
  selectedRun.value.gateDecisionLabel ||
  selectedRun.value.gate_decision ||
  '—'
)
const contextTrustLabel = computed(() => {
  const score = selectedReview.value.summary?.trustCompletenessScore ??
    selectedTrustBundle.value.completeness?.score ??
    selectedGate.value.trustCompletenessScore
  if (score != null && score !== '') return scoreLabel(score)
  if (selectedTrustBundle.value.trust_bundle_id || selectedTrustBundle.value.trustBundleId) return '已关联'
  return '—'
})
const contextEvidenceLabel = computed(() => {
  const games = props.selectedGames || {}
  const total = sampleCount(games.training) + sampleCount(games.baseline) + sampleCount(games.candidate)
  const proposals = selectedReview.value.summary?.accepted || selectedReview.value.summary?.accepted_count || 0
  return `${total} 样本 · ${proposals} 已接受`
})
const contextDiagnostics = computed(() => {
  const diagnostics = Array.isArray(selectedRun.value.diagnostics) ? selectedRun.value.diagnostics : []
  return diagnostics.slice(0, 4)
})
function progressPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function displayText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function sampleCount(rows) {
  return Array.isArray(rows) ? rows.length : 0
}

function scoreLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  const pct = Math.abs(number) <= 1 ? number * 100 : number
  return `${Math.round(pct)}%`
}

function signedDelta(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number > 0 ? '+' : ''}${Math.round(number)}%`
}

function roleRunCounts(role) {
  const rows = runRows.value.filter((run) => run?.role === role || run?.displayRole === role)
  const active = rows.filter((run) => Boolean(run?.isActive)).length
  const reviewing = rows.filter((run) => run?.status === 'reviewing').length
  return { active, reviewing }
}

function errorMessage(value) {
  if (value && typeof value === 'object' && 'message' in value) {
    return String(value.message || value)
  }
  return value
}

function diagnosticKey(diagnostic, index) {
  return diagnostic?.id || diagnostic?.kind || diagnostic?.type || diagnostic?.message || index
}

function diagnosticText(diagnostic) {
  return displayText(diagnostic?.message || diagnostic?.summary || diagnostic?.reason || diagnostic?.type, '暂无诊断内容')
}

function retryRefresh() {
  if (refreshRetryDisabled.value) return
  emit('refresh')
}
</script>

<template>
  <section class="evo-shell parchment-logbook">
    <aside class="evo-control-rail" aria-label="进化角色">
      <header class="evo-rail-header">
        <span>角色上下文</span>
      </header>

      <div class="evo-rail-summary">
        <span>
          <small>知识库</small>
          <b>{{ selectedRoleRow?.label || '—' }}</b>
        </span>
        <span>
          <small>基线</small>
          <b>{{ selectedRoleRow?.baselineShort || '—' }}</b>
        </span>
        <span>
          <small>运行中</small>
          <b>{{ railCounts.active }}</b>
        </span>
        <span>
          <small>待审核</small>
          <b>{{ railCounts.reviewing }}</b>
        </span>
      </div>

      <div class="evo-role-panel" aria-label="知识库角色上下文">
        <span class="evo-role-bar-label">知识库角色</span>
        <div class="evo-role-list">
          <button
            v-for="role in roles"
            :key="role.key"
            type="button"
            :class="['evo-role-chip', { selected: selectedRole === role.key }]"
            @click="emit('select-role', role.key)"
          >
            <span class="evo-role-identity">
              <img :src="role.image" alt="" aria-hidden="true" />
              <b>{{ role.label }}</b>
            </span>
            <span class="evo-role-statuses" aria-label="角色运行状态">
              <small>运行 {{ roleRunCounts(role.key).active }}</small>
              <small>待审 {{ roleRunCounts(role.key).reviewing }}</small>
            </span>
          </button>
        </div>
      </div>
    </aside>

    <main class="evo-detail-panel">
      <header class="evo-command-bar">
        <div class="evo-command-title">
          <h2>{{ title }}工作台</h2>
        </div>
        <div class="evo-command-metrics" aria-label="自进化工具状态条">
          <span>
            <small>当前角色：</small>
            <b>{{ selectedRoleRow?.label || '—' }}</b>
          </span>
          <span>
            <small>当前运行：</small>
            <b>{{ displayText(runSummary.id) }}</b>
          </span>
          <span>
            <small>阶段：</small>
            <b>{{ runSummary.currentStageLabel || '—' }}</b>
          </span>
          <span>
            <small>门禁：</small>
            <b>{{ contextGateLabel }}</b>
          </span>
          <span>
            <small>信任包：</small>
            <b>{{ contextTrustLabel }}</b>
          </span>
          <span>
            <small>进度：</small>
            <b>{{ progressPercent(runSummary.overallProgressPercent) }}%</b>
          </span>
        </div>
        <div class="evo-command-actions">
          <button type="button" class="evo-refresh-button" @click="emit('refresh')">
            <span aria-hidden="true">&#8635;</span> 刷新
          </button>
        </div>
      </header>

      <div class="evo-detail-topbar">
        <nav class="evo-nav detail-workspace-tabs" aria-label="自进化视图">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            :class="['evo-nav-tab', { active: activeTab === tab.key }]"
            @click="emit('update:activeTab', tab.key)"
          >
            <span>{{ tab.label }}</span>
          </button>
        </nav>
      </div>

      <section class="evo-main-pane">
        <div class="evo-scroll">
          <ApiErrorPanel
            v-if="errorNotice"
            class="evo-error-panel"
            :error="errorNotice"
            title="自进化操作失败"
            retry-label="重试刷新"
            retry-busy-label="刷新中"
            :retrying="refreshRetrying"
            :retry-disabled="refreshRetryDisabled"
            compact
            @retry="retryRefresh"
          />
          <div v-else-if="inlineNotice" :class="['evo-alert', inlineNotice.type]">{{ inlineNotice.message }}</div>
          <slot />
        </div>
      </section>
    </main>

    <aside class="evo-context-rail" aria-label="当前上下文" data-evolution-context-rail>
      <div class="evo-context-scroll">
        <header class="evo-context-head">
          <span>
            <small>当前上下文</small>
            <strong>{{ activeTabLabel }}</strong>
          </span>
          <b>{{ runSummary.statusLabel || '—' }}</b>
        </header>

        <section class="evo-context-section">
          <h3>运行摘要</h3>
          <div class="evo-context-run-id">
            <small>run_id</small>
            <code>{{ displayText(runSummary.id) }}</code>
          </div>
          <div class="evo-context-progress">
            <span>
              <b>{{ progressPercent(runSummary.overallProgressPercent) }}%</b>
              <small>{{ runSummary.overallProgressLabel || '等待' }}</small>
            </span>
            <i aria-hidden="true">
              <em :style="{ width: `${progressPercent(runSummary.overallProgressPercent)}%` }"></em>
            </i>
          </div>
          <div class="evo-context-kpis">
            <span v-for="item in contextKpis" :key="item.key">
              <small>{{ item.label }}</small>
              <code v-if="item.code">{{ item.value }}</code>
              <b v-else>{{ item.value }}</b>
            </span>
          </div>
        </section>

        <section class="evo-context-section">
          <h3>发布审计</h3>
          <div class="evo-context-kpis two">
            <span>
              <small>推荐结论</small>
              <b>{{ runSummary.recommendationLabel || '—' }}</b>
            </span>
            <span>
              <small>胜率差</small>
              <b>{{ signedDelta(runSummary.winRateDeltaPct) }}</b>
            </span>
            <span>
              <small>门禁</small>
              <b>{{ contextGateLabel }}</b>
            </span>
            <span>
              <small>信任包</small>
              <b>{{ contextTrustLabel }}</b>
            </span>
            <span class="wide">
              <small>证据强度</small>
              <b>{{ contextEvidenceLabel }}</b>
            </span>
          </div>
        </section>

        <section class="evo-context-section">
          <h3>诊断</h3>
          <div class="evo-context-kpis three">
            <span>
              <small>诊断</small>
              <b>{{ runSummary.diagnosticCount || 0 }}</b>
            </span>
            <span>
              <small>警告</small>
              <b>{{ runSummary.warningCount || 0 }}</b>
            </span>
            <span>
              <small>错误</small>
              <b>{{ runSummary.errorCount || 0 }}</b>
            </span>
          </div>
          <ol v-if="contextDiagnostics.length" class="evo-context-diagnostics">
            <li
              v-for="(diagnostic, index) in contextDiagnostics"
              :key="diagnosticKey(diagnostic, index)"
            >
              {{ diagnosticText(diagnostic) }}
            </li>
          </ol>
          <p v-else class="evo-context-empty">暂无诊断。</p>
        </section>
      </div>
    </aside>
  </section>
</template>

<script setup lang="ts">
import type { PropType, Ref } from 'vue'
import EvolutionDiffViewer from './EvolutionDiffViewer.vue'

type BattleSideName = 'baseline' | 'candidate'
type MaybeNumber = number | string | null | undefined

interface EvolutionRunConfig {
  max_days?: MaybeNumber
  auto_promote?: boolean | number | string | null
}

interface BattleSideData {
  target_win_rate?: unknown
  avg_role_weighted_score?: unknown
  completed?: unknown
  games?: unknown
  [key: string]: unknown
}

interface BattleResult {
  baseline?: BattleSideData | null
  candidate?: BattleSideData | null
  baseline_win_rate?: unknown
  candidate_win_rate?: unknown
  win_rate_delta?: unknown
  skipped?: boolean | null
  significant?: boolean | null
  significance?: {
    significant?: boolean | null
    reasons?: unknown
  } | null
  reason?: unknown
  error?: unknown
  [key: string]: unknown
}

interface DiagnosticRow {
  id?: string | number
  kind?: string
  stage?: string
  message?: unknown
  level?: string
  type?: string
  summary?: unknown
  reason?: unknown
  error?: unknown
}

interface ProposalRow {
  proposal_id?: string | number
  id?: string | number
  target_file?: string
  operation?: string
  action?: string
  rationale?: unknown
  summary?: unknown
  description?: unknown
  recommendation?: unknown
  reason?: unknown
}

interface ChildRunRow {
  id?: string
  run_id?: string
  status?: string
  statusLabel?: string
  displayRole?: string
  progressPercent?: MaybeNumber
}

interface EvolutionRun {
  id?: string
  run_id?: string
  entityLabel?: string
  status?: string
  statusLabel?: string
  stage?: string
  current_stage?: string
  currentStage?: string
  currentStageLabel?: string
  progressPercent?: MaybeNumber
  progressLabel?: string
  overallProgressPercent?: MaybeNumber
  overallProgressLabel?: string
  stageProgressPercent?: MaybeNumber
  stageProgressLabel?: string
  trainingProgressPercent?: MaybeNumber
  trainingProgressLabel?: string
  battleProgressPercent?: MaybeNumber
  battleProgressLabel?: string
  recommendation?: string
  recommendationLabel?: string
  battle_result?: BattleResult | null
  combined_battle_result?: BattleResult | null
  completedRoleCount?: MaybeNumber
  roleCount?: MaybeNumber
  childRunCount?: MaybeNumber
  parentShort?: string
  candidateShort?: string
  publishedReleaseStageLabel?: string
  trainingGameCompleted?: MaybeNumber
  trainingGameRequested?: MaybeNumber
  battleGameCompleted?: MaybeNumber
  battleGameRequested?: MaybeNumber
  config?: EvolutionRunConfig | null
  startedLabel?: unknown
  heartbeatLabel?: unknown
  finishedLabel?: unknown
  proposalCount?: MaybeNumber
  diffCount?: MaybeNumber
  diagnosticCount?: MaybeNumber
  warningCount?: MaybeNumber
  errorCount?: MaybeNumber
  diagnostics?: DiagnosticRow[] | null
  proposals?: ProposalRow[] | null
  childRuns?: ChildRunRow[] | null
}

interface SampleGames {
  training?: unknown[] | null
  baseline?: unknown[] | null
  candidate?: unknown[] | null
  [bucket: string]: unknown[] | null | undefined
}

interface SampleState {
  error?: string
}

interface LegacyDiffItem {
  filename?: string
  file?: string
  action?: string
  action_type?: string
  title?: string
  label?: string
  display_name?: string
}

interface EvolutionDiffData {
  skill_changes?: unknown[]
  patterns_added?: unknown[]
  patterns_removed?: unknown[]
  patterns_updated?: unknown[]
  metrics_delta?: Record<string, number | string | null> | null
}

interface EvolutionConsoleModel {
  loading: Ref<boolean>
  actionLoading: Ref<string>
  form: Ref<{
    training_games: MaybeNumber
    battle_games: MaybeNumber
    max_days: MaybeNumber
  }>
  selectedRole: Ref<string>
  selectedRoleLabel: Ref<string>
  selectedRunId: Ref<string>
  selectedRun: Ref<EvolutionRun>
  hasSelection: Ref<boolean>
  selectedGames: Ref<SampleGames>
  selectedSampleState: Ref<SampleState>
  selectedDiffData: Ref<EvolutionDiffData | null>
  selectedDiff: Ref<LegacyDiffItem[]>
  runtimeHealthGateBlocked?: Ref<boolean>
  runtimeHealthGateReason?: Ref<string>
  runtimeHealthGate?: Ref<{ actions?: unknown[] }>
  statusText?: (value: unknown) => string
  startSingle: () => void | Promise<void>
  runAction: (id: string, action: 'promote' | 'reject' | 'terminate') => void | Promise<void>
  selectRun: (id: string) => void | Promise<void>
}

interface ProgressRow {
  key: string
  label: string
  percent?: MaybeNumber
  text?: string
}

defineProps({
  evo: { type: Object as PropType<EvolutionConsoleModel>, required: true },
  selectedIsBatch: Boolean,
  selectedCanReview: Boolean,
  selectedCanPromote: Boolean,
  selectedPromoteDisabledReason: { type: String, default: '' },
  selectedCanTerminate: Boolean
})

function actionLoadingText(value: unknown, loading = false): string {
  const text = String(value || '')
  if (text.startsWith('start-single')) return '正在启动当前角色'
  if (text.startsWith('promote')) return '晋升中'
  if (text.startsWith('reject')) return '拒绝中'
  if (text.startsWith('terminate')) return '终止中'
  if (text.startsWith('rollback')) return '回滚中'
  return loading ? '读取中' : ''
}

function stageLabel(evo: EvolutionConsoleModel): string {
  const run = evo.selectedRun.value || {}
  if (run.currentStageLabel) return run.currentStageLabel
  const value = run.current_stage || run.currentStage || run.stage || run.status
  return evo.statusText?.(value) || (value ? String(value) : '未知')
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function finiteNumber(value: unknown): number | null {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function clampPercent(value: unknown): number {
  const number = finiteNumber(value)
  if (number == null) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function progressLabel(run: EvolutionRun | null | undefined): string {
  if (!run) return '—'
  if (run.progressLabel) return run.progressLabel
  const percent = finiteNumber(run.progressPercent)
  return percent == null ? '—' : `${Math.round(percent)}%`
}

function displayText(value: unknown, fallback = '—'): string {
  const text = String(value ?? '').trim()
  return text || fallback
}

function verdictText(value: unknown): string {
  const verdictLabels: Record<string, string> = {
    promote: '建议晋升',
    reject: '建议拒绝',
    hold: '继续观察',
    pending: '待评审',
    baseline: '基线'
  }
  return verdictLabels[String(value ?? '')] || displayText(value)
}

function recommendationLabel(run: EvolutionRun | null | undefined): string {
  if (!run) return '—'
  return run.recommendationLabel || verdictText(run.recommendation || run.battle_result?.recommendation)
}

function timeLabel(value: unknown): string {
  return displayText(value)
}

function sampleCount(games: SampleGames | null | undefined, bucket: string): number {
  return asArray(games?.[bucket]).length
}

function sampleTotal(games: SampleGames | null | undefined): number {
  return sampleCount(games, 'training') + sampleCount(games, 'baseline') + sampleCount(games, 'candidate')
}

function diagnosticRows(run: EvolutionRun | null | undefined): DiagnosticRow[] {
  return asArray<DiagnosticRow>(run?.diagnostics).slice(0, 5)
}

function diagnosticKey(diagnostic: DiagnosticRow, index: number): string | number {
  const key = diagnostic?.id || diagnostic?.kind || diagnostic?.stage || diagnostic?.message
  if (typeof key === 'string' || typeof key === 'number') return key
  return key == null ? index : String(key)
}

function diagnosticLabel(diagnostic: DiagnosticRow): string {
  return displayText(diagnostic?.level || diagnostic?.kind || diagnostic?.type || diagnostic?.stage, '诊断')
}

function diagnosticText(diagnostic: DiagnosticRow): string {
  return displayText(diagnostic?.message || diagnostic?.summary || diagnostic?.reason || diagnostic?.error)
}

function proposalRows(run: EvolutionRun | null | undefined): ProposalRow[] {
  return asArray<ProposalRow>(run?.proposals).slice(0, 5)
}

function proposalKey(proposal: ProposalRow, index: number): string | number {
  return proposal?.proposal_id || proposal?.id || proposal?.target_file || index
}

function proposalLabel(proposal: ProposalRow, index: number): string {
  return displayText(proposal?.proposal_id || proposal?.id || proposal?.target_file, `提案 ${index + 1}`)
}

function proposalMeta(proposal: ProposalRow): string {
  return displayText([proposal?.target_file, proposal?.operation || proposal?.action].filter(Boolean).join(' · '))
}

function proposalText(proposal: ProposalRow): string {
  return displayText(
    proposal?.rationale ||
      proposal?.summary ||
      proposal?.description ||
      proposal?.recommendation ||
      proposal?.reason
  )
}

function battleResult(run: EvolutionRun | null | undefined): BattleResult | null {
  return run?.combined_battle_result || run?.battle_result || null
}

function battleSide(result: BattleResult | null | undefined, side: BattleSideName): BattleSideData {
  const sideData = result?.[side]
  return sideData && typeof sideData === 'object' ? sideData : {}
}

function battleRate(result: BattleResult | null | undefined, side: BattleSideName): number | null {
  if (!result) return null
  const sideData = battleSide(result, side)
  const topLevel = side === 'candidate' ? result.candidate_win_rate : result.baseline_win_rate
  return finiteNumber(topLevel ?? sideData.target_win_rate ?? sideData.avg_role_weighted_score)
}

function rateLabel(value: unknown): string {
  const number = finiteNumber(value)
  if (number == null) return '—'
  return `${Math.round(number * 100)}%`
}

function signedRateLabel(value: unknown): string {
  const number = finiteNumber(value)
  if (number == null) return '—'
  const percent = Math.round(number * 100)
  return `${percent > 0 ? '+' : ''}${percent}%`
}

function battleDelta(result: BattleResult | null | undefined): number | null {
  if (!result) return null
  const direct = finiteNumber(result.win_rate_delta)
  if (direct != null) return direct
  const candidate = battleRate(result, 'candidate')
  const baseline = battleRate(result, 'baseline')
  if (candidate == null || baseline == null) return null
  return candidate - baseline
}

function battleSideMeta(result: BattleResult | null | undefined, side: BattleSideName): string {
  const data = battleSide(result, side)
  const completed = finiteNumber(data.completed)
  const games = finiteNumber(data.games)
  if (completed == null && games == null) return ''
  return `${completed ?? 0} / ${games ?? completed ?? 0} 局`
}

function battleSignificantLabel(result: BattleResult | null | undefined): string {
  if (!result || result.skipped) return '—'
  const value = result.significant ?? result.significance?.significant
  if (value === true) return '是'
  if (value === false) return '否'
  return '—'
}

function battleSkippedLabel(result: BattleResult | null | undefined): string {
  if (!result) return '—'
  return result.skipped ? '是' : '否'
}

function battleReason(result: BattleResult | null | undefined): string {
  if (!result) return '—'
  const reasons = asArray(result.significance?.reasons).join(', ')
  return displayText(result.reason || result.error || reasons)
}

function progressRows(run: EvolutionRun | null | undefined): ProgressRow[] {
  if (!run) return []
  return [
    {
      key: 'overall',
      label: '整体',
      percent: run.overallProgressPercent,
      text: run.overallProgressLabel
    },
    {
      key: 'stage',
      label: '当前阶段',
      percent: run.stageProgressPercent,
      text: `${run.stageProgressLabel || '等待'} · ${run.currentStageLabel || '未知'}`
    },
    {
      key: 'training',
      label: '训练',
      percent: run.trainingProgressPercent,
      text: run.trainingProgressLabel
    },
    {
      key: 'battle',
      label: '对战',
      percent: run.battleProgressPercent,
      text: run.battleProgressLabel
    }
  ]
}

function childRunRows(run: EvolutionRun | null | undefined): ChildRunRow[] {
  return asArray<ChildRunRow>(run?.childRuns).slice(0, 12)
}

function childRunKey(run: ChildRunRow, index: number): string | number {
  return run?.id || run?.run_id || index
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card evo-console-card">
      <header>
        <h2>进化控制台</h2>
      </header>

      <div class="evo-form-grid evo-console-grid">
        <div class="evo-console-fields" aria-label="进化启动参数">
          <label class="evo-console-field">
            <span>训练局数</span>
            <input v-model.number="evo.form.value.training_games" type="number" min="1" max="200" inputmode="numeric" />
          </label>
          <label class="evo-console-field">
            <span>对战局数</span>
            <input v-model.number="evo.form.value.battle_games" type="number" min="1" max="200" inputmode="numeric" />
          </label>
          <label class="evo-console-field">
            <span>最大天数</span>
            <input v-model.number="evo.form.value.max_days" type="number" min="1" max="100" inputmode="numeric" />
          </label>
        </div>
        <div
          v-if="evo.runtimeHealthGateReason?.value"
          class="evo-runtime-gate"
          :data-blocked="String(Boolean(evo.runtimeHealthGateBlocked?.value))"
          role="status"
        >
          <i aria-hidden="true"></i>
          <div>
            <strong>{{ evo.runtimeHealthGateBlocked?.value ? '启动已阻断' : '启动预检' }}</strong>
            <span>{{ evo.runtimeHealthGateReason.value }}</span>
          </div>
          <small v-if="evo.runtimeHealthGate?.value?.actions?.length">
            {{ evo.runtimeHealthGate.value.actions[0] }}
          </small>
        </div>
        <div class="evo-console-actions">
          <div class="evo-start-panel">
            <button
              type="button"
              class="evo-action evo-start-action"
              :disabled="Boolean(evo.actionLoading.value) || !evo.selectedRole.value || Boolean(evo.runtimeHealthGateBlocked?.value)"
              @click="evo.startSingle()"
            >
              启动
            </button>
            <em v-if="evo.loading.value || evo.actionLoading.value">
              {{ actionLoadingText(evo.actionLoading.value, evo.loading.value) }}
            </em>
          </div>
          <div v-if="evo.hasSelection.value" class="evo-run-actions" aria-label="候选操作">
            <span
              class="evo-action-tooltip"
              :title="selectedPromoteDisabledReason || undefined"
            >
              <button
                type="button"
                class="evo-action evo-action-promote"
                :disabled="!selectedCanPromote || Boolean(evo.actionLoading.value)"
                @click="evo.runAction(evo.selectedRunId.value, 'promote')"
              >
                晋升
              </button>
            </span>
            <span
              class="evo-action-tooltip"
              title="拒绝：运行已完成但不采纳候选结果，候选版本不会晋升。"
            >
              <button
                type="button"
                class="evo-action evo-action-reject"
                :disabled="!selectedCanReview || Boolean(evo.actionLoading.value)"
                @click="evo.runAction(evo.selectedRunId.value, 'reject')"
              >
                拒绝
              </button>
            </span>
            <span
              class="evo-action-tooltip"
              title="终止：停止仍在执行或卡住的运行，不代表评审通过或拒绝。"
            >
              <button
                type="button"
                class="evo-action evo-action-terminate"
                :disabled="!selectedCanTerminate || Boolean(evo.actionLoading.value)"
                @click="evo.runAction(evo.selectedRunId.value, 'terminate')"
              >
                终止
              </button>
            </span>
          </div>
        </div>
      </div>
    </article>

    <article class="evo-card evo-review-card">
      <header>
        <h2>评审面板</h2>
        <div v-if="evo.hasSelection.value" class="evo-review-head-kpis">
          <template v-if="selectedIsBatch">
            <span><small>角色完成</small><b>{{ evo.selectedRun.value.completedRoleCount || 0 }} / {{ evo.selectedRun.value.roleCount || 0 }}</b></span>
            <span><small>子运行</small><b>{{ evo.selectedRun.value.childRunCount || 0 }}</b></span>
            <span><small>训练</small><b>{{ evo.selectedRun.value.trainingProgressLabel }}</b></span>
            <span><small>对战</small><b>{{ evo.selectedRun.value.battleProgressLabel }}</b></span>
          </template>
          <template v-else>
            <span><small>父版本</small><b>{{ evo.selectedRun.value.parentShort }}</b></span>
            <span><small>候选版本</small><b>{{ evo.selectedRun.value.candidateShort }}</b></span>
            <span><small>发布阶段</small><b>{{ evo.selectedRun.value.publishedReleaseStageLabel || '—' }}</b></span>
            <span><small>训练</small><b>{{ evo.selectedRun.value.trainingGameCompleted || 0 }} / {{ evo.selectedRun.value.trainingGameRequested || 0 }}</b></span>
            <span><small>对战</small><b>{{ evo.selectedRun.value.battleGameCompleted || 0 }} / {{ evo.selectedRun.value.battleGameRequested || 0 }}</b></span>
          </template>
          <span class="status"><small>状态</small><b>{{ evo.selectedRun.value?.statusLabel || '—' }}</b></span>
        </div>
        <b v-else>{{ evo.selectedRun.value?.statusLabel || '—' }}</b>
      </header>

      <div v-if="!evo.hasSelection.value" class="evo-empty">选择一个运行</div>
      <div v-else class="evo-review-body">
        <div class="evo-mini-columns">
          <div class="evo-progress-card">
            <div class="evo-progress-head">
              <strong>整体进度</strong>
              <span>{{ clampPercent(evo.selectedRun.value.overallProgressPercent) }}%</span>
            </div>
            <div class="evo-progress-track" aria-hidden="true">
              <span
                class="evo-progress-fill"
                :style="{ width: `${clampPercent(evo.selectedRun.value.overallProgressPercent)}%` }"
              ></span>
            </div>
            <p>
              {{ progressLabel(evo.selectedRun.value) }}
              · {{ stageLabel(evo) }}
              · {{ selectedIsBatch ? '批量聚合' : recommendationLabel(evo.selectedRun.value) }}
            </p>
          </div>
        </div>

        <div class="evo-progress-grid">
          <div
            v-for="row in progressRows(evo.selectedRun.value)"
            :key="row.key"
            class="evo-progress-card compact"
          >
            <div class="evo-progress-head">
              <strong>{{ row.label }}</strong>
              <span>{{ clampPercent(row.percent) }}%</span>
            </div>
            <div class="evo-progress-track" aria-hidden="true">
              <span class="evo-progress-fill" :style="{ width: `${clampPercent(row.percent)}%` }"></span>
            </div>
            <p>{{ row.text || '等待' }}</p>
          </div>
        </div>

        <div class="evo-config-grid">
          <span><small>发布策略</small><b>{{ evo.selectedRun.value.config?.auto_promote ? '评审门禁' : '仅训练记录' }}</b></span>
          <span><small>开始</small><b>{{ timeLabel(evo.selectedRun.value.startedLabel) }}</b></span>
          <span><small>心跳</small><b>{{ timeLabel(evo.selectedRun.value.heartbeatLabel) }}</b></span>
          <span><small>结束</small><b>{{ timeLabel(evo.selectedRun.value.finishedLabel) }}</b></span>
          <span><small>变更</small><b>{{ selectedIsBatch ? '进入子运行查看' : `${evo.selectedRun.value.proposalCount || 0} 提案 · ${evo.selectedRun.value.diffCount || 0} diff` }}</b></span>
          <span><small>诊断</small><b>{{ evo.selectedRun.value.diagnosticCount || 0 }} 诊断 · {{ evo.selectedRun.value.warningCount || 0 }} 警告 · {{ evo.selectedRun.value.errorCount || 0 }} 错误</b></span>
        </div>

        <div v-if="selectedIsBatch" class="evo-batch-detail">
          <h3>批量子运行</h3>
          <p>批量任务只显示聚合状态；样本局、diff 和评审动作请进入具体子运行查看。</p>
          <div v-if="childRunRows(evo.selectedRun.value).length" class="evo-child-run-list">
            <button
              v-for="(child, index) in childRunRows(evo.selectedRun.value)"
              :key="childRunKey(child, index)"
              type="button"
              class="evo-child-run-row"
              :disabled="!child.id"
              @click="evo.selectRun(child.id)"
            >
              <span class="evo-run-status" :data-status="child.status">{{ child.statusLabel }}</span>
              <strong>{{ child.displayRole }}</strong>
              <small>{{ child.id || child.run_id || '—' }}</small>
              <b>{{ clampPercent(child.progressPercent) }}%</b>
            </button>
          </div>
          <div v-else class="evo-empty compact">暂无子运行详情</div>
        </div>

        <template v-else>
          <div class="evo-mini-columns">
            <div>
              <h3>样本局</h3>
              <p>
                训练 {{ sampleCount(evo.selectedGames.value, 'training') }}
                · 基线 {{ sampleCount(evo.selectedGames.value, 'baseline') }}
                · 候选 {{ sampleCount(evo.selectedGames.value, 'candidate') }}
                · 合计 {{ sampleTotal(evo.selectedGames.value) }}
              </p>
              <p>
                训练进度 {{ evo.selectedRun.value.trainingProgressLabel }}
                · 对战进度 {{ evo.selectedRun.value.battleProgressLabel }}
              </p>
              <p v-if="evo.selectedSampleState.value.error">样本状态 {{ evo.selectedSampleState.value.error }}</p>
            </div>
            <div>
              <h3>对战结果</h3>
              <p>
                基线 {{ rateLabel(battleRate(battleResult(evo.selectedRun.value), 'baseline')) }}
                <span v-if="battleSideMeta(battleResult(evo.selectedRun.value), 'baseline')">
                  ({{ battleSideMeta(battleResult(evo.selectedRun.value), 'baseline') }})
                </span>
                · 候选 {{ rateLabel(battleRate(battleResult(evo.selectedRun.value), 'candidate')) }}
                <span v-if="battleSideMeta(battleResult(evo.selectedRun.value), 'candidate')">
                  ({{ battleSideMeta(battleResult(evo.selectedRun.value), 'candidate') }})
                </span>
                · 差值 {{ signedRateLabel(battleDelta(battleResult(evo.selectedRun.value))) }}
              </p>
              <p>
                跳过 {{ battleSkippedLabel(battleResult(evo.selectedRun.value)) }}
                · 显著 {{ battleSignificantLabel(battleResult(evo.selectedRun.value)) }}
                · 原因 {{ battleReason(battleResult(evo.selectedRun.value)) }}
              </p>
            </div>
          </div>

          <div class="evo-evidence-columns">
            <div>
              <h4>诊断摘要</h4>
              <ol v-if="diagnosticRows(evo.selectedRun.value).length">
                <li
                  v-for="(diagnostic, index) in diagnosticRows(evo.selectedRun.value)"
                  :key="diagnosticKey(diagnostic, index)"
                >
                  <strong>{{ diagnosticLabel(diagnostic) }}</strong>
                  <span>{{ diagnosticText(diagnostic) }}</span>
                </li>
              </ol>
              <span v-else>—</span>
            </div>
            <div>
              <h4>提案摘要</h4>
              <ol v-if="proposalRows(evo.selectedRun.value).length">
                <li
                  v-for="(proposal, index) in proposalRows(evo.selectedRun.value)"
                  :key="proposalKey(proposal, index)"
                >
                  <strong>{{ proposalLabel(proposal, index) }}</strong>
                  <span>{{ proposalMeta(proposal) }} · {{ proposalText(proposal) }}</span>
                </li>
              </ol>
              <span v-else>—</span>
            </div>
          </div>

          <EvolutionDiffViewer
            :diff-data="evo.selectedDiffData.value"
            :legacy-diff="evo.selectedDiff.value"
          />
        </template>
      </div>
    </article>
  </div>
</template>

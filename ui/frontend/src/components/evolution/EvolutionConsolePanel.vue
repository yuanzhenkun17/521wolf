<script setup>
import EvolutionDiffViewer from './EvolutionDiffViewer.vue'

defineProps({
  evo: { type: Object, required: true },
  selectedIsBatch: Boolean,
  selectedCanReview: Boolean,
  selectedCanTerminate: Boolean
})

function actionLoadingText(value, loading = false) {
  const text = String(value || '')
  if (text.startsWith('start-single')) return '启动单角色'
  if (text.startsWith('start-batch')) return '启动批量'
  if (text.startsWith('promote')) return '晋升中'
  if (text.startsWith('reject')) return '拒绝中'
  if (text.startsWith('terminate')) return '终止中'
  if (text.startsWith('rollback')) return '回滚中'
  return loading ? '读取中' : ''
}

function stageLabel(evo) {
  const run = evo.selectedRun.value || {}
  if (run.currentStageLabel) return run.currentStageLabel
  const value = run.current_stage || run.currentStage || run.stage || run.status
  return evo.statusText?.(value) || value || '未知'
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function finiteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function clampPercent(value) {
  const number = finiteNumber(value)
  if (number == null) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function progressLabel(run) {
  if (!run) return '—'
  if (run.progressLabel) return run.progressLabel
  const percent = finiteNumber(run.progressPercent)
  return percent == null ? '—' : `${Math.round(percent)}%`
}

function displayText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function verdictText(value) {
  return {
    promote: '建议晋升',
    reject: '建议拒绝',
    hold: '继续观察',
    pending: '待评审',
    baseline: '基线'
  }[value] || displayText(value)
}

function recommendationLabel(run) {
  if (!run) return '—'
  return run.recommendationLabel || verdictText(run.recommendation || run.battle_result?.recommendation)
}

function timeLabel(value) {
  return displayText(value)
}

function sampleCount(games, bucket) {
  return asArray(games?.[bucket]).length
}

function sampleTotal(games) {
  return sampleCount(games, 'training') + sampleCount(games, 'baseline') + sampleCount(games, 'candidate')
}

function diagnosticRows(run) {
  return asArray(run?.diagnostics).slice(0, 5)
}

function diagnosticKey(diagnostic, index) {
  return diagnostic?.id || diagnostic?.kind || diagnostic?.stage || diagnostic?.message || index
}

function diagnosticLabel(diagnostic) {
  return displayText(diagnostic?.level || diagnostic?.kind || diagnostic?.type || diagnostic?.stage, '诊断')
}

function diagnosticText(diagnostic) {
  return displayText(diagnostic?.message || diagnostic?.summary || diagnostic?.reason || diagnostic?.error)
}

function proposalRows(run) {
  return asArray(run?.proposals).slice(0, 5)
}

function proposalKey(proposal, index) {
  return proposal?.proposal_id || proposal?.id || proposal?.target_file || index
}

function proposalLabel(proposal, index) {
  return displayText(proposal?.proposal_id || proposal?.id || proposal?.target_file, `提案 ${index + 1}`)
}

function proposalMeta(proposal) {
  return displayText([proposal?.target_file, proposal?.operation || proposal?.action].filter(Boolean).join(' · '))
}

function proposalText(proposal) {
  return displayText(
    proposal?.rationale ||
      proposal?.summary ||
      proposal?.description ||
      proposal?.recommendation ||
      proposal?.reason
  )
}

function battleResult(run) {
  return run?.combined_battle_result || run?.battle_result || null
}

function battleSide(result, side) {
  return result?.[side] && typeof result[side] === 'object' ? result[side] : {}
}

function battleRate(result, side) {
  if (!result) return null
  const sideData = battleSide(result, side)
  const topLevel = side === 'candidate' ? result.candidate_win_rate : result.baseline_win_rate
  return finiteNumber(topLevel ?? sideData.target_win_rate ?? sideData.avg_role_weighted_score)
}

function rateLabel(value) {
  const number = finiteNumber(value)
  if (number == null) return '—'
  return `${Math.round(number * 100)}%`
}

function signedRateLabel(value) {
  const number = finiteNumber(value)
  if (number == null) return '—'
  const percent = Math.round(number * 100)
  return `${percent > 0 ? '+' : ''}${percent}%`
}

function battleDelta(result) {
  if (!result) return null
  const direct = finiteNumber(result.win_rate_delta)
  if (direct != null) return direct
  const candidate = battleRate(result, 'candidate')
  const baseline = battleRate(result, 'baseline')
  if (candidate == null || baseline == null) return null
  return candidate - baseline
}

function battleSideMeta(result, side) {
  const data = battleSide(result, side)
  const completed = finiteNumber(data.completed)
  const games = finiteNumber(data.games)
  if (completed == null && games == null) return ''
  return `${completed ?? 0} / ${games ?? completed ?? 0} 局`
}

function battleSignificantLabel(result) {
  if (!result || result.skipped) return '—'
  const value = result.significant ?? result.significance?.significant
  if (value === true) return '是'
  if (value === false) return '否'
  return '—'
}

function battleSkippedLabel(result) {
  if (!result) return '—'
  return result.skipped ? '是' : '否'
}

function battleReason(result) {
  if (!result) return '—'
  const reasons = asArray(result.significance?.reasons).join(', ')
  return displayText(result.reason || result.error || reasons)
}

function progressRows(run) {
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

function childRunRows(run) {
  return asArray(run?.childRuns).slice(0, 12)
}

function childRunKey(run, index) {
  return run?.id || run?.run_id || index
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card">
      <header>
        <h2>进化控制台</h2>
        <b>{{ evo.selectedRoleLabel.value }}</b>
      </header>

      <div class="evo-form-grid">
        <label>训练局数<input v-model.number="evo.form.value.training_games" type="number" min="1" max="200" inputmode="numeric" /></label>
        <label>对战局数<input v-model.number="evo.form.value.battle_games" type="number" min="1" max="200" inputmode="numeric" /></label>
        <label>最大天数<input v-model.number="evo.form.value.max_days" type="number" min="1" max="100" inputmode="numeric" /></label>
        <label class="evo-check-field">
          自动晋升
          <input v-model="evo.form.value.auto_promote" type="checkbox" disabled />
        </label>
      </div>

      <div class="evo-batch-role-grid">
        <button
          v-for="role in evo.roleRows.value"
          :key="role.key"
          type="button"
          :class="['evo-role-toggle', { selected: role.selected }]"
          :aria-pressed="role.selected"
          @click="evo.toggleBatchRole(role.key)"
        >
          <img :src="role.image" alt="" aria-hidden="true" />
          <span>{{ role.label }}</span>
        </button>
      </div>

      <div class="evo-command-row">
        <button
          type="button"
          class="evo-action"
          :disabled="Boolean(evo.actionLoading.value) || !evo.selectedRole.value"
          @click="evo.startSingle()"
        >
          <span aria-hidden="true">&#9654;</span> 单角色
        </button>
        <button
          type="button"
          class="evo-action"
          :disabled="Boolean(evo.actionLoading.value) || !evo.selectedBatchRoles.value.length"
          @click="evo.startBatch()"
        >
          <span aria-hidden="true">&#9654;</span> 批量
        </button>
        <span v-if="evo.loading.value || evo.actionLoading.value" class="evo-loading">
          {{ actionLoadingText(evo.actionLoading.value, evo.loading.value) }}
        </span>
      </div>
    </article>

    <article class="evo-card">
      <header>
        <h2>评审面板</h2>
        <b>{{ evo.selectedRun.value?.statusLabel || '—' }}</b>
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

        <div v-if="selectedIsBatch" class="evo-kpis">
          <span><small>角色完成</small><b>{{ evo.selectedRun.value.completedRoleCount || 0 }} / {{ evo.selectedRun.value.roleCount || 0 }}</b></span>
          <span><small>子运行</small><b>{{ evo.selectedRun.value.childRunCount || 0 }}</b></span>
          <span><small>训练</small><b>{{ evo.selectedRun.value.trainingProgressLabel }}</b></span>
          <span><small>对战</small><b>{{ evo.selectedRun.value.battleProgressLabel }}</b></span>
        </div>
        <div v-else class="evo-kpis">
          <span><small>父版本</small><b>{{ evo.selectedRun.value.parentShort }}</b></span>
          <span><small>候选版本</small><b>{{ evo.selectedRun.value.candidateShort }}</b></span>
          <span><small>训练</small><b>{{ evo.selectedRun.value.trainingGameCompleted || 0 }} / {{ evo.selectedRun.value.trainingGameRequested || 0 }}</b></span>
          <span><small>对战</small><b>{{ evo.selectedRun.value.battleGameCompleted || 0 }} / {{ evo.selectedRun.value.battleGameRequested || 0 }}</b></span>
        </div>

        <div class="evo-config-grid">
          <span><small>类型</small><b>{{ evo.selectedRun.value.entityLabel }}</b></span>
          <span><small>最大天数</small><b>{{ evo.selectedRun.value.config?.max_days || 5 }}</b></span>
          <span><small>自动晋升</small><b>{{ evo.selectedRun.value.config?.auto_promote ? '开启' : '关闭' }}</b></span>
          <span><small>阶段</small><b>{{ stageLabel(evo) }}</b></span>
          <span><small>推荐</small><b>{{ selectedIsBatch ? '—' : recommendationLabel(evo.selectedRun.value) }}</b></span>
          <span><small>开始</small><b>{{ timeLabel(evo.selectedRun.value.startedLabel) }}</b></span>
          <span><small>心跳</small><b>{{ timeLabel(evo.selectedRun.value.heartbeatLabel) }}</b></span>
          <span><small>结束</small><b>{{ timeLabel(evo.selectedRun.value.finishedLabel) }}</b></span>
          <span><small>变更</small><b>{{ selectedIsBatch ? '进入子运行查看' : `${evo.selectedRun.value.proposalCount || 0} 提案 · ${evo.selectedRun.value.diffCount || 0} diff` }}</b></span>
          <span><small>诊断</small><b>{{ evo.selectedRun.value.diagnosticCount || 0 }} 诊断 · {{ evo.selectedRun.value.warningCount || 0 }} 警告 · {{ evo.selectedRun.value.errorCount || 0 }} 错误</b></span>
        </div>

        <div class="evo-review-actions">
          <button
            type="button"
            class="evo-action"
            :disabled="!selectedCanReview || Boolean(evo.actionLoading.value)"
            @click="evo.runAction(evo.selectedRunId.value, 'promote')"
          >
            <span aria-hidden="true">&#8593;</span> 晋升
          </button>
          <button
            type="button"
            class="evo-action danger"
            :disabled="!selectedCanReview || Boolean(evo.actionLoading.value)"
            @click="evo.runAction(evo.selectedRunId.value, 'reject')"
          >
            <span aria-hidden="true">&#215;</span> 拒绝
          </button>
          <button
            type="button"
            class="evo-ghost-action danger"
            :disabled="!selectedCanTerminate || Boolean(evo.actionLoading.value)"
            @click="evo.runAction(evo.selectedRunId.value, 'terminate')"
          >
            终止
          </button>
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
                · delta {{ signedRateLabel(battleDelta(battleResult(evo.selectedRun.value))) }}
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

<script setup lang="ts">
import type { PropType } from 'vue'

interface RefLike<T> {
  value: T
}

interface BattleSideResult {
  target_win_rate?: number
  avg_role_weighted_score?: number
}

interface BattleResult {
  skipped?: boolean
  candidate?: BattleSideResult
  baseline?: BattleSideResult
  candidate_win_rate?: number
  baseline_win_rate?: number
}

interface EvolutionRunRow {
  id: string
  entityType?: string
  completedRoleCount?: number
  roleCount?: number
  combined_battle_result?: BattleResult
  battle_result?: BattleResult
  overallProgressPercent?: number
  progressPercent?: number
  status?: string
  statusLabel?: string
  displayRole?: string
  entityLabel?: string
  currentStageLabel?: string
  overallProgressLabel?: string
}

interface EvolutionRunsModel {
  runPagination: RefLike<{ total?: number }>
  runRows: RefLike<EvolutionRunRow[]>
  runFilter: RefLike<string>
  visibleRunRows: RefLike<EvolutionRunRow[]>
  filteredRunRows: RefLike<EvolutionRunRow[]>
  selectedRunId: RefLike<string>
  runHasMore: RefLike<boolean>
  runLoadingMore: RefLike<boolean>
  selectRun: (id: string) => void
  loadMoreRuns: () => void
}

defineProps({
  evo: { type: Object as PropType<EvolutionRunsModel>, required: true }
})

function scoreLabel(value: unknown) {
  const n = Number(value || 0)
  return `${Math.round(n * 100)}%`
}

function primaryMetric(run: EvolutionRunRow | null | undefined) {
  if (!run) return '—'
  if (run.entityType === 'batch') {
    return `${run.completedRoleCount || 0} / ${run.roleCount || 0} 角色`
  }
  const result = run.combined_battle_result || run.battle_result
  if (result?.skipped) return '跳过'
  const candidate = result?.candidate || {}
  const baseline = result?.baseline || {}
  // New battle shape: target-team win rates (top-level or per-side).
  // Falls back to the legacy avg_role_weighted_score for older runs.
  const c = result?.candidate_win_rate ?? candidate.target_win_rate ?? candidate.avg_role_weighted_score
  const b = result?.baseline_win_rate ?? baseline.target_win_rate ?? baseline.avg_role_weighted_score
  if (c == null || b == null) return '—'
  return `${scoreLabel(c)} / ${scoreLabel(b)}`
}

function progressPercent(run: EvolutionRunRow) {
  const number = Number(run?.overallProgressPercent ?? run?.progressPercent ?? 0)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card">
      <header>
        <h2>运行队列</h2>
        <b>{{ evo.runPagination.value.total || evo.runRows.value.length }}</b>
      </header>

      <div class="evo-run-tools">
        <input v-model="evo.runFilter.value" type="search" placeholder="筛选 run / 角色 / 状态" />
        <span>{{ evo.visibleRunRows.value.length }} / {{ evo.runPagination.value.total || evo.filteredRunRows.value.length }}</span>
      </div>

      <div v-if="!evo.filteredRunRows.value.length" class="evo-empty">暂无运行记录</div>
      <div v-else class="evo-run-scroll">
        <button
          v-for="run in evo.visibleRunRows.value"
          :key="run.id"
          type="button"
          :class="['evo-run-row', { selected: evo.selectedRunId.value === run.id }]"
          @click="evo.selectRun(run.id)"
        >
          <span class="evo-run-status" :data-status="run.status">{{ run.statusLabel }}</span>
          <span class="evo-run-main">
            <strong>{{ run.displayRole }} · {{ run.entityLabel }}</strong>
            <small>{{ run.id }} · {{ run.currentStageLabel }} · {{ run.overallProgressLabel }}</small>
            <span class="evo-run-progress" aria-hidden="true">
              <i :style="{ width: `${progressPercent(run)}%` }"></i>
            </span>
          </span>
          <span class="evo-run-metric">{{ primaryMetric(run) }}</span>
        </button>
        <div v-if="evo.runHasMore.value" class="evo-run-more">
          <button type="button" class="evo-load-more" :disabled="evo.runLoadingMore.value" @click="evo.loadMoreRuns()">
            {{ evo.runLoadingMore.value ? '加载中' : '加载更多' }}
          </button>
        </div>
      </div>
    </article>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const suite = computed(() => props.benchmark.selectedBenchmarkSuite.value || null)
const plan = computed(() => props.benchmark.benchmarkPlan.value || null)
const budget = computed(() => plan.value?.budget || {})
const gates = computed(() => suite.value?.gates || suite.value?.rankable_gates || {})
const targetType = computed(() => props.benchmark.selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version')

const scopeLabel = computed(() =>
  targetType.value === 'model' ? 'scope=model' : `scope=role_version / ${props.benchmark.selectedRoleLabel.value}`
)
const subjectLabel = computed(() => {
  if (targetType.value === 'model') {
    return props.benchmark.form.value.model_config_hash || props.benchmark.form.value.model_id || 'current backend model'
  }
  return props.benchmark.form.value.target_version_id || 'baseline version'
})
const gateLabel = computed(() => {
  const minGames = gates.value?.min_completed_games ?? gates.value?.min_rankable_games
  const validRate = gates.value?.min_valid_game_rate
  const fallback = gates.value?.max_fallback_rate
  const parts = []
  if (minGames != null) parts.push(`min ${minGames} games`)
  if (validRate != null) parts.push(`valid >= ${Math.round(Number(validRate) * 100)}%`)
  if (fallback != null) parts.push(`fallback <= ${Math.round(Number(fallback) * 100)}%`)
  return parts.length ? parts.join(' / ') : 'default gates'
})
const budgetLabel = computed(() => {
  if (!plan.value) return 'plan pending'
  if (budget.value?.exceeded) return 'budget exceeded'
  const units = budget.value?.estimated_units ?? plan.value?.estimates?.estimated_llm_call_units
  return units == null ? 'budget ok' : `${Number(units).toLocaleString('zh-CN')} units`
})
const configHash = computed(() =>
  suite.value?.config_hash || suite.value?.benchmark_config_hash || suite.value?.benchmark?.config_hash || ''
)
</script>

<template>
  <section class="benchmark-boundary-bar" aria-label="Benchmark boundary">
    <div class="boundary-cell boundary-cell--suite">
      <small>Suite</small>
      <b>{{ benchmark.selectedBenchmarkSuiteLabel.value }}</b>
      <em>{{ suite?.id || 'ad-hoc' }}</em>
    </div>
    <div class="boundary-cell">
      <small>Comparison</small>
      <b>{{ scopeLabel }}</b>
      <em>{{ subjectLabel }}</em>
    </div>
    <div class="boundary-cell">
      <small>Evaluation Set</small>
      <b>{{ benchmark.selectedBenchmarkEvaluationSetId.value || 'ad-hoc' }}</b>
      <em>{{ suite?.seed_set_id || 'ad-hoc seed set' }}</em>
    </div>
    <div class="boundary-cell">
      <small>Rankable Gate</small>
      <b>{{ gateLabel }}</b>
      <em>{{ configHash || 'config hash pending' }}</em>
    </div>
    <div :class="['boundary-cell', 'boundary-cell--budget', { danger: benchmark.benchmarkPlanBudgetExceeded.value }]">
      <small>Budget</small>
      <b>{{ budgetLabel }}</b>
      <em>{{ benchmark.selectedBenchmarkCanLaunch.value ? 'launchable' : 'not launchable' }}</em>
    </div>
  </section>
</template>

<style scoped>
.benchmark-boundary-bar {
  display: grid;
  grid-template-columns: minmax(190px, 1.05fr) minmax(190px, 1fr) minmax(220px, 1.15fr) minmax(220px, 1.2fr) minmax(150px, 0.8fr);
  gap: 8px;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: #f7f8f8;
}

.boundary-cell {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 58px;
  padding: 9px 10px;
  border: 1px solid #d8dedb;
  border-radius: 7px;
  background: #ffffff;
}

.boundary-cell--suite {
  border-left: 4px solid #1f6f54;
}

.boundary-cell--budget {
  border-left: 4px solid #256b8f;
}

.boundary-cell--budget.danger {
  border-left-color: #a13d36;
  background: #fff6f5;
}

.boundary-cell small,
.boundary-cell b,
.boundary-cell em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.boundary-cell small {
  color: #66736d;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.boundary-cell b {
  color: #1f2a27;
  font-size: 12px;
  font-weight: 900;
}

.boundary-cell em {
  color: #66736d;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}
</style>

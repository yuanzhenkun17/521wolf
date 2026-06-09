<script setup lang="ts">
// @ts-nocheck
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
  targetType.value === 'model' ? '模型范围' : `角色版本范围 / ${props.benchmark.selectedRoleLabel.value}`
)
const subjectLabel = computed(() => {
  if (targetType.value === 'model') {
    return props.benchmark.form.value.model_config_hash || props.benchmark.form.value.model_id || '当前后端模型'
  }
  return props.benchmark.form.value.target_version_id || '当前基线版本'
})
const gateLabel = computed(() => {
  const minGames = gates.value?.min_completed_games ?? gates.value?.min_rankable_games
  const validRate = gates.value?.min_valid_game_rate
  const fallback = gates.value?.max_fallback_rate
  const parts = []
  if (minGames != null) parts.push(`至少 ${minGames} 局`)
  if (validRate != null) parts.push(`有效率 >= ${Math.round(Number(validRate) * 100)}%`)
  if (fallback != null) parts.push(`回退率 <= ${Math.round(Number(fallback) * 100)}%`)
  return parts.length ? parts.join(' / ') : '默认门禁'
})
const budgetLabel = computed(() => {
  if (!plan.value) return '计划待生成'
  if (props.benchmark.benchmarkPlanBudgetExceeded.value) return '预算超限'
  const units = budget.value?.estimated_units ?? plan.value?.estimates?.estimated_llm_call_units
  return units == null ? '预算正常' : `${Number(units).toLocaleString('zh-CN')} 单位`
})
const configHash = computed(() =>
  suite.value?.config_hash || suite.value?.benchmark_config_hash || suite.value?.benchmark?.config_hash || ''
)
</script>

<template>
  <section class="benchmark-boundary-bar" aria-label="评测边界">
    <div class="boundary-cell boundary-cell--suite">
      <small>套件</small>
      <b :title="benchmark.selectedBenchmarkSuiteLabel.value">{{ benchmark.selectedBenchmarkSuiteLabel.value }}</b>
      <em :title="suite?.id || '临时'">{{ suite?.id || '临时' }}</em>
    </div>
    <div class="boundary-cell">
      <small>比较边界</small>
      <b :title="scopeLabel">{{ scopeLabel }}</b>
      <em :title="subjectLabel">{{ subjectLabel }}</em>
    </div>
    <div class="boundary-cell">
      <small>评测集</small>
      <b :title="benchmark.selectedBenchmarkEvaluationSetId.value || '临时'">{{ benchmark.selectedBenchmarkEvaluationSetId.value || '临时' }}</b>
      <em :title="suite?.seed_set_id || '临时种子集'">{{ suite?.seed_set_id || '临时种子集' }}</em>
    </div>
    <div class="boundary-cell">
      <small>入榜门禁</small>
      <b :title="gateLabel">{{ gateLabel }}</b>
      <em :title="configHash || 'Config Hash 待生成'">{{ configHash || 'Config Hash 待生成' }}</em>
    </div>
    <div :class="['boundary-cell', 'boundary-cell--budget', { danger: benchmark.benchmarkPlanBudgetExceeded.value }]">
      <small>预算</small>
      <b :title="budgetLabel">{{ budgetLabel }}</b>
      <em>{{ benchmark.selectedBenchmarkCanLaunch.value ? '可启动' : '不可启动' }}</em>
    </div>
  </section>
</template>

<style scoped>
.benchmark-boundary-bar {
  --boundary-bg: var(--bench-bg-texture, var(--logbook-bg-texture, #f2dfae));
  --boundary-surface: var(--bench-surface, var(--logbook-surface, rgba(255, 252, 245, 0.7)));
  --boundary-border: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.15)));
  --boundary-text: var(--bench-text, var(--logbook-text, #3a2a18));
  --boundary-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --boundary-accent: var(--bench-accent, var(--logbook-accent, #8b5e34));
  --boundary-accent-strong: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --boundary-soft: var(--bench-active-bg, var(--logbook-active-bg, rgba(139, 94, 52, 0.1)));
  display: grid;
  grid-template-columns:
    minmax(240px, 1.1fr)
    minmax(220px, 1fr)
    minmax(220px, 1fr)
    minmax(260px, 1.2fr)
    minmax(150px, 0.72fr);
  gap: 6px;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px;
  border: 1px solid var(--boundary-border);
  border-radius: 8px;
  background: var(--boundary-bg);
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}

.boundary-cell {
  display: grid;
  align-content: center;
  gap: 2px;
  min-width: 0;
  min-height: 50px;
  padding: 7px 9px;
  border: 1px solid var(--boundary-border);
  border-radius: 7px;
  background: var(--boundary-surface);
}

.boundary-cell--suite {
  border-left: 4px solid var(--boundary-accent-strong);
}

.boundary-cell--budget {
  border-left: 4px solid rgba(139, 94, 52, 0.72);
}

.boundary-cell--budget.danger {
  border-left-color: var(--boundary-accent-strong);
  background: var(--boundary-soft);
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
  color: var(--boundary-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.boundary-cell b {
  color: var(--boundary-text);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.18;
}

.boundary-cell em {
  color: var(--boundary-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  line-height: 1.18;
}
</style>

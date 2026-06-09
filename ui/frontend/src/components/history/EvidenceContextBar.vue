<script setup>
import { computed } from 'vue'
import { displayRoleLabel, normalizeHistoryDisplayText } from './historyDisplay.js'

const props = defineProps({
  game: { type: Object, default: null }
})

const SOURCE_LABELS = {
  normal: '普通对局',
  benchmark: '批量评测',
  evolution: '自进化样本'
}

function firstText(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && String(value).trim() !== '') return String(value)
  }
  return ''
}

function sourceContext(game = {}) {
  const existing = game.evidence_source && typeof game.evidence_source === 'object' ? game.evidence_source : {}
  const config = game.config && typeof game.config === 'object' ? game.config : {}
  return { existing, config }
}

const context = computed(() => sourceContext(props.game || {}))
const sourceKey = computed(() =>
  firstText(context.value.existing.log_source, props.game?.log_source, context.value.config.log_source, 'normal').toLowerCase()
)
const sourceLabel = computed(() =>
  firstText(
    context.value.existing.log_source_label,
    props.game?.log_source_label,
    context.value.config.log_source_label,
    SOURCE_LABELS[sourceKey.value],
    sourceKey.value
  )
)
const seedLabel = computed(() =>
  firstText(context.value.existing.seed, props.game?.seed, context.value.config.seed, '随机')
)
const runLabel = computed(() =>
  firstText(context.value.existing.source_run_id, props.game?.source_run_id, context.value.config.source_run_id, '未记录')
)
const phaseLabel = computed(() =>
  firstText(
    context.value.existing.source_phase_label,
    props.game?.source_phase_label,
    context.value.config.source_phase_label,
    context.value.existing.source_phase,
    props.game?.source_phase,
    context.value.config.source_phase,
    sourceKey.value === 'normal' ? '普通局' : '未分阶段'
  )
)
const roleVersions = computed(() => {
  const candidates = [
    context.value.existing.role_versions,
    props.game?.role_versions,
    context.value.config.role_versions,
    props.game?.role_skill_dirs,
    context.value.config.role_skill_dirs
  ]
  const source = candidates.find((item) => item && typeof item === 'object' && !Array.isArray(item)) || {}
  return Object.entries(source)
    .filter(([, version]) => version !== null && version !== undefined && String(version).trim() !== '')
    .map(([role, version]) => ({
      role: displayRoleLabel(role),
      version: normalizeHistoryDisplayText(version) || String(version)
    }))
})
const visibleRoleVersions = computed(() => roleVersions.value.slice(0, 4))
const hiddenRoleVersionCount = computed(() => Math.max(0, roleVersions.value.length - visibleRoleVersions.value.length))
</script>

<template>
  <section v-if="game" class="evidence-context-bar" :data-source="sourceKey" aria-label="证据上下文">
    <div class="evidence-context-title">
      <small>证据上下文</small>
      <b>{{ sourceLabel }}</b>
    </div>
    <dl class="evidence-context-meta">
      <div>
        <dt>Seed</dt>
        <dd>{{ seedLabel }}</dd>
      </div>
      <div>
        <dt>Run</dt>
        <dd :title="runLabel">{{ runLabel }}</dd>
      </div>
      <div>
        <dt>阶段</dt>
        <dd>{{ phaseLabel }}</dd>
      </div>
    </dl>
    <div class="evidence-context-versions" :aria-label="`角色版本 ${roleVersions.length} 项`">
      <span v-if="!roleVersions.length">角色版本：默认基线</span>
      <span v-for="item in visibleRoleVersions" :key="`${item.role}-${item.version}`">
        <small>{{ item.role }}</small>
        <b :title="item.version">{{ item.version }}</b>
      </span>
      <span v-if="hiddenRoleVersionCount">+{{ hiddenRoleVersionCount }}</span>
    </div>
  </section>
</template>

<style scoped>
.evidence-context-bar {
  display: grid;
  grid-template-columns: minmax(120px, 0.8fr) minmax(220px, 1.2fr) minmax(220px, 1.4fr);
  gap: 8px;
  align-items: stretch;
  width: 100%;
  min-width: 0;
  padding: 8px;
  border: 1px solid rgba(92, 54, 20, 0.18);
  border-radius: 8px;
  background: rgba(255, 249, 232, 0.72);
  color: #3d2818;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.66);
}

.evidence-context-bar[data-source="benchmark"] {
  border-color: rgba(45, 96, 134, 0.24);
  background: rgba(232, 242, 248, 0.78);
}

.evidence-context-bar[data-source="evolution"] {
  border-color: rgba(97, 82, 148, 0.24);
  background: rgba(239, 236, 248, 0.78);
}

.evidence-context-title,
.evidence-context-meta > div,
.evidence-context-versions > span {
  min-width: 0;
  border: 1px solid rgba(92, 54, 20, 0.1);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.48);
}

.evidence-context-title {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
}

.evidence-context-title small,
.evidence-context-meta dt,
.evidence-context-versions small {
  color: rgba(61, 40, 24, 0.58);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  text-transform: uppercase;
}

.evidence-context-title b {
  min-width: 0;
  overflow: hidden;
  color: #2f2116;
  font-size: 14px;
  font-weight: 900;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-context-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
  margin: 0;
}

.evidence-context-meta > div {
  display: grid;
  gap: 4px;
  padding: 8px;
}

.evidence-context-meta dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 850;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-context-versions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: stretch;
  min-width: 0;
}

.evidence-context-versions > span {
  display: inline-grid;
  min-width: 0;
  max-width: 160px;
  gap: 3px;
  justify-content: center;
  padding: 7px 9px;
  font-size: 12px;
  font-weight: 850;
  line-height: 1.15;
}

.evidence-context-versions b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 860px) {
  .evidence-context-bar {
    grid-template-columns: 1fr;
  }

  .evidence-context-meta {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .evidence-context-meta {
    grid-template-columns: 1fr;
  }

  .evidence-context-versions > span {
    max-width: 100%;
  }
}
</style>

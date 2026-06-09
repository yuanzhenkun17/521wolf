<script setup>
import { computed } from 'vue'
import EvidenceLink from './EvidenceLink.vue'
import { buildEvidenceLink } from './evidenceLinks.js'
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
  firstText(context.value.existing.source_run_id, props.game?.source_run_id, context.value.config.source_run_id, props.game?.run_id, '未记录')
)
const sourceRunId = computed(() =>
  firstText(context.value.existing.source_run_id, props.game?.source_run_id, context.value.config.source_run_id, props.game?.run_id)
)
const archiveLink = computed(() => buildEvidenceLink(props.game || {}, { kind: 'game', label: 'Archive' }))
const runLink = computed(() =>
  buildEvidenceLink({ ...(props.game || {}), source_run_id: sourceRunId.value }, { kind: 'run', label: 'Run' })
)
const archiveLabel = computed(() =>
  firstText(archiveLink.value.id, archiveLink.value.unavailableReason, archiveLink.value.href, '未记录')
)
const archiveTitle = computed(() =>
  archiveLink.value.disabled
    ? firstText(archiveLink.value.unavailableReason, archiveLabel.value)
    : firstText(archiveLink.value.href, archiveLabel.value)
)
const runTitle = computed(() =>
  runLink.value.disabled
    ? firstText(runLink.value.unavailableReason, runLabel.value)
    : firstText(runLink.value.href, runLabel.value)
)
const proposalId = computed(() =>
  firstText(context.value.existing.proposal_id, props.game?.proposal_id, context.value.config.proposal_id)
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
const roleVersionTitle = computed(() =>
  roleVersions.value.length
    ? roleVersions.value.map((item) => `${item.role}: ${item.version}`).join(' / ')
    : '默认基线'
)
const proposalEvidenceMissing = computed(() => sourceKey.value === 'evolution' && !proposalId.value)
const evidenceLinkTargets = computed(() => {
  const game = props.game || {}
  const rows = []
  if (proposalId.value) {
    rows.push({
      key: 'proposal',
      kind: 'proposal',
      label: 'Proposal',
      target: {
        ...game,
        source_run_id: sourceRunId.value,
        proposal_id: proposalId.value
      }
    })
  }
  return rows
})
</script>

<template>
  <section v-if="game" class="evidence-context-bar" :data-source="sourceKey" aria-label="证据上下文">
    <dl class="evidence-context-summary">
      <div class="evidence-context-item evidence-context-item--source">
        <dt>证据上下文</dt>
        <dd :title="sourceLabel">{{ sourceLabel }}</dd>
      </div>
      <div class="evidence-context-item evidence-context-item--archive">
        <dt>Archive</dt>
        <dd :title="archiveTitle">
          <a
            v-if="!archiveLink.disabled"
            class="evidence-context-value-link"
            :href="archiveLink.href"
          >
            {{ archiveLabel }}
          </a>
          <span v-else class="evidence-context-disabled-value">{{ archiveLabel }}</span>
        </dd>
      </div>
      <div class="evidence-context-item evidence-context-item--run">
        <dt>Run</dt>
        <dd :title="runTitle">
          <a
            v-if="!runLink.disabled"
            class="evidence-context-value-link"
            :href="runLink.href"
          >
            {{ runLabel }}
          </a>
          <span v-else class="evidence-context-disabled-value">{{ runLabel }}</span>
        </dd>
      </div>
      <div class="evidence-context-item evidence-context-item--phase">
        <dt>阶段</dt>
        <dd :title="phaseLabel">{{ phaseLabel }}</dd>
      </div>
      <div class="evidence-context-item evidence-context-item--seed">
        <dt>Seed</dt>
        <dd :title="seedLabel">{{ seedLabel }}</dd>
      </div>
      <div
        class="evidence-context-item evidence-context-item--versions"
        :aria-label="`角色版本 ${roleVersions.length} 项`"
      >
        <dt>角色版本</dt>
        <dd class="evidence-context-version-value" :title="roleVersionTitle">
          <span v-if="!roleVersions.length" class="version-baseline">默认基线</span>
          <template v-else>
            <span
              v-for="item in visibleRoleVersions"
              :key="`${item.role}-${item.version}`"
              class="version-chip"
            >
              <small>{{ item.role }}</small>
              <b>{{ item.version }}</b>
            </span>
          </template>
          <span v-if="hiddenRoleVersionCount" class="version-more">+{{ hiddenRoleVersionCount }}</span>
        </dd>
      </div>
    </dl>
    <nav v-if="evidenceLinkTargets.length || proposalEvidenceMissing" class="evidence-context-links" aria-label="证据跳转">
      <EvidenceLink
        v-for="item in evidenceLinkTargets"
        :key="item.key"
        :kind="item.kind"
        :label="item.label"
        :target="item.target"
        compact
      />
      <span
        v-if="proposalEvidenceMissing"
        class="evidence-context-status"
        data-state="missing"
      >
        <span>Proposal</span>
        <small>未关联提案</small>
      </span>
    </nav>
  </section>
</template>

<style scoped>
.evidence-context-bar {
  display: block;
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

.evidence-context-summary {
  display: grid;
  grid-template-columns:
    minmax(160px, 1.25fr)
    minmax(140px, 0.95fr)
    minmax(220px, 1.3fr)
    minmax(120px, 0.75fr)
    minmax(74px, 0.45fr)
    minmax(150px, 1fr);
  gap: 8px;
  min-width: 0;
  margin: 0;
}

.evidence-context-item {
  display: grid;
  align-content: center;
  gap: 5px;
  min-width: 0;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid rgba(92, 54, 20, 0.1);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.48);
}

.evidence-context-item dt,
.version-chip small {
  color: rgba(61, 40, 24, 0.58);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  text-transform: uppercase;
}

.evidence-context-item dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 850;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-context-item--source dd {
  font-size: 14px;
}

.evidence-context-value-link {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-decoration: none;
}

.evidence-context-value-link:hover {
  color: #70401e;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.evidence-context-disabled-value {
  color: rgba(61, 40, 24, 0.68);
}

.evidence-context-version-value {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  line-height: 1.1;
}

.version-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  max-width: 100%;
}

.version-chip small {
  flex: 0 0 auto;
}

.version-chip b,
.version-baseline,
.version-more {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-chip b {
  min-width: 0;
  max-width: 88px;
}

.version-more {
  flex: 0 0 auto;
  color: rgba(61, 40, 24, 0.68);
}

.evidence-context-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  margin-top: 8px;
}

.evidence-context-links :deep(.evidence-link) {
  flex: 0 1 190px;
}

.evidence-context-status {
  display: inline-grid;
  align-content: center;
  gap: 2px;
  flex: 0 1 190px;
  min-width: 0;
  max-width: 100%;
  min-height: 30px;
  padding: 5px 8px;
  border: 1px solid rgba(92, 63, 37, 0.16);
  border-radius: 6px;
  background: rgba(247, 241, 232, 0.72);
  color: rgba(68, 48, 32, 0.7);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.62);
}

.evidence-context-status span {
  overflow: hidden;
  font-size: 11px;
  font-weight: 850;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-context-status small {
  overflow: hidden;
  color: rgba(96, 65, 40, 0.68);
  font-size: 10px;
  font-weight: 750;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1080px) {
  .evidence-context-summary {
    grid-template-columns:
      minmax(150px, 1.2fr)
      minmax(130px, 0.95fr)
      minmax(180px, 1.2fr)
      minmax(110px, 0.8fr)
      minmax(74px, 0.5fr)
      minmax(140px, 1fr);
  }
}

@media (max-width: 860px) {
  .evidence-context-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evidence-context-item--source,
  .evidence-context-item--run,
  .evidence-context-item--versions {
    grid-column: span 2;
  }
}

@media (max-width: 560px) {
  .evidence-context-summary {
    grid-template-columns: 1fr;
  }

  .evidence-context-item--source,
  .evidence-context-item--run,
  .evidence-context-item--versions {
    grid-column: auto;
  }
}
</style>

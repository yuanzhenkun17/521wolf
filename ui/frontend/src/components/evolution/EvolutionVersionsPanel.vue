<script setup>
import { computed, reactive, ref } from 'vue'
import { roleLabel, sourceText } from '../../composables/workbenchShared.js'
import TrustBundleDrawer from './TrustBundleDrawer.vue'

const props = defineProps({
  evo: { type: Object, required: true }
})

const patternRoleFilter = ref('')
const patternStatusFilter = ref('')
const expandedPatterns = reactive(new Set())

const versionDetail = computed(() => props.evo.selectedVersionDetail.value?.data || null)

const PATTERN_STATUS_COLORS = {
  candidate: '#666',
  active: '#4a9eff',
  crystallized: '#f5a623',
  archived: '#555',
  deprecated: '#993333'
}

const PATTERN_STATUS_LABELS = {
  candidate: '候选',
  active: '激活',
  crystallized: '结晶',
  archived: '归档',
  deprecated: '废弃'
}

const versionPatterns = computed(() => {
  const data = versionDetail.value
  if (!data?.patterns?.length) return []
  return data.patterns.map((pattern) => ({
    pattern_id: pattern.pattern_id || pattern.id || pattern.pattern || '未知模式',
    role: pattern.role || data.role || '',
    situation: pattern.situation || pattern.pattern || pattern.name || '—',
    recommendation: pattern.recommendation || pattern.summary || pattern.description || pattern.pattern || '—',
    win_rate_with: Number(pattern.win_rate_with ?? pattern.winRateWith ?? 0),
    win_rate_without: Number(pattern.win_rate_without ?? pattern.winRateWithout ?? 0),
    sample_size: Number(pattern.sample_size ?? pattern.sampleSize ?? pattern.games ?? 0),
    confidence: Number(pattern.confidence ?? pattern.conf ?? 0),
    status: pattern.status || 'candidate',
    source_games: Array.isArray(pattern.source_games)
      ? pattern.source_games
      : Array.isArray(pattern.sourceGames)
        ? pattern.sourceGames
        : []
  }))
})

const versionAuditFields = computed(() => {
  const data = versionDetail.value || {}
  const provenance = data.provenance || {}
  return [
    { key: 'trust', label: 'Trust', value: data.trust_bundle_id || data.trustBundleId || provenance.trust_bundle_id || provenance.trustBundleId },
    { key: 'hash', label: 'Hash', value: data.bundle_hash || data.bundleHash || provenance.bundle_hash || provenance.bundleHash },
    { key: 'gate', label: 'Gate', value: data.gate_report_id || data.gateReportId || provenance.gate_report_id || provenance.gateReportId },
    { key: 'source', label: 'Source Run', value: data.source_run_id || data.sourceRunId || provenance.source_run_id || provenance.sourceRunId }
  ].filter((field) => String(field.value || '').trim())
})

const hasVersionAudit = computed(() => versionAuditFields.value.length > 0)

const patternRoles = computed(() => {
  const roles = new Set(versionPatterns.value.map((pattern) => pattern.role).filter(Boolean))
  return [...roles].sort()
})

const patternStatuses = computed(() => {
  const statuses = new Set(versionPatterns.value.map((pattern) => pattern.status).filter(Boolean))
  return [...statuses].sort()
})

const filteredPatterns = computed(() => {
  let list = versionPatterns.value
  if (patternRoleFilter.value) {
    list = list.filter((pattern) => pattern.role === patternRoleFilter.value)
  }
  if (patternStatusFilter.value) {
    list = list.filter((pattern) => pattern.status === patternStatusFilter.value)
  }
  return list
})

function versionMetric(value) {
  if (value == null) return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n <= 1 ? `${Math.round(n * 100)}%` : String(Math.round(n * 100) / 100)
}

function versionSkillLabel(skill) {
  if (!skill) return '技能文件'
  const rawLabel = skill.title || skill.label || skill.name || ''
  const label = rawLabel && !/^[a-z0-9_.:/\\-]+$/i.test(String(rawLabel)) ? rawLabel : '技能文件'
  const hash = skill.content_hash || skill.hash || ''
  return hash ? `${label} · ${String(hash).slice(0, 8)}` : label
}

function versionSourceLabel(version) {
  const source = sourceText(version?.source || (version?.is_baseline ? 'baseline' : 'version'))
  const stage = version?.releaseStageLabel || sourceText(version?.release_stage || version?.provenance?.release_stage)
  return stage && stage !== '未知' ? `${source} · ${stage}` : source
}

function versionDetailSourceLabel(data) {
  const source = sourceText(data?.provenance?.source || data?.source || 'version')
  const stage = sourceText(data?.release_stage || data?.provenance?.release_stage)
  return stage && stage !== '未知' ? `${source} · ${stage}` : source
}

function patternStatusColor(status) {
  return PATTERN_STATUS_COLORS[status] || '#666'
}

function patternStatusLabel(status) {
  return PATTERN_STATUS_LABELS[status] || status || '未知'
}

function patternRoleLabel(role) {
  return roleLabel(role)
}

function winRatePct(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function winRateBarColor(value) {
  const n = Number(value) || 0
  if (n >= 0.6) return '#2e7d32'
  if (n >= 0.45) return '#f9a825'
  return '#c62828'
}

function togglePatternSource(patternId) {
  if (expandedPatterns.has(patternId)) {
    expandedPatterns.delete(patternId)
  } else {
    expandedPatterns.add(patternId)
  }
}

function confidenceWidth(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function auditFieldText(value) {
  const text = String(value ?? '').trim()
  return text || '—'
}

function openVersionTrustAudit() {
  props.evo.openTrustBundleDrawer?.('version', { version: versionDetail.value || {} })
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card">
      <header>
        <h2>版本</h2>
        <b>{{ evo.selectedRoleVersions.value.length }}</b>
      </header>

      <div v-if="!evo.selectedRoleVersions.value.length" class="evo-empty">暂无版本</div>
      <div v-else class="evo-version-list">
        <div v-for="version in evo.selectedRoleVersions.value" :key="version.version_id" class="evo-version-row">
          <span>
            <strong>{{ version.short }}</strong>
            <small>{{ versionSourceLabel(version) }} · {{ version.createdLabel }}</small>
          </span>
          <div class="evo-version-actions">
            <button
              type="button"
              class="evo-ghost-action"
              :disabled="evo.selectedVersionDetail.value.loading && evo.selectedVersionId.value === version.version_id"
              @click="evo.loadVersionDetail(evo.selectedRole.value, version.version_id)"
            >
              {{ evo.selectedVersionId.value === version.version_id && evo.selectedVersionDetail.value.loading ? '读取' : '详情' }}
            </button>
            <button
              type="button"
              class="evo-ghost-action"
              :disabled="version.rollbackDisabled || version.is_baseline || Boolean(evo.actionLoading.value)"
              :title="version.rollbackDisabledReason || ''"
              @click="evo.rollback(evo.selectedRole.value, version.version_id)"
            >
              {{ version.rollbackLabel || (version.is_baseline ? '当前基线' : '回滚') }}
            </button>
          </div>
        </div>
      </div>

      <div class="evo-version-detail">
        <div v-if="evo.selectedVersionDetail.value.loading" class="evo-empty compact">读取版本...</div>
        <div v-else-if="evo.selectedVersionDetail.value.error" class="evo-alert compact">
          {{ evo.selectedVersionDetail.value.error }}
        </div>
        <template v-else-if="evo.selectedVersionDetail.value.data">
          <header>
            <span>
              <strong>{{ evo.shortId(evo.selectedVersionDetail.value.data.version_id) }}</strong>
              <small>
                {{ versionDetailSourceLabel(evo.selectedVersionDetail.value.data) }}
              </small>
            </span>
            <b>{{ evo.selectedVersionDetail.value.data.skills?.length || 0 }} 个技能</b>
          </header>

          <div class="evo-version-kpis">
            <span><small>胜率</small><b>{{ versionMetric(evo.selectedVersionDetail.value.data.metrics?.win_rate) }}</b></span>
            <span><small>评分</small><b>{{ versionMetric(evo.selectedVersionDetail.value.data.metrics?.score) }}</b></span>
            <span><small>局数</small><b>{{ evo.selectedVersionDetail.value.data.metrics?.games_played || 0 }}</b></span>
          </div>

          <div v-if="hasVersionAudit" class="evo-version-audit-strip">
            <span v-for="field in versionAuditFields" :key="field.key">
              <small>{{ field.label }}</small>
              <code>{{ auditFieldText(field.value) }}</code>
            </span>
            <button type="button" class="evo-ghost-action" @click="openVersionTrustAudit">Trust 审计</button>
          </div>

          <ul v-if="evo.selectedVersionDetail.value.data.skills?.length" class="evo-version-skill-list">
            <li v-for="skill in evo.selectedVersionDetail.value.data.skills.slice(0, 4)" :key="skill.path || skill.content_hash">
              {{ versionSkillLabel(skill) }}
            </li>
          </ul>

          <div v-if="versionPatterns.length" class="evo-pattern-browser">
            <div class="evo-pattern-filter-bar">
              <select v-model="patternRoleFilter">
                <option value="">全部角色</option>
                <option v-for="role in patternRoles" :key="role" :value="role">{{ patternRoleLabel(role) }}</option>
              </select>
              <select v-model="patternStatusFilter">
                <option value="">全部状态</option>
                <option v-for="status in patternStatuses" :key="status" :value="status">{{ patternStatusLabel(status) }}</option>
              </select>
              <small>{{ filteredPatterns.length }} / {{ versionPatterns.length }}</small>
            </div>

            <div class="evo-pattern-card-list">
              <div v-for="pattern in filteredPatterns" :key="pattern.pattern_id" class="evo-pattern-card">
                <div class="evo-pattern-card-header">
                  <span class="evo-pattern-status-badge" :style="{ background: patternStatusColor(pattern.status) }">
                    {{ patternStatusLabel(pattern.status) }}
                  </span>
                  <span class="evo-pattern-role-tag">{{ patternRoleLabel(pattern.role) }}</span>
                  <span class="evo-pattern-id">{{ pattern.pattern_id }}</span>
                </div>

                <div class="evo-pattern-situation">
                  <code>{{ pattern.situation }}</code>
                </div>

                <p class="evo-pattern-recommendation">{{ pattern.recommendation }}</p>

                <div class="evo-pattern-winrate-bars">
                  <div class="evo-pattern-wr-row">
                    <span class="evo-pattern-wr-label">执行</span>
                    <div class="evo-pattern-wr-bar-track">
                      <div
                        class="evo-pattern-wr-bar-fill"
                        :style="{ width: winRatePct(pattern.win_rate_with), background: winRateBarColor(pattern.win_rate_with) }"
                      ></div>
                    </div>
                    <span class="evo-pattern-wr-value">{{ winRatePct(pattern.win_rate_with) }}</span>
                  </div>
                  <div class="evo-pattern-wr-row">
                    <span class="evo-pattern-wr-label">不执行</span>
                    <div class="evo-pattern-wr-bar-track">
                      <div
                        class="evo-pattern-wr-bar-fill"
                        :style="{ width: winRatePct(pattern.win_rate_without), background: winRateBarColor(pattern.win_rate_without) }"
                      ></div>
                    </div>
                    <span class="evo-pattern-wr-value">{{ winRatePct(pattern.win_rate_without) }}</span>
                  </div>
                </div>

                <div class="evo-pattern-meta-row">
                  <span>样本: <b>{{ pattern.sample_size }}</b></span>
                  <span class="evo-pattern-confidence">
                    置信度:
                    <span class="evo-pattern-conf-track">
                      <span class="evo-pattern-conf-fill" :style="{ width: confidenceWidth(pattern.confidence) }"></span>
                    </span>
                    <b>{{ winRatePct(pattern.confidence) }}</b>
                  </span>
                </div>

                <div v-if="pattern.source_games.length" class="evo-pattern-source-games">
                  <button type="button" class="evo-pattern-toggle-btn" @click="togglePatternSource(pattern.pattern_id)">
                    {{ expandedPatterns.has(pattern.pattern_id) ? '收起' : '来源局' }} ({{ pattern.source_games.length }})
                  </button>
                  <ul v-if="expandedPatterns.has(pattern.pattern_id)" class="evo-pattern-source-list">
                    <li v-for="gameId in pattern.source_games" :key="gameId">{{ gameId }}</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
          <div v-else-if="evo.selectedVersionDetail.value.data.patterns" class="evo-pattern-empty">
            该版本暂无策略模式数据
          </div>
        </template>
        <div v-else class="evo-empty compact">选择一个版本查看包内容</div>
      </div>
    </article>
    <TrustBundleDrawer :evo="evo" />
  </div>
</template>

<style scoped>
.evo-version-audit-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
  align-items: stretch;
  gap: 8px;
  margin: 10px 0;
}

.evo-version-audit-strip span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-input-bg);
}

.evo-version-audit-strip small {
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.evo-version-audit-strip code {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 760px) {
  .evo-version-audit-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-version-audit-strip > button {
    grid-column: 1 / -1;
  }
}
</style>

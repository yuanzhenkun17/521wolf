<script setup lang="ts">
import { computed, type PropType } from 'vue'

type ReadableRef<T> = {
  readonly value: T
}

interface BenchmarkTargetForm {
  model_id: string
  model_config_hash: string
  target_version_id: string
}

interface BenchmarkRoleRow {
  key: string
  label: string
  image: string
}

interface BenchmarkRoleTargetVersion {
  version_id: string
  short?: string
  is_baseline?: boolean
  release_stage?: string
  releaseStage?: string
  releaseStageLabel?: string
  games?: number | string | null
  targetDisabled?: boolean
  targetDisabledReason?: string
}

interface BenchmarkTargetBenchmark {
  roleRows: ReadableRef<BenchmarkRoleRow[]>
  roleTargetVersionRows: ReadableRef<BenchmarkRoleTargetVersion[]>
  selectedBenchmarkIsModelSuite: ReadableRef<boolean>
  selectedRoleTargetVersion: ReadableRef<BenchmarkRoleTargetVersion | null>
  selectedRoleTargetVersionBlockedReason: ReadableRef<string>
  selectedRole: ReadableRef<string>
  form: ReadableRef<BenchmarkTargetForm>
  selectRole: (role: string) => void
}

const props = defineProps({
  benchmark: {
    type: Object as PropType<BenchmarkTargetBenchmark>,
    required: true
  }
})

const roleRows = computed(() => props.benchmark.roleRows.value || [])
const roleVersionRows = computed(() => props.benchmark.roleTargetVersionRows.value || [])
const isModel = computed(() => props.benchmark.selectedBenchmarkIsModelSuite.value)
const selectedTargetVersion = computed(() => props.benchmark.selectedRoleTargetVersion.value || null)
const selectedTargetBlockedReason = computed(() => props.benchmark.selectedRoleTargetVersionBlockedReason.value || '')

const versionStageLabels: Record<string, string> = {
  baseline: '基线',
  canary: '金丝雀',
  shadow: '影子',
  draft: '草稿',
  released: '已发布',
  production: '生产',
  deprecated: '废弃'
}

function versionStageClass(version: BenchmarkRoleTargetVersion | null | undefined) {
  return String(version?.release_stage || version?.releaseStage || 'unknown').trim().toLowerCase() || 'unknown'
}

function versionStageLabel(version: BenchmarkRoleTargetVersion | null | undefined) {
  const stage = String(version?.release_stage || version?.releaseStage || '').trim().toLowerCase()
  const explicit = String(version?.releaseStageLabel || '').trim()
  return versionStageLabels[stage] || versionStageLabels[explicit.toLowerCase()] || explicit || version?.release_stage || version?.releaseStage || '未标记'
}

function versionOptionText(version: BenchmarkRoleTargetVersion) {
  const parts = [
    version.short || version.version_id,
    version.is_baseline ? '当前基线' : versionStageLabel(version)
  ]
  if (version.games) parts.push(`${version.games} 局`)
  if (version.targetDisabledReason) parts.push('不可选')
  return parts.filter(Boolean).join(' · ')
}
</script>

<template>
  <article class="benchmark-target-selector" aria-label="评测目标选择器">
    <header>
      <div>
        <small>目标</small>
        <h2>被测对象</h2>
      </div>
    </header>

    <section v-if="isModel" class="target-fields target-fields--model">
      <label>
        <span>模型 ID</span>
        <input
          v-model.trim="benchmark.form.value.model_id"
          type="text"
          autocomplete="off"
          placeholder="留空使用当前后端模型"
        />
      </label>
      <label>
        <span>Config Hash</span>
        <input
          v-model.trim="benchmark.form.value.model_config_hash"
          type="text"
          autocomplete="off"
          placeholder="留空由后端生成"
        />
      </label>
    </section>

    <section v-else class="target-fields target-fields--role">
      <div class="role-target-list" aria-label="角色选择器">
        <button
          v-for="role in roleRows"
          :key="role.key"
          type="button"
          :class="['role-target-chip', { selected: benchmark.selectedRole.value === role.key }]"
          @click="benchmark.selectRole(role.key)"
        >
          <img :src="role.image" alt="" aria-hidden="true" />
          <span>{{ role.label }}</span>
        </button>
      </div>
      <label class="target-version-field">
        <span>目标版本</span>
        <select
          v-model.trim="benchmark.form.value.target_version_id"
          :aria-invalid="selectedTargetBlockedReason ? 'true' : 'false'"
        >
          <option value="">当前基线版本</option>
          <option
            v-for="version in roleVersionRows"
            :key="version.version_id"
            :value="version.version_id"
            :disabled="version.targetDisabled"
          >
            {{ versionOptionText(version) }}
          </option>
        </select>
      </label>
      <div v-if="roleVersionRows.length" class="target-version-list" aria-label="版本发布阶段">
        <button
          v-for="version in roleVersionRows"
          :key="'version-row-' + version.version_id"
          type="button"
          class="target-version-chip"
          :class="[versionStageClass(version), { selected: benchmark.form.value.target_version_id === version.version_id, disabled: version.targetDisabled }]"
          :disabled="version.targetDisabled"
          :title="version.targetDisabledReason || versionOptionText(version)"
          @click="benchmark.form.value.target_version_id = version.version_id"
        >
          <b>{{ version.short || version.version_id }}</b>
          <span>{{ version.is_baseline ? '基线' : versionStageLabel(version) }}</span>
        </button>
      </div>
      <p v-if="selectedTargetBlockedReason" class="target-warning" role="status">
        {{ selectedTargetBlockedReason }}
      </p>
      <p v-else-if="!roleVersionRows.length" class="target-warning neutral" role="status">
        暂无可列出的版本，启动时将使用当前基线。
      </p>
    </section>
  </article>
</template>

<style scoped>
.benchmark-target-selector {
  --target-bg: var(--bench-bg-texture, var(--logbook-bg-texture, #f2dfae));
  --target-surface: var(--bench-surface, var(--logbook-surface, rgba(255, 252, 245, 0.7)));
  --target-border: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.15)));
  --target-text: var(--bench-text, var(--logbook-text, #3a2a18));
  --target-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --target-accent: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --target-soft: var(--bench-hover, var(--logbook-hover, rgba(139, 94, 52, 0.06)));
  --target-soft-strong: var(--bench-active-bg, var(--logbook-active-bg, rgba(139, 94, 52, 0.1)));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  border: 1px solid var(--target-border);
  border-radius: 8px;
  background: var(--target-bg);
  overflow: hidden;
}

.benchmark-target-selector header {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  min-height: 52px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--target-border);
  background: var(--target-surface);
}

.benchmark-target-selector h2,
.benchmark-target-selector small {
  margin: 0;
}

.benchmark-target-selector small,
.target-fields label span {
  color: var(--target-muted);
  font-size: 11px;
  font-weight: 800;
}

.benchmark-target-selector h2 {
  margin-top: 2px;
  color: var(--target-text);
  font-size: 15px;
  font-weight: 900;
}

.target-fields {
  display: grid;
  gap: 10px;
  padding: 12px;
}

.target-fields--model {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.target-fields label {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.target-fields input {
  box-sizing: border-box;
  width: 100%;
  height: 34px;
  min-width: 0;
  padding: 0 10px;
  border: 1px solid var(--target-border);
  border-radius: 6px;
  background: var(--target-surface);
  color: var(--target-text);
  font-size: 13px;
  font-weight: 800;
}

.target-fields select {
  box-sizing: border-box;
  width: 100%;
  height: 34px;
  min-width: 0;
  padding: 0 10px;
  border: 1px solid var(--target-border);
  border-radius: 6px;
  background: var(--target-surface);
  color: var(--target-text);
  font-size: 13px;
  font-weight: 800;
}

.target-fields input:focus,
.target-fields select:focus {
  border-color: var(--target-accent);
  outline: none;
  box-shadow: 0 0 0 2px rgba(139, 94, 52, 0.12);
}

.target-fields select[aria-invalid='true'] {
  border-color: var(--target-accent);
  box-shadow: 0 0 0 2px rgba(90, 51, 25, 0.12);
}

.role-target-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.role-target-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--target-border);
  border-radius: 6px;
  background: var(--target-surface);
  color: var(--target-text);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.role-target-chip:hover {
  border-color: var(--target-accent);
}

.role-target-chip.selected {
  border-color: var(--target-accent);
  background: var(--target-soft-strong);
  box-shadow: inset 0 0 0 1px var(--target-accent);
}

.role-target-chip img {
  width: 18px;
  height: 18px;
  border-radius: 50%;
}

.target-version-field {
  grid-column: 1 / -1;
}

.target-version-list {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.target-version-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--target-border);
  border-radius: 6px;
  background: var(--target-surface);
  color: var(--target-text);
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
}

.target-version-chip b,
.target-version-chip span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-version-chip b {
  max-width: 94px;
}

.target-version-chip span {
  color: var(--target-muted);
}

.target-version-chip.baseline,
.target-version-chip.selected {
  border-color: var(--target-accent);
  background: var(--target-soft-strong);
}

.target-version-chip.canary {
  border-color: rgba(90, 51, 25, 0.32);
  background: rgba(255, 252, 245, 0.7);
}

.target-version-chip.shadow,
.target-version-chip.disabled {
  border-color: rgba(139, 94, 52, 0.15);
  background: rgba(139, 94, 52, 0.08);
  color: rgba(58, 42, 24, 0.54);
  cursor: not-allowed;
}

.target-warning {
  grid-column: 1 / -1;
  margin: 0;
  padding: 7px 9px;
  border: 1px solid rgba(90, 51, 25, 0.24);
  border-radius: 6px;
  background: rgba(90, 51, 25, 0.08);
  color: var(--target-accent);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.target-warning.neutral {
  border-color: var(--target-border);
  background: var(--target-soft);
  color: var(--target-muted);
}
</style>

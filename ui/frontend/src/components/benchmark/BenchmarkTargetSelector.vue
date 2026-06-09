<script setup>
import { computed } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const roleRows = computed(() => props.benchmark.roleRows.value || [])
const roleVersionRows = computed(() => props.benchmark.roleTargetVersionRows.value || [])
const isModel = computed(() => props.benchmark.selectedBenchmarkIsModelSuite.value)
const selectedRoleLabel = computed(() => props.benchmark.selectedRoleLabel.value)
const selectedTargetVersion = computed(() => props.benchmark.selectedRoleTargetVersion.value || null)
const selectedTargetBlockedReason = computed(() => props.benchmark.selectedRoleTargetVersionBlockedReason.value || '')
const targetModeLabel = computed(() => isModel.value ? 'Model Benchmark' : 'Role-Version Benchmark')
const subjectLabel = computed(() => {
  if (isModel.value) return props.benchmark.form.value.model_id || '当前后端模型'
  if (!props.benchmark.form.value.target_version_id) return '当前基线版本'
  return selectedTargetVersion.value?.short || props.benchmark.form.value.target_version_id
})

function versionStageClass(version) {
  return String(version?.release_stage || version?.releaseStage || 'unknown').trim().toLowerCase() || 'unknown'
}

function versionStageLabel(version) {
  return version?.releaseStageLabel || version?.release_stage || version?.releaseStage || '未标记'
}

function versionOptionText(version) {
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
  <article class="benchmark-target-selector" aria-label="Benchmark target selector">
    <header>
      <div>
        <small>Target</small>
        <h2>{{ targetModeLabel }}</h2>
      </div>
      <b>{{ subjectLabel }}</b>
    </header>

    <section v-if="isModel" class="target-fields target-fields--model">
      <label>
        <span>Model ID</span>
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
      <p class="target-note">
        Model benchmark 比较的是 model/runtime config，启动 payload 不携带 roles 或 target_versions。
      </p>
    </section>

    <section v-else class="target-fields target-fields--role">
      <div class="role-target-list" aria-label="Role selector">
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
        <span>Target Version</span>
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
      <div v-if="roleVersionRows.length" class="target-version-list" aria-label="Version release stages">
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
          <span>{{ version.is_baseline ? 'baseline' : versionStageLabel(version) }}</span>
        </button>
      </div>
      <p v-if="selectedTargetBlockedReason" class="target-warning" role="status">
        {{ selectedTargetBlockedReason }}
      </p>
      <p v-else-if="!roleVersionRows.length" class="target-warning neutral" role="status">
        暂无可列出的版本，启动时将使用当前基线。
      </p>
      <p class="target-note">
        Role-version benchmark 只比较当前角色的目标版本；baseline 与 canary 可评测，shadow 需先晋升 canary。
      </p>
    </section>
  </article>
</template>

<style scoped>
.benchmark-target-selector {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: var(--bench-surface);
  overflow: hidden;
}

.benchmark-target-selector header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--bench-border);
  background: #ffffff;
}

.benchmark-target-selector h2,
.benchmark-target-selector small {
  margin: 0;
}

.benchmark-target-selector small,
.target-fields label span,
.target-note {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
}

.benchmark-target-selector h2 {
  margin-top: 2px;
  color: var(--bench-text);
  font-size: 15px;
  font-weight: 900;
}

.benchmark-target-selector header b {
  max-width: 220px;
  overflow: hidden;
  padding: 3px 8px;
  border: 1px solid var(--bench-border);
  border-radius: 6px;
  background: #f7f8f8;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: var(--bench-input-bg);
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.target-fields select {
  box-sizing: border-box;
  width: 100%;
  height: 34px;
  min-width: 0;
  padding: 0 10px;
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: var(--bench-input-bg);
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.target-fields input:focus,
.target-fields select:focus {
  border-color: #1f6f54;
  outline: none;
  box-shadow: 0 0 0 2px rgba(31, 111, 84, 0.12);
}

.target-fields select[aria-invalid='true'] {
  border-color: var(--bench-danger);
  box-shadow: 0 0 0 2px rgba(161, 61, 54, 0.12);
}

.target-note {
  grid-column: 1 / -1;
  margin: 0;
  line-height: 1.45;
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
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: #ffffff;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.role-target-chip:hover {
  border-color: #1f6f54;
}

.role-target-chip.selected {
  border-color: #1f6f54;
  background: #e6f2ee;
  box-shadow: inset 0 0 0 1px #1f6f54;
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
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: #ffffff;
  color: var(--bench-text);
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
  color: var(--bench-text-secondary);
}

.target-version-chip.baseline,
.target-version-chip.selected {
  border-color: #1f6f54;
  background: #e6f2ee;
}

.target-version-chip.canary {
  border-color: rgba(37, 107, 143, 0.34);
  background: rgba(226, 240, 248, 0.92);
}

.target-version-chip.shadow,
.target-version-chip.disabled {
  border-color: rgba(102, 115, 109, 0.22);
  background: #f2f5f3;
  color: rgba(31, 42, 39, 0.54);
  cursor: not-allowed;
}

.target-warning {
  grid-column: 1 / -1;
  margin: 0;
  padding: 7px 9px;
  border: 1px solid rgba(161, 61, 54, 0.18);
  border-radius: 6px;
  background: rgba(161, 61, 54, 0.08);
  color: var(--bench-danger);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.target-warning.neutral {
  border-color: rgba(102, 115, 109, 0.18);
  background: rgba(102, 115, 109, 0.08);
  color: var(--bench-text-secondary);
}
</style>

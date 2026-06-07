<script setup>
import { computed } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const rows = computed(() => props.benchmark.filteredBatchRunRows.value)
const visibleRows = computed(() => props.benchmark.visibleBatchRunRows.value)
const statusCounts = computed(() => {
  const counts = { queued: 0, running: 0, completed: 0, failed: 0, other: 0 }
  for (const run of rows.value) {
    if (run.status === 'queued') counts.queued += 1
    else if (run.status === 'running') counts.running += 1
    else if (run.status === 'completed') counts.completed += 1
    else if (run.status === 'failed') counts.failed += 1
    else counts.other += 1
  }
  return counts
})
const activeCount = computed(() => statusCounts.value.queued + statusCounts.value.running)
const roleGroups = computed(() => {
  const groups = new Map()
  for (const run of rows.value) {
    const key = props.benchmark.selectedRoleLabel.value || '未知角色'
    groups.set(key, (groups.get(key) || 0) + 1)
  }
  return [...groups.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
})
const recentRows = computed(() => visibleRows.value.slice(0, 6))
const statusRows = computed(() => [
  { label: '排队', count: statusCounts.value.queued },
  { label: '运行', count: statusCounts.value.running },
  { label: '完成', count: statusCounts.value.completed },
  { label: '失败', count: statusCounts.value.failed },
  { label: '其他', count: statusCounts.value.other }
].map((item) => ({
  ...item,
  width: rows.value.length ? Math.max(8, Math.round((item.count / rows.value.length) * 100)) : 0
})))

function runLabel(index) {
  return `批次${index + 1}`
}
</script>

<template>
  <div class="bench-tab-panel">
    <section v-if="rows.length" class="bench-run-stats">
      <span>
        <small>总数</small>
        <b>{{ rows.length }}</b>
        <em>评测批次</em>
      </span>
      <span>
        <small>运行中</small>
        <b>{{ activeCount }}</b>
        <em>运行 / 排队</em>
      </span>
      <span>
        <small>已完成</small>
        <b>{{ statusCounts.completed }}</b>
        <em>已完成</em>
      </span>
      <span>
        <small>失败</small>
        <b>{{ statusCounts.failed }}</b>
        <em>失败</em>
      </span>
    </section>
    <section v-else class="bench-run-empty">
      <strong>暂无评测批次</strong>
      <span>从配置页启动评测后，这里会显示批次状态和停止操作。</span>
    </section>

    <div class="bench-runs-layout">
    <div class="bench-runs-main">
      <article class="bench-card">
        <header>
          <div>
            <small>评测批次</small>
            <h2>评测记录</h2>
          </div>
          <b>{{ rows.length }}</b>
        </header>
        <div v-if="!rows.length" class="bench-empty">暂无评测记录</div>
        <div v-else class="bench-table">
          <div class="bench-row bench-header">
            <span>批次</span>
            <span>角色</span>
            <span>状态</span>
            <span>操作</span>
          </div>
          <div
            v-for="(run, index) in visibleRows"
            :key="run.id"
            :class="['bench-row', { 'bench-row-running': ['queued', 'running'].includes(run.status) }]"
          >
            <span class="bench-id">{{ runLabel(index) }}</span>
            <span>{{ benchmark.selectedRoleLabel.value }}</span>
            <span>{{ run.statusLabel }}</span>
            <span>
              <button
                v-if="['queued', 'running'].includes(run.status)"
                type="button"
                class="bench-action small"
                :disabled="Boolean(benchmark.actionLoading.value)"
                @click="benchmark.stopBatch(run.id)"
              >
                停止
              </button>
            </span>
          </div>
        </div>
      </article>

      <article v-if="recentRows.length" class="bench-card bench-run-ledger">
        <header>
          <div>
            <small>最近批次</small>
            <h2>最近批次</h2>
          </div>
          <b>{{ recentRows.length }}</b>
        </header>
        <div class="bench-run-ledger-list">
          <div v-for="(run, index) in recentRows" :key="'ledger-' + run.id" class="bench-run-ledger-row">
            <strong>{{ runLabel(index) }}</strong>
            <span>{{ benchmark.selectedRoleLabel.value }}</span>
            <em>{{ run.statusLabel }}</em>
          </div>
        </div>
      </article>
    </div>

    <aside class="bench-card bench-runs-side">
      <header>
        <div>
          <small>记录分布</small>
          <h2>状态概览</h2>
        </div>
        <b>{{ rows.length }} 批</b>
      </header>
      <div v-if="!rows.length" class="bench-empty bench-empty--side">暂无评测记录</div>
      <template v-else>
        <div class="bench-status-grid">
          <span><small>排队</small><b>{{ statusCounts.queued }}</b></span>
          <span><small>运行</small><b>{{ statusCounts.running }}</b></span>
          <span><small>完成</small><b>{{ statusCounts.completed }}</b></span>
          <span><small>其他</small><b>{{ statusCounts.other }}</b></span>
        </div>
        <div class="bench-role-run-list">
          <div class="bench-side-title">
            <span>角色覆盖</span>
            <small>{{ roleGroups.length }} 组</small>
          </div>
          <div class="bench-run-role-rows">
            <div v-for="item in roleGroups" :key="item.label" class="bench-run-role-row">
              <span>{{ item.label }}</span>
              <i aria-hidden="true"><b :style="{ width: Math.max(8, Math.round(item.count / Math.max(1, rows.length) * 100)) + '%' }"></b></i>
              <em>{{ item.count }}</em>
            </div>
          </div>
        </div>
        <div class="bench-role-run-list">
          <div class="bench-side-title">
            <span>状态占比</span>
            <small>{{ rows.length }} 批</small>
          </div>
          <div class="bench-run-role-rows">
            <div v-for="item in statusRows" :key="item.label" class="bench-run-role-row">
              <span>{{ item.label }}</span>
              <i aria-hidden="true"><b :style="{ width: item.width + '%' }"></b></i>
              <em>{{ item.count }}</em>
            </div>
          </div>
        </div>
      </template>
    </aside>
    </div>
  </div>
</template>

<style scoped>
.bench-tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.bench-run-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.bench-run-stats span {
  display: grid;
  gap: 5px;
  min-height: 70px;
  padding: 10px 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: var(--bench-surface);
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
}

.bench-run-stats small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.bench-run-stats b {
  color: var(--bench-text);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
}

.bench-run-stats em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.bench-runs-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
  gap: 14px;
  align-items: start;
}

.bench-runs-main {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.bench-run-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.48);
}

.bench-run-empty strong {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}

.bench-run-empty span {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-card {
  display: grid;
  grid-template-rows: auto auto;
  background: var(--bench-surface);
  border: 1px solid var(--bench-border);
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
  overflow: hidden;
}

.bench-card header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--bench-border);
  background: rgba(255, 252, 245, 0.42);
}

.bench-card header div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.bench-card header small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1;
}

.bench-card header h2 {
  margin: 0;
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
}

.bench-card header b {
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--bench-accent);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.bench-empty {
  padding: 32px 20px;
  color: var(--bench-text-secondary);
  font-size: 14px;
  font-weight: 600;
  text-align: center;
}

.bench-empty.compact {
  padding: 18px 12px;
  border-top: 1px solid var(--bench-border);
}

.bench-empty--side {
  padding: 24px 16px;
  color: var(--bench-text-secondary);
  font-size: 13px;
  font-weight: 800;
}

.bench-table {
  display: flex;
  flex-direction: column;
  padding: 6px 8px 8px;
  overflow-x: auto;
  min-height: 0;
}

.bench-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.9fr) minmax(180px, 1.2fr) minmax(84px, 0.55fr) minmax(86px, 0.45fr);
  gap: 10px;
  align-items: center;
  min-width: 660px;
  padding: 9px 10px;
  border-radius: 6px;
  border-bottom: 1px solid rgba(139, 94, 52, 0.08);
  color: var(--bench-text);
  font-size: 13px;
  transition: background 0.15s ease;
}

.bench-row:last-child {
  border-bottom: none;
}

.bench-row:not(.bench-header):hover {
  background: var(--bench-hover);
}

.bench-row-running {
  background: rgba(255, 226, 157, 0.22);
}

.bench-row.bench-header {
  min-height: 30px;
  border-bottom-color: var(--bench-border);
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.bench-row span {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-id {
  overflow: hidden;
  color: var(--bench-text-secondary) !important;
  font-size: 12px !important;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 18px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-radius: 6px;
  background: var(--bench-accent-strong);
  color: #fff7dc;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.16s ease, transform 0.16s ease;
  box-shadow: 0 2px 6px rgba(91, 47, 18, 0.15);
}

.bench-action:hover {
  background: var(--bench-accent);
  transform: translateY(-1px);
}

.bench-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  box-shadow: none;
}

.bench-action.small {
  height: 28px;
  padding: 0 12px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 700;
}

.bench-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
}

.bench-status-grid span {
  display: grid;
  gap: 4px;
  min-height: 54px;
  padding: 9px 10px;
  border: 1px solid rgba(139, 94, 52, 0.11);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-status-grid small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.bench-status-grid b {
  color: var(--bench-text);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
}

.bench-role-run-list {
  display: grid;
  gap: 8px;
  padding: 0 12px 12px;
}

.bench-side-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--bench-border);
}

.bench-side-title span {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.bench-side-title small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.bench-run-role-rows {
  display: grid;
  gap: 7px;
}

.bench-run-role-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px 24px;
  align-items: center;
  gap: 8px;
  min-height: 30px;
}

.bench-run-role-row span {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-run-role-row i {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.12);
}

.bench-run-role-row i b {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--bench-accent-strong);
}

.bench-run-role-row em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  text-align: right;
}

.bench-runs-side {
  grid-template-rows: auto auto auto auto;
  align-content: start;
}

.bench-run-ledger {
  grid-template-rows: auto auto;
}

.bench-run-ledger-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 7px 14px;
  align-content: start;
  padding: 12px;
}

.bench-run-ledger-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(72px, 0.6fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid rgba(139, 94, 52, 0.11);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-run-ledger-row strong,
.bench-run-ledger-row span,
.bench-run-ledger-row em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-run-ledger-row strong {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-run-ledger-row span {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-run-ledger-row em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  text-align: right;
}

@media (max-width: 960px) {
  .bench-tab-panel {
    flex: initial;
    min-height: 0;
  }

  .bench-runs-layout {
    grid-template-columns: 1fr;
    align-items: start;
    flex: initial;
    min-height: 0;
  }

  .bench-runs-main {
    grid-template-rows: auto auto;
    min-height: 0;
  }

  .bench-card {
    grid-template-rows: auto auto;
  }

  .bench-runs-side {
    grid-template-rows: auto auto auto auto;
    align-content: start;
  }
}

@media (max-width: 640px) {
  .bench-run-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bench-run-stats span {
    min-height: 60px;
    padding: 8px 10px;
  }

  .bench-card header {
    grid-template-columns: minmax(0, 1fr);
  }

  .bench-card header b {
    justify-self: start;
  }
}
</style>

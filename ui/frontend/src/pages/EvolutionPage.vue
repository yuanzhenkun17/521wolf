<script setup>
import { computed, onMounted, ref, reactive } from 'vue'
import { useEvolutionWorkbench } from '../composables/useEvolutionWorkbench.js'

defineOptions({
  inheritAttrs: false
})

defineProps({
  returnToMatchAvailable: Boolean
})

const emit = defineEmits(['back-to-match'])

const evo = useEvolutionWorkbench()

const selectedIsBatch = computed(() => evo.selectedRun.value?.entityType === 'batch')
const selectedCanReview = computed(() => evo.selectedRun.value?.status === 'reviewing')
const selectedCanResume = computed(() => ['paused', 'failed'].includes(evo.selectedRun.value?.status))
const selectedCanStop = computed(() => evo.selectedRun.value?.isActive)
const selectedCanTerminate = computed(() => {
  const status = evo.selectedRun.value?.status
  return Boolean(evo.selectedRun.value) && !['promoted', 'rejected', 'failed', 'completed'].includes(status)
})

function scoreLabel(value) {
  const n = Number(value || 0)
  return `${Math.round(n * 100)}%`
}

function deltaLabel(value) {
  const n = Number(value || 0)
  if (!n) return '0'
  return `${n > 0 ? '+' : ''}${Math.round(n * 100)}%`
}

function diffLabel(diff) {
  const file = diff?.filename || diff?.file || 'skill.md'
  const action = diff?.action || diff?.action_type || 'change'
  return `${file} · ${action}`
}

function primaryMetric(run) {
  if (!run) return '—'
  const result = run.combined_battle_result || run.battle_result
  if (result?.skipped) return '跳过'
  const candidate = result?.candidate || {}
  const baseline = result?.baseline || {}
  const c = candidate.avg_role_weighted_score
  const b = baseline.avg_role_weighted_score
  if (c == null || b == null) return '—'
  return `${scoreLabel(c)} / ${scoreLabel(b)}`
}

function sampleTitle(game) {
  if (!game) return '—'
  return `${game.short} · ${game.winnerLabel}`
}

function decisionText(decision) {
  return decision?.public_summary || decision?.reason || decision?.private_reasoning || decision?.action || '—'
}

function eventText(event) {
  return event?.message || event?.public_summary || event?.event_type || event?.type || '—'
}

function versionMetric(value) {
  if (value == null) return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n <= 1 ? `${Math.round(n * 100)}%` : String(Math.round(n * 100) / 100)
}

function versionSkillLabel(skill) {
  if (!skill) return 'skill'
  const path = skill.path || skill.filename || 'skill.md'
  const hash = skill.content_hash || skill.hash || ''
  return hash ? `${path} · ${String(hash).slice(0, 8)}` : path
}

function patternText(pattern) {
  if (!pattern) return '—'
  return pattern.summary || pattern.pattern || pattern.name || pattern.situation || pattern.pattern_id || JSON.stringify(pattern).slice(0, 120)
}

function valueLabel(value, fallback = '—') {
  return value == null || value === '' ? fallback : value
}

// ── Pattern Browser State ──
const patternRoleFilter = ref('')
const patternStatusFilter = ref('')
const expandedPatterns = reactive(new Set())

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

const ROLE_LABELS = {
  werewolf: '狼人',
  villager: '村民',
  seer: '预言家',
  witch: '女巫',
  hunter: '猎人',
  guard: '守卫',
  white_wolf_king: '白狼王'
}

const versionPatterns = computed(() => {
  const data = evo.selectedVersionDetail.value?.data
  if (!data?.patterns?.length) return []
  return data.patterns.map(p => ({
    pattern_id: p.pattern_id || p.id || p.pattern || 'unknown',
    role: p.role || data.role || '',
    situation: p.situation || p.pattern || p.name || '—',
    recommendation: p.recommendation || p.summary || p.description || p.pattern || '—',
    win_rate_with: Number(p.win_rate_with ?? p.winRateWith ?? 0),
    win_rate_without: Number(p.win_rate_without ?? p.winRateWithout ?? 0),
    sample_size: Number(p.sample_size ?? p.sampleSize ?? p.games ?? 0),
    confidence: Number(p.confidence ?? p.conf ?? 0),
    status: p.status || 'candidate',
    source_games: p.source_games || p.sourceGames || []
  }))
})

const patternRoles = computed(() => {
  const roles = new Set(versionPatterns.value.map(p => p.role).filter(Boolean))
  return [...roles].sort()
})

const patternStatuses = computed(() => {
  const statuses = new Set(versionPatterns.value.map(p => p.status).filter(Boolean))
  return [...statuses].sort()
})

const filteredPatterns = computed(() => {
  let list = versionPatterns.value
  if (patternRoleFilter.value) {
    list = list.filter(p => p.role === patternRoleFilter.value)
  }
  if (patternStatusFilter.value) {
    list = list.filter(p => p.status === patternStatusFilter.value)
  }
  return list
})

function patternStatusColor(status) {
  return PATTERN_STATUS_COLORS[status] || '#666'
}

function patternStatusLabel(status) {
  return PATTERN_STATUS_LABELS[status] || status || '未知'
}

function patternRoleLabel(role) {
  return ROLE_LABELS[role] || role || '—'
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

// ── Diff Viewer State & Helpers ──

const normalizedDiff = computed(() => {
  const raw = evo.selectedDiffData.value
  if (raw) return raw
  // Fallback: try to build structured data from legacy selectedDiff array
  const legacy = evo.selectedDiff.value
  if (!Array.isArray(legacy) || !legacy.length) return null
  return {
    skill_changes: legacy.map(d => ({
      file: d.filename || d.file || 'skill.md',
      action: d.action || d.action_type || 'modified'
    })),
    patterns_added: [],
    patterns_removed: [],
    patterns_updated: [],
    metrics_delta: null
  }
})

function diffActionLabel(action) {
  return { created: '新建', modified: '修改', deleted: '删除', renamed: '重命名' }[action] || action || '变更'
}

function diffActionColor(action) {
  return { created: '#2e7d32', modified: '#f9a825', deleted: '#c62828', renamed: '#4a9eff' }[action] || '#666'
}

function computeLineDiff(before, after) {
  const bLines = (before || '').split('\n')
  const aLines = (after || '').split('\n')
  const result = []
  // Simple LCS-based line diff for basic unified view
  const bSet = new Map()
  bLines.forEach((line, i) => {
    if (!bSet.has(line)) bSet.set(line, [])
    bSet.get(line).push(i)
  })
  const matched = new Set()
  const aMatched = new Set()
  for (let i = 0; i < aLines.length; i++) {
    const indices = bSet.get(aLines[i])
    if (indices) {
      for (const j of indices) {
        if (!matched.has(j)) {
          matched.add(j)
          aMatched.add(i)
          break
        }
      }
    }
  }
  // Output removed lines from before
  bLines.forEach((line, i) => {
    if (!matched.has(i)) result.push({ type: 'removed', text: line })
  })
  // Output context + added lines from after
  aLines.forEach((line, i) => {
    if (aMatched.has(i)) {
      result.push({ type: 'context', text: line })
    } else {
      result.push({ type: 'added', text: line })
    }
  })
  return result
}

function metricsDeltaEntries(delta) {
  if (!delta) return []
  const labelMap = { win_rate: '胜率', score: '得分', speech_score: '发言', vote_score: '投票', skill_score: '技能' }
  return Object.entries(delta)
    .filter(([, v]) => v != null)
    .map(([k, v]) => ({
      key: k,
      label: labelMap[k] || k,
      value: Number(v) || 0,
      isPositive: Number(v) >= 0
    }))
}

onMounted(() => evo.refreshAll())
</script>

<template>
  <section class="evolution-page" aria-label="自进化">
    <button v-if="returnToMatchAvailable" class="return-match-button" @click="emit('back-to-match')">
      <span>返回对局</span>
      <i aria-hidden="true">▶</i>
    </button>

    <section class="evolution-shell parchment-logbook">
      <aside class="evolution-baseline">
        <header>
          <span>Baseline 角色</span>
          <strong>{{ evo.roleRows.value.length }}</strong>
        </header>

        <div class="evolution-baseline-list">
          <button
            v-for="role in evo.roleRows.value"
            :key="role.key"
            type="button"
            :class="['evolution-baseline-row', { selected: evo.selectedRole.value === role.key }]"
            @click="evo.selectRole(role.key)"
          >
            <span class="evolution-checkbox" :class="{ checked: role.selected }" @click.stop="evo.toggleBatchRole(role.key)">
              <span v-if="role.selected">✓</span>
            </span>
            <span class="role-info">
              <img :src="role.image" :alt="role.label" />
              <span>{{ role.label }}</span>
            </span>
            <span class="version-badge">{{ role.baselineShort }}</span>
          </button>
        </div>

        <footer class="evolution-baseline-footer">
          <button type="button" class="evolution-ghost-action" @click="evo.refreshAll()">
            刷新
          </button>
          <span>{{ evo.selectedBatchRoles.value.length }} 个批量角色</span>
        </footer>
      </aside>

      <div class="evolution-panels">
        <article class="evolution-card evolution-command">
          <header>
            <h2>进化控制台</h2>
            <b>{{ evo.selectedRoleLabel.value }}</b>
          </header>

          <div v-if="evo.error.value" class="evolution-alert">{{ evo.error.value }}</div>

          <div class="evolution-form-grid">
            <label>训练局数<input v-model.number="evo.form.value.training_games" inputmode="numeric" /></label>
            <label>对战局数<input v-model.number="evo.form.value.battle_games" inputmode="numeric" /></label>
            <label>角色并发<input v-model.number="evo.form.value.role_concurrency" inputmode="numeric" /></label>
            <label>局并发<input v-model.number="evo.form.value.game_concurrency" inputmode="numeric" /></label>
            <label>LLM并发<input v-model.number="evo.form.value.llm_concurrency" inputmode="numeric" /></label>
            <label>LLM RPM<input v-model.number="evo.form.value.llm_rpm" inputmode="numeric" /></label>
          </div>

          <div class="evolution-command-row">
            <button
              type="button"
              class="evolution-action"
              :disabled="Boolean(evo.actionLoading.value) || !evo.selectedRole.value"
              @click="evo.startSingle()"
            >
              <span aria-hidden="true">▶</span> 单角色
            </button>
            <button
              type="button"
              class="evolution-action"
              :disabled="Boolean(evo.actionLoading.value) || !evo.selectedBatchRoles.value.length"
              @click="evo.startBatch()"
            >
              <span aria-hidden="true">▶</span> 批量
            </button>
            <span class="evolution-loading" v-if="evo.loading.value || evo.actionLoading.value">
              {{ evo.actionLoading.value || 'loading' }}
            </span>
          </div>
        </article>

        <section class="evolution-grid">
          <article class="evolution-card evolution-run-list">
            <header>
              <h2>运行队列</h2>
              <b>{{ evo.runRows.value.length }}</b>
            </header>

            <div class="evolution-run-tools">
              <input v-model="evo.runFilter.value" type="search" placeholder="筛选 run / 角色 / 状态" />
              <span>{{ evo.visibleRunRows.value.length }} / {{ evo.filteredRunRows.value.length }}</span>
            </div>

            <div v-if="!evo.filteredRunRows.value.length" class="evolution-empty">暂无运行记录</div>
            <div v-else class="evolution-run-scroll">
              <button
                v-for="run in evo.visibleRunRows.value"
                :key="run.id"
                type="button"
                :class="['evolution-run-row', { selected: evo.selectedRunId.value === run.id }]"
                @click="evo.selectRun(run.id)"
              >
                <span class="run-status" :data-status="run.status">{{ run.statusLabel }}</span>
                <span class="run-main">
                  <strong>{{ run.displayRole }}</strong>
                  <small>{{ run.id }}</small>
                </span>
                <span class="run-metric">{{ primaryMetric(run) }}</span>
              </button>
              <div v-if="evo.filteredRunRows.value.length > evo.visibleRunRows.value.length" class="evolution-run-more">
                继续筛选可查看其余 {{ evo.filteredRunRows.value.length - evo.visibleRunRows.value.length }} 条
              </div>
            </div>
          </article>

          <article class="evolution-card evolution-review">
            <header>
              <h2>评审面板</h2>
              <b>{{ evo.selectedRun.value?.statusLabel || '—' }}</b>
            </header>

            <div v-if="!evo.hasSelection.value" class="evolution-empty">选择一个运行</div>
            <div v-else class="evolution-review-body">
              <div class="evolution-kpis">
                <span><small>Parent</small><b>{{ evo.selectedRun.value.parentShort }}</b></span>
                <span><small>Candidate</small><b>{{ evo.selectedRun.value.candidateShort }}</b></span>
                <span><small>训练</small><b>{{ evo.selectedRun.value.training_completed || 0 }} / {{ evo.selectedRun.value.training_games || 0 }}</b></span>
                <span><small>对战</small><b>{{ evo.selectedRun.value.battle_completed || 0 }} / {{ evo.selectedRun.value.battle_games || 0 }}</b></span>
              </div>

              <div class="evolution-config-grid">
                <span><small>类型</small><b>{{ selectedIsBatch ? '批量' : '单角色' }}</b></span>
                <span><small>角色并发</small><b>{{ valueLabel(evo.selectedRun.value.role_concurrency, selectedIsBatch ? 2 : '—') }}</b></span>
                <span><small>局并发</small><b>{{ evo.selectedRun.value.game_concurrency || 1 }}</b></span>
                <span><small>LLM并发</small><b>{{ evo.selectedRun.value.llm_concurrency || 5 }}</b></span>
                <span><small>LLM RPM</small><b>{{ evo.selectedRun.value.llm_rpm || 60 }}</b></span>
                <span><small>阶段</small><b>{{ evo.selectedRun.value.current_stage || evo.selectedRun.value.stage || evo.selectedRun.value.status }}</b></span>
              </div>

              <div class="evolution-review-actions">
                <button
                  type="button"
                  class="evolution-action"
                  :disabled="!selectedCanReview || Boolean(evo.actionLoading.value)"
                  @click="evo.runAction(evo.selectedRunId.value, 'promote')"
                >
                  <span aria-hidden="true">↑</span> 晋升
                </button>
                <button
                  type="button"
                  class="evolution-action danger"
                  :disabled="!selectedCanReview || Boolean(evo.actionLoading.value)"
                  @click="evo.runAction(evo.selectedRunId.value, 'reject')"
                >
                  <span aria-hidden="true">×</span> 拒绝
                </button>
                <button
                  type="button"
                  class="evolution-ghost-action"
                  :disabled="!selectedCanResume || selectedIsBatch || Boolean(evo.actionLoading.value)"
                  @click="evo.runAction(evo.selectedRunId.value, 'resume')"
                >
                  继续
                </button>
                <button
                  type="button"
                  class="evolution-ghost-action"
                  :disabled="!selectedCanStop || Boolean(evo.actionLoading.value)"
                  @click="evo.runAction(evo.selectedRunId.value, 'stop')"
                >
                  暂停
                </button>
                <button
                  type="button"
                  class="evolution-ghost-action danger"
                  :disabled="!selectedCanTerminate || Boolean(evo.actionLoading.value)"
                  @click="evo.runAction(evo.selectedRunId.value, 'terminate')"
                >
                  终止
                </button>
              </div>

              <div class="evolution-mini-columns">
                <div>
                  <h3>样本局</h3>
                  <p>训练 {{ evo.selectedGames.value.training.length }} · 基线 {{ evo.selectedGames.value.baseline.length }} · 候选 {{ evo.selectedGames.value.candidate.length }}</p>
                </div>
              </div>

              <!-- ── Version Diff Viewer ── -->
              <div v-if="normalizedDiff" class="evo-diff-viewer">
                <!-- Metrics Delta Strip -->
                <div v-if="normalizedDiff.metrics_delta && metricsDeltaEntries(normalizedDiff.metrics_delta).length" class="evo-diff-metrics-strip">
                  <h3>指标变化</h3>
                  <div class="evo-diff-metrics-row">
                    <span
                      v-for="entry in metricsDeltaEntries(normalizedDiff.metrics_delta)"
                      :key="entry.key"
                      :class="['evo-diff-metric-kpi', entry.isPositive ? 'positive' : 'negative']"
                    >
                      <small>{{ entry.label }}</small>
                      <b>
                        <span class="evo-diff-arrow">{{ entry.isPositive ? '▲' : '▼' }}</span>
                        {{ deltaLabel(entry.value) }}
                      </b>
                    </span>
                  </div>
                </div>

                <!-- Skill Changes -->
                <div v-if="normalizedDiff.skill_changes?.length" class="evo-diff-section">
                  <h3>技能文件变更</h3>
                  <div v-for="(sc, scIdx) in normalizedDiff.skill_changes" :key="scIdx" class="evo-diff-file-block">
                    <div class="evo-diff-file-header">
                      <span class="evo-diff-filename">{{ sc.file || sc.filename || 'skill.md' }}</span>
                      <span class="evo-diff-action-badge" :style="{ background: diffActionColor(sc.action || sc.action_type) }">
                        {{ diffActionLabel(sc.action || sc.action_type) }}
                      </span>
                    </div>
                    <div
                      v-if="sc.before || sc.after || sc.before_lines || sc.after_lines"
                      class="evo-diff-code-block"
                    >
                      <div
                        v-for="(line, lineIdx) in computeLineDiff(sc.before || sc.before_lines, sc.after || sc.after_lines)"
                        :key="lineIdx"
                        :class="['evo-diff-line', `evo-diff-line-${line.type}`]"
                      >
                        <span class="evo-diff-line-marker">
                          {{ line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' ' }}
                        </span>
                        <span class="evo-diff-line-text">{{ line.text }}</span>
                      </div>
                    </div>
                    <p v-else class="evo-diff-no-content">仅记录变更类型，无详细内容</p>
                  </div>
                </div>

                <!-- Pattern Changes -->
                <div
                  v-if="(normalizedDiff.patterns_added?.length) || (normalizedDiff.patterns_removed?.length) || (normalizedDiff.patterns_updated?.length)"
                  class="evo-diff-section"
                >
                  <h3>Pattern 变更</h3>
                  <!-- Added patterns -->
                  <div v-if="normalizedDiff.patterns_added?.length" class="evo-diff-pattern-group">
                    <small class="evo-diff-group-label added-label">新增</small>
                    <div v-for="(pat, pIdx) in normalizedDiff.patterns_added" :key="'add-' + pIdx" class="evo-diff-pattern-card added">
                      <strong>{{ pat.pattern_id || pat.id || 'new' }}</strong>
                      <span>{{ pat.recommendation || pat.summary || pat.situation || '—' }}</span>
                    </div>
                  </div>
                  <!-- Removed patterns -->
                  <div v-if="normalizedDiff.patterns_removed?.length" class="evo-diff-pattern-group">
                    <small class="evo-diff-group-label removed-label">移除</small>
                    <div v-for="(pat, pIdx) in normalizedDiff.patterns_removed" :key="'rm-' + pIdx" class="evo-diff-pattern-card removed">
                      <strong>{{ pat.pattern_id || pat.id || 'old' }}</strong>
                      <span>{{ pat.recommendation || pat.summary || pat.situation || '—' }}</span>
                    </div>
                  </div>
                  <!-- Updated patterns -->
                  <div v-if="normalizedDiff.patterns_updated?.length" class="evo-diff-pattern-group">
                    <small class="evo-diff-group-label updated-label">更新</small>
                    <div v-for="(pat, pIdx) in normalizedDiff.patterns_updated" :key="'upd-' + pIdx" class="evo-diff-pattern-card updated">
                      <strong>{{ pat.pattern_id || pat.id || 'pat' }}</strong>
                      <span v-if="pat.old_confidence != null || pat.new_confidence != null">
                        置信度: {{ pat.old_confidence != null ? Math.round(pat.old_confidence * 100) + '%' : '—' }} → {{ pat.new_confidence != null ? Math.round(pat.new_confidence * 100) + '%' : '—' }}
                      </span>
                      <span v-if="pat.old_win_rate != null || pat.new_win_rate != null">
                        胜率: {{ pat.old_win_rate != null ? Math.round(pat.old_win_rate * 100) + '%' : '—' }} → {{ pat.new_win_rate != null ? Math.round(pat.new_win_rate * 100) + '%' : '—' }}
                      </span>
                      <span v-if="pat.recommendation || pat.summary">{{ pat.recommendation || pat.summary }}</span>
                    </div>
                  </div>
                </div>

                <!-- Legacy fallback: show raw diff items if no structured data -->
                <div v-if="!normalizedDiff.skill_changes?.length && !normalizedDiff.patterns_added?.length && !normalizedDiff.patterns_removed?.length && !normalizedDiff.patterns_updated?.length && evo.selectedDiff.value.length" class="evo-diff-section">
                  <h3>Diff</h3>
                  <ul class="evo-diff-legacy-list">
                    <li v-for="(diff, idx) in evo.selectedDiff.value.slice(0, 8)" :key="idx">
                      {{ diffLabel(diff) }}
                    </li>
                  </ul>
                </div>
              </div>
              <div v-else class="evo-diff-empty">
                <h3>Diff</h3>
                <p>—</p>
              </div>
            </div>
          </article>
        </section>

        <section class="evolution-grid lower">
          <article class="evolution-card leaderboard">
            <header>
              <h2>角色排行榜</h2>
              <b>{{ evo.selectedRoleLabel.value }}</b>
            </header>
            <div v-if="!evo.selectedRoleLeaderboard.value.length" class="evolution-empty">暂无 battle 数据</div>
            <div v-else class="leaderboard-chart evolution-real-board">
              <div
                v-for="item in evo.selectedRoleLeaderboard.value"
                :key="item.hash"
                class="leaderboard-row"
              >
                <span class="leaderboard-label">
                  {{ item.short }}<small>{{ item.is_baseline ? 'base' : item.recommendation }}</small>
                </span>
                <div class="leaderboard-bar-wrap">
                  <div class="leaderboard-bar" :style="{ width: item.scorePct + '%', background: item.is_baseline ? '#7b5735' : '#0f6b72' }"></div>
                </div>
                <span class="leaderboard-value">{{ item.scorePct }}%</span>
              </div>
            </div>
          </article>

          <article class="evolution-card evolution-versions">
            <header>
              <h2>版本</h2>
              <b>{{ evo.selectedRoleVersions.value.length }}</b>
            </header>
            <div v-if="!evo.selectedRoleVersions.value.length" class="evolution-empty">暂无版本</div>
            <div v-else class="evolution-version-list">
              <div v-for="version in evo.selectedRoleVersions.value" :key="version.version_id" class="evolution-version-row">
                <span>
                  <strong>{{ version.short }}</strong>
                  <small>{{ version.source }} · {{ version.createdLabel }}</small>
                </span>
                <div class="evolution-version-actions">
                  <button
                    type="button"
                    class="evolution-ghost-action"
                    :disabled="evo.selectedVersionDetail.value.loading && evo.selectedVersionId.value === version.version_id"
                    @click="evo.loadVersionDetail(evo.selectedRole.value, version.version_id)"
                  >
                    {{ evo.selectedVersionId.value === version.version_id && evo.selectedVersionDetail.value.loading ? '读取' : '详情' }}
                  </button>
                  <button
                    type="button"
                    class="evolution-ghost-action"
                    :disabled="version.is_baseline || Boolean(evo.actionLoading.value)"
                    @click="evo.rollback(evo.selectedRole.value, version.version_id)"
                  >
                    {{ version.is_baseline ? 'baseline' : '回滚' }}
                  </button>
                </div>
              </div>
            </div>
            <div class="evolution-version-detail">
              <div v-if="evo.selectedVersionDetail.value.loading" class="evolution-empty compact">读取版本...</div>
              <div v-else-if="evo.selectedVersionDetail.value.error" class="evolution-alert compact">{{ evo.selectedVersionDetail.value.error }}</div>
              <template v-else-if="evo.selectedVersionDetail.value.data">
                <header>
                  <span>
                    <strong>{{ evo.shortId(evo.selectedVersionDetail.value.data.version_id) }}</strong>
                    <small>{{ evo.selectedVersionDetail.value.data.provenance?.source || evo.selectedVersionDetail.value.data.source || 'version' }}</small>
                  </span>
                  <b>{{ evo.selectedVersionDetail.value.data.skills?.length || 0 }} skills</b>
                </header>
                <div class="evolution-version-kpis">
                  <span><small>Win</small><b>{{ versionMetric(evo.selectedVersionDetail.value.data.metrics?.win_rate) }}</b></span>
                  <span><small>Score</small><b>{{ versionMetric(evo.selectedVersionDetail.value.data.metrics?.score) }}</b></span>
                  <span><small>Games</small><b>{{ evo.selectedVersionDetail.value.data.metrics?.games_played || 0 }}</b></span>
                </div>
                <ul v-if="evo.selectedVersionDetail.value.data.skills?.length" class="evolution-version-skill-list">
                  <li v-for="skill in evo.selectedVersionDetail.value.data.skills.slice(0, 4)" :key="skill.path || skill.content_hash">
                    {{ versionSkillLabel(skill) }}
                  </li>
                </ul>
                <!-- ── Pattern Browser ── -->
                <div v-if="versionPatterns.length" class="evo-pattern-browser">
                  <div class="evo-pattern-filter-bar">
                    <select v-model="patternRoleFilter">
                      <option value="">全部角色</option>
                      <option v-for="r in patternRoles" :key="r" :value="r">{{ patternRoleLabel(r) }}</option>
                    </select>
                    <select v-model="patternStatusFilter">
                      <option value="">全部状态</option>
                      <option v-for="s in patternStatuses" :key="s" :value="s">{{ patternStatusLabel(s) }}</option>
                    </select>
                    <small>{{ filteredPatterns.length }} / {{ versionPatterns.length }}</small>
                  </div>

                  <div class="evo-pattern-card-list">
                    <div v-for="pat in filteredPatterns" :key="pat.pattern_id" class="evo-pattern-card">
                      <div class="evo-pattern-card-header">
                        <span
                          class="evo-pattern-status-badge"
                          :style="{ background: patternStatusColor(pat.status) }"
                        >
                          {{ patternStatusLabel(pat.status) }}
                        </span>
                        <span class="evo-pattern-role-tag">{{ patternRoleLabel(pat.role) }}</span>
                        <span class="evo-pattern-id">{{ pat.pattern_id }}</span>
                      </div>

                      <div class="evo-pattern-situation">
                        <code>{{ pat.situation }}</code>
                      </div>

                      <p class="evo-pattern-recommendation">{{ pat.recommendation }}</p>

                      <div class="evo-pattern-winrate-bars">
                        <div class="evo-pattern-wr-row">
                          <span class="evo-pattern-wr-label">执行</span>
                          <div class="evo-pattern-wr-bar-track">
                            <div
                              class="evo-pattern-wr-bar-fill"
                              :style="{ width: winRatePct(pat.win_rate_with), background: winRateBarColor(pat.win_rate_with) }"
                            ></div>
                          </div>
                          <span class="evo-pattern-wr-value">{{ winRatePct(pat.win_rate_with) }}</span>
                        </div>
                        <div class="evo-pattern-wr-row">
                          <span class="evo-pattern-wr-label">不执行</span>
                          <div class="evo-pattern-wr-bar-track">
                            <div
                              class="evo-pattern-wr-bar-fill"
                              :style="{ width: winRatePct(pat.win_rate_without), background: winRateBarColor(pat.win_rate_without) }"
                            ></div>
                          </div>
                          <span class="evo-pattern-wr-value">{{ winRatePct(pat.win_rate_without) }}</span>
                        </div>
                      </div>

                      <div class="evo-pattern-meta-row">
                        <span>样本: <b>{{ pat.sample_size }}</b></span>
                        <span class="evo-pattern-confidence">
                          置信度:
                          <span class="evo-pattern-conf-track">
                            <span class="evo-pattern-conf-fill" :style="{ width: confidenceWidth(pat.confidence) }"></span>
                          </span>
                          <b>{{ winRatePct(pat.confidence) }}</b>
                        </span>
                      </div>

                      <div v-if="pat.source_games.length" class="evo-pattern-source-games">
                        <button
                          type="button"
                          class="evo-pattern-toggle-btn"
                          @click="togglePatternSource(pat.pattern_id)"
                        >
                          {{ expandedPatterns.has(pat.pattern_id) ? '收起' : '来源局' }} ({{ pat.source_games.length }})
                        </button>
                        <ul v-if="expandedPatterns.has(pat.pattern_id)" class="evo-pattern-source-list">
                          <li v-for="gid in pat.source_games" :key="gid">{{ gid }}</li>
                        </ul>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else-if="evo.selectedVersionDetail.value.data.patterns" class="evo-pattern-empty">
                  该版本暂无 Pattern 数据
                </div>
              </template>
              <div v-else class="evolution-empty compact">选择一个版本查看包内容</div>
            </div>
          </article>

          <article class="evolution-card evolution-events">
            <header>
              <h2>事件</h2>
              <b>{{ evo.eventLog.value.length }}</b>
            </header>
            <div v-if="!evo.eventLog.value.length" class="evolution-empty">暂无实时事件</div>
            <ol v-else class="evolution-event-list">
              <li v-for="event in evo.eventLog.value" :key="event.id">
                <strong>{{ event.type }}</strong>
                <span>{{ event.payload?.stage || event.payload?.status || event.payload?.run_id || event.payload?.batch_id || 'progress' }}</span>
              </li>
            </ol>
          </article>
        </section>

        <section class="evolution-grid evidence">
          <article class="evolution-card evolution-samples">
            <header>
              <h2>样本局</h2>
              <b>{{ evo.selectedGameRows.value.length }}</b>
            </header>

            <div class="evolution-sample-tabs">
              <button
                v-for="bucket in evo.sampleBuckets.value"
                :key="bucket.key"
                type="button"
                :class="{ active: evo.selectedGameBucket.value === bucket.key }"
                @click="evo.selectSampleGame(bucket.key)"
              >
                {{ bucket.label }} <span>{{ bucket.count }}</span>
              </button>
            </div>

            <div class="evolution-run-tools">
              <input v-model="evo.sampleGameFilter.value" type="search" placeholder="筛选 game / 阶段 / 胜负" />
              <span>{{ evo.visibleSampleGameRows.value.length }} / {{ evo.filteredSampleGameRows.value.length }}</span>
            </div>

            <div class="evolution-sample-layout">
              <div v-if="!evo.filteredSampleGameRows.value.length" class="evolution-empty compact">暂无样本局</div>
              <div v-else class="evolution-sample-list">
                <button
                  v-for="game in evo.visibleSampleGameRows.value"
                  :key="game.id"
                  type="button"
                  :class="['evolution-sample-row', { selected: evo.selectedGameId.value === game.id }]"
                  @click="evo.selectSampleGame(game.bucket, game.id)"
                >
                  <strong>{{ sampleTitle(game) }}</strong>
                  <span>{{ game.dayLabel }} · {{ game.phaseLabel }} · {{ game.eventCount }} events</span>
                </button>
                <div v-if="evo.filteredSampleGameRows.value.length > evo.visibleSampleGameRows.value.length" class="evolution-run-more">
                  继续筛选可查看其余 {{ evo.filteredSampleGameRows.value.length - evo.visibleSampleGameRows.value.length }} 条
                </div>
              </div>

              <div class="evolution-sample-detail">
                <div v-if="evo.selectedGameDetail.value.loading" class="evolution-empty compact">读取样本局...</div>
                <div v-else-if="evo.selectedGameDetail.value.error" class="evolution-alert">{{ evo.selectedGameDetail.value.error }}</div>
                <template v-else>
                  <h3>{{ evo.selectedGameDetail.value.archive?.title || evo.selectedGameId.value || '选择一局样本' }}</h3>
                  <p>{{ evo.selectedGameDetail.value.archive?.summary || '暂无 archive 摘要' }}</p>

                  <ul v-if="evo.selectedGameDetail.value.archive?.highlights?.length" class="evolution-highlight-list">
                    <li v-for="item in evo.selectedGameDetail.value.archive.highlights.slice(0, 3)" :key="item">
                      {{ item }}
                    </li>
                  </ul>

                  <div class="evolution-evidence-columns">
                    <div>
                      <h4>决策</h4>
                      <ol v-if="evo.selectedGameDetail.value.decisions.length">
                        <li v-for="decision in evo.selectedGameDetail.value.decisions.slice(0, 4)" :key="decision.id || decision.action || decisionText(decision)">
                          <strong>{{ decision.actor_name || decision.role || decision.action || 'agent' }}</strong>
                          <span>{{ decisionText(decision) }}</span>
                        </li>
                      </ol>
                      <span v-else>—</span>
                    </div>
                    <div>
                      <h4>事件</h4>
                      <ol v-if="evo.selectedGameDetail.value.events.length">
                        <li v-for="event in evo.selectedGameDetail.value.events.slice(0, 4)" :key="event.sequence || event.event_type || eventText(event)">
                          <strong>{{ event.phase || event.event_type || event.type || 'event' }}</strong>
                          <span>{{ eventText(event) }}</span>
                        </li>
                      </ol>
                      <span v-else>—</span>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </article>
        </section>
      </div>
    </section>
  </section>
</template>

<style scoped>
/* ═══════════════════════════════════════
   Pattern Browser
   ═══════════════════════════════════════ */
.evo-pattern-browser {
  margin-top: 10px;
  border-top: 1px solid rgba(242, 202, 80, 0.12);
  padding-top: 10px;
}

.evo-pattern-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.evo-pattern-filter-bar select {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 8px;
  border: 1px solid rgba(242, 202, 80, 0.18);
  border-radius: 4px;
  color: var(--text, #eae1d4);
  background: rgba(17, 14, 7, 0.7);
  font-size: 12px;
}

.evo-pattern-filter-bar small {
  color: rgba(208, 197, 175, 0.7);
  font-size: 11px;
  white-space: nowrap;
}

.evo-pattern-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 4px;
}

.evo-pattern-card {
  padding: 10px 12px;
  border: 1px solid rgba(242, 202, 80, 0.12);
  border-radius: 6px;
  background: rgba(31, 27, 19, 0.5);
}

.evo-pattern-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.evo-pattern-status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.evo-pattern-role-tag {
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(191, 205, 255, 0.12);
  color: #bfcdff;
  font-size: 10px;
  font-weight: 700;
}

.evo-pattern-id {
  margin-left: auto;
  color: rgba(208, 197, 175, 0.5);
  font-size: 10px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-pattern-situation {
  margin-bottom: 4px;
}

.evo-pattern-situation code {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.3);
  color: #d0c5af;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  font-size: 11px;
  word-break: break-all;
}

.evo-pattern-recommendation {
  margin: 6px 0;
  color: var(--text, #eae1d4);
  font-size: 13px;
  line-height: 1.5;
}

/* Win rate comparison bars */
.evo-pattern-winrate-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 8px 0;
}

.evo-pattern-wr-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.evo-pattern-wr-label {
  flex: 0 0 42px;
  color: rgba(208, 197, 175, 0.78);
  font-size: 11px;
  text-align: right;
}

.evo-pattern-wr-bar-track {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
}

.evo-pattern-wr-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.evo-pattern-wr-value {
  flex: 0 0 36px;
  color: var(--text, #eae1d4);
  font-size: 11px;
  font-weight: 700;
}

/* Meta row */
.evo-pattern-meta-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 6px;
  color: rgba(208, 197, 175, 0.7);
  font-size: 11px;
}

.evo-pattern-meta-row b {
  color: var(--text, #eae1d4);
}

.evo-pattern-confidence {
  display: flex;
  align-items: center;
  gap: 4px;
}

.evo-pattern-conf-track {
  display: inline-block;
  width: 48px;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.evo-pattern-conf-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: #f5a623;
  transition: width 0.3s ease;
}

/* Source games collapsible */
.evo-pattern-source-games {
  margin-top: 6px;
}

.evo-pattern-toggle-btn {
  padding: 2px 8px;
  border: 1px solid rgba(242, 202, 80, 0.16);
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.03);
  color: rgba(208, 197, 175, 0.8);
  font-size: 11px;
  cursor: pointer;
}

.evo-pattern-toggle-btn:hover {
  border-color: rgba(242, 202, 80, 0.4);
  background: rgba(242, 202, 80, 0.06);
}

.evo-pattern-source-list {
  margin: 4px 0 0;
  padding: 0 0 0 16px;
  list-style: none;
  color: rgba(208, 197, 175, 0.6);
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-pattern-source-list li {
  padding: 1px 0;
}

.evo-pattern-empty {
  padding: 10px 0;
  color: rgba(208, 197, 175, 0.5);
  font-size: 12px;
  text-align: center;
}

/* ═══════════════════════════════════════
   Diff Viewer
   ═══════════════════════════════════════ */
.evo-diff-viewer {
  margin-top: 12px;
  border-top: 1px solid rgba(242, 202, 80, 0.12);
  padding-top: 10px;
}

.evo-diff-viewer h3 {
  margin: 0 0 6px;
  color: rgba(242, 202, 80, 0.8);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

/* Metrics Delta Strip */
.evo-diff-metrics-strip {
  margin-bottom: 12px;
}

.evo-diff-metrics-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.evo-diff-metric-kpi {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  min-width: 72px;
}

.evo-diff-metric-kpi small {
  color: rgba(208, 197, 175, 0.7);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.evo-diff-metric-kpi b {
  font-size: 14px;
  font-weight: 800;
  margin-top: 2px;
}

.evo-diff-metric-kpi.positive b {
  color: #4caf50;
}

.evo-diff-metric-kpi.negative b {
  color: #ef5350;
}

.evo-diff-arrow {
  font-size: 9px;
  margin-right: 2px;
}

/* Diff sections */
.evo-diff-section {
  margin-bottom: 12px;
}

/* Skill file changes */
.evo-diff-file-block {
  margin-bottom: 10px;
  border: 1px solid rgba(242, 202, 80, 0.1);
  border-radius: 5px;
  overflow: hidden;
}

.evo-diff-file-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: rgba(0, 0, 0, 0.25);
}

.evo-diff-filename {
  color: var(--text, #eae1d4);
  font-size: 12px;
  font-weight: 700;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-diff-action-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 3px;
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.evo-diff-code-block {
  max-height: 220px;
  overflow-y: auto;
  padding: 6px 0;
  background: rgba(0, 0, 0, 0.18);
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  font-size: 11px;
  line-height: 1.55;
}

.evo-diff-line {
  display: flex;
  padding: 0 10px;
  white-space: pre-wrap;
  word-break: break-all;
}

.evo-diff-line-added {
  background: rgba(0, 200, 0, 0.1);
}

.evo-diff-line-added .evo-diff-line-marker {
  color: #4caf50;
}

.evo-diff-line-removed {
  background: rgba(200, 0, 0, 0.1);
}

.evo-diff-line-removed .evo-diff-line-marker {
  color: #ef5350;
}

.evo-diff-line-context {
  background: transparent;
}

.evo-diff-line-context .evo-diff-line-marker {
  color: rgba(208, 197, 175, 0.35);
}

.evo-diff-line-marker {
  flex: 0 0 14px;
  text-align: center;
  font-weight: 700;
  user-select: none;
}

.evo-diff-line-text {
  flex: 1;
  color: rgba(234, 225, 212, 0.85);
}

.evo-diff-no-content {
  margin: 0;
  padding: 6px 10px;
  color: rgba(208, 197, 175, 0.5);
  font-size: 11px;
  font-style: italic;
}

/* Pattern changes */
.evo-diff-pattern-group {
  margin-bottom: 8px;
}

.evo-diff-group-label {
  display: block;
  margin-bottom: 4px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.added-label {
  color: #4caf50;
}

.removed-label {
  color: #ef5350;
}

.updated-label {
  color: #f9a825;
}

.evo-diff-pattern-card {
  padding: 6px 10px;
  border-radius: 4px;
  margin-bottom: 4px;
  font-size: 12px;
}

.evo-diff-pattern-card strong {
  display: block;
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  margin-bottom: 2px;
}

.evo-diff-pattern-card span {
  display: block;
  color: rgba(234, 225, 212, 0.8);
  line-height: 1.4;
}

.evo-diff-pattern-card.added {
  border-left: 3px solid #4caf50;
  background: rgba(0, 200, 0, 0.06);
}

.evo-diff-pattern-card.added strong {
  color: #66bb6a;
}

.evo-diff-pattern-card.removed {
  border-left: 3px solid #ef5350;
  background: rgba(200, 0, 0, 0.06);
}

.evo-diff-pattern-card.removed strong {
  color: #ef5350;
  text-decoration: line-through;
}

.evo-diff-pattern-card.removed span {
  text-decoration: line-through;
  color: rgba(208, 197, 175, 0.5);
}

.evo-diff-pattern-card.updated {
  border-left: 3px solid #f9a825;
  background: rgba(200, 160, 0, 0.06);
}

.evo-diff-pattern-card.updated strong {
  color: #f9a825;
}

/* Legacy fallback list */
.evo-diff-legacy-list {
  margin: 0;
  padding: 0 0 0 16px;
  list-style: none;
  color: rgba(208, 197, 175, 0.7);
  font-size: 12px;
}

.evo-diff-legacy-list li {
  padding: 2px 0;
}

.evo-diff-empty h3 {
  margin: 10px 0 4px;
  color: rgba(242, 202, 80, 0.6);
  font-size: 12px;
}

.evo-diff-empty p {
  margin: 0;
  color: rgba(208, 197, 175, 0.5);
}
</style>

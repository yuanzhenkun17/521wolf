<script setup lang="ts">
import { computed } from 'vue'
import { normalizeHistoryDisplayText } from './historyDisplay.ts'

type ReviewRecord = Record<string, unknown>
interface JudgeEvidence {
  evidenceRefs?: unknown
  counterfactuals?: unknown
  rubricMisses?: unknown
  degradedReasons?: unknown
  warnings?: unknown
  diagnostics?: unknown
}

const props = defineProps({
  evidence: { type: Object, default: null },
  rowKey: { type: [String, Number], default: '' },
  formatJson: { type: Function, default: null }
})

const evidenceGroups = computed(() => ({
  evidenceRefs: arrayRows((props.evidence as JudgeEvidence | null)?.evidenceRefs),
  counterfactuals: arrayRows((props.evidence as JudgeEvidence | null)?.counterfactuals),
  rubricMisses: arrayRows((props.evidence as JudgeEvidence | null)?.rubricMisses),
  degradedReasons: arrayRows((props.evidence as JudgeEvidence | null)?.degradedReasons),
  warnings: arrayRows((props.evidence as JudgeEvidence | null)?.warnings),
  diagnostics: arrayRows((props.evidence as JudgeEvidence | null)?.diagnostics)
}))

const evidenceTotal = computed(() =>
  Object.values(evidenceGroups.value).reduce((sum, rows) => sum + rows.length, 0)
)
const hasEvidence = computed(() => evidenceTotal.value > 0)

function arrayRows(value: unknown): unknown[] {
  return Array.isArray(value) ? value.filter((row) => row != null && row !== '') : []
}

function rowIdentity(value: unknown): string {
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return Object.prototype.toString.call(value)
    }
  }
  return String(value)
}

function formatReviewText(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') {
    const record = value as ReviewRecord
    return formatReviewText(record.description || record.summary || record.event || record.message || jsonText(value))
  }
  return normalizeHistoryDisplayText(value) || '—'
}

function judgeEvidenceText(value: unknown): string {
  if (value && typeof value === 'object') {
    const record = value as ReviewRecord
    const parts = [
      record.kind,
      record.stage,
      record.reason,
      record.message || record.exception_message || record.detail || record.summary
    ].filter((part) => part != null && String(part).trim())
    return parts.length ? parts.map(formatReviewText).join(' · ') : jsonText(value)
  }
  return formatReviewText(value)
}

function evidenceKey(prefix: string, value: unknown, index: number): string {
  return `${prefix}-${props.rowKey}-${index}-${rowIdentity(value)}`
}

function jsonText(value: unknown): string {
  if (props.formatJson) return props.formatJson(value)
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <details v-if="hasEvidence" class="review-judge-evidence">
    <summary>
      <span>证据展开</span>
      <b>{{ evidenceTotal }} 项</b>
    </summary>
    <div class="review-judge-evidence-grid">
      <section v-if="evidenceGroups.evidenceRefs.length" class="review-judge-evidence-block">
        <small>证据引用</small>
        <ul class="review-judge-evidence-list code-list">
          <li v-for="(ref, index) in evidenceGroups.evidenceRefs" :key="evidenceKey('ref', ref, index)">
            <code>{{ judgeEvidenceText(ref) }}</code>
          </li>
        </ul>
      </section>
      <section v-if="evidenceGroups.counterfactuals.length" class="review-judge-evidence-block">
        <small>反事实</small>
        <p v-for="(counterfactual, index) in evidenceGroups.counterfactuals" :key="evidenceKey('cf', counterfactual, index)">
          {{ judgeEvidenceText(counterfactual) }}
        </p>
      </section>
      <section v-if="evidenceGroups.rubricMisses.length" class="review-judge-evidence-block">
        <small>评分规则未命中</small>
        <ul class="review-judge-evidence-list">
          <li v-for="(miss, index) in evidenceGroups.rubricMisses" :key="evidenceKey('miss', miss, index)">
            {{ judgeEvidenceText(miss) }}
          </li>
        </ul>
      </section>
      <section v-if="evidenceGroups.degradedReasons.length" class="review-judge-evidence-block warning-block">
        <small>降级/失败原因</small>
        <ul class="review-judge-evidence-list">
          <li v-for="(reason, index) in evidenceGroups.degradedReasons" :key="evidenceKey('degraded', reason, index)">
            {{ judgeEvidenceText(reason) }}
          </li>
        </ul>
      </section>
      <section v-if="evidenceGroups.warnings.length" class="review-judge-evidence-block warning-block">
        <small>警告</small>
        <ul class="review-judge-evidence-list">
          <li v-for="(warning, index) in evidenceGroups.warnings" :key="evidenceKey('warning', warning, index)">
            {{ judgeEvidenceText(warning) }}
          </li>
        </ul>
      </section>
      <section v-if="evidenceGroups.diagnostics.length" class="review-judge-evidence-block wide-block">
        <small>诊断</small>
        <ul class="review-judge-evidence-list diagnostic-list">
          <li v-for="(diagnostic, index) in evidenceGroups.diagnostics" :key="evidenceKey('diagnostic', diagnostic, index)">
            {{ judgeEvidenceText(diagnostic) }}
          </li>
        </ul>
      </section>
    </div>
  </details>
</template>

<style scoped>
.review-judge-evidence {
  min-width: 0;
  padding-top: 7px;
  border-top: 1px dashed rgba(93, 48, 17, 0.16);
}

.review-judge-evidence summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  color: var(--log-text);
  cursor: pointer;
  list-style: none;
}

.review-judge-evidence summary::-webkit-details-marker {
  display: none;
}

.review-judge-evidence summary span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  overflow: hidden;
  font-size: 11px;
  font-weight: 900;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-judge-evidence summary span::before {
  content: '>';
  color: var(--log-accent);
  font-size: 13px;
  line-height: 1;
  transition: transform 0.15s ease;
}

.review-judge-evidence[open] summary span::before {
  transform: rotate(90deg);
}

.review-judge-evidence summary b {
  flex: 0 0 auto;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--log-accent);
  font-size: 10px;
  font-weight: 950;
  line-height: 1;
}

.review-judge-evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
  margin-top: 7px;
}

.review-judge-evidence-block {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 7px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.46);
}

.review-judge-evidence-block.wide-block {
  grid-column: 1 / -1;
}

.review-judge-evidence-block.warning-block {
  border-color: rgba(163, 61, 53, 0.14);
  background: rgba(163, 61, 53, 0.06);
}

.review-judge-evidence-block small {
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.review-judge-evidence-list {
  display: grid;
  gap: 4px;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.review-judge-evidence-block p,
.review-judge-evidence-list li {
  min-width: 0;
  margin: 0;
  color: var(--log-text);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.review-judge-evidence-list.code-list code {
  display: inline;
  max-width: 100%;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(93, 48, 17, 0.07);
  color: #4c2610;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 10px;
  white-space: normal;
  overflow-wrap: anywhere;
}

.review-judge-evidence-list.diagnostic-list li {
  color: var(--log-text-secondary);
}

@media (max-width: 720px) {
  .review-judge-evidence-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

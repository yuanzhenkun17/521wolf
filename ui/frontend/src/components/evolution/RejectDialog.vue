<script setup lang="ts">
// @ts-nocheck
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  proposal: { type: Object, default: null },
  reason: { type: String, default: '' },
  tags: { type: Array, default: () => [] },
  rejectBuffer: { type: Object, default: () => ({}) },
  busy: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['cancel', 'confirm'])

const reasonDraft = ref('')
const tagDraft = ref('')
const tagDrafts = ref([])
const reasonTouched = ref(false)
const reasonInput = ref(null)

const normalizedReason = computed(() => reasonDraft.value.trim())
const hasReason = computed(() => Boolean(normalizedReason.value))
const canConfirm = computed(() => props.open && !props.busy && !props.disabled && hasReason.value)
const showReasonError = computed(() => reasonTouched.value && !hasReason.value)
const proposalTitle = computed(() => displayText(props.proposal?.title || props.proposal?.id || props.proposal?.proposal_id, '待拒绝提案'))
const buffer = computed(() => props.rejectBuffer || {})
const hasBufferSummary = computed(() => Boolean(buffer.value?.visible))
const matched = computed(() => buffer.value?.matched || {})
const hasMatched = computed(() => Boolean(matched.value.proposalId || matched.value.sourceRunId || matched.value.reason))
const summaryItems = computed(() => {
  const items = []
  if (buffer.value.savedLabel) items.push({ key: 'saved', label: '保存', value: buffer.value.savedLabel })
  if (buffer.value.duplicateLabel) items.push({ key: 'duplicate', label: '去重', value: buffer.value.duplicateLabel })
  if (buffer.value.dedupeKey) items.push({ key: 'dedupe', label: '去重键', value: buffer.value.dedupeKey, code: true })
  if (buffer.value.scope) items.push({ key: 'scope', label: '范围', value: buffer.value.scope })
  if (buffer.value.similarityScore != null) items.push({ key: 'similarity', label: '相似度', value: scoreLabel(buffer.value.similarityScore) })
  if (buffer.value.overfitScore != null) items.push({ key: 'overfit', label: '过拟合', value: scoreLabel(buffer.value.overfitScore) })
  return items
})
const bufferTags = computed(() => [
  ...normalizeTags(buffer.value.tags || []),
  ...normalizeTags(buffer.value.overfitEvidence || [])
])

watch(() => props.open, async (open) => {
  if (!open) return
  reasonDraft.value = props.reason || ''
  tagDrafts.value = normalizeTags(props.tags.length ? props.tags : buffer.value.tags || [])
  tagDraft.value = ''
  reasonTouched.value = false
  await nextTick()
  reasonInput.value?.focus?.()
})

watch(() => props.reason, (reason) => {
  if (!props.open) reasonDraft.value = reason || ''
})

watch(() => props.tags, (tags) => {
  if (!props.open) tagDrafts.value = normalizeTags(tags || [])
})

function displayText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function scoreLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  const pct = Math.abs(number) <= 1 ? number * 100 : number
  return `${Math.round(pct)}%`
}

function normalizeTags(tags) {
  const values = Array.isArray(tags) ? tags : String(tags || '').split(/[,\s]+/)
  return [...new Set(values.map((tag) => String(tag ?? '').trim()).filter(Boolean))].slice(0, 12)
}

function matchedLabel() {
  const parts = [
    matched.value.proposalId ? `提案 ${matched.value.proposalId}` : '',
    matched.value.sourceRunId ? `运行 ${matched.value.sourceRunId}` : ''
  ].filter(Boolean)
  return parts.join(' · ')
}

function bufferStatusLabel() {
  if (buffer.value.savedLabel) return buffer.value.savedLabel
  if (buffer.value.status) return displayText(buffer.value.status)
  if (buffer.value.duplicateLabel) return buffer.value.duplicateLabel
  return '已记录'
}

function addTags() {
  const nextTags = normalizeTags([...tagDrafts.value, ...String(tagDraft.value || '').split(/[,\n]+/)])
  tagDrafts.value = nextTags
  tagDraft.value = ''
}

function removeTag(tag) {
  tagDrafts.value = tagDrafts.value.filter((item) => item !== tag)
}

function handleTagKeydown(event) {
  if (event.key !== 'Enter' && event.key !== ',') return
  event.preventDefault()
  addTags()
}

function cancel() {
  if (props.busy) return
  emit('cancel')
}

function confirm() {
  reasonTouched.value = true
  addTags()
  if (!canConfirm.value) return
  emit('confirm', {
    reason: normalizedReason.value,
    tags: [...tagDrafts.value],
    metadata: {
      tags: [...tagDrafts.value],
      rejectBuffer: buffer.value
    }
  })
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="evo-reject-dialog-backdrop"
      data-reject-dialog-backdrop
      @click.self="cancel"
      @keydown.esc.prevent="cancel"
    >
      <form
        class="evo-reject-dialog"
        data-reject-dialog
        role="dialog"
        aria-modal="true"
        aria-labelledby="evo-reject-dialog-title"
        @submit.prevent="confirm"
      >
        <header class="evo-reject-dialog-head">
          <span>
            <small>审计动作</small>
            <h2 id="evo-reject-dialog-title">拒绝提案</h2>
          </span>
          <button type="button" class="evo-ghost-action" :disabled="busy" @click="cancel">取消</button>
        </header>

        <section class="evo-reject-dialog-proposal">
          <small>目标</small>
          <b>{{ proposalTitle }}</b>
          <code v-if="proposal?.apiId || proposal?.proposal_id || proposal?.id">
            {{ proposal?.apiId || proposal?.proposal_id || proposal?.id }}
          </code>
        </section>

        <section
          v-if="hasBufferSummary"
          class="evo-reject-dialog-buffer"
          data-reject-buffer-summary
        >
          <header>
            <small>拒绝缓冲</small>
            <b>{{ bufferStatusLabel() }}</b>
          </header>
          <div v-if="summaryItems.length" class="evo-reject-dialog-buffer-grid">
            <span v-for="item in summaryItems" :key="item.key">
              <small>{{ item.label }}</small>
              <code v-if="item.code">{{ item.value }}</code>
              <b v-else>{{ item.value }}</b>
            </span>
          </div>
          <p v-if="buffer.reason">{{ buffer.reason }}</p>
          <div v-if="bufferTags.length" class="evo-reject-dialog-tags compact">
            <span v-for="tag in bufferTags" :key="`buffer-${tag}`">{{ tag }}</span>
          </div>
          <div v-if="hasMatched" class="evo-reject-dialog-match">
            <small>命中拒绝记录</small>
            <b v-if="matchedLabel()">{{ matchedLabel() }}</b>
            <p v-if="matched.reason">{{ matched.reason }}</p>
          </div>
        </section>

        <label class="evo-reject-dialog-field">
          <span>
            <small>拒绝原因</small>
            <b>必填</b>
          </span>
          <textarea
            ref="reasonInput"
            v-model="reasonDraft"
            rows="4"
            maxlength="1000"
            placeholder="写清楚拒绝该提案的证据、风险或门禁原因"
            :aria-invalid="showReasonError ? 'true' : 'false'"
            :disabled="busy || disabled"
            required
            @blur="reasonTouched = true"
          />
          <em v-if="showReasonError">拒绝原因不能为空。</em>
        </label>

        <section class="evo-reject-dialog-field" data-review-metadata-tags>
          <span>
            <small>审核标签</small>
            <b>拒绝元数据</b>
          </span>
          <div class="evo-reject-dialog-tag-editor">
            <input
              v-model="tagDraft"
              type="text"
              placeholder="添加标签，Enter 确认"
              :disabled="busy || disabled"
              @keydown="handleTagKeydown"
              @blur="addTags"
            />
            <button type="button" class="evo-ghost-action" :disabled="busy || disabled || !tagDraft.trim()" @click="addTags">
              添加
            </button>
          </div>
          <div v-if="tagDrafts.length" class="evo-reject-dialog-tags">
            <button
              v-for="tag in tagDrafts"
              :key="tag"
              type="button"
              :disabled="busy || disabled"
              @click="removeTag(tag)"
            >
              {{ tag }} ×
            </button>
          </div>
          <p>标签会随拒绝原因写入后端拒绝缓冲，用于去重和过拟合审计。</p>
        </section>

        <footer class="evo-reject-dialog-actions">
          <button type="button" class="evo-ghost-action" :disabled="busy" @click="cancel">取消</button>
          <button
            type="submit"
            class="evo-ghost-action danger"
            data-reject-confirm
            :disabled="!canConfirm"
          >
            {{ busy ? '拒绝中' : '确认拒绝' }}
          </button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.evo-reject-dialog-backdrop {
  --logbook-bg: var(--workbench-logbook-bg, #f2dfae);
  --logbook-bg-texture: var(
    --workbench-logbook-bg-texture,
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    var(--logbook-bg)
  );
  --logbook-surface: var(--workbench-logbook-surface, rgba(255, 252, 245, 0.7));
  --logbook-border: var(--workbench-logbook-border, rgba(139, 94, 52, 0.15));
  --logbook-text: var(--workbench-logbook-text, #3a2a18);
  --logbook-muted: var(--workbench-logbook-muted, #8b6b4a);
  --logbook-accent: var(--workbench-logbook-accent, #8b5e34);
  --logbook-accent-strong: var(--workbench-logbook-accent-strong, #5a3319);
  --logbook-input-bg: var(--workbench-logbook-input-bg, rgba(255, 255, 250, 0.8));
  --logbook-input-border: var(--workbench-logbook-input-border, rgba(139, 94, 52, 0.2));
  --logbook-hover: var(--workbench-logbook-hover, rgba(139, 94, 52, 0.06));
  --logbook-danger: var(--workbench-logbook-danger, #993026);
  --evo-bg: var(--logbook-bg);
  --evo-bg-texture: var(--logbook-bg-texture);
  --evo-border: var(--logbook-border, rgba(139, 94, 52, 0.15));
  --evo-text: var(--logbook-text, #3a2a18);
  --evo-text-secondary: var(--logbook-muted, #8b6b4a);
  --evo-accent: var(--logbook-accent, #8b5e34);
  --evo-accent-strong: var(--logbook-accent-strong, #5a3319);
  --evo-card-bg: var(--logbook-surface);
  --evo-input-bg: var(--logbook-input-bg, rgba(255, 255, 250, 0.8));
  --evo-input-border: var(--logbook-input-border, rgba(139, 94, 52, 0.2));
  --evo-hover: var(--logbook-hover, rgba(139, 94, 52, 0.06));
  --evo-danger: var(--logbook-danger, #993026);
  --evo-danger-bg: rgba(248, 205, 181, 0.6);
  --evo-danger-border: rgba(154, 45, 36, 0.3);
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  box-sizing: border-box;
  min-width: 0;
  padding: 16px;
  background: rgba(23, 18, 13, 0.36);
}

.evo-reject-dialog {
  display: grid;
  gap: 12px;
  box-sizing: border-box;
  width: min(720px, 100%);
  max-height: calc(100dvh - 32px);
  min-width: 0;
  overflow: auto;
  padding: 16px;
  border: 1px solid var(--evo-danger-border);
  border-radius: 8px;
  background: var(--evo-bg-texture);
  box-shadow: 0 18px 46px rgba(23, 18, 13, 0.22);
}

.evo-reject-dialog-head,
.evo-reject-dialog-actions,
.evo-reject-dialog-buffer header,
.evo-reject-dialog-field > span {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.evo-reject-dialog-head h2 {
  margin: 2px 0 0;
  color: var(--evo-text, #2f261c);
  font-size: 18px;
  font-weight: 850;
  line-height: 1.2;
}

.evo-reject-dialog-head small,
.evo-reject-dialog-proposal small,
.evo-reject-dialog-buffer small,
.evo-reject-dialog-field small,
.evo-reject-dialog-match small {
  overflow: hidden;
  color: var(--evo-text-secondary, #756957);
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0;
  line-height: 1.1;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.evo-reject-dialog-proposal,
.evo-reject-dialog-buffer,
.evo-reject-dialog-field,
.evo-reject-dialog-match {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.evo-reject-dialog-proposal,
.evo-reject-dialog-buffer {
  padding: 10px;
  border: 1px solid var(--evo-danger-border);
  border-radius: 8px;
  background: var(--evo-danger-bg);
}

.evo-reject-dialog-proposal b,
.evo-reject-dialog-buffer b,
.evo-reject-dialog-buffer code,
.evo-reject-dialog-field b,
.evo-reject-dialog-match b {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text, #2f261c);
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-reject-dialog-proposal code {
  justify-self: start;
  max-width: 100%;
  overflow: hidden;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(58, 42, 24, 0.07);
  color: var(--evo-text-secondary, #756957);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-reject-dialog-buffer-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
}

.evo-reject-dialog-buffer-grid span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 6px 7px;
  border: 1px solid rgba(139, 58, 42, 0.12);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.58);
}

.evo-reject-dialog-buffer p,
.evo-reject-dialog-field p,
.evo-reject-dialog-match p {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--evo-text-secondary, #756957);
  font-size: 11px;
  font-weight: 650;
  line-height: 1.4;
}

.evo-reject-dialog-match {
  padding: 8px;
  border: 1px dashed rgba(139, 58, 42, 0.22);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.48);
}

.evo-reject-dialog-field textarea,
.evo-reject-dialog-tag-editor input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  border: 1px solid var(--evo-input-border, rgba(58, 42, 24, 0.18));
  border-radius: 7px;
  background: rgba(255, 255, 250, 0.72);
  color: var(--evo-text, #2f261c);
  font-size: 12px;
}

.evo-reject-dialog-field textarea {
  min-height: 104px;
  resize: vertical;
  padding: 9px 10px;
  line-height: 1.5;
}

.evo-reject-dialog-tag-editor input {
  height: 32px;
  padding: 0 9px;
}

.evo-reject-dialog-field textarea[aria-invalid="true"] {
  border-color: rgba(139, 58, 42, 0.56);
  box-shadow: 0 0 0 2px rgba(139, 58, 42, 0.08);
}

.evo-reject-dialog-field textarea:disabled,
.evo-reject-dialog-tag-editor input:disabled {
  opacity: 0.55;
}

.evo-reject-dialog-field em {
  color: var(--evo-danger);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.evo-reject-dialog-tag-editor {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
  min-width: 0;
}

.evo-reject-dialog-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.evo-reject-dialog-tags span,
.evo-reject-dialog-tags button {
  max-width: 100%;
  overflow: hidden;
  padding: 3px 7px;
  border: 1px solid rgba(58, 42, 24, 0.08);
  border-radius: 6px;
  background: rgba(58, 42, 24, 0.06);
  color: var(--evo-text-secondary, #756957);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-reject-dialog-tags button {
  cursor: pointer;
}

.evo-reject-dialog-tags button:disabled {
  cursor: default;
  opacity: 0.55;
}

.evo-reject-dialog-tags.compact span {
  white-space: normal;
}

.evo-reject-dialog-actions {
  padding-top: 2px;
}

@media (max-width: 760px) {
  .evo-reject-dialog-backdrop {
    align-items: end;
    padding: 10px;
  }

  .evo-reject-dialog {
    width: min(100%, calc(100vw - 20px));
    max-height: calc(100dvh - 20px);
    padding: 12px;
  }

  .evo-reject-dialog-buffer-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-reject-dialog-tag-editor,
  .evo-reject-dialog-actions {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-reject-dialog-actions {
    display: grid;
  }
}
</style>

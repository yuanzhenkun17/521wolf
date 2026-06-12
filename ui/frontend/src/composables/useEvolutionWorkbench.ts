import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { createGameApi } from './gameApi.ts'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.ts'
import { createNoticeAutoDismiss } from './noticeAutoDismiss.ts'
import { createResumableEventSource } from './resumableEventSource.ts'
import { addLegacyHashChangeListener, currentLegacyHash } from '../router/legacyViewNavigation'
import { runtimeHealthGateSummary, runtimeHealthPayloadFromPreflight } from '../domain/runtimeHealth/gates'
import {
  evolutionDeepLinkFromHash as routeEvolutionDeepLinkFromHash,
  evolutionDeepLinkFromRoute as routeEvolutionDeepLinkFromRoute,
  evolutionDeepLinkPanel as routeEvolutionDeepLinkPanel
} from '../router/workbenchDeepLinks.ts'
import {
  EVOLUTION_ACTIVE_STATUSES,
  EVOLUTION_TERMINAL_STATUSES,
  isEvolutionBatch,
  normalizeLeaderboardEntry,
  recommendationText,
  roleMeta,
  shortId,
  sourceText,
  statusText
} from './workbenchShared.ts'

import {
  type LooseRecord,
  DEFAULT_RUN_PAGE_SIZE,
  DEFAULT_SAMPLE_GAME_PAGE_SIZE,
  SAMPLE_GAME_BUCKETS,
  SAMPLE_BUCKET_LABELS,
  ROLLBACK_BLOCKED_RELEASE_STAGES,
  createPagination,
  paginationFromResponse,
  mergeById,
  samplePaginationMap,
  emptySampleGames,
  percentValue,
  stageText,
  normalizeReleaseStage,
  rollbackDisabledReason,
  timeLabel,
  finiteNumber,
  firstFinite,
  firstBoolean,
  maxFinite,
  arrayLength,
  isCompletedPipelineStatus,
  isBattleStage,
  isTrainingStage,
  isAfterTrainingStage,
  isAfterBattleStage,
  progressFromCount,
  progressWithExplicit,
  normalizeChildRun,
  buildBatchProgress,
  buildRunProgress,
  normalizeRun,
  normalizeVersion,
  normalizeSampleGame,
  asArray,
  firstArray,
  isLooseRecord,
  firstObject,
  uniqueText,
  textItems,
  shortText,
  firstTextValue,
  structuredText,
  metricTargetRows,
  gateDecisionText,
  proposalStatusText,
  preflightStatusText,
  attributionStatusText,
  normalizePairedSeed,
  normalizeProposalAttributionReport,
  normalizeGateReport,
  proposalRiskTags,
  normalizeRejectBuffer,
  normalizeProposal,
  proposalSource,
  pairedSeedSource,
  normalizeProposalReview,
  promotionTrustBundle,
  promotionGateReport,
  promotionReleaseDecision,
  promoteRequiresCompleteTrust,
  promotionTrustCompleteness,
  hasPromotionGateReference,
  hasPromotionTrainingEvidenceReference,
  hasPromotionProposalReference,
  trustMissingItemKey,
  trustMissingItemLabel,
  baselinePromoteTrustDisabledReason,
  sourceRunIdFrom,
  rollbackTargetFrom,
  trustAuditSourceText,
  hashHref,
  evidenceHref,
  evolutionHref,
  evolutionDeepLinkPanel,
  evolutionDeepLinkFromHash,
  evolutionDeepLinkFromRoute,
  auditEvidenceRows,
  auditText,
  auditFieldValue,
  trustConsistencyStatus,
  trustConsistencyMessage,
  trustAuditConsistencyChecks,
  trustAuditMismatches,
  normalizeTrustCompleteness,
  normalizeTrustBundleAudit
} from './evolutionNormalizers.ts'

function isMissingProposalEndpoint(error) {
  const message = String(error?.message || '').toLowerCase()
  return message.includes('404') || message.includes('not found') || message.includes('unexpected')
}

function errorText(error) {
  return String(error?.message || error || '').trim()
}

function evolutionNoticeFromError(error, fallback = '操作失败', context = '') {
  const raw = errorText(error)
  const message = raw.toLowerCase()
  const code = String(error?.code || error?.payload?.error?.code || '').toLowerCase()
  const notFound = message.includes('not found') || message.includes('404')
  if (message.includes('batch does not support')) {
    return { type: 'warning', message: '批量任务不支持该操作，请选择子运行。', reason: 'batchUnsupported' }
  }
  if (message.includes('no accepted proposals to apply')) {
    return { type: 'warning', message: '没有已接受提案可应用。', reason: 'noAcceptedProposals' }
  }
  if (message.includes('accepted or applied proposal') || message.includes('proposal review required')) {
    return { type: 'warning', message: '至少接受或应用一个提案后才能晋升。', reason: 'proposalReviewRequired' }
  }
  if (code === 'evolution_trust_bundle_required' || (context === 'run' && message.includes('trust bundle required'))) {
    return { type: 'warning', message: '缺少完整信任包，不能晋升为基线。', reason: 'trustBundleRequired' }
  }
  if (
    code === 'evolution_trust_bundle_incomplete' ||
    (context === 'run' && (message.includes('complete trust bundle') || message.includes('trust bundle/gate/evidence')))
  ) {
    return { type: 'warning', message: '信任包不完整，不能晋升为基线。', reason: 'trustBundleIncomplete' }
  }
  if (code === 'evolution_model_profile_invalid' || message.includes('evolution model profile is unavailable')) {
    const detail = String(error?.detail || raw || '').toLowerCase()
    if (detail.includes('environment llm config is locked')) {
      return {
        type: 'warning',
        message: '自进化模型 Profile 不可用：当前由 WEREWOLF_LLM_* 环境变量锁定默认模型，请不要再指定单独的 Profile。',
        reason: 'modelProfileInvalid'
      }
    }
    if (detail.includes('disabled')) {
      return { type: 'warning', message: '自进化模型 Profile 不可用：该 Profile 已禁用。', reason: 'modelProfileInvalid' }
    }
    if (detail.includes('api key')) {
      return { type: 'warning', message: '自进化模型 Profile 不可用：该 Profile 没有保存 API key。', reason: 'modelProfileInvalid' }
    }
    return {
      type: 'warning',
      message: '自进化模型 Profile 不可用，请在设置页启用 Profile、保存 API key 并勾选 Evolution 默认用途。',
      reason: 'modelProfileInvalid'
    }
  }
  if (message.includes('proposal not found') || (context === 'proposal' && notFound)) {
    return { type: 'warning', message: '提案不存在，请刷新审核面板。', reason: 'proposalNotFound' }
  }
  if (message.includes('version not found') || (context === 'version' && notFound)) {
    return { type: 'warning', message: '版本不存在，请刷新版本列表。', reason: 'versionNotFound' }
  }
  if (message.includes('run not found') || message.includes('evolution run not found') || (context === 'run' && notFound)) {
    return { type: 'warning', message: '运行不存在，请刷新列表。', reason: 'runNotFound' }
  }
  return { type: 'error', message: raw || fallback, reason: 'error' }
}

function runActionSuccessMessage(action) {
  if (action === 'resume') return '运行已从断点恢复。'
  if (action === 'promote') return '运行已晋升。'
  if (action === 'reject') return '运行已拒绝。'
  if (action === 'terminate') return '运行已终止。'
  return '运行操作已完成。'
}

function proposalActionSuccessMessage(action) {
  if (action === 'accept') return '提案已接受。'
  if (action === 'reject') return '提案已拒绝。'
  return '提案操作已完成。'
}

function useEvolutionWorkbench(options: LooseRecord = {}) {
  const { apiFetch, apiBase } = options.apiFetch
    ? { apiFetch: options.apiFetch, apiBase: options.apiBase || '/api' }
    : createGameApi(options.apiBase)

  const loading = ref(false)
  const actionLoading = ref('')
  const error = ref('')
  const notice = ref({ type: '', message: '' })
  const runtimeHealth = ref(null)
  const noticeAutoDismiss = createNoticeAutoDismiss(notice, {
    enabled: options.installLifecycle !== false,
    onDismiss(dismissed) {
      if (dismissed.type !== 'error' && error.value === dismissed.message) error.value = ''
    }
  })
  const roles = ref([])
  const versionsByRole = ref({})
  const leaderboardsByRole = ref({})
  const runs = ref([])
  const batches = ref([])
  const selectedRole = ref('')
  const selectedRunId = ref('')
  const selectedRun = ref<LooseRecord | null>(null)
  const selectedDiff = ref([])
  const selectedDiffData = ref(null)
  const selectedProposalReview = ref<LooseRecord>(normalizeProposalReview(null, null, { source: 'none' }))
  const loadedRunArtifacts = ref<Record<string, LooseRecord>>({})
  const selectedGames = ref(emptySampleGames())
  const selectedGameBucket = ref('training')
  const selectedGameId = ref('')
  const selectedVersionId = ref('')
  const selectedVersionDetail = ref<LooseRecord>({
    loading: false,
    error: '',
    data: null
  })
  const trustBundleDrawerOpen = ref(false)
  const trustBundleAudit = ref<LooseRecord>(normalizeTrustBundleAudit({ source: 'review' }))
  const trustBundleAuditLoading = ref(false)
  const trustBundleAuditError = ref('')
  const initialDeepLinkHash = Object.prototype.hasOwnProperty.call(options, 'initialHash')
    ? options.initialHash
    : currentLegacyHash()
  const initialDeepLinkTarget = Object.prototype.hasOwnProperty.call(options, 'initialRoute')
    ? evolutionDeepLinkFromRoute(options.initialRoute)
    : evolutionDeepLinkFromHash(initialDeepLinkHash || '')
  const evolutionDeepLinkTarget = ref<LooseRecord | null>(initialDeepLinkTarget as LooseRecord | null)
  const versionDetailCache = ref({})
  const selectedGameDetail = ref({
    loading: false,
    error: '',
    warning: '',
    archive: null,
    decisions: [],
    events: []
  })
  const selectedSampleState = ref({
    loading: false,
    error: '',
    unsupported: false,
    errorsByBucket: {}
  })
  const selectedBatchRoles = ref([])
  const eventLog = ref([])
  const sse = ref(null)
  const runFilter = ref('')
  const sampleGameFilter = ref('')
  const modelProfilePreflight = ref(null)
  const modelProfilePreflightLoading = ref(false)
  const modelProfilePreflightError = ref('')
  const modelProfiles = ref([])
  const modelProfilesLoading = ref(false)
  const modelProfilesError = ref('')
  const runPageSize = Math.max(1, Number(options.runListLimit || DEFAULT_RUN_PAGE_SIZE))
  const sampleGamePageSize = Math.max(1, Number(options.sampleGameListLimit || DEFAULT_SAMPLE_GAME_PAGE_SIZE))
  const runPagination = ref(createPagination(runPageSize))
  const runLoadingMore = ref(false)
  const sampleGamePagination = ref(samplePaginationMap(sampleGamePageSize))
  const sampleGameLoadingMoreBucket = ref('')
  const roleRequests = createLatestOnlyTracker()
  const versionListRequests = createLatestOnlyMap()
  const leaderboardRequests = createLatestOnlyMap()
  const runListRequests = createLatestOnlyTracker()
  const refreshRequests = createLatestOnlyTracker()
  const runSelectionRequests = createLatestOnlyTracker()
  const diffRequests = createLatestOnlyTracker()
  const proposalReviewRequests = createLatestOnlyTracker()
  const sampleListRequests = createLatestOnlyTracker()
  const sampleDetailRequests = createLatestOnlyTracker()
  const versionDetailRequests = createLatestOnlyTracker()
  const trustBundleRequests = createLatestOnlyTracker()
  const actionRequests = createLatestOnlyTracker()
  const runtimeHealthRequests = createLatestOnlyTracker()
  const modelProfileRequests = createLatestOnlyTracker()
  const modelProfilePreflightRequests = createLatestOnlyTracker()

  const form = ref({
    training_games: 20,
    battle_games: 20,
    max_days: 20,
    auto_promote: true,
    model_profile_id: ''
  })

  const roleRows = computed(() => roles.value.map((role) => {
    const meta = roleMeta(role)
    const versions = versionsByRole.value[role] || []
    const baseline = versions.find((item) => item.is_baseline)
    const leaderboard = leaderboardsByRole.value[role] || []
    const top = leaderboard.find((item) => item.is_baseline) || leaderboard[0]
    return {
      key: role,
      role,
      label: meta.label,
      image: meta.image,
      baseline: baseline?.version_id || '',
      baselineShort: shortId(baseline?.version_id),
      versionCount: versions.length,
      scorePct: top ? top.scorePct : 0,
      winRatePct: top ? top.winRatePct : 0,
      selected: selectedBatchRoles.value.includes(role)
    }
  }))

  const runRows = computed(() => [
    ...runs.value.map(normalizeRun),
    ...batches.value.map(normalizeRun)
  ].sort((a, b) => String(b.started_at || '').localeCompare(String(a.started_at || ''))))
  const filteredRunRows = computed(() => {
    const query = runFilter.value.trim().toLowerCase()
    if (!query) return runRows.value
    return runRows.value.filter((run) =>
      [
        run.id,
        run.role,
        run.displayRole,
        run.status,
        run.statusLabel,
        run.candidate_hash,
        run.parent_hash
      ].some((value) => String(value || '').toLowerCase().includes(query))
    )
  })
  const visibleRunRows = computed(() => filteredRunRows.value)
  const runHasMore = computed(() => Boolean(runPagination.value.has_more))

  const selectedRoleVersions = computed(() => versionsByRole.value[selectedRole.value] || [])
  const selectedVersion = computed(() =>
    selectedRoleVersions.value.find((version) => version.version_id === selectedVersionId.value) || null
  )
  const selectedRoleLeaderboard = computed(() => leaderboardsByRole.value[selectedRole.value] || [])
  const selectedRoleLabel = computed(() => roleMeta(selectedRole.value).label)
  const hasSelection = computed(() => Boolean(selectedRun.value))
  const selectedIsBatch = computed(() => selectedRun.value?.entityType === 'batch')
  const selectedIsRun = computed(() => selectedRun.value?.entityType === 'run')
  const selectedRunSummary = computed(() => {
    const run = selectedRun.value
    if (!run) {
      return {
        id: '',
        entityLabel: '—',
        displayRole: '—',
        statusLabel: '—',
        currentStageLabel: '—',
        overallProgressPercent: 0,
        overallProgressLabel: '等待',
        stageProgressPercent: 0,
        stageProgressLabel: '等待',
        trainingProgressLabel: '等待',
        battleProgressLabel: '等待',
        recommendationLabel: '—',
        parentShort: '—',
        candidateShort: '—',
        publishedReleaseStageLabel: '—',
        trainingGameCompleted: 0,
        trainingGameRequested: 0,
        battleGameCompleted: 0,
        battleGameRequested: 0,
        winRateDeltaPct: 0,
        proposalCount: 0,
        diffCount: 0,
        diagnosticCount: 0,
        warningCount: 0,
        errorCount: 0,
        interrupted: false,
        canResume: false,
        resumeFromStage: ''
      }
    }
    return {
      id: run.id,
      entityLabel: run.entityLabel,
      displayRole: run.displayRole,
      statusLabel: run.statusLabel,
      currentStageLabel: run.currentStageLabel,
      overallProgressPercent: run.overallProgressPercent,
      overallProgressLabel: run.overallProgressLabel,
      stageProgressPercent: run.stageProgressPercent,
      stageProgressLabel: run.stageProgressLabel,
      trainingProgressLabel: run.trainingProgressLabel,
      battleProgressLabel: run.battleProgressLabel,
      recommendationLabel: run.recommendationLabel || recommendationText(run.recommendation),
      parentShort: run.parentShort,
      candidateShort: run.candidateShort,
      publishedReleaseStageLabel: run.publishedReleaseStageLabel,
      trainingGameCompleted: run.trainingGameCompleted,
      trainingGameRequested: run.trainingGameRequested,
      battleGameCompleted: run.battleGameCompleted,
      battleGameRequested: run.battleGameRequested,
      winRateDeltaPct: run.winRateDeltaPct,
      proposalCount: run.proposalCount,
      diffCount: run.diffCount,
      diagnosticCount: run.diagnosticCount,
      warningCount: run.warningCount,
      errorCount: run.errorCount,
      interrupted: run.interrupted,
      canResume: run.canResume,
      resumeFromStage: run.resumeFromStage
    }
  })
  const sampleBuckets = computed(() => [
    { key: 'training', label: SAMPLE_BUCKET_LABELS.training, count: Number(sampleGamePagination.value.training?.total ?? selectedGames.value.training.length) },
    { key: 'baseline', label: SAMPLE_BUCKET_LABELS.baseline, count: Number(sampleGamePagination.value.baseline?.total ?? selectedGames.value.baseline.length) },
    { key: 'candidate', label: SAMPLE_BUCKET_LABELS.candidate, count: Number(sampleGamePagination.value.candidate?.total ?? selectedGames.value.candidate.length) }
  ])
  const selectedGameRows = computed(() =>
    (selectedGames.value[selectedGameBucket.value] || []).map((game) =>
      normalizeSampleGame(game, selectedGameBucket.value)
    )
  )
  const selectedSampleGame = computed(() =>
    selectedGameRows.value.find((game) => game.id === selectedGameId.value) || null
  )
  const selectedSampleHistoryGameId = computed(() =>
    firstTextValue(
      selectedGameDetail.value.archive?.history_game_id,
      selectedGameDetail.value.archive?.historyGameId,
      selectedGameDetail.value.archive?.history_id,
      selectedGameDetail.value.archive?.historyId,
      selectedSampleGame.value?.history_game_id,
      selectedSampleGame.value?.historyGameId,
      selectedSampleGame.value?.history_id,
      selectedSampleGame.value?.historyId
    ) ||
    ''
  )
  const filteredSampleGameRows = computed(() => {
    const query = sampleGameFilter.value.trim().toLowerCase()
    if (!query) return selectedGameRows.value
    return selectedGameRows.value.filter((game) =>
      [
        game.id,
        game.short,
        game.phase,
        game.phaseLabel,
        game.winner,
        game.winnerLabel
      ].some((value) => String(value || '').toLowerCase().includes(query))
    )
  })
  const visibleSampleGameRows = computed(() => filteredSampleGameRows.value)
  const selectedSamplePagination = computed(() =>
    sampleGamePagination.value[selectedGameBucket.value] || createPagination(sampleGamePageSize)
  )
  const sampleGameHasMore = computed(() => Boolean(selectedSamplePagination.value.has_more))
  const sampleGameLoadingMore = computed(() => sampleGameLoadingMoreBucket.value === selectedGameBucket.value)
  const selectedSampleBucketError = computed(() =>
    selectedSampleState.value.errorsByBucket?.[selectedGameBucket.value] || ''
  )
  const selectedSampleHistoryUnavailableReason = computed(() => {
    if (selectedIsBatch.value) return '批量任务没有单局回放，请进入子运行查看样本局。'
    if (!selectedSampleGame.value) return '请先选择一局样本。'
    if (selectedGameDetail.value.loading) return '样本局详情仍在读取。'
    if (!selectedSampleHistoryGameId.value) return '缺少历史对局 ID，无法打开大厅回放或日志。'
    return ''
  })
  const selectedProposalRows = computed(() => selectedProposalReview.value.proposals || [])
  const selectedBaselinePromoteTrustDisabledReason = computed(() => {
    if (!selectedRun.value) return ''
    return baselinePromoteTrustDisabledReason(selectedRun.value, selectedProposalReview.value || {})
  })
  const selectedPromoteDisabledReason = computed(() => {
    if (!selectedRun.value) return '请选择一个运行。'
    if (selectedIsBatch.value) return '批量任务不能直接晋升，请选择子运行。'
    if (!selectedIsRun.value) return '请选择单角色运行。'
    if (selectedRun.value.status !== 'reviewing') return '只有待评审运行可以晋升。'
    const review = selectedProposalReview.value || {}
    if (review.loading) return '提案审核状态读取中。'
    if (review.unsupported) return review.error || '提案审核不可用，无法晋升。'
    if (review.error) return '提案审核读取失败，请刷新后重试。'
    const summary = review.summary || {}
    const accepted = Number(summary.accepted || summary.accepted_count || 0)
    const applied = Number(summary.applied || summary.applied_count || 0)
    if ((Number.isFinite(accepted) ? accepted : 0) + (Number.isFinite(applied) ? applied : 0) <= 0) {
      return '至少接受或应用一个提案后才能晋升。'
    }
    const trustReason = selectedBaselinePromoteTrustDisabledReason.value
    if (trustReason) return trustReason
    return ''
  })
  const selectedCanPromote = computed(() => !selectedPromoteDisabledReason.value)
  const selectedRejectDisabledReason = computed(() => {
    if (!selectedRun.value) return '请选择一个运行。'
    if (selectedIsBatch.value) return '批量任务不能直接拒绝，请选择子运行。'
    if (!selectedIsRun.value) return '请选择单角色运行。'
    if (selectedRun.value.status !== 'reviewing') return '只有待评审运行可以拒绝。'
    return ''
  })
  const selectedCanReject = computed(() => !selectedRejectDisabledReason.value)
  const selectedTerminateDisabledReason = computed(() => {
    if (!selectedRun.value) return '请选择一个运行。'
    if (selectedRun.value.isTerminal) return '运行已结束，不能终止。'
    return ''
  })
  const selectedCanTerminate = computed(() => !selectedTerminateDisabledReason.value)
  const selectedRollbackDisabledReason = computed(() => {
    if (!selectedVersion.value) return '请选择一个版本。'
    return selectedVersion.value.rollbackDisabledReason || ''
  })
  const launchModelProfiles = computed(() =>
    modelProfiles.value
      .filter((profile) => profile?.enabled && profile?.has_api_key)
      .sort((left, right) => Number(Boolean(right?.default_scopes?.evolution)) - Number(Boolean(left?.default_scopes?.evolution)))
  )
  const selectedModelProfile = computed(() =>
    launchModelProfiles.value.find((profile) => profile.profile_id === form.value.model_profile_id) || null
  )
  const modelProfilePreflightHealth = computed(() =>
    runtimeHealthPayloadFromPreflight(modelProfilePreflight.value, 'evolution_start')
  )
  const effectiveRuntimeHealth = computed(() =>
    form.value.model_profile_id && modelProfilePreflightHealth.value
      ? modelProfilePreflightHealth.value
      : runtimeHealth.value
  )
  const runtimeHealthGate = computed(() => runtimeHealthGateSummary(effectiveRuntimeHealth.value, 'evolution_start'))
  const runtimeHealthGateBlocked = computed(() => {
    if (form.value.model_profile_id) {
      if (modelProfilePreflightLoading.value || modelProfilePreflightError.value) return true
      if (!modelProfilePreflight.value) return false
    }
    return runtimeHealthGate.value.disabled
  })
  const runtimeHealthGateReason = computed(() => {
    if (form.value.model_profile_id) {
      if (modelProfilePreflightLoading.value) return '模型 Profile 预检中。'
      if (modelProfilePreflightError.value) return modelProfilePreflightError.value
      if (!modelProfilePreflight.value) return ''
    }
    return runtimeHealthGate.value.reason || runtimeHealthGate.value.warning
  })

  function setError(message) {
    error.value = message || ''
  }

  function setNotice(type, message) {
    notice.value = { type, message }
  }

  function clearNotice() {
    notice.value = { type: '', message: '' }
  }

  function setNoticeFromError(err, fallback, context = '') {
    const next = evolutionNoticeFromError(err, fallback, context)
    setNotice(next.type, next.message)
    return next
  }

  async function loadRuntimeHealth() {
    const token = runtimeHealthRequests.next()
    try {
      const data = await apiFetch('/health')
      if (!token.isLatest()) return false
      runtimeHealth.value = data || null
      return true
    } catch {
      if (token.isLatest()) runtimeHealth.value = null
      return false
    }
  }

  async function loadModelProfilePreflight() {
    const profileId = String(form.value.model_profile_id || '').trim()
    const token = modelProfilePreflightRequests.next()
    modelProfilePreflight.value = null
    modelProfilePreflightError.value = ''
    if (!profileId) {
      modelProfilePreflightLoading.value = false
      return true
    }
    modelProfilePreflightLoading.value = true
    try {
      const query = new URLSearchParams({
        scope: 'evolution_start',
        model_scope: 'evolution',
        model_profile_id: profileId
      })
      const data = await apiFetch(`/health/preflight?${query.toString()}`, { method: 'POST' })
      if (!token.isLatest()) return false
      modelProfilePreflight.value = data || null
      return Boolean(data?.ready)
    } catch (err) {
      if (token.isLatest()) {
        modelProfilePreflight.value = null
        modelProfilePreflightError.value = err?.message || '模型 Profile 预检失败'
      }
      return false
    } finally {
      if (token.isLatest()) modelProfilePreflightLoading.value = false
    }
  }

  async function loadModelProfiles() {
    const token = modelProfileRequests.next()
    modelProfilesLoading.value = true
    modelProfilesError.value = ''
    try {
      const data = await apiFetch('/settings/model-profiles?compact=true')
      if (!token.isLatest()) return false
      const profiles = Array.isArray(data?.profiles) ? data.profiles : []
      modelProfiles.value = profiles
      const launchableProfiles = profiles.filter((profile) => profile?.enabled && profile?.has_api_key)
      if (form.value.model_profile_id && !launchableProfiles.some((profile) => profile.profile_id === form.value.model_profile_id)) {
        form.value.model_profile_id = ''
      }
      if (!form.value.model_profile_id) {
        form.value.model_profile_id = launchableProfiles.find((profile) => profile?.default_scopes?.evolution)?.profile_id || ''
      }
      return true
    } catch (err) {
      if (token.isLatest()) {
        modelProfiles.value = []
        modelProfilesError.value = err?.message || '模型 Profile 读取失败'
      }
      return false
    } finally {
      if (token.isLatest()) modelProfilesLoading.value = false
    }
  }

  function clearVersionDetail() {
    selectedVersionId.value = ''
    selectedVersionDetail.value = { loading: false, error: '', data: null }
  }

  function currentTrustBundleAudit(source: string | LooseRecord = 'review', payload: LooseRecord = {}) {
    const input: LooseRecord = typeof source === 'object' && source !== null ? source : { ...payload, source }
    const normalizedSource = shortText(input.source || source || 'review', 'review')
    return normalizeTrustBundleAudit({
      ...input,
      source: normalizedSource,
      run: input.run || selectedRun.value || {},
      review: input.review || selectedProposalReview.value || {},
      version: input.version || (normalizedSource === 'version' ? selectedVersionDetail.value.data : {}) || {}
    })
  }

  function trustBundleAuthorityRunId(audit: LooseRecord = {}, payload: LooseRecord = {}) {
    return firstTextValue(
      payload.run_id,
      payload.runId,
      payload.source_run_id,
      payload.sourceRunId,
      audit.source_run_id,
      selectedRun.value?.run_id,
      selectedRun.value?.id,
      selectedRunId.value
    )
  }

  async function refreshTrustBundleAudit(source: string | LooseRecord = trustBundleAudit.value.source || 'review', payload: LooseRecord = {}) {
    const baseAudit = payload.baseAudit || currentTrustBundleAudit(source, payload)
    const runId = trustBundleAuthorityRunId(baseAudit, payload)
    if (!runId) {
      trustBundleAuditError.value = '缺少来源运行，无法读取权威信任包。'
      trustBundleAudit.value = {
        ...baseAudit,
        authorityStatus: 'unavailable',
        authorityMessage: trustBundleAuditError.value
      }
      return trustBundleAudit.value
    }

    const token = trustBundleRequests.next()
    trustBundleAuditLoading.value = true
    trustBundleAuditError.value = ''
    trustBundleAudit.value = {
      ...baseAudit,
      authorityStatus: 'loading',
      authorityMessage: '正在读取权威信任包。'
    }
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(runId)}/trust-bundle`)
      if (!token.isLatest()) return trustBundleAudit.value
      const authorityAudit = normalizeTrustBundleAudit({
        ...data,
        source: 'authority',
        run: selectedRun.value || { run_id: runId },
        review: selectedProposalReview.value || {},
        version: selectedVersionDetail.value.data || {}
      })
      const consistencyChecks = trustAuditConsistencyChecks(baseAudit, authorityAudit)
      const mismatchLabels = trustAuditMismatches(baseAudit, authorityAudit)
      trustBundleAudit.value = {
        ...authorityAudit,
        cachedAudit: baseAudit,
        authorityStatus: mismatchLabels.length ? 'mismatch' : 'verified',
        authorityMessage: mismatchLabels.length
          ? '权威信任包与当前页面缓存不一致。'
          : '已读取权威信任包。',
        mismatchLabels,
        consistency_checks: consistencyChecks
      }
      return trustBundleAudit.value
    } catch (err) {
      if (!token.isLatest()) return trustBundleAudit.value
      trustBundleAuditError.value = err?.message || '权威信任包读取失败'
      trustBundleAudit.value = {
        ...baseAudit,
        authorityStatus: 'unavailable',
        authorityMessage: trustBundleAuditError.value
      }
      return trustBundleAudit.value
    } finally {
      if (token.isLatest()) trustBundleAuditLoading.value = false
    }
  }

  function openTrustBundleDrawer(source: string | LooseRecord = 'review', payload: LooseRecord = {}) {
    const baseAudit = currentTrustBundleAudit(source, payload)
    trustBundleAudit.value = baseAudit
    trustBundleDrawerOpen.value = true
    const runId = trustBundleAuthorityRunId(baseAudit, payload)
    if (!runId) return Promise.resolve(baseAudit)
    return refreshTrustBundleAudit(source, { ...payload, baseAudit, run_id: runId })
  }

  function closeTrustBundleDrawer() {
    trustBundleDrawerOpen.value = false
  }

  function setEvolutionDeepLinkTarget(target: LooseRecord | null, patch: LooseRecord = {}) {
    if (!target) {
      evolutionDeepLinkTarget.value = null
      return null
    }
    const next = {
      ...target,
      panel: target.panel || evolutionDeepLinkPanel(target),
      ...patch
    }
    evolutionDeepLinkTarget.value = next
    return next
  }

  function consumeEvolutionDeepLink(value = currentLegacyHash()) {
    const target = value && typeof value === 'object'
      ? evolutionDeepLinkFromRoute(value)
      : evolutionDeepLinkFromHash(value)
    if (!target) return null
    const current = evolutionDeepLinkTarget.value
    if (!current || current.query !== target.query || current.status === 'applied') {
      return setEvolutionDeepLinkTarget(target)
    }
    return current
  }

  function proposalDeepLinkResolved(proposalId) {
    const id = String(proposalId || '').trim()
    if (!id) return true
    if (selectedProposalRows.value.some((proposal) =>
      [proposal.apiId, proposal.proposal_id, proposal.id].some((value) => String(value || '') === id)
    )) return true
    return textItems(
      selectedProposalReview.value?.trustBundle?.proposal_ids,
      selectedProposalReview.value?.trustBundle?.proposalIds,
      selectedProposalReview.value?.trust_bundle?.proposal_ids,
      selectedRun.value?.trust_bundle?.proposal_ids,
      selectedRun.value?.trustBundle?.proposalIds
    ).includes(id)
  }

  function gateDeepLinkResolved(gateReportId) {
    const id = String(gateReportId || '').trim()
    if (!id) return true
    const review = selectedProposalReview.value || {}
    const gate = review.gate || {}
    const trustBundle = review.trustBundle || review.trust_bundle || {}
    return [
      gate.gate_report_id,
      gate.gateReportId,
      trustBundle.gate_report_id,
      trustBundle.gateReportId,
      selectedRun.value?.gate_report_id,
      selectedRun.value?.gateReportId,
      selectedRun.value?.trust_bundle?.gate_report_id,
      selectedRun.value?.trustBundle?.gateReportId
    ].some((value) => String(value || '') === id)
  }

  async function applyEvolutionDeepLink(target = evolutionDeepLinkTarget.value) {
    if (!target) return false
    const runId = firstTextValue(target.run_id)
    const explicitRole = firstTextValue(target.role)
    const versionId = firstTextValue(target.version_id)
    const proposalId = firstTextValue(target.proposal_id)
    const gateReportId = firstTextValue(target.gate_report_id)
    const pending = []
    setEvolutionDeepLinkTarget(target, {
      status: 'applying',
      pending: [],
      selected_run_id: selectedRunId.value,
      selected_version_id: selectedVersionId.value,
      message: '正在恢复自进化定位链接。'
    })
    try {
      if (runId && (selectedRunId.value !== runId || !selectedRun.value)) {
        await selectRun(runId)
      }
    } catch (err) {
      pending.push('run')
      setEvolutionDeepLinkTarget(target, {
        status: 'partial',
        pending,
        error: err?.message || '运行详情读取失败',
        selected_run_id: selectedRunId.value,
        selected_version_id: selectedVersionId.value,
        message: '运行目标未能恢复，已保留定位链接待重试。'
      })
      return true
    }

    if (runId && selectedRunId.value !== runId) pending.push('run')

    const role = explicitRole || (versionId ? firstTextValue(selectedRun.value?.role) : '')
    if (role) selectRole(role)
    if (versionId) {
      if (role) {
        await loadVersionDetail(role, versionId)
        if (selectedVersionDetail.value.error) pending.push('version_detail')
      } else {
        selectedVersionId.value = versionId
        pending.push('role')
      }
      if (selectedVersionId.value !== versionId) pending.push('version')
    }

    if (proposalId || gateReportId) {
      if (!selectedRunId.value) {
        pending.push('run')
      } else {
        if (!loadedRunArtifacts.value[selectedRunId.value]?.proposals) {
          await loadProposalReview(selectedRunId.value)
        }
        if (!proposalDeepLinkResolved(proposalId)) pending.push('proposal')
        if (!gateDeepLinkResolved(gateReportId)) pending.push('gate_report')
        trustBundleAudit.value = currentTrustBundleAudit('review')
        trustBundleDrawerOpen.value = true
      }
    }

    const status = pending.length ? 'partial' : 'applied'
    setEvolutionDeepLinkTarget(target, {
      status,
      pending,
      selected_run_id: selectedRunId.value,
      selected_version_id: selectedVersionId.value,
      trust_drawer_open: trustBundleDrawerOpen.value,
      message: status === 'applied'
        ? '自进化定位链接已恢复。'
        : '自进化定位链接已部分恢复，剩余目标保留为待恢复状态。'
    })
    return true
  }

  function handleEvolutionHashChange(event: LooseRecord = {}) {
    const target = consumeEvolutionDeepLink(event.newURL || currentLegacyHash())
    if (target) void applyEvolutionDeepLink(target)
  }

  function clearSampleSelection({ unsupported = false, message = '' } = {}) {
    sampleGameLoadingMoreBucket.value = ''
    selectedGames.value = emptySampleGames()
    sampleGamePagination.value = samplePaginationMap(sampleGamePageSize)
    selectedGameBucket.value = 'training'
    selectedGameId.value = ''
    selectedGameDetail.value = {
      loading: false,
      error: '',
      warning: '',
      archive: null,
      decisions: [],
      events: []
    }
    selectedSampleState.value = {
      loading: false,
      error: message,
      unsupported,
      errorsByBucket: {}
    }
  }

  function clearDiffSelection() {
    selectedDiff.value = []
    selectedDiffData.value = null
  }

  function clearProposalReview({ unsupported = false, message = '' } = {}) {
    selectedProposalReview.value = normalizeProposalReview(null, selectedRun.value, {
      source: unsupported ? 'unsupported' : 'run-detail',
      unsupported,
      error: message
    })
  }

  function selectRole(role) {
    if (!role) return
    if (selectedRole.value !== role) clearVersionDetail()
    selectedRole.value = role
  }

  async function loadRoles({ includeOverview = false } = {}) {
    const token = roleRequests.next()
    if (includeOverview) try {
      const overview = await apiFetch('/roles/overview', { signal: token.signal })
      if (!token.isLatest()) return false
      roles.value = overview.roles || []
      if (!selectedRole.value && roles.value.length) selectedRole.value = roles.value[0]
      if (!selectedBatchRoles.value.length) selectedBatchRoles.value = roles.value.slice()
      const overviewVersions = overview.versions || {}
      const overviewLeaderboards = overview.leaderboards || {}
      versionsByRole.value = Object.fromEntries(
        roles.value.map((role) => [role, (overviewVersions[role] || []).map(normalizeVersion)])
      )
      leaderboardsByRole.value = Object.fromEntries(
        roles.value.map((role) => [role, (overviewLeaderboards[role]?.entries || []).map(normalizeLeaderboardEntry)])
      )
      return token.isLatest()
    } catch {
      // Keep compatibility with frontend mock data and older backend instances.
    }

    const data = await apiFetch('/roles', { signal: token.signal })
    if (!token.isLatest()) return false
    roles.value = data.roles || []
    if (!selectedRole.value && roles.value.length) selectedRole.value = roles.value[0]
    if (!selectedBatchRoles.value.length) selectedBatchRoles.value = roles.value.slice()
    return token.isLatest()
  }

  async function loadVersions(role) {
    if (!role) return
    const token = versionListRequests.next(role)
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/versions`, { signal: token.signal })
      if (!token.isLatest()) return
      versionsByRole.value = {
        ...versionsByRole.value,
        [role]: (data.versions || []).map(normalizeVersion)
      }
    } catch {
      if (token.isLatest()) versionsByRole.value = { ...versionsByRole.value, [role]: [] }
    }
  }

  async function loadLeaderboard(role) {
    if (!role) return
    const token = leaderboardRequests.next(role)
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/leaderboard`, { signal: token.signal })
      if (!token.isLatest()) return
      leaderboardsByRole.value = {
        ...leaderboardsByRole.value,
        [role]: (data.entries || []).map(normalizeLeaderboardEntry)
      }
    } catch {
      if (token.isLatest()) leaderboardsByRole.value = { ...leaderboardsByRole.value, [role]: [] }
    }
  }

  function runListQuery(offset = 0) {
    const params = new URLSearchParams()
    params.set('limit', String(runPageSize))
    params.set('offset', String(Math.max(0, offset || 0)))
    params.set('source', 'evolution')
    return `?${params.toString()}`
  }

  async function fetchRunPage(offset = 0, signal: AbortSignal | undefined = undefined) {
    const data = await apiFetch(`/evolution-runs${runListQuery(offset)}`, { signal })
    const pageRuns = data.runs || []
    const pageBatches = (data.batches || []).filter(isEvolutionBatch)
    return {
      pageRuns,
      pageBatches,
      pagination: paginationFromResponse(data, [...pageRuns, ...pageBatches], { offset, limit: runPageSize })
    }
  }

  async function fetchRunDetail(id, fallback = null, signal: AbortSignal | undefined = undefined) {
    try {
      return normalizeRun(await apiFetch(`/evolution-runs/${encodeURIComponent(id)}`, { signal }))
    } catch (err) {
      if (fallback) return normalizeRun(fallback)
      throw err
    }
  }

  function rememberRunDetail(run) {
    if (!run?.id) return
    if (run.entityType === 'batch') {
      if (!batches.value.some((item) => (item.batch_id || item.id) === run.id)) {
        batches.value = mergeById(batches.value, [run], ['batch_id', 'id']).filter(isEvolutionBatch)
      }
      return
    }
    if (!runs.value.some((item) => (item.run_id || item.id) === run.id)) {
      runs.value = mergeById(runs.value, [run], ['run_id', 'id'])
    }
  }

  async function loadRuns({ append = false, selectFirst = true } = {}) {
    const token = runListRequests.next()
    if (!append) runLoadingMore.value = false
    const offset = append ? runPagination.value.offset + runPagination.value.returned : 0
    const { pageRuns, pageBatches, pagination } = await fetchRunPage(offset, token.signal)
    if (!token.isLatest()) return false
    runs.value = append ? mergeById(runs.value, pageRuns, 'run_id') : pageRuns
    batches.value = append ? mergeById(batches.value, pageBatches, 'batch_id').filter(isEvolutionBatch) : pageBatches
    runPagination.value = pagination
    if (selectFirst && !selectedRunId.value && runRows.value.length) {
      await selectRun(runRows.value[0].id)
    } else if (selectedRunId.value) {
      const current = runRows.value.find((item) => item.id === selectedRunId.value)
      if (current && (!selectedRun.value || selectedRun.value.id !== current.id)) selectedRun.value = current
    }
    return token.isLatest()
  }

  async function loadMoreRuns() {
    if (runLoadingMore.value || !runPagination.value.has_more) return
    const token = runListRequests.next()
    runLoadingMore.value = true
    clearNotice()
    try {
      const offset = runPagination.value.offset + runPagination.value.returned
      const { pageRuns, pageBatches, pagination } = await fetchRunPage(offset, token.signal)
      if (!token.isLatest()) return
      runs.value = mergeById(runs.value, pageRuns, 'run_id')
      batches.value = mergeById(batches.value, pageBatches, 'batch_id').filter(isEvolutionBatch)
      runPagination.value = pagination
      if (selectedRunId.value) {
        const current = runRows.value.find((item) => item.id === selectedRunId.value)
        if (current && (!selectedRun.value || selectedRun.value.id !== current.id)) selectedRun.value = current
      }
      setNotice('success', pageRuns.length + pageBatches.length ? '已加载更多运行记录。' : '没有更多运行记录。')
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '运行记录读取失败', 'run')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) runLoadingMore.value = false
    }
  }

  async function refreshAll({ silent = false } = {}) {
    const refreshToken = refreshRequests.next()
    const token = runListRequests.next()
    const deepLinkTarget = consumeEvolutionDeepLink() || evolutionDeepLinkTarget.value
    runLoadingMore.value = false
    if (!silent) loading.value = true
    setError('')
    try {
      await Promise.all([loadRoles({ includeOverview: true }), loadModelProfiles()])
      if (!token.isLatest()) return
      if (selectedRole.value && !versionsByRole.value[selectedRole.value]) {
        await loadVersions(selectedRole.value)
      }
      const { pageRuns, pageBatches, pagination } = await fetchRunPage(0, token.signal)
      if (!token.isLatest()) return
      runs.value = pageRuns
      batches.value = pageBatches
      runPagination.value = pagination
      const deepLinkApplied = await applyEvolutionDeepLink(deepLinkTarget)
      if (!deepLinkApplied && !selectedRunId.value && runRows.value.length) {
        await selectRun(runRows.value[0].id)
      } else if (!deepLinkApplied && selectedRunId.value) {
        const current = runRows.value.find((item) => item.id === selectedRunId.value)
        if (current) await selectRun(selectedRunId.value)
      }
    } catch (err) {
      if (refreshToken.isLatest()) setError(err?.message || '自进化数据读取失败')
    } finally {
      if (refreshToken.isLatest()) loading.value = false
    }
  }

  async function selectRun(id) {
    if (!id) return
    const token = runSelectionRequests.next()
    selectedRunId.value = id
    const row = runRows.value.find((item) => item.id === id)
    const loaded = await fetchRunDetail(id, row, token.signal)
    if (!token.isLatest() || selectedRunId.value !== id) return
    selectedRun.value = loaded
    rememberRunDetail(loaded)
    if (selectedRun.value?.role) selectRole(selectedRun.value.role)
    loadedRunArtifacts.value = { ...loadedRunArtifacts.value, [id]: {} }
    clearDiffSelection()
    clearProposalReview()
    clearSampleSelection()
    if (selectedRun.value?.entityType === 'batch') {
      clearDiffSelection()
      clearProposalReview({
        unsupported: true,
        message: '批量任务不直接提供逐条提案评审，请进入子运行查看。'
      })
      clearSampleSelection({
        unsupported: true,
        message: '批量任务不直接提供样本局和 diff，请在子运行中查看单角色详情。'
      })
    }
    if (!token.isLatest() || selectedRunId.value !== id) return
    if (selectedRun.value?.isActive) {
      connect(id)
    }
  }

  async function loadDiff(id = selectedRunId.value, { parentToken = null } = {}) {
    if (!id) return
    const token = diffRequests.next()
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/diff`, { signal: token.signal })
      if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return
      // Legacy flat array format
      selectedDiff.value = data.diffs || data.diff || []
      // Full structured KnowledgeDiff object (may coexist with legacy fields)
      if (data.skill_changes || data.patterns_added || data.patterns_removed || data.patterns_updated || data.metrics_delta) {
        selectedDiffData.value = {
          skill_changes: data.skill_changes || [],
          patterns_added: data.patterns_added || [],
          patterns_removed: data.patterns_removed || [],
          patterns_updated: data.patterns_updated || [],
          metrics_delta: data.metrics_delta || null
        }
      } else if (data.diff_data) {
        // Nested diff_data wrapper
        selectedDiffData.value = {
          skill_changes: data.diff_data.skill_changes || [],
          patterns_added: data.diff_data.patterns_added || [],
          patterns_removed: data.diff_data.patterns_removed || [],
          patterns_updated: data.diff_data.patterns_updated || [],
          metrics_delta: data.diff_data.metrics_delta || null
        }
      } else {
        selectedDiffData.value = null
      }
      loadedRunArtifacts.value = {
        ...loadedRunArtifacts.value,
        [id]: { ...(loadedRunArtifacts.value[id] || {}), diff: true }
      }
    } catch {
      if (token.isLatest() && (!parentToken || parentToken.isLatest()) && selectedRunId.value === id) {
        selectedDiff.value = []
        selectedDiffData.value = null
      }
    }
  }

  async function loadProposalReview(id = selectedRunId.value, { parentToken = null } = {}) {
    if (!id) return
    const token = proposalReviewRequests.next()
    selectedProposalReview.value = {
      ...normalizeProposalReview(null, selectedRun.value, { source: 'run-detail' }),
      loading: true,
      error: ''
    }
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/proposals`, { signal: token.signal })
      if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return
      selectedProposalReview.value = normalizeProposalReview(data, selectedRun.value, { source: 'api' })
      loadedRunArtifacts.value = {
        ...loadedRunArtifacts.value,
        [id]: { ...(loadedRunArtifacts.value[id] || {}), proposals: true }
      }
    } catch (err) {
      if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return
      const missing = isMissingProposalEndpoint(err)
      selectedProposalReview.value = normalizeProposalReview(null, selectedRun.value, {
        source: 'run-detail',
        unsupported: missing,
        error: missing ? '' : (err?.message || '提案评审读取失败')
      })
    }
  }

  function sampleGameParams(bucket = selectedGameBucket.value) {
    const params = new URLSearchParams()
    if (bucket === 'training') {
      params.set('phase', 'training')
    } else {
      params.set('phase', 'battle')
      params.set('side', bucket)
    }
    return params
  }

  function sampleGameListQuery(bucket = selectedGameBucket.value, offset = 0) {
    const params = sampleGameParams(bucket)
    params.set('limit', String(sampleGamePageSize))
    params.set('offset', String(Math.max(0, offset || 0)))
    return `?${params.toString()}`
  }

  async function fetchSampleGamePage(id, bucket, offset = 0, signal: AbortSignal | undefined = undefined) {
    const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/games${sampleGameListQuery(bucket, offset)}`, { signal })
    const rows = data.games || []
    return {
      rows,
      pagination: paginationFromResponse(data, rows, { offset, limit: sampleGamePageSize })
    }
  }

  async function loadRunGames(
    id = selectedRunId.value,
    { parentToken = null, bucket = selectedGameBucket.value, force = false } = {}
  ) {
    if (!id) return
    const targetBucket = SAMPLE_GAME_BUCKETS.includes(bucket) ? bucket : 'training'
    const loadedBuckets = loadedRunArtifacts.value[id]?.sampleBuckets || {}
    if (!force && loadedBuckets[targetBucket]) return true
    const token = sampleListRequests.next()
    sampleGameLoadingMoreBucket.value = ''
    selectedSampleState.value = {
      loading: true,
      error: '',
      unsupported: false,
      errorsByBucket: {}
    }
    let page
    try {
      page = { bucket: targetBucket, ...(await fetchSampleGamePage(id, targetBucket, 0, token.signal)), error: '' }
    } catch (err) {
      page = {
        bucket: targetBucket,
        rows: [],
        pagination: createPagination(sampleGamePageSize),
        error: err?.message || `${SAMPLE_BUCKET_LABELS[targetBucket] || targetBucket}样本局读取失败`
      }
    }
    if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return false
    const errorsByBucket = {
      ...selectedSampleState.value.errorsByBucket,
      [targetBucket]: page.error
    }
    selectedGames.value = { ...selectedGames.value, [targetBucket]: page.rows || [] }
    sampleGamePagination.value = {
      ...sampleGamePagination.value,
      [targetBucket]: page.pagination || createPagination(sampleGamePageSize)
    }
    selectedSampleState.value = {
      loading: false,
      error: page.error || '',
      unsupported: false,
      errorsByBucket
    }
    loadedRunArtifacts.value = {
      ...loadedRunArtifacts.value,
      [id]: {
        ...(loadedRunArtifacts.value[id] || {}),
        sampleBuckets: { ...loadedBuckets, [targetBucket]: !page.error }
      }
    }
    selectedGameBucket.value = targetBucket
    const currentList = selectedGames.value[targetBucket] || []
    const hasCurrent = currentList.some((game) => (game.game_id || game.id) === selectedGameId.value)
    if (!hasCurrent) {
      selectedGameId.value = currentList[0]?.game_id || currentList[0]?.id || ''
    }
    if (selectedGameId.value) {
      await loadSampleGameDetail(selectedGameBucket.value, selectedGameId.value)
    } else {
      selectedGameDetail.value = { loading: false, error: '', warning: '', archive: null, decisions: [], events: [] }
    }
    return token.isLatest()
  }

  function sampleGameQuery(bucket = selectedGameBucket.value) {
    return sampleGameParams(bucket).toString()
  }

  async function loadMoreSampleGames(bucket = selectedGameBucket.value) {
    const runId = selectedRunId.value
    const pagination = sampleGamePagination.value[bucket] || createPagination(sampleGamePageSize)
    if (!runId || selectedIsBatch.value || sampleGameLoadingMoreBucket.value || !pagination.has_more) return
    const token = sampleListRequests.next()
    sampleGameLoadingMoreBucket.value = bucket
    clearNotice()
    try {
      const offset = pagination.offset + pagination.returned
      const { rows, pagination: nextPagination } = await fetchSampleGamePage(runId, bucket, offset, token.signal)
      if (!token.isLatest() || selectedRunId.value !== runId) return
      selectedGames.value = {
        ...selectedGames.value,
        [bucket]: mergeById(selectedGames.value[bucket] || [], rows, ['game_id', 'id'])
      }
      sampleGamePagination.value = {
        ...sampleGamePagination.value,
        [bucket]: nextPagination
      }
      selectedSampleState.value = {
        ...selectedSampleState.value,
        error: '',
        errorsByBucket: {
          ...selectedSampleState.value.errorsByBucket,
          [bucket]: ''
        }
      }
      setNotice('success', `已加载更多${SAMPLE_BUCKET_LABELS[bucket] || bucket}样本局。`)
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, `${SAMPLE_BUCKET_LABELS[bucket] || bucket}样本局读取失败`, 'run')
        const message = next.message
        selectedSampleState.value = {
          ...selectedSampleState.value,
          error: message,
          errorsByBucket: {
            ...selectedSampleState.value.errorsByBucket,
            [bucket]: message
          }
        }
      }
    } finally {
      if (token.isLatest()) sampleGameLoadingMoreBucket.value = ''
    }
  }

  async function loadSampleGameDetail(bucket = selectedGameBucket.value, gameId = selectedGameId.value) {
    const runId = selectedRunId.value
    if (!runId || !gameId || selectedIsBatch.value) return
    const token = sampleDetailRequests.next()
    selectedGameDetail.value = {
      ...selectedGameDetail.value,
      loading: true,
      error: '',
      warning: ''
    }
    const base = `/evolution-runs/${encodeURIComponent(runId)}/games/${encodeURIComponent(gameId)}`
    const query = sampleGameQuery(bucket)
    try {
      const [archiveResult, decisionsResult, eventsResult] = await Promise.allSettled([
        apiFetch(`${base}/archive?${query}`, { signal: token.signal }),
        apiFetch(`${base}/decisions?${query}`, { signal: token.signal }),
        apiFetch(`${base}/events?${query}`, { signal: token.signal })
      ])
      if (!token.isLatest() || selectedRunId.value !== runId || selectedGameBucket.value !== bucket || selectedGameId.value !== gameId) return
      const archive = archiveResult.status === 'fulfilled' ? archiveResult.value : null
      const decisions = decisionsResult.status === 'fulfilled' ? decisionsResult.value : { decisions: [] }
      const events = eventsResult.status === 'fulfilled' ? eventsResult.value : { events: [] }
      const failures = [
        archiveResult.status === 'rejected' ? '档案' : '',
        decisionsResult.status === 'rejected' ? '决策' : '',
        eventsResult.status === 'rejected' ? '事件' : ''
      ].filter(Boolean)
      selectedGameDetail.value = {
        loading: false,
        error: failures.length === 3 ? '样本局详情读取失败' : '',
        warning: failures.length && failures.length < 3 ? `${failures.join('、')}读取失败，当前仅展示可用详情。` : '',
        archive,
        decisions: decisions?.decisions || [],
        events: events?.events || []
      }
    } catch (err) {
      if (token.isLatest()) {
        selectedGameDetail.value = {
          loading: false,
          error: err?.message || '样本局详情读取失败',
          warning: '',
          archive: null,
          decisions: [],
          events: []
        }
      }
    }
  }

  async function selectSampleGame(bucket, gameId = null) {
    if (!bucket) return
    selectedGameBucket.value = bucket
    await loadRunGames(selectedRunId.value, { bucket })
    const rows = selectedGames.value[bucket] || []
    selectedGameId.value = gameId || rows[0]?.game_id || rows[0]?.id || ''
    if (selectedGameId.value) {
      await loadSampleGameDetail(bucket, selectedGameId.value)
    } else {
      selectedGameDetail.value = { loading: false, error: '', warning: '', archive: null, decisions: [], events: [] }
    }
  }

  async function loadVersionDetail(role = selectedRole.value, versionId = selectedVersionId.value) {
    if (!role || !versionId) return
    const key = `${role}:${versionId}`
    selectedVersionId.value = versionId
    if (versionDetailCache.value[key]) {
      selectedVersionDetail.value = {
        loading: false,
        error: '',
        data: versionDetailCache.value[key]
      }
      return
    }
    const token = versionDetailRequests.next()
    selectedVersionDetail.value = {
      loading: true,
      error: '',
      data: selectedVersionDetail.value.data?.version_id === versionId ? selectedVersionDetail.value.data : null
    }
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/versions/${encodeURIComponent(versionId)}`, { signal: token.signal })
      if (!token.isLatest() || selectedRole.value !== role || selectedVersionId.value !== versionId) return
      versionDetailCache.value = {
        ...versionDetailCache.value,
        [key]: data
      }
      selectedVersionDetail.value = { loading: false, error: '', data }
    } catch (err) {
      if (token.isLatest()) {
        selectedVersionDetail.value = {
          loading: false,
          error: err?.message || '版本详情读取失败',
          data: null
        }
      }
    }
  }

  function closeEventStream() {
    evolutionStream.closeAll()
    sse.value = null
  }

  function resetLastEventId(id) {
    evolutionStream.resetEventId(id)
  }

  const evolutionStream = createResumableEventSource({
    events: ['progress', 'reviewing', 'promoted', 'rejected', 'failed', 'completed'],
    backoff: true,
    makeUrl(id, lastEventId) {
      const base = `${apiBase}/evolution-runs/${encodeURIComponent(id)}/events`
      return lastEventId ? `${base}?lastEventId=${encodeURIComponent(lastEventId)}` : base
    },
    shouldReconnect(id) {
      const current = runRows.value.find((item) => item.id === id) || selectedRun.value
      return selectedRunId.value === id && Boolean(current?.isActive)
    },
    isTerminal(event) {
      return event.type === 'reviewing' || EVOLUTION_TERMINAL_STATUSES.has(event.type)
    },
    async onEvent({ id, event, payload, source }) {
      const terminal = event.type === 'reviewing' || EVOLUTION_TERMINAL_STATUSES.has(event.type)
      if (terminal) {
        if (sse.value === source) sse.value = null
      }
      eventLog.value = [
        { id: `${Date.now()}-${event.type}`, type: event.type, payload },
        ...eventLog.value
      ].slice(0, 24)
      await loadRuns()
      if (selectedRunId.value === id) {
        if (terminal) {
          const current = runRows.value.find((item) => item.id === id)
          selectedRun.value = normalizeRun({ ...(current || selectedRun.value || {}), ...(payload || {}), run_id: id })
          if (selectedRun.value?.entityType === 'batch') {
            clearDiffSelection()
            clearProposalReview({
              unsupported: true,
              message: '批量任务不直接提供逐条提案评审，请进入子运行查看。'
            })
            clearSampleSelection({
              unsupported: true,
              message: '批量任务不直接提供样本局和 diff，请在子运行中查看单角色详情。'
            })
          } else {
            loadedRunArtifacts.value = { ...loadedRunArtifacts.value, [id]: {} }
          }
          return
        }
        await selectRun(id)
      }
    },
    onError({ id, source }) {
      if (sse.value === source) sse.value = null
    }
  })

  async function ensureEvolutionTabLoaded(tab, { force = false } = {}) {
    const id = selectedRunId.value
    if (!id || selectedIsBatch.value) return
    const loaded = loadedRunArtifacts.value[id] || {}
    if (tab === 'console' && (force || !loaded.diff)) {
      await loadDiff(id)
      return
    }
    if (tab === 'review' && (force || !loaded.proposals)) {
      await loadProposalReview(id)
      return
    }
    if (tab === 'samples') {
      await loadRunGames(id, { bucket: selectedGameBucket.value, force })
      return
    }
    if (tab === 'leaderboard' && selectedRole.value) {
      await loadLeaderboard(selectedRole.value)
      return
    }
    if (tab === 'versions' && selectedRole.value) {
      await loadVersions(selectedRole.value)
    }
  }

  function connect(id) {
    if (!id || typeof EventSource === 'undefined') return
    if (String(id).startsWith('mock-')) return
    const current = runRows.value.find((item) => item.id === id) || selectedRun.value
    if (current && !current.isActive) return
    if (evolutionStream.has(id)) {
      sse.value = evolutionStream.connect(id)
      return
    }
    closeEventStream()
    sse.value = evolutionStream.connect(id)
  }

  function toggleBatchRole(role) {
    const current = selectedBatchRoles.value
    selectedBatchRoles.value = current.includes(role)
      ? current.filter((item) => item !== role)
      : [...current, role]
  }

  function numberField(name, fallback, min = 1) {
    if (form.value[name] === '' || form.value[name] == null) return fallback
    const value = Number(form.value[name])
    return Number.isFinite(value) && value >= min ? Math.floor(value) : fallback
  }

  function autoPromoteField() {
    return Boolean(form.value.auto_promote)
  }

  async function startSingle() {
    if (!selectedRole.value) {
      const message = '请选择一个有基线版本的角色'
      setError(message)
      setNotice('warning', message)
      return
    }
    if (form.value.model_profile_id) {
      await loadModelProfilePreflight()
    }
    if (runtimeHealthGateBlocked.value) {
      const message = runtimeHealthGateReason.value || '运行环境未就绪，不能启动进化任务。'
      setError(message)
      setNotice('warning', message)
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start-single'
    setError('')
    clearNotice()
    let created = null
    try {
      created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [selectedRole.value],
          training_games: numberField('training_games', 20),
          battle_games: numberField('battle_games', 20),
          max_days: numberField('max_days', 20),
          auto_promote: autoPromoteField(),
          ...(String(form.value.model_profile_id || '').trim() ? { model_profile_id: String(form.value.model_profile_id || '').trim() } : {})
        })
      })
      if (!token.isLatest()) return
      resetLastEventId(created.run_id || created.batch_id)
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(created.run_id || created.batch_id)
      if (!token.isLatest()) return
      setNotice('success', '单角色进化已启动。')
    } catch (err) {
      if (token.isLatest()) {
        if (created?.run_id || created?.batch_id) {
          const message = '单角色进化已启动，但列表刷新失败，请手动刷新。'
          setError(message)
          setNotice('warning', message)
        } else {
          const next = setNoticeFromError(err, '启动单角色进化失败', 'run')
          setError(next.message)
        }
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function startBatch() {
    if (!selectedBatchRoles.value.length) {
      const message = '请选择至少一个角色'
      setError(message)
      setNotice('warning', message)
      return
    }
    if (form.value.model_profile_id) {
      await loadModelProfilePreflight()
    }
    if (runtimeHealthGateBlocked.value) {
      const message = runtimeHealthGateReason.value || '运行环境未就绪，不能启动进化任务。'
      setError(message)
      setNotice('warning', message)
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start-batch'
    setError('')
    clearNotice()
    let created = null
    try {
      created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [...selectedBatchRoles.value],
          training_games: numberField('training_games', 20),
          battle_games: numberField('battle_games', 20),
          max_days: numberField('max_days', 20),
          auto_promote: autoPromoteField(),
          ...(String(form.value.model_profile_id || '').trim() ? { model_profile_id: String(form.value.model_profile_id || '').trim() } : {})
        })
      })
      if (!token.isLatest()) return
      resetLastEventId(created.batch_id || created.run_id)
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(created.batch_id || created.run_id)
      if (!token.isLatest()) return
      setNotice('success', '批量进化已启动。')
    } catch (err) {
      if (token.isLatest()) {
        if (created?.run_id || created?.batch_id) {
          const message = '批量进化已启动，但列表刷新失败，请手动刷新。'
          setError(message)
          setNotice('warning', message)
        } else {
          const next = setNoticeFromError(err, '启动批量进化失败', 'run')
          setError(next.message)
        }
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function runAction(id, action) {
    if (!id || !action) return
    const token = actionRequests.next()
    actionLoading.value = `${action}:${id}`
    setError('')
    clearNotice()
    try {
      const result = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action })
      })
      if (!token.isLatest()) return
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(result.run_id || result.batch_id || id)
      if (!token.isLatest()) return
      await loadRoles()
      if (!token.isLatest()) return
      setNotice('success', runActionSuccessMessage(action))
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '操作失败', 'run')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function updateProposal(id, proposalId, action, body = {}) {
    if (!id || !proposalId || !action) return
    const token = actionRequests.next()
    actionLoading.value = `proposal-${action}:${proposalId}`
    setError('')
    clearNotice()
    try {
      const result = await apiFetch(
        `/evolution-runs/${encodeURIComponent(id)}/proposals/${encodeURIComponent(proposalId)}/${encodeURIComponent(action)}`,
        {
          method: 'POST',
          body: JSON.stringify(body)
        }
      )
      if (!token.isLatest()) return
      if (result?.run || result?.run_id || result?.batch_id) {
        selectedRun.value = normalizeRun(result.run || { ...(selectedRun.value || {}), ...(result || {}), run_id: id })
      }
      await loadProposalReview(id)
      if (!token.isLatest()) return
      setNotice('success', proposalActionSuccessMessage(action))
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '提案操作失败', 'proposal')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function acceptProposal(proposal, id = selectedRunId.value) {
    const proposalId = proposal?.apiId || proposal?.proposal_id || proposal?.id
    await updateProposal(id, proposalId, 'accept')
  }

  async function rejectProposal(proposal, id = selectedRunId.value, reason = '', options = {}) {
    const proposalId = proposal?.apiId || proposal?.proposal_id || proposal?.id
    if (isLooseRecord(options)) {
      const tags = textItems(options?.tags, options?.metadata?.tags)
      await updateProposal(id, proposalId, 'reject', {
        reason: reason || 'manual_reject',
        tags
      })
      return
    }
    await updateProposal(id, proposalId, 'reject', {
      reason: reason || 'manual_reject',
      tags: []
    })
  }

  async function applyAcceptedProposals(id = selectedRunId.value) {
    if (!id) return
    const token = actionRequests.next()
    actionLoading.value = `proposal-apply:${id}`
    setError('')
    clearNotice()
    try {
      const result = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/proposals/apply-accepted`, {
        method: 'POST'
      })
      if (!token.isLatest()) return
      if (result?.run || result?.run_id || result?.batch_id) {
        selectedRun.value = normalizeRun(result.run || { ...(selectedRun.value || {}), ...(result || {}), run_id: id })
      }
      await Promise.all([loadProposalReview(id), loadDiff(id)])
      if (!token.isLatest()) return
      setNotice('success', '已应用接受提案。')
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '应用已接受提案失败', 'proposal')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function rollback(role, versionId) {
    if (!role || !versionId) return
    const token = actionRequests.next()
    actionLoading.value = `rollback:${role}:${versionId}`
    setError('')
    clearNotice()
    try {
      await apiFetch(`/roles/${encodeURIComponent(role)}/rollback/${encodeURIComponent(versionId)}`, {
        method: 'POST'
      })
      if (!token.isLatest()) return
      await Promise.all([loadVersions(role), loadLeaderboard(role), loadRuns()])
      if (!token.isLatest()) return
      setNotice('success', '基线版本已回滚。')
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '回滚基线失败', 'version')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  if (options.installLifecycle !== false) {
    let removeEvolutionHashChangeListener = () => {}
    onMounted(() => {
      consumeEvolutionDeepLink()
      removeEvolutionHashChangeListener = addLegacyHashChangeListener(handleEvolutionHashChange)
    })
    onBeforeUnmount(() => {
      closeEventStream()
      noticeAutoDismiss.dispose()
      removeEvolutionHashChangeListener()
      removeEvolutionHashChangeListener = () => {}
    })
  }

  return {
    loading,
    actionLoading,
    error,
    notice,
    roles,
    roleRows,
    versionsByRole,
    leaderboardsByRole,
    runs,
    batches,
    runRows,
    filteredRunRows,
    visibleRunRows,
    runPagination,
    runLoadingMore,
    runHasMore,
    runFilter,
    selectedRole,
    selectRole,
    selectedRoleLabel,
    selectedRoleVersions,
    selectedVersion,
    selectedVersionId,
    selectedVersionDetail,
    evolutionDeepLinkTarget,
    trustBundleDrawerOpen,
    trustBundleAudit,
    trustBundleAuditLoading,
    trustBundleAuditError,
    selectedRoleLeaderboard,
    selectedRunId,
    selectedRun,
    selectedIsBatch,
    selectedIsRun,
    selectedRunSummary,
    selectedDiff,
    selectedDiffData,
    selectedProposalReview,
    selectedProposalRows,
    selectedCanPromote,
    selectedPromoteDisabledReason,
    selectedCanReject,
    selectedRejectDisabledReason,
    selectedCanTerminate,
    selectedTerminateDisabledReason,
    selectedRollbackDisabledReason,
    runtimeHealth,
    runtimeHealthGate,
    runtimeHealthGateBlocked,
    runtimeHealthGateReason,
    loadRuntimeHealth,
    modelProfiles,
    launchModelProfiles,
    selectedModelProfile,
    modelProfilePreflight,
    modelProfilePreflightLoading,
    modelProfilePreflightError,
    loadModelProfilePreflight,
    modelProfilesLoading,
    modelProfilesError,
    loadModelProfiles,
    baselinePromoteTrustDisabledReason: selectedBaselinePromoteTrustDisabledReason,
    selectedGames,
    sampleBuckets,
    selectedGameBucket,
    selectedGameId,
    selectedGameRows,
    selectedSampleGame,
    selectedSampleHistoryGameId,
    filteredSampleGameRows,
    visibleSampleGameRows,
    sampleGamePagination,
    selectedSamplePagination,
    sampleGameHasMore,
    sampleGameLoadingMore,
    sampleGameFilter,
    selectedGameDetail,
    selectedSampleState,
    selectedSampleBucketError,
    selectedSampleHistoryUnavailableReason,
    selectedBatchRoles,
    eventLog,
    form,
    hasSelection,
    refreshAll,
    selectRun,
    loadMoreRuns,
    startSingle,
    startBatch,
    runAction,
    loadProposalReview,
    ensureEvolutionTabLoaded,
    consumeEvolutionDeepLink,
    applyEvolutionDeepLink,
    acceptProposal,
    rejectProposal,
    applyAcceptedProposals,
    rollback,
    selectSampleGame,
    loadMoreSampleGames,
    loadSampleGameDetail,
    loadVersionDetail,
    openTrustBundleDrawer,
    refreshTrustBundleAudit,
    closeTrustBundleDrawer,
    toggleBatchRole,
    shortId,
    sourceText,
    statusText,
    roleMeta
  }
}

export { useEvolutionWorkbench, statusText, shortId, roleMeta, sourceText }

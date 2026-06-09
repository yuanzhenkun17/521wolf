// @ts-nocheck
const KIND_LABELS = {
  game: 'Archive',
  run: 'Run',
  proposal: 'Proposal',
  gate: 'Gate',
  version: 'Version'
}

function textValue(value) {
  if (value === null || value === undefined) return ''
  const text = String(value).trim()
  return text || ''
}

function firstText(...values) {
  for (const value of values) {
    const text = textValue(value)
    if (text) return text
  }
  return ''
}

function sourceContext(source = {}) {
  const existing = source.evidence_source && typeof source.evidence_source === 'object'
    ? source.evidence_source
    : {}
  const config = source.config && typeof source.config === 'object' ? source.config : {}
  return { existing, config }
}

function normalizeEvidenceSourceKey(value) {
  const key = textValue(value).toLowerCase()
  if (key === 'bench' || key === 'eval' || key === 'evaluation') return 'benchmark'
  if (key === 'evo' || key === 'role_evolution' || key === 'self_evolution' || key === 'self-evolution') {
    return 'evolution'
  }
  return key
}

function sourceEvidenceKey(source = {}) {
  const { existing, config } = sourceContext(source)
  const explicit = normalizeEvidenceSourceKey(firstText(
    existing.log_source,
    source.log_source,
    config.log_source,
    existing.source,
    source.source,
    config.source
  ))
  if (explicit) return explicit

  const benchmarkId = firstText(
    source.batch_id,
    existing.batch_id,
    config.batch_id,
    source.benchmark_batch_id,
    existing.benchmark_batch_id,
    config.benchmark_batch_id,
    source.result_batch_id,
    existing.result_batch_id,
    config.result_batch_id,
    source.benchmark_id,
    existing.benchmark_id,
    config.benchmark_id
  )
  if (benchmarkId) return 'benchmark'

  const evolutionId = firstText(source.evolution_run_id, existing.evolution_run_id, config.evolution_run_id)
  if (evolutionId || proposalEvidenceId(source) || gateEvidenceId(source) || versionEvidenceId(source)) {
    return 'evolution'
  }

  const runId = runEvidenceId(source).toLowerCase()
  if (/^(bench|benchmark)[-_]/.test(runId)) return 'benchmark'
  if (/^(evo|evolution|mock-evo)[-_]/.test(runId)) return 'evolution'
  return 'normal'
}

function buildHashLink(route, params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    const text = textValue(value)
    if (text) query.set(key, text)
  })
  const queryString = query.toString()
  return queryString ? `#${route}?${queryString}` : `#${route}`
}

function disabledEvidenceLink(kind, reason, { label = '', id = '' } = {}) {
  return {
    kind,
    label: label || KIND_LABELS[kind] || 'Evidence',
    id: textValue(id),
    href: '',
    disabled: true,
    unavailableReason: reason
  }
}

function enabledEvidenceLink(kind, href, { label = '', id = '', params = {} } = {}) {
  return {
    kind,
    label: label || KIND_LABELS[kind] || 'Evidence',
    id: textValue(id),
    href,
    params,
    disabled: false,
    unavailableReason: ''
  }
}

function availabilityReason(source = {}, kind = '') {
  const { existing } = sourceContext(source)
  const sourceKey = sourceEvidenceKey(source)
  const genericReason = firstText(
    source.evidence_unavailable_reason,
    existing.evidence_unavailable_reason,
    source.unavailable_reason,
    existing.unavailable_reason
  )
  if (genericReason) return genericReason
  if (kind === 'game' && (source.archive_available === false || existing.archive_available === false)) {
    return firstText(source.archive_unavailable_reason, existing.archive_unavailable_reason, '对局档案当前不可用。')
  }
  if (kind === 'run' && sourceKey === 'benchmark' && (source.benchmark_available === false || existing.benchmark_available === false)) {
    return firstText(source.benchmark_unavailable_reason, existing.benchmark_unavailable_reason, '评测运行当前不可用。')
  }
  if (kind === 'run' && sourceKey === 'evolution' && (source.evolution_available === false || existing.evolution_available === false)) {
    return firstText(source.evolution_unavailable_reason, existing.evolution_unavailable_reason, 'Evolution 证据当前不可用。')
  }
  if ((kind === 'proposal' || kind === 'gate') && (source.evolution_available === false || existing.evolution_available === false)) {
    return firstText(source.evolution_unavailable_reason, existing.evolution_unavailable_reason, 'Evolution 证据当前不可用。')
  }
  return ''
}

function gameEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  return firstText(
    source.history_game_id,
    existing.history_game_id,
    config.history_game_id,
    source.game_id,
    existing.game_id,
    config.game_id,
    source.evidence_game_id,
    existing.evidence_game_id,
    source.id
  )
}

function runEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  return firstText(
    source.source_run_id,
    existing.source_run_id,
    config.source_run_id,
    source.run_id,
    existing.run_id,
    config.run_id,
    source.evolution_run_id,
    existing.evolution_run_id
  )
}

function benchmarkRunEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  return firstText(
    source.source_run_id,
    existing.source_run_id,
    config.source_run_id,
    source.batch_id,
    existing.batch_id,
    config.batch_id,
    source.benchmark_batch_id,
    existing.benchmark_batch_id,
    config.benchmark_batch_id,
    source.run_id,
    existing.run_id,
    config.run_id
  )
}

function proposalEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  const proposal = source.proposal && typeof source.proposal === 'object' ? source.proposal : {}
  return firstText(
    source.proposal_id,
    existing.proposal_id,
    config.proposal_id,
    proposal.proposal_id,
    proposal.id
  )
}

function gateEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  return firstText(
    source.gate_report_id,
    existing.gate_report_id,
    config.gate_report_id,
    source.gate_id,
    existing.gate_id
  )
}

function versionEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  return firstText(
    source.version_id,
    existing.version_id,
    config.version_id,
    source.role_version_id,
    existing.role_version_id
  )
}

function roleEvidenceId(source = {}) {
  const { existing, config } = sourceContext(source)
  return firstText(source.role, existing.role, config.role)
}

function buildGameEvidenceLink(source = {}, options = {}) {
  const reason = availabilityReason(source, 'game')
  const gameId = gameEvidenceId(source)
  if (reason) return disabledEvidenceLink('game', reason, { ...options, id: gameId })
  if (!gameId) {
    return disabledEvidenceLink('game', '缺少 game_id/history_game_id，无法跳转到对局档案。', options)
  }
  return enabledEvidenceLink('game', buildHashLink('logs', { game_id: gameId, workspace: 'archive' }), {
    ...options,
    id: gameId,
    params: { game_id: gameId, workspace: 'archive' }
  })
}

function buildRunEvidenceLink(source = {}, options = {}) {
  const reason = availabilityReason(source, 'run')
  const sourceKey = sourceEvidenceKey(source)
  const runId = sourceKey === 'benchmark' ? benchmarkRunEvidenceId(source) : runEvidenceId(source)
  if (reason) return disabledEvidenceLink('run', reason, { ...options, id: runId })
  if (!runId) {
    const missingReason = sourceKey === 'benchmark'
      ? '缺少 source_run_id/batch_id，无法跳转到评测运行。'
      : '缺少 source_run_id/run_id，无法定位运行。'
    return disabledEvidenceLink('run', missingReason, options)
  }
  if (sourceKey === 'evolution') {
    return enabledEvidenceLink('run', buildHashLink('evolution', { run_id: runId }), {
      ...options,
      id: runId,
      params: { run_id: runId }
    })
  }
  if (sourceKey === 'benchmark') {
    return enabledEvidenceLink('run', buildHashLink('benchmark', { batch_id: runId }), {
      ...options,
      id: runId,
      params: { batch_id: runId }
    })
  }
  return disabledEvidenceLink('run', '普通对局没有独立 Run 工作台，请在对局档案查看。', {
    ...options,
    id: runId
  })
}

function buildProposalEvidenceLink(source = {}, options = {}) {
  const reason = availabilityReason(source, 'proposal')
  const runId = runEvidenceId(source)
  const proposalId = proposalEvidenceId(source)
  if (reason) return disabledEvidenceLink('proposal', reason, { ...options, id: proposalId })
  if (!proposalId) return disabledEvidenceLink('proposal', '缺少 proposal_id，无法跳转到 Proposal Evidence。', options)
  if (!runId) {
    return disabledEvidenceLink('proposal', '缺少 source_run_id/run_id，无法定位 Proposal Evidence。', {
      ...options,
      id: proposalId
    })
  }
  return enabledEvidenceLink('proposal', buildHashLink('evolution', { run_id: runId, proposal_id: proposalId }), {
    ...options,
    id: proposalId,
    params: { run_id: runId, proposal_id: proposalId }
  })
}

function buildGateEvidenceLink(source = {}, options = {}) {
  const reason = availabilityReason(source, 'gate')
  const runId = runEvidenceId(source)
  const gateId = gateEvidenceId(source)
  if (reason) return disabledEvidenceLink('gate', reason, { ...options, id: gateId })
  if (!gateId) return disabledEvidenceLink('gate', '缺少 gate_report_id，无法跳转到 Promotion Gate。', options)
  if (!runId) return disabledEvidenceLink('gate', '缺少 source_run_id/run_id，无法定位 Promotion Gate。', { ...options, id: gateId })
  return enabledEvidenceLink('gate', buildHashLink('evolution', { run_id: runId, gate_report_id: gateId }), {
    ...options,
    id: gateId,
    params: { run_id: runId, gate_report_id: gateId }
  })
}

function buildVersionEvidenceLink(source = {}, options = {}) {
  const role = roleEvidenceId(source)
  const versionId = versionEvidenceId(source)
  if (!versionId) return disabledEvidenceLink('version', '缺少 version_id，无法跳转到角色版本。', options)
  if (!role) return disabledEvidenceLink('version', '缺少 role，无法定位角色版本。', { ...options, id: versionId })
  return enabledEvidenceLink('version', buildHashLink('evolution', { role, version_id: versionId }), {
    ...options,
    id: versionId,
    params: { role, version_id: versionId }
  })
}

function buildEvidenceLink(source = {}, options = {}) {
  const kind = textValue(options.kind || source.kind || source.evidence_kind || source.type || 'game').toLowerCase()
  if (kind === 'run' || kind === 'source_run') return buildRunEvidenceLink(source, options)
  if (kind === 'proposal') return buildProposalEvidenceLink(source, options)
  if (kind === 'gate' || kind === 'gate_report') return buildGateEvidenceLink(source, options)
  if (kind === 'version' || kind === 'role_version') return buildVersionEvidenceLink(source, options)
  return buildGameEvidenceLink(source, options)
}

function buildEvidenceLinks(source = {}, options = {}) {
  const kinds = Array.isArray(options.kinds) && options.kinds.length
    ? options.kinds
    : ['game', 'run', 'proposal']
  return kinds.map((kind) => buildEvidenceLink(source, { kind, label: options.labels?.[kind] }))
}

export {
  benchmarkRunEvidenceId,
  buildEvidenceLink,
  buildEvidenceLinks,
  buildGameEvidenceLink,
  buildGateEvidenceLink,
  buildHashLink,
  buildProposalEvidenceLink,
  buildRunEvidenceLink,
  buildVersionEvidenceLink,
  gameEvidenceId,
  proposalEvidenceId,
  runEvidenceId,
  sourceEvidenceKey
}

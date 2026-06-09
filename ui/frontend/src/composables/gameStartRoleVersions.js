const EXPERIMENTAL_RELEASE_STAGES = new Set(['shadow', 'canary'])

function roleVersionId(version) {
  return String(version?.version_id || '').trim()
}

function roleVersionReleaseStage(version) {
  return String(
    version?.releaseStage ||
    version?.release_stage ||
    version?.provenance?.release_stage ||
    ''
  ).trim().toLowerCase()
}

function isExperimentalRoleVersion(version) {
  return EXPERIMENTAL_RELEASE_STAGES.has(roleVersionReleaseStage(version))
}

function isGameStartEligibleRoleVersion(version) {
  return Boolean(version) && !isExperimentalRoleVersion(version)
}

function gameStartEligibleRoleVersions(versions = []) {
  return versions.filter(isGameStartEligibleRoleVersion)
}

function latestGameStartRoleVersion(versions = [], baseline = null, { isFallbackVersion = () => false } = {}) {
  const eligibleVersions = gameStartEligibleRoleVersions(versions)
  const candidates = eligibleVersions.filter((version) =>
    version
    && !isFallbackVersion(version)
    && String(version.status || '').trim().toLowerCase() !== 'rejected'
  )
  if (candidates.length) return candidates.at(-1)
  if (isGameStartEligibleRoleVersion(baseline)) return baseline
  return eligibleVersions[0] || null
}

function gameStartRoleVersionState({
  versions = [],
  selectedVersionId = '',
  mode = 'baseline',
  isFallbackVersion = () => false
} = {}) {
  const eligibleVersions = gameStartEligibleRoleVersions(versions)
  const baseline = eligibleVersions.find((version) => version.is_baseline) || eligibleVersions[0] || null
  const selectedId = String(selectedVersionId || '').trim()
  const selectedVersion = selectedId
    ? eligibleVersions.find((version) => roleVersionId(version) === selectedId) || baseline
    : baseline
  const latestVersion = latestGameStartRoleVersion(eligibleVersions, baseline, { isFallbackVersion })
  const effectiveVersion = mode === 'latest'
    ? latestVersion
    : mode === 'custom'
      ? selectedVersion
      : baseline
  return {
    versions: eligibleVersions,
    baseline,
    latestVersion,
    customVersion: selectedVersion,
    effectiveVersion,
    choices: eligibleVersions.filter((version) => roleVersionId(version) !== roleVersionId(baseline)),
    hasOverride: Boolean(
      roleVersionId(effectiveVersion)
      && roleVersionId(baseline)
      && roleVersionId(effectiveVersion) !== roleVersionId(baseline)
    )
  }
}

export {
  gameStartEligibleRoleVersions,
  gameStartRoleVersionState,
  isExperimentalRoleVersion,
  isGameStartEligibleRoleVersion,
  latestGameStartRoleVersion,
  roleVersionReleaseStage
}

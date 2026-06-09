type GameStartRoleVersionMode = 'baseline' | 'latest' | 'custom'

interface GameStartRoleVersionProvenance {
  release_stage?: unknown
  [key: string]: unknown
}

interface GameStartRoleVersion {
  version_id?: unknown
  releaseStage?: unknown
  release_stage?: unknown
  provenance?: GameStartRoleVersionProvenance | null
  is_baseline?: unknown
  status?: unknown
  source?: unknown
  [key: string]: unknown
}

type GameStartRoleVersionPredicate<T extends GameStartRoleVersion = GameStartRoleVersion> = (
  version: T
) => boolean

interface LatestGameStartRoleVersionOptions<T extends GameStartRoleVersion = GameStartRoleVersion> {
  isFallbackVersion?: GameStartRoleVersionPredicate<T>
}

interface GameStartRoleVersionStateOptions<T extends GameStartRoleVersion = GameStartRoleVersion>
  extends LatestGameStartRoleVersionOptions<T> {
  versions?: readonly T[]
  selectedVersionId?: string | number | null
  mode?: GameStartRoleVersionMode
}

interface GameStartRoleVersionState<T extends GameStartRoleVersion = GameStartRoleVersion> {
  versions: T[]
  baseline: T | null
  latestVersion: T | null
  customVersion: T | null
  effectiveVersion: T | null
  choices: T[]
  hasOverride: boolean
}

const EXPERIMENTAL_RELEASE_STAGES: ReadonlySet<string> = new Set(['shadow', 'canary'])

function roleVersionId(version: GameStartRoleVersion | null | undefined): string {
  return String(version?.version_id || '').trim()
}

function roleVersionReleaseStage(version: GameStartRoleVersion | null | undefined): string {
  return String(
    version?.releaseStage ||
    version?.release_stage ||
    version?.provenance?.release_stage ||
    ''
  ).trim().toLowerCase()
}

function isExperimentalRoleVersion(version: GameStartRoleVersion | null | undefined): boolean {
  return EXPERIMENTAL_RELEASE_STAGES.has(roleVersionReleaseStage(version))
}

function isGameStartEligibleRoleVersion<T extends GameStartRoleVersion>(
  version: T | null | undefined
): version is T {
  return Boolean(version) && !isExperimentalRoleVersion(version)
}

function gameStartEligibleRoleVersions<T extends GameStartRoleVersion = GameStartRoleVersion>(
  versions: readonly T[] = []
): T[] {
  return versions.filter(isGameStartEligibleRoleVersion)
}

function latestGameStartRoleVersion<T extends GameStartRoleVersion = GameStartRoleVersion>(
  versions: readonly T[] = [],
  baseline: T | null = null,
  { isFallbackVersion = () => false }: LatestGameStartRoleVersionOptions<T> = {}
): T | null {
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

function gameStartRoleVersionState<T extends GameStartRoleVersion = GameStartRoleVersion>({
  versions = [],
  selectedVersionId = '',
  mode = 'baseline',
  isFallbackVersion = () => false
}: GameStartRoleVersionStateOptions<T> = {}): GameStartRoleVersionState<T> {
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
  type GameStartRoleVersion,
  type GameStartRoleVersionMode,
  type GameStartRoleVersionPredicate,
  type GameStartRoleVersionState,
  type GameStartRoleVersionStateOptions,
  type LatestGameStartRoleVersionOptions,
  gameStartEligibleRoleVersions,
  gameStartRoleVersionState,
  isExperimentalRoleVersion,
  isGameStartEligibleRoleVersion,
  latestGameStartRoleVersion,
  roleVersionReleaseStage
}

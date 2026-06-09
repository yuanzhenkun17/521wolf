import type { EvolutionProposal, EvolutionRun, EvolutionSampleGame, RoleVersion } from '../../types/evolution'

export function evolutionRunId(run: Partial<EvolutionRun> | null | undefined): string {
  return String(run?.run_id || run?.batch_id || run?.id || '')
}

export function activeEvolutionRuns(runs: EvolutionRun[]): EvolutionRun[] {
  return runs.filter((run) => run.isActive)
}

export function reviewableEvolutionRuns(runs: EvolutionRun[]): EvolutionRun[] {
  return runs.filter((run) => run.isReviewing || run.proposalCount > 0)
}

export function baselineVersion(versions: RoleVersion[]): RoleVersion | null {
  return versions.find((version) => Boolean(version.is_baseline)) || versions[0] || null
}

export function rollbackEligibleVersions(versions: RoleVersion[]): RoleVersion[] {
  return versions.filter((version) => !version.rollbackDisabled)
}

export function proposalEvidenceIds(proposals: EvolutionProposal[]): string[] {
  return [...new Set(proposals.flatMap((proposal) => proposal.evidenceGameIds || []).filter(Boolean))]
}

export function sampleGamesByBucket(games: EvolutionSampleGame[]): Record<string, EvolutionSampleGame[]> {
  return games.reduce<Record<string, EvolutionSampleGame[]>>((groups, game) => {
    const key = game.bucket || 'training'
    groups[key] ||= []
    groups[key].push(game)
    return groups
  }, {})
}

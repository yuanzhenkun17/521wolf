import type { BenchmarkDiagnostic, BenchmarkRun, BenchmarkSuite } from '../../types/benchmark'

export function launchableSuites(suites: BenchmarkSuite[]): BenchmarkSuite[] {
  return suites.filter((suite) => suite.launchable)
}

export function benchmarkRunId(run: Partial<BenchmarkRun> | null | undefined): string {
  return String(run?.batch_id || run?.run_id || run?.id || '')
}

export function activeBenchmarkRuns(runs: BenchmarkRun[]): BenchmarkRun[] {
  return runs.filter((run) => run.isActive)
}

export function terminalBenchmarkRuns(runs: BenchmarkRun[]): BenchmarkRun[] {
  return runs.filter((run) => run.isTerminal)
}

export function diagnosticsByLevel(diagnostics: BenchmarkDiagnostic[]): Record<string, BenchmarkDiagnostic[]> {
  return diagnostics.reduce<Record<string, BenchmarkDiagnostic[]>>((groups, diagnostic) => {
    const key = diagnostic.level || 'info'
    groups[key] ||= []
    groups[key].push(diagnostic)
    return groups
  }, {})
}

export function benchmarkEvidenceGameIds(diagnostics: BenchmarkDiagnostic[]): string[] {
  return [...new Set(diagnostics.map((diagnostic) => diagnostic.history_game_id || diagnostic.game_id).filter(Boolean))]
}

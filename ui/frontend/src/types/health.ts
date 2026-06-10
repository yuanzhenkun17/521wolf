export type RuntimeHealthGateScope = 'game_start' | 'benchmark_start' | 'evolution_start' | string

export interface RuntimeHealthGate {
  ready?: boolean
  status?: string
  blockers?: unknown[]
  warnings?: unknown[]
  actions?: unknown[]
  [key: string]: unknown
}

export interface RuntimeHealthPayload {
  schema_version?: number
  ok?: boolean
  status?: string
  ready?: boolean
  mode?: string
  summary?: string
  checks?: Record<string, unknown>
  gates?: Record<string, RuntimeHealthGate | unknown>
  actions?: unknown[]
  external?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface RuntimeHealthGateSummary {
  scope: RuntimeHealthGateScope
  known: boolean
  ready: boolean
  status: string
  blockers: string[]
  warnings: string[]
  actions: string[]
  disabled: boolean
  reason: string
  warning: string
}

export type SettingsScopeKey = 'game_decision' | 'judge' | 'benchmark' | 'evolution' | 'prompt_test'
export type SettingsStatus = 'ok' | 'degraded' | 'error' | 'unknown' | 'stale' | 'untested' | string

export interface ModelProfile {
  profile_id: string
  name: string
  provider: string
  base_url: string
  model: string
  api_key_masked: string
  has_api_key: boolean
  temperature: number | null
  timeout_seconds: number | null
  max_retries: number | null
  enabled: boolean
  default_scopes: Record<string, boolean>
  capabilities: Record<string, boolean>
  metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
  last_tested_at?: string | null
  last_test_status?: SettingsStatus
  last_test_error?: string
  model_config_hash?: string
}

export interface SettingsAdminState {
  enabled: boolean
  token_configured: boolean
  write_available: boolean
}

export interface SettingsScopeOption {
  key: SettingsScopeKey | string
  label: string
}

export interface SettingsVariable {
  key: string
  label: string
  value: string
  state: string
  locked: boolean
  secret: boolean
}

export interface SettingsModelProfilesResponse {
  kind: string
  schema_version: number
  profiles: ModelProfile[]
  env_locks: Record<string, unknown>
  admin: SettingsAdminState
  scopes: SettingsScopeOption[]
  providers: string[]
  variables: SettingsVariable[]
  health: Record<string, unknown>
}

export interface ModelProfilePayload {
  name: string
  provider: string
  base_url: string
  model: string
  api_key?: string | null
  clear_api_key?: boolean
  temperature?: number | null
  timeout_seconds?: number | null
  max_retries?: number | null
  enabled?: boolean
  default_scopes?: Record<string, boolean>
  capabilities?: Record<string, boolean>
  metadata?: Record<string, unknown>
}

export interface ModelProfileResponse {
  kind: string
  schema_version: number
  profile: ModelProfile
}

export interface ModelProfileTestResponse {
  ok: boolean
  status: SettingsStatus
  checked_at: string
  latency_ms: number
  profile_id: string
  model: string
  message: string
  error?: {
    type?: string
    message?: string
  }
}

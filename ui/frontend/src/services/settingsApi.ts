import type { QueryParams, ServiceOptions } from '../types/api'
import type { RuntimeHealthProbeResult } from '../types/health'
import type {
  ModelProfilePayload,
  ModelProfileResponse,
  ModelProfileTestResponse,
  SettingsModelProfilesResponse,
  SettingsRuntimeModelProbeOptions,
  SettingsRuntimeVariablePayload,
  SettingsRuntimeVariableResponse,
  SettingsRuntimeVariablesResponse
} from '../types/settings'
import { defaultApiClient } from './api'

const DEFAULT_RUNTIME_PROBE_SCOPE = 'settings_model_test'

function adminHeaders(token = ''): Record<string, string> {
  const text = String(token || '').trim()
  return text ? { 'X-Settings-Admin-Token': text } : {}
}

function queryText(value: unknown): string | undefined {
  const text = String(value ?? '').trim()
  return text || undefined
}

function normalizeProbeRuntimeModelQuery(options: string | SettingsRuntimeModelProbeOptions = DEFAULT_RUNTIME_PROBE_SCOPE): QueryParams {
  if (typeof options === 'string') {
    return { scope: queryText(options) || DEFAULT_RUNTIME_PROBE_SCOPE }
  }

  return {
    scope: queryText(options.scope) || DEFAULT_RUNTIME_PROBE_SCOPE,
    model_scope: queryText(options.model_scope),
    model_profile_id: queryText(options.model_profile_id)
  }
}

export function createSettingsService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    async listModelProfiles(): Promise<SettingsModelProfilesResponse> {
      return client.fetch('/settings/model-profiles')
    },
    async listRuntimeVariables(): Promise<SettingsRuntimeVariablesResponse> {
      return client.fetch('/settings/runtime-variables')
    },
    async probeRuntimeModel(options: string | SettingsRuntimeModelProbeOptions = DEFAULT_RUNTIME_PROBE_SCOPE): Promise<RuntimeHealthProbeResult> {
      return client.fetch('/health/probes/llm', {
        method: 'POST',
        query: normalizeProbeRuntimeModelQuery(options)
      })
    },
    async updateRuntimeVariable(settingKey: string, payload: SettingsRuntimeVariablePayload, token = ''): Promise<SettingsRuntimeVariableResponse> {
      return client.fetch(`/settings/runtime-variables/${encodeURIComponent(settingKey)}`, {
        method: 'PATCH',
        headers: adminHeaders(token),
        body: payload
      })
    },
    async createModelProfile(payload: ModelProfilePayload, token = ''): Promise<ModelProfileResponse> {
      return client.fetch('/settings/model-profiles', {
        method: 'POST',
        headers: adminHeaders(token),
        body: payload
      })
    },
    async updateModelProfile(profileId: string, payload: Partial<ModelProfilePayload>, token = ''): Promise<ModelProfileResponse> {
      return client.fetch(`/settings/model-profiles/${encodeURIComponent(profileId)}`, {
        method: 'PATCH',
        headers: adminHeaders(token),
        body: payload
      })
    },
    async testModelProfile(profileId: string, token = ''): Promise<ModelProfileTestResponse> {
      return client.fetch(`/settings/model-profiles/${encodeURIComponent(profileId)}/test`, {
        method: 'POST',
        headers: adminHeaders(token)
      })
    },
    async disableModelProfile(profileId: string, token = ''): Promise<ModelProfileResponse> {
      return client.fetch(`/settings/model-profiles/${encodeURIComponent(profileId)}/disable`, {
        method: 'POST',
        headers: adminHeaders(token)
      })
    },
    async deleteModelProfile(profileId: string, token = ''): Promise<{ deleted: boolean; profile_id: string }> {
      return client.fetch(`/settings/model-profiles/${encodeURIComponent(profileId)}`, {
        method: 'DELETE',
        headers: adminHeaders(token)
      })
    }
  }
}

export type SettingsService = ReturnType<typeof createSettingsService>

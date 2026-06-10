import type { ServiceOptions } from '../types/api'
import type {
  ModelProfilePayload,
  ModelProfileResponse,
  ModelProfileTestResponse,
  SettingsModelProfilesResponse,
  SettingsRuntimeVariablePayload,
  SettingsRuntimeVariableResponse,
  SettingsRuntimeVariablesResponse
} from '../types/settings'
import { defaultApiClient } from './api'

function adminHeaders(token = ''): Record<string, string> {
  const text = String(token || '').trim()
  return text ? { 'X-Settings-Admin-Token': text } : {}
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

import { http, type ApiResponse } from './http'

export interface AiProviderConfig {
  id: number | null
  source: 'database' | 'environment'
  base_url: string | null
  model_name: string
  api_key_masked: string | null
  temperature: number
  timeout_seconds: number
  streaming_enabled: boolean
  last_test_status: string | null
  last_test_message: string | null
  last_test_time: string | null
  updated_time: string | null
}

export interface AiProviderConfigInput {
  base_url: string
  model_name: string
  api_key?: string
  temperature: number
  timeout_seconds: number
  streaming_enabled: boolean
}

export interface AiConnectionTest {
  success: boolean
  model_name: string
  latency_ms: number
  message: string
}

export const AI_CAPABILITY_NAMES = [
  'text',
  'embedding',
  'vision',
  'asr',
  'image_generation',
] as const

export type AiCapabilityName = typeof AI_CAPABILITY_NAMES[number]
export type AiUnifiedProviderName = 'dashscope' | 'custom'

export interface AiCapabilityInput {
  enabled: boolean
  base_url: string
  model_name: string
  api_key?: string
  timeout_seconds: number
  dimensions?: number
  temperature?: number
  streaming_enabled?: boolean
}

export type AiCapabilityInputMap = Record<AiCapabilityName, AiCapabilityInput>

export interface AiCapabilityConfig {
  id?: number | null
  capability: AiCapabilityName
  provider_name?: string
  source: 'database' | 'environment' | string
  enabled: boolean
  base_url: string | null
  model_name: string
  api_key_masked?: string | null
  dimensions?: number | null
  temperature?: number | null
  timeout_seconds: number
  streaming_enabled?: boolean | null
  last_test_status: string | null
  last_test_message: string | null
  last_test_time: string | null
  updated_time: string | null
}

export interface AiUnifiedConfig {
  provider_name: AiUnifiedProviderName | string
  api_key_masked: string | null
  capabilities: Partial<Record<AiCapabilityName, AiCapabilityConfig>>
}

export interface AiProviderPreset {
  id: AiUnifiedProviderName | string
  name: string
  description: string
  capabilities: Partial<Record<AiCapabilityName, AiCapabilityInput>>
}

export interface AiProviderPresetList {
  presets: AiProviderPreset[]
}

export interface AiUnifiedConfigInput {
  provider_name: AiUnifiedProviderName
  api_key?: string | null
  capabilities: AiCapabilityInputMap
}

export interface AiCapabilityOperationResult {
  capability: AiCapabilityName
  success: boolean
  skipped: boolean
  latency_ms?: number | null
  message: string
  kept_previous?: boolean
  config?: AiCapabilityConfig | null
}

export interface AiUnifiedConfigOperationResult {
  provider_name: AiUnifiedProviderName | string
  capabilities: Partial<Record<AiCapabilityName, AiCapabilityOperationResult>>
}

export interface AiCallLog {
  id: number
  request_id: string
  user_id: number | null
  username: string | null
  feature: string
  model_name: string
  status: string
  streaming: boolean
  input_chars: number
  output_chars: number
  prompt_tokens: number | null
  completion_tokens: number | null
  latency_ms: number | null
  error_type: string | null
  error_message: string | null
  started_time: string
  finished_time: string | null
}

export interface AiModelTokenUsage {
  model_name: string
  call_count: number
  tokenized_calls: number
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
}

export interface AiOperationSummary {
  total_24h: number
  success_24h: number
  failed_24h: number
  running: number
  average_latency_ms: number | null
  success_rate: number
  active_model: string
  config_source: string
  prompt_tokens_24h?: number | null
  completion_tokens_24h?: number | null
  total_tokens_24h?: number | null
  tokenized_calls_24h?: number
  model_token_usage_24h?: AiModelTokenUsage[]
}

export const aiOperationsApi = {
  // 旧版单一文本模型接口继续保留，供尚未迁移的调用方与部署版本使用。
  config: () => http.get<ApiResponse<AiProviderConfig>>('/admin/ai-operations/config'),
  testConfig: (payload: AiProviderConfigInput) =>
    http.post<ApiResponse<AiConnectionTest>>('/admin/ai-operations/config/test', payload, { timeout: 35_000 }),
  activateConfig: (payload: AiProviderConfigInput) =>
    http.put<ApiResponse<AiProviderConfig>>('/admin/ai-operations/config', payload, { timeout: 35_000 }),
  configPresets: () =>
    http.get<ApiResponse<AiProviderPresetList>>('/admin/ai-operations/config/presets'),
  allConfig: () =>
    http.get<ApiResponse<AiUnifiedConfig>>('/admin/ai-operations/config/all'),
  testAllConfig: (payload: AiUnifiedConfigInput) =>
    http.post<ApiResponse<AiUnifiedConfigOperationResult>>(
      '/admin/ai-operations/config/all/test',
      payload,
      { timeout: 180_000 },
    ),
  activateAllConfig: (payload: AiUnifiedConfigInput) =>
    http.put<ApiResponse<AiUnifiedConfigOperationResult>>(
      '/admin/ai-operations/config/all',
      payload,
      { timeout: 180_000 },
    ),
  calls: (params?: { status?: string; feature?: string; limit?: number }) =>
    http.get<ApiResponse<AiCallLog[]>>('/admin/ai-operations/calls', { params }),
  summary: () => http.get<ApiResponse<AiOperationSummary>>('/admin/ai-operations/summary'),
}

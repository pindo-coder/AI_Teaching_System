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

export interface AiOperationSummary {
  total_24h: number
  success_24h: number
  failed_24h: number
  running: number
  average_latency_ms: number | null
  success_rate: number
  active_model: string
  config_source: string
}

export const aiOperationsApi = {
  config: () => http.get<ApiResponse<AiProviderConfig>>('/admin/ai-operations/config'),
  testConfig: (payload: AiProviderConfigInput) =>
    http.post<ApiResponse<AiConnectionTest>>('/admin/ai-operations/config/test', payload, { timeout: 35_000 }),
  activateConfig: (payload: AiProviderConfigInput) =>
    http.put<ApiResponse<AiProviderConfig>>('/admin/ai-operations/config', payload, { timeout: 35_000 }),
  calls: (params?: { status?: string; feature?: string; limit?: number }) =>
    http.get<ApiResponse<AiCallLog[]>>('/admin/ai-operations/calls', { params }),
  summary: () => http.get<ApiResponse<AiOperationSummary>>('/admin/ai-operations/summary'),
}

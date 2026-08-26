import { http, type ApiResponse } from './http'
import type { LearningStage } from '@/types'

export type AiTaskType =
  | 'question_answer'
  | 'chapter_summary'
  | 'preview_questions'
  | 'review_outline'
  | 'mock_questions'
  | 'note_polish'
  | 'note_expand'
  | 'note_outline'
  | 'note_knowledge_structure'
  | 'note_real_significance'
  | 'note_concept_compare'
  | 'news_study_note'

export type AiWorkspaceMode = 'chat' | 'agent'
export type AiWorkspaceRole = 'student' | 'teacher' | 'admin'

export interface AiSource {
  source_type: string
  source_title: string
  course_id: number
  chapter_id: number
  excerpt: string
  position: string
  document_id: number | null
  vector_id: string | null
  section_path: string | null
  pdf_page_start: number | null
  pdf_page_end: number | null
  paragraph_index: number | null
  printed_page_start: string | null
  printed_page_end: string | null
  evidence_type: string
  material_type: 'central' | 'textbook' | 'local' | string
  publisher: string | null
  published_date: string | null
  source_url: string | null
}

export interface AiAssistData {
  answer: string
  grounded: boolean
  model: string
  sources: AiSource[]
}

export interface AiAssistPayload {
  course_id: number
  chapter_id: number
  learning_stage: LearningStage
  task_type: AiTaskType
  question: string
  attachment_ids?: number[]
}

export interface AiWorkspacePayload {
  mode: AiWorkspaceMode
  role: AiWorkspaceRole
  course_id?: number | null
  chapter_id?: number | null
  chapter_ids?: number[]
  learning_stage?: LearningStage
  task_type?: AiTaskType
  question: string
  attachment_ids?: number[]
  conversation_history?: Array<{ role: 'user' | 'assistant'; content: string }>
}

export interface AiWorkspaceContextCandidate {
  course_id: number
  course_name: string
  teaching_class_id: number | null
  teaching_class_name: string | null
}

export interface AiWorkspaceChapterOption {
  id: number
  title: string
  sort_order: number
}

export interface AiWorkspaceContext {
  course_id: number | null
  course_name: string | null
  chapter_id: number | null
  chapter_title: string | null
  chapter_ids: number[]
  chapter_titles: string[]
  teaching_class_id: number | null
  teaching_class_name: string | null
  learning_stage: LearningStage
  source: 'page' | 'manual' | 'recent_learning' | 'default_class' | 'assignment' | 'none'
  confidence: 'high' | 'medium' | 'low'
  requires_chapter_selection: boolean
  chapters: AiWorkspaceChapterOption[]
  candidates: AiWorkspaceContextCandidate[]
  state_summary: string[]
}

export interface AiWorkspaceContextPayload {
  course_id?: number | null
  chapter_id?: number | null
  chapter_ids?: number[]
  teaching_class_id?: number | null
  learning_stage?: LearningStage
  page_name?: string | null
}

export interface AiAgentPlan {
  intent: string
  title: string
  steps: Array<{ key: string; title: string; status: 'completed' | 'pending' | 'running' | 'ready' | 'needs_input' | 'blocked' }>
}

export interface AiAgentAction {
  kind: string
  label: string
  href?: string
  run_id?: number | null
  requires_confirmation: boolean
  output_types?: Array<'ppt' | 'lesson_plan' | 'classroom_activities'>
  status?: 'ready' | 'running' | 'completed' | 'failed'
}

export interface AiAgentToolResult {
  tool: string
  title: string
  status: 'completed' | 'failed' | 'running'
  summary: string
  data: Record<string, unknown>
  action: AiAgentAction | Record<string, never>
  warnings: string[]
  retryable: boolean
  requires_confirmation: boolean
}

export interface AiAgentExecution {
  id: number
  role: AiWorkspaceRole
  status: 'planning' | 'running' | 'waiting_confirmation' | 'completed' | 'failed' | 'cancelled'
  intent: string
  question: string
  course_id: number | null
  chapter_id: number | null
  teaching_class_id: number | null
  context: AiWorkspaceContext
  plan: AiAgentPlan | Record<string, never>
  tool_results: AiAgentToolResult[]
  result: {
    summary?: string
    actions?: AiAgentAction[]
    next_actions?: AiAgentAction[]
    blocking_actions?: AiAgentAction[]
    warnings?: string[]
    verified?: boolean
    verification?: { checks: Array<{ key: string; label: string; passed: boolean; detail?: string }> }
  }
  error_message: string | null
  retry_count: number
  retry_of_execution_id: number | null
  created_time: string | null
  updated_time: string | null
  finished_time: string | null
}

export interface AiAgentTemplate {
  key: string
  category: 'generate' | 'interaction' | 'task' | 'review' | 'monitor' | 'plan' | string
  title: string
  description: string
  prompt: string
  requires_context: boolean
}

export interface AiWorkspaceAgentPayload extends AiWorkspaceContextPayload {
  role: AiWorkspaceRole
  question: string
  execution_id?: number | null
}

async function readSse(
  response: Response,
  onEvent: (event: string, data: any) => void,
  unavailableMessage: string,
) {
  if (!response.ok || !response.body) {
    // SSE 请求在开始发送事件前发生 4xx/5xx 时，浏览器不会进入事件循环，
    // 原先只显示“工作流暂时不可用”，导致参数校验错误无法定位。保留后端
    // 的 detail/message，并附带状态码，方便用户和管理员快速修复部署问题。
    let detail = ''
    try {
      const payload = await response.clone().json() as { detail?: string; message?: string; errors?: unknown }
      detail = payload.detail || payload.message || ''
      if (payload.errors) {
        const validation = typeof payload.errors === 'string' ? payload.errors : JSON.stringify(payload.errors)
        detail = detail ? `${detail}（${validation}）` : validation
      }
    } catch {
      try { detail = (await response.clone().text()).trim() } catch { /* ignore */ }
    }
    const suffix = detail ? `：${detail}` : ''
    throw new Error(`${unavailableMessage}（HTTP ${response.status}${suffix}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const block of events) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1]
      const dataLine = block.match(/^data:\s*(.+)$/m)?.[1]
      if (!event || !dataLine) continue
      const data = JSON.parse(dataLine)
      if (event === 'error') throw new Error(data.message || 'AI 生成失败')
      onEvent(event, data)
    }
  }
}

export const aiApi = {
  assist: (payload: AiAssistPayload) => http.post<ApiResponse<AiAssistData>>('/ai/assist', payload, { timeout: 90_000 }),
  async assistStream(payload: AiAssistPayload, handlers: {
    onMeta: (data: { grounded: boolean; model: string }) => void
    onChunk: (text: string) => void
    onSources: (sources: AiSource[]) => void
  }, options: { signal?: AbortSignal } = {}) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const response = await fetch(`${baseURL}/ai/assist/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      body: JSON.stringify(payload),
      signal: options.signal,
    })
    if (!response.ok || !response.body) throw new Error('AI 流式服务暂时不可用')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const block of events) {
        const event = block.match(/^event:\s*(.+)$/m)?.[1]
        const dataLine = block.match(/^data:\s*(.+)$/m)?.[1]
        if (!event || !dataLine) continue
        const data = JSON.parse(dataLine)
        if (event === 'meta') handlers.onMeta(data)
        if (event === 'chunk') handlers.onChunk(data.text)
        if (event === 'sources') handlers.onSources(data)
        if (event === 'error') throw new Error(data.message || 'AI 生成失败')
      }
    }
  },
  async workspaceStream(payload: AiWorkspacePayload, handlers: {
    onMeta: (data: { grounded: boolean; model: string; mode: AiWorkspaceMode; role: AiWorkspaceRole }) => void
    onChunk: (text: string) => void
    onSources: (sources: AiSource[]) => void
  }) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const response = await fetch(`${baseURL}/ai/workspace/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      body: JSON.stringify(payload),
    })
    await readSse(response, (event, data) => {
      if (event === 'meta') handlers.onMeta(data)
      if (event === 'chunk') handlers.onChunk(data.text)
      if (event === 'sources') handlers.onSources(data)
    }, 'AI 工作台暂时不可用')
  },
  workspaceContext: (payload: AiWorkspaceContextPayload) =>
    http.post<ApiResponse<AiWorkspaceContext>>('/ai/workspace/context', payload),
  workspaceAgentExecutions: (limit = 12) =>
    http.get<ApiResponse<AiAgentExecution[]>>('/ai/workspace/agent/executions', { params: { limit } }),
  clearWorkspaceAgentExecutions: () =>
    http.delete<ApiResponse<{ deleted_count: number }>>('/ai/workspace/agent/executions'),
  deleteWorkspaceAgentExecution: (executionId: number) =>
    http.delete<ApiResponse<null>>(`/ai/workspace/agent/executions/${executionId}`),
  workspaceAgentTemplates: () =>
    http.get<ApiResponse<AiAgentTemplate[]>>('/ai/workspace/agent/templates'),
  retryWorkspaceAgentExecution: (executionId: number) =>
    http.post<ApiResponse<AiAgentExecution>>(`/ai/workspace/agent/executions/${executionId}/retry`),
  resolveWorkspaceAgentExecution: (executionId: number, resolution: 'confirmed' | 'cancelled', note?: string) =>
    http.post<ApiResponse<AiAgentExecution>>(`/ai/workspace/agent/executions/${executionId}/resolve`, { resolution, note }),
  async workspaceAgentStream(payload: AiWorkspaceAgentPayload, handlers: {
    onContext: (context: AiWorkspaceContext) => void
    onMeta: (data: { grounded: boolean; model: string; mode: AiWorkspaceMode; role: AiWorkspaceRole; execution_id?: number }) => void
    onExecution: (execution: AiAgentExecution) => void
    onPlan: (plan: AiAgentPlan) => void
    onProgress: (progress: { title: string; status: string }) => void
    onTool: (tool: { name: string; title: string; status: string; error?: string; requires_confirmation?: boolean }) => void
    onAction: (action: AiAgentAction) => void
    onChunk: (text: string) => void
    onSources: (sources: AiSource[]) => void
  }) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    // 不把可选范围字段的 null 发送给旧版后端。新后端支持 null，省略后
    // 仍会按“自动识别教学范围”处理，同时兼容尚未完成迁移的部署实例。
    const requestBody = Object.fromEntries(
      Object.entries(payload).filter(([, value]) => value !== null && value !== undefined && value !== ''),
    )
    const response = await fetch(`${baseURL}/ai/workspace/agent/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      body: JSON.stringify(requestBody),
    })
    await readSse(response, (event, data) => {
      if (event === 'context') handlers.onContext(data)
      if (event === 'meta') handlers.onMeta(data)
      if (event === 'execution') handlers.onExecution(data)
      if (event === 'plan') handlers.onPlan(data)
      if (event === 'progress') handlers.onProgress(data)
      if (event === 'tool') handlers.onTool(data)
      if (event === 'action') handlers.onAction(data)
      if (event === 'chunk') handlers.onChunk(data.text)
      if (event === 'sources') handlers.onSources(data)
    }, 'Agent 工作流暂时不可用')
  },
}

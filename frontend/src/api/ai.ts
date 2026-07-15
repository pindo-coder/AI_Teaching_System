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

export interface AiSource {
  source_type: string
  source_title: string
  course_id: number
  chapter_id: number
  excerpt: string
  position: string
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
}

export const aiApi = {
  assist: (payload: AiAssistPayload) => http.post<ApiResponse<AiAssistData>>('/ai/assist', payload, { timeout: 90_000 }),
  async assistStream(payload: AiAssistPayload, handlers: {
    onMeta: (data: { grounded: boolean; model: string }) => void
    onChunk: (text: string) => void
    onSources: (sources: AiSource[]) => void
  }) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const response = await fetch(`${baseURL}/ai/assist/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      body: JSON.stringify(payload),
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
}

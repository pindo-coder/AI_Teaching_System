import { http, type ApiResponse } from './http'
import type { LearningStage } from '@/types'

export type AiTaskType =
  | 'question_answer'
  | 'chapter_summary'
  | 'preview_questions'
  | 'review_outline'
  | 'mock_questions'

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

export const aiApi = {
  assist: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    task_type: AiTaskType
    question: string
  }) => http.post<ApiResponse<AiAssistData>>('/ai/assist', payload, { timeout: 90_000 }),
}

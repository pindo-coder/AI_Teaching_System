import { http, type ApiResponse } from './http'
import type { DashboardData, LearningProgress, LearningStage } from '@/types'

export const learningApi = {
  dashboard: () => http.get<ApiResponse<DashboardData>>('/dashboard'),
  updateProgress: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    progress: number
  }) => http.put<ApiResponse<LearningProgress>>('/learning/progress', payload),
}

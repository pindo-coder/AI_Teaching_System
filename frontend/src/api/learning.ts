import { http, type ApiResponse } from './http'
import type { DashboardData, LearningFootprint, LearningProgress, LearningStage, TaskProgressSummary } from '@/types'

export const learningApi = {
  dashboard: () => http.get<ApiResponse<DashboardData>>('/dashboard'),
  updateProgress: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    progress: number
  }) => http.put<ApiResponse<LearningProgress>>('/learning/progress', payload),
  taskPoints: (courseId: number, chapterId: number, stage: LearningStage) =>
    http.get<ApiResponse<TaskProgressSummary>>('/learning/task-points', { params: { course_id: courseId, chapter_id: chapterId, learning_stage: stage } }),
  footprint: (courseId: number, chapterId: number, stage: LearningStage) =>
    http.get<ApiResponse<LearningFootprint>>('/learning/footprint', { params: { course_id: courseId, chapter_id: chapterId, learning_stage: stage } }),
  recordActivity: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    event_type: 'chapter_opened' | 'reading_progress'
    event_data?: Record<string, unknown>
  }) => http.post<ApiResponse<LearningFootprint>>('/learning/activity', payload),
  recordEvent: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    event_type: 'chapter_opened' | 'reading_progress'
    event_data?: Record<string, unknown>
  }) => http.post<ApiResponse<TaskProgressSummary>>('/learning/events', payload),
  submitQuestion: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    content: string
  }) => http.post<ApiResponse<TaskProgressSummary>>('/learning/questions', payload),
}

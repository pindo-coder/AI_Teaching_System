import { http, type ApiResponse } from './http'
import type { DashboardData, LearningProgress, LearningStage, TaskProgressSummary } from '@/types'

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
  recordEvent: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    event_type: 'chapter_opened' | 'reading_progress' | 'ai_assist_used' | 'question_submitted' | 'note_saved' | 'activity_submitted' | 'quiz_completed'
    event_data?: Record<string, unknown>
  }) => http.post<ApiResponse<TaskProgressSummary>>('/learning/events', payload),
}

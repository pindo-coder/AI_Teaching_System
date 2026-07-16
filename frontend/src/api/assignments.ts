import { http, type ApiResponse } from './http'
import type { LearningStage } from '@/types'

export type AssignmentTaskKind = 'reading' | 'ai_assist' | 'note'

export interface AssignmentStudent {
  id: number
  username: string
  identity_no: string | null
}

export interface StudentAssignment {
  id: number
  course_id: number
  chapter_id: number
  course_name: string
  chapter_title: string
  learning_stage: LearningStage
  task_kind: AssignmentTaskKind
  title: string
  description: string
  due_time: string
  status: 'not_started' | 'in_progress' | 'completed' | 'overdue'
  progress_value: number
  completed_time: string | null
  created_time: string
  teacher_name: string
}

export interface TeacherAssignment {
  id: number
  course_id: number
  chapter_id: number
  course_name: string
  chapter_title: string
  learning_stage: LearningStage
  task_kind: AssignmentTaskKind
  title: string
  description: string
  due_time: string
  status: 'published' | 'cancelled'
  target_scope: 'all_students' | 'selected_students'
  created_time: string
  total_count: number
  completed_count: number
  in_progress_count: number
  overdue_count: number
}

export const assignmentApi = {
  student: (includeCompleted = true) => http.get<ApiResponse<StudentAssignment[]>>('/assignments/student', { params: { include_completed: includeCompleted } }),
  teacher: () => http.get<ApiResponse<TeacherAssignment[]>>('/assignments'),
  students: () => http.get<ApiResponse<AssignmentStudent[]>>('/assignments/students'),
  create: (payload: {
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    task_kind: AssignmentTaskKind
    title: string
    description: string
    due_time: string
    target_scope: 'all_students' | 'selected_students'
    student_ids: number[]
  }) => http.post<ApiResponse<TeacherAssignment>>('/assignments', payload),
  cancel: (id: number) => http.delete<ApiResponse<{ id: number }>>(`/assignments/${id}`),
}

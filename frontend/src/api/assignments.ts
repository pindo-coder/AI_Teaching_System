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
  teaching_class_id: number | null
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
  teaching_class_id: number | null
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
  target_scope: 'all_students' | 'selected_students' | 'selected_groups'
  created_time: string
  total_count: number
  completed_count: number
  in_progress_count: number
  overdue_count: number
}

export interface AssignmentRecipientDetail {
  user_id: number
  username: string
  identity_no: string | null
  group_name: string | null
  status: 'not_started' | 'in_progress' | 'completed' | 'overdue'
  progress_value: number
  completed_time: string | null
  last_activity_time: string | null
}

export const assignmentApi = {
  student: (includeCompleted = true) => http.get<ApiResponse<StudentAssignment[]>>('/assignments/student', { params: { include_completed: includeCompleted } }),
  teacher: () => http.get<ApiResponse<TeacherAssignment[]>>('/assignments'),
  students: (teachingClassId?: number) => http.get<ApiResponse<AssignmentStudent[]>>('/assignments/students', { params: teachingClassId ? { teaching_class_id: teachingClassId } : undefined }),
  create: (payload: {
    teaching_class_id: number | null
    course_id: number
    chapter_id: number
    learning_stage: LearningStage
    task_kind: AssignmentTaskKind
    title: string
    description: string
    due_time: string
    target_scope: 'all_students' | 'selected_students' | 'selected_groups'
    student_ids: number[]
    group_ids: number[]
  }) => http.post<ApiResponse<TeacherAssignment>>('/assignments', payload),
  recipients: (id: number) => http.get<ApiResponse<AssignmentRecipientDetail[]>>(`/assignments/${id}/recipients`),
  cancel: (id: number) => http.delete<ApiResponse<{ id: number }>>(`/assignments/${id}`),
}

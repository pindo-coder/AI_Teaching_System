import { http, type ApiResponse } from './http'
import type { LearningStage } from '@/types'

export type AssignmentTaskKind = 'reading' | 'ai_assist' | 'note' | 'composite'
export type AssignmentRequirementEvent =
  | 'reading_progress'
  | 'ai_assist_used'
  | 'note_saved'
  | 'quiz_completed'
  | 'question_submitted'
  | 'activity_submitted'
  | 'discussion_created'
  | 'discussion_reply_created'

export interface AssignmentCompletionRequirement {
  key: string
  label: string
  event: AssignmentRequirementEvent
  metric: 'percent' | 'count' | 'length'
  target: number
  weight: number
  required: boolean
  stage: 'assignment' | 'any' | LearningStage
  task_types: string[]
}

export interface AssignmentCompletionPolicy {
  mode: 'all_required'
  items: AssignmentCompletionRequirement[]
}

export interface AssignmentRequirementProgress {
  key: string
  label: string
  event: AssignmentRequirementEvent
  current_value: number
  target_value: number
  progress_value: number
  status: 'not_started' | 'in_progress' | 'completed'
  evidence_summary: string
  next_path: string
}

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
  rubric: { items: Array<{ label: string; weight: number; description: string }>; feedback_template: string }
  due_time: string
  status: 'not_started' | 'in_progress' | 'completed' | 'overdue'
  progress_value: number
  completed_time: string | null
  created_time: string
  teacher_name: string
  completion_policy: AssignmentCompletionPolicy | null
  requirements: AssignmentRequirementProgress[]
  next_path: string
  completion_status: 'not_started' | 'in_progress' | 'completed'
  is_overdue: boolean
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
  rubric: { items: Array<{ label: string; weight: number; description: string }>; feedback_template: string }
  due_time: string
  status: 'published' | 'cancelled'
  target_scope: 'all_students' | 'selected_students' | 'selected_groups'
  created_time: string
  total_count: number
  completed_count: number
  in_progress_count: number
  overdue_count: number
  completion_policy: AssignmentCompletionPolicy | null
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
  completion_status: 'not_started' | 'in_progress' | 'completed'
  is_overdue: boolean
  requirements: AssignmentRequirementProgress[]
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
    rubric: { items: Array<{ label: string; weight: number; description: string }>; feedback_template: string }
    due_time: string
    target_scope: 'all_students' | 'selected_students' | 'selected_groups'
    student_ids: number[]
    group_ids: number[]
    completion_policy: AssignmentCompletionPolicy
  }) => http.post<ApiResponse<TeacherAssignment>>('/assignments', payload),
  recipients: (id: number) => http.get<ApiResponse<AssignmentRecipientDetail[]>>(`/assignments/${id}/recipients`),
  cancel: (id: number) => http.delete<ApiResponse<{ id: number }>>(`/assignments/${id}`),
  confirmRubric: (id: number, rubric: TeacherAssignment['rubric']) =>
    http.post<ApiResponse<TeacherAssignment>>(`/assignments/${id}/rubric/confirm`, { rubric }),
  updateCompletionPolicy: (id: number, completionPolicy: AssignmentCompletionPolicy) =>
    http.put<ApiResponse<TeacherAssignment>>(`/assignments/${id}/completion-policy`, { completion_policy: completionPolicy }),
}

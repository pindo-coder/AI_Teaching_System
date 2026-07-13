export type UserRole = 'student' | 'teacher' | 'admin'
export type LearningStage = 'preview' | 'review' | 'exam'

export interface User {
  id: number
  username: string
  role: UserRole
  identity_no: string | null
  created_time: string
}

export interface Course {
  id: number
  name: string
  description: string | null
  created_time: string
  updated_time: string
}

export interface Chapter {
  id: number
  course_id: number
  title: string
  content: string | null
  sort_order: number
  created_time: string
  updated_time: string
}

export interface CourseDetail extends Course { chapters: Chapter[] }

export interface LearningProgress {
  id: number
  user_id: number
  course_id: number
  chapter_id: number
  learning_stage: LearningStage
  progress: number
  last_study_time: string
}

export interface TaskPoint {
  id: number
  course_id: number
  chapter_id: number
  learning_stage: LearningStage
  task_type: string
  title: string
  description: string
  weight: number
  sort_order: number
  status: 'not_started' | 'in_progress' | 'completed'
  progress_value: number
  evidence_summary: string
  completed_time: string | null
}

export interface TaskProgressSummary {
  course_id: number
  chapter_id: number
  learning_stage: LearningStage
  completed_count: number
  total_count: number
  progress: number
  tasks: TaskPoint[]
}

export interface DashboardData {
  user: User
  current_course: Course | null
  current_chapter: Chapter | null
  recent_progress: LearningProgress[]
  overall_progress: number
}

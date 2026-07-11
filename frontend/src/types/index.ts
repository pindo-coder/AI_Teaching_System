export type UserRole = 'student' | 'teacher' | 'admin'
export type LearningStage = 'preview' | 'review' | 'exam'

export interface User {
  id: number
  username: string
  role: UserRole
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

export interface DashboardData {
  user: User
  current_course: Course | null
  current_chapter: Chapter | null
  recent_progress: LearningProgress[]
  overall_progress: number
}

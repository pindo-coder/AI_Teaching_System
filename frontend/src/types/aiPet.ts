import type { LearningStage, UserRole } from '@/types'

export type AiPetState = 'idle' | 'focused' | 'reminding' | 'alert' | 'thinking'
export type AiPetActionType = 'continue-learning' | 'open-task' | 'open-task-center' | 'open-teaching-center'

export interface AiPetNextTask {
  title: string
  dueTime: string | null
  path: string
}

/**
 * AI 学习伙伴的稳定上下文接口。
 * 后续替换形象、动画或完整 UI 时，只需消费该接口，不需要改动首页业务数据。
 */
export interface AiPetContext {
  role: UserRole
  username: string
  chapterTitle: string | null
  learningStage: LearningStage | null
  progress: number
  pendingCount: number
  overdueCount: number
  continuePath: string
  nextTask: AiPetNextTask | null
}

export interface AiPetAction {
  type: AiPetActionType
  path: string
}

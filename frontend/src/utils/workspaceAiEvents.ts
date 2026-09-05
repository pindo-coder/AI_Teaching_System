import type { AiTaskType } from '@/api/ai'
import type { LearningStage } from '@/types'

export const WORKSPACE_AI_REQUEST_EVENT = 'workspace-ai-request'

export interface WorkspaceAiRequest {
  courseId: number
  chapterId: number
  learningStage: LearningStage
  taskType: AiTaskType
  prompt: string
  mode?: 'chat' | 'agent'
  autoSend?: boolean
}

export function requestWorkspaceAi(request: WorkspaceAiRequest) {
  window.dispatchEvent(new CustomEvent<WorkspaceAiRequest>(WORKSPACE_AI_REQUEST_EVENT, { detail: request }))
}

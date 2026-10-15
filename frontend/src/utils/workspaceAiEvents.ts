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

export interface WorkspaceAiPageScope {
  courseId?: number | null
  chapterId?: number | null
  learningStage?: LearningStage | null
}

// Only an explicit page scope is binding. The workspace's cached dashboard can
// lag behind the home page and must not silently reject a fresh user request.
export function workspaceAiRequestError(request: WorkspaceAiRequest | null | undefined, page: WorkspaceAiPageScope): string | null {
  if (!request || !Number.isSafeInteger(request.courseId) || request.courseId <= 0
    || !Number.isSafeInteger(request.chapterId) || request.chapterId <= 0
    || !['preview', 'review', 'exam'].includes(request.learningStage)
    || typeof request.prompt !== 'string' || !request.prompt.trim()) {
    return 'AI 请求缺少有效的教材、专题或问题，请重新选择后重试。'
  }
  if ((page.courseId && page.courseId !== request.courseId)
    || (page.chapterId && page.chapterId !== request.chapterId)
    || (page.learningStage && page.learningStage !== request.learningStage)) {
    return 'AI 请求与当前页面的教材、专题或学习阶段不一致，请切换到对应专题后重试。'
  }
  return null
}

export function requestWorkspaceAi(request: WorkspaceAiRequest) {
  window.dispatchEvent(new CustomEvent<WorkspaceAiRequest>(WORKSPACE_AI_REQUEST_EVENT, { detail: request }))
}

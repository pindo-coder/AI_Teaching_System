export type LongTaskStatus = 'queued' | 'running' | 'pending_confirmation' | 'success' | 'failed' | 'cancelled'
export type SemanticStatus = 'neutral' | 'authority' | 'info' | 'warning' | 'success' | 'danger'

export interface WorkspaceLongTask {
  id: string
  title: string
  status: LongTaskStatus
  progress: number
  description: string
  resultPath?: string
}


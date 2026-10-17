import type { AgentRun } from '../api/agents'

export interface LessonArtifactProgress {
  percentage: number
  label: string
  detail: string
  status: 'success' | 'warning' | 'exception' | undefined
  active: boolean
  elapsed: string
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0
}

function timestamp(value: unknown, legacyOffset = '+08:00'): number {
  if (typeof value !== 'string' || !value) return NaN
  // Agent attempt/step clocks historically used local Beijing wall time, not
  // UTC. Keep this compatibility rule scoped to these fields; generic entity
  // updated_time is UTC and is parsed separately below. New protocol timestamps
  // carry an explicit offset and must retain their original meaning.
  const normalized = value.trim().replace(' ', 'T')
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : `${normalized}${legacyOffset}`)
}

function elapsedTime(start: unknown, end: unknown, now: number): string {
  const started = timestamp(start)
  if (!Number.isFinite(started)) return ''
  const finished = timestamp(end)
  const seconds = Math.floor(Math.max(0, (Number.isFinite(finished) ? finished : now) - started) / 1000)
  const minutes = Math.floor(seconds / 60)
  return `已用时 ${minutes ? `${minutes} 分 ` : ''}${seconds % 60} 秒`
}

/** Phase-weighted estimate, never a timer or a prediction of remaining seconds.
 * PPT page counts come from checkpoints. Image generation/export are separate
 * phases: designing every page does not mean the downloadable file is ready.
 */
export function lessonArtifactProgress(
  run: AgentRun | null,
  options: { submitting?: boolean; now?: number } = {},
): LessonArtifactProgress | null {
  if (options.submitting) return {
    percentage: 0, label: '正在提交本次生成请求', detail: '准备进入后台队列，上一版成果保持不变。',
    status: undefined, active: true, elapsed: '',
  }
  if (!run) return null
  const attempt = run.output_data.artifact_attempt
  const step = run.steps.find(item => item.step_key === 'generate_artifacts')
  if (!attempt && (!step || !['queued', 'running', 'completed', 'failed', 'cancelled'].includes(step.status))) return null
  if (['queued', 'running'].includes(run.output_data.ppt_image_job?.status || '')) return null
  const active = ['queued', 'running'].includes(run.status) && run.current_step === 3
  const cancelled = run.status === 'cancelled' || step?.status === 'cancelled'
  const failed = !cancelled && (attempt?.status === 'failed' || step?.status === 'failed' || run.status === 'failed')
  const partial = attempt?.status === 'partial'
  const completed = run.status === 'completed' && !active && !cancelled && !failed && !partial
    && (attempt?.status === 'completed' || step?.status === 'completed')
  const workflow = (step?.output_data.ppt_workflow || {}) as Record<string, unknown>
  const stage = typeof workflow.stage === 'string' ? workflow.stage : ''
  const requested = attempt?.requested_types || (Array.isArray(run.input_data.artifact_output_types)
    ? run.input_data.artifact_output_types.filter((key): key is string => typeof key === 'string') : [])
  const hasPpt = requested.includes('ppt') || Boolean(stage)
  const documents = requested.filter(key => key !== 'ppt')
  const pptWeight = hasPpt ? 8 : 0
  const totalWeight = pptWeight + documents.length || 1
  const total = Math.floor(number(workflow.total_pages))
  const done = total ? Math.min(Math.floor(number(workflow.completed_pages)), total) : 0
  const ratio = total ? done / total : 0
  const hasImages = (run.input_data.ppt_preferences as { include_visuals?: boolean } | undefined)?.include_visuals
  const labels: Record<string, string> = {
    waiting_slot: '等待课件生成资源', planning: '正在编排教学内容', designing: '正在设计课件页面',
    illustrating: '正在生成辅助插图', exporting: '正在导出与检查课件', completed: '正在保存教学成果',
  }
  // The weights model work phases, not time. A slow model call does not advance
  // the percentage; repairing a page does not manufacture extra completed pages.
  const pptFraction: Record<string, number> = {
    waiting_slot: 0, planning: .05, designing: .12 + (hasImages ? .58 : .73) * ratio,
    illustrating: .75, exporting: .9, completed: .98,
  }
  let percentage = Math.floor(((pptFraction[stage] || 0) * pptWeight) / totalWeight * 100)
  let label = labels[stage] || (run.status === 'queued' ? '等待后台开始生成' : '正在生成教学成果')
  let detail = '进度按后台阶段更新，模型响应期间会暂时停留在当前百分比。'
  if (stage === 'designing') detail = total
    ? `已设计 ${done}/${total} 页${done < total ? `，剩余 ${total - done} 页` : '，接下来准备配图或导出'}。`
    : '正在设计课件页面，等待后台返回页数。'
  if (stage === 'illustrating') detail = '页面设计已完成；配图生成与复核耗时波动较大，请耐心等待。'
  if (stage === 'exporting') detail = '正在生成可编辑 PPT 并渲染逐页预览，文件就绪后才会完成。'
  if (stage === 'completed' && documents.length) {
    label = '正在生成教案与课堂活动'
    detail = 'PPT 已完成检查，正在处理本次选择的其他教学成果。'
  }
  if (!hasPpt && active) {
    percentage = run.status === 'queued' ? 0 : 5
    label = run.status === 'queued' ? '等待后台开始生成' : '正在生成教学文档'
  }
  if (active && run.status === 'queued') percentage = 0
  if (completed) {
    percentage = 100
    label = '本次教学成果已生成'
    detail = '文件已就绪，可进入预览发布；发布前仍需教师核验。'
  } else if (cancelled) {
    label = '本次生成已停止'
    detail = '进度停留在最后收到的阶段，原有成果未被覆盖。'
  } else if (failed || partial) {
    label = partial ? '本次成果部分完成' : '本次生成未完成'
    detail = '请查看失败说明并重试未完成部分，原有成果仍保留。'
  }
  const finished = !active ? attempt?.finished_time || step?.finished_time || run.finished_time : undefined
  const updated = !active ? timestamp(run.updated_time, 'Z') : NaN
  const now = !active && Number.isFinite(updated) ? updated : options.now ?? Date.now()
  return {
    percentage: Math.max(0, Math.min(completed ? 100 : partial ? 95 : 99, percentage)),
    label, detail, active,
    status: cancelled || partial ? 'warning' : failed ? 'exception' : completed ? 'success' : undefined,
    elapsed: elapsedTime(attempt?.started_time || step?.started_time, finished, now),
  }
}

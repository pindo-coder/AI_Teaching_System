import { http, type ApiResponse } from './http'
import type { AiSource } from './ai'
import type { LearningStage } from '@/types'

export type AgentStatus =
  | 'queued'
  | 'running'
  | 'waiting_confirmation'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface PptPreferences {
  title?: string | null
  image_frame_shape?: 'roundRect' | 'circle'
  scenario: 'classroom' | 'open_lesson' | 'presentation'
  visual_style: 'serious' | 'modern' | 'youthful'
  content_density: 'concise' | 'standard' | 'detailed'
  min_slides: number
  max_slides: number
  slide_count: number
  include_interaction: boolean
  include_visuals: boolean
  template_id: number | null
}

export interface PresentationTemplate {
  id: number
  owner_id: number
  name: string
  description: string | null
  original_filename: string
  status: string
  is_shared: boolean
  slide_count: number
  aspect_ratio: string
  theme_data: {
    palette?: Record<string, string>
    fonts?: Record<string, string>
    layout_names?: string[]
    compatibility?: string
    compatibility_note?: string
  }
  created_time: string
  updated_time: string
}

export interface AgentStep {
  id: number
  step_key: string
  title: string
  step_order: number
  status: string
  output_data: Record<string, unknown>
  error_message: string | null
  started_time: string | null
  finished_time: string | null
}

export interface LessonOutline {
  title: string
  positioning: string
  objectives: {
    knowledge: string[]
    ability: string[]
    values: string[]
  }
  key_points: string[]
  difficult_points: string[]
  teaching_flow: Array<{
    stage: string
    duration_minutes: number
    teacher_activity: string
    student_activity: string
    evidence_refs: string[]
  }>
  discussion_questions: string[]
  after_class_task: string
  citation_notes: string[]
}

export interface AgentRun {
  id: number
  created_by: number
  agent_type: string
  status: AgentStatus
  course_id: number | null
  chapter_id: number | null
  teaching_class_id: number | null
  current_step: number
  input_data: Record<string, unknown>
  evidence_snapshot: AiSource[]
  output_data: {
    outline?: LessonOutline
    artifact_errors?: Partial<Record<'ppt' | 'lesson_plan' | 'classroom_activities', string>>
    ppt_image_job?: { id: string; status: 'queued' | 'running' | 'failed' | 'completed' | 'cancelled'; slide_index: number; stage?: string; error?: string }
    artifact_attempt?: { id?: string; status: 'queued' | 'running' | 'failed' | 'partial' | 'completed';
      resume?: boolean; requested_types?: string[]; started_time?: string; finished_time?: string }
    artifact_bundle?: {
      ppt?: {
        skill?: { name: string; version: string; commit: string; integration: string }
        pipeline_version?: string
        revision_id?: string
        preferences?: PptPreferences
        title: string
        subtitle?: string
        design?: {
          name: string
          concept: string
          topic_keywords?: string[]
          visual_motif?: string
          image_style?: string
          image_frame_shape?: 'roundRect' | 'circle'
          mood?: string
          status?: 'personalized' | 'fallback'
          designed_pages?: number
          palette?: Record<string, string>
          fonts?: Record<string, string>
          template_reference?: {
            id: number
            name: string
            compatibility?: string
          }
        }
        quality_report?: {
          score?: number
          passed: boolean
          summary: string
          reviewer: string
          visual_review?: 'teacher_required'
          checks?: string[]
          issues: Array<{
            slide_index: number | null
            severity: 'high' | 'medium' | 'low'
            category: string
            message: string
            suggestion: string
          }>
        }
        slides: Array<{
          preview_available?: boolean
          layout: string
          title: string
          takeaway: string
          bullets: string[]
          diagram_labels?: string[]
          visual_prompt?: string
          visual_brief?: { kind: 'illustration' | 'diagram' | 'none'; purpose: string; content_anchors: string[];
            scene_family?: string; key_elements?: string[]; difference?: string; avoid?: string[] } | null
          keyword?: string
          left?: {
            title: string
            points: string[]
          }
          right?: {
            title: string
            points: string[]
          }
          steps?: Array<{
            title: string
            description: string
          }>
          timeline?: Array<{
            label: string
            title: string
          }>
          canvas_background?: string
          canvas?: Array<{
            type: 'text' | 'shape' | 'line' | 'image'
            source: string
            style: 'hero' | 'title' | 'subtitle' | 'body' | 'label' | 'number' | 'quote'
            x: number
            y: number
            w: number
            h: number
            color: string
            fill?: string
            shape: 'rect' | 'roundRect' | 'ellipse' | 'arc'
            align: 'left' | 'center' | 'right'
            bold: boolean
          }>
          visual_asset?: {
            file_name: string
            media_type: string
            model: string
            prompt?: string
            review?: { status: 'passed' | 'rejected' | 'unreviewed'; reason: string; model?: string;
              matched_elements?: string[]; missing_elements?: string[] }
          }
          speaker_notes: string
          evidence_refs: string[]
        }>
        multimodal?: {
          status: 'completed' | 'partial' | 'fallback' | 'unavailable'
          generated_count: number
          requested_count?: number
          selected_slides?: number[]
          model?: string
          message: string
          errors?: string[]
          semantic_review?: { passed: number; unreviewed: number }
        }
      }
      lesson_plan?: {
        title: string
        overview: string
        objectives: string[]
        preparation: string[]
        procedures: LessonOutline['teaching_flow']
        assessment: string[]
        homework: string
      }
      classroom_activities?: Array<{
        title: string
        purpose: string
        duration_minutes: number
        format: string
        instructions: string[]
        questions: string[]
        evidence_refs: string[]
        evaluation: string
      }>
    }
    artifacts?: Record<string, {
      kind: 'ppt' | 'lesson_plan' | 'classroom_activities'
      title: string
      file_name: string
      media_type: string
      slide_count?: number
      activity_count?: number
      preview?: unknown
      generated_time?: string
      attempt_id?: string
      revision_id?: string
      requires_previous_confirmation?: boolean
    }>
    ppt_versions?: Array<{
      version_id: string
      created_time: string
      reason: string
      title: string
      slide_count: number
      design_name?: string
      restorable?: boolean
      revision_id?: string
      generated_time?: string
      unavailable_reason?: string | null
      is_current?: boolean
    }>
  }
  model_name: string | null
  prompt_version: string
  error_message: string | null
  cancel_requested: boolean
  retry_of_run_id: number | null
  started_time: string | null
  finished_time: string | null
  created_time: string
  updated_time: string
  steps: AgentStep[]
}

export type PptDeck = NonNullable<NonNullable<AgentRun['output_data']['artifact_bundle']>['ppt']>
export type AgentArtifact = NonNullable<AgentRun['output_data']['artifacts']>[string]
export type PptVersion = NonNullable<AgentRun['output_data']['ppt_versions']>[number]
export interface PptVersionPreview extends PptVersion {
  ppt: PptDeck
  artifact: Partial<AgentArtifact>
}

export interface CreateLessonPrepRun {
  agent_type: 'teacher_lesson_prep'
  course_id: number
  chapter_id: number
  teaching_class_id: number | null
  input: {
    lesson_hours: number
    learning_stage: LearningStage
    student_level: string
    completion_condition: string | null
    teaching_goal: string | null
    output_types: Array<'outline' | 'lesson_plan' | 'ppt'>
  }
}

export interface AgentCapabilities {
  ppt_multimodal_available: boolean
  ppt_multimodal_model: string | null
  ppt_multimodal_max_images: number
}

export interface LessonPublication {
  id: number
  agent_run_id: number
  teaching_class_id: number
  teaching_class_name: string
  course_id: number
  chapter_id: number
  chapter_title: string
  created_by: number
  teacher_name: string
  title: string
  description: string
  ppt_available: boolean
  ppt_file_name: string | null
  discussion_activity_ids: number[]
  status: string
  created_time: string
}

export const agentApi = {
  pptSlidePreview: (id: number, slideIndex: number, versionId?: string, expectedRevision?: string, signal?: AbortSignal) =>
    http.get<Blob>(`/agent/runs/${id}/ppt/slides/${slideIndex}/preview`, {
      responseType: 'blob', params: { version_id: versionId, expected_revision: expectedRevision }, signal,
    }),
  capabilities: () =>
    http.get<ApiResponse<AgentCapabilities>>('/agent/capabilities'),
  create: (payload: CreateLessonPrepRun) =>
    http.post<ApiResponse<AgentRun>>('/agent/runs', payload, { timeout: 90_000 }),
  list: (limit = 30) =>
    http.get<ApiResponse<AgentRun[]>>('/agent/runs', { params: { limit } }),
  detail: (id: number) =>
    http.get<ApiResponse<AgentRun>>(`/agent/runs/${id}`),
  confirmEvidence: (id: number) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/confirm`, { action: 'approve_evidence' }),
  generateArtifacts: (
    id: number,
    outputTypes: Array<'lesson_plan' | 'ppt' | 'classroom_activities'>,
    pptPreferences?: PptPreferences,
    resume = false,
  ) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/artifacts`, {
      output_types: outputTypes,
      ppt_preferences: outputTypes.includes('ppt') ? pptPreferences : undefined,
      resume,
    }),
  revisePptSlide: (
    id: number,
    slideIndex: number,
    instruction: string,
    mode: 'content' | 'design' | 'both',
  ) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/ppt/slides/${slideIndex}/revise`, {
      instruction,
      mode,
    }, { timeout: 180_000 }),
  previewPptVersion: (id: number, versionId: string, signal?: AbortSignal) =>
    http.get<ApiResponse<PptVersionPreview>>(`/agent/runs/${id}/ppt/versions/${encodeURIComponent(versionId)}`, { signal }),
  restorePptVersion: (id: number, versionId: string, expectedRevision?: string) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/ppt/versions/restore`, {
      version_id: versionId, expected_revision: expectedRevision,
    }, { timeout: 120_000 }),
  listPptTemplates: () =>
    http.get<ApiResponse<PresentationTemplate[]>>('/agent/ppt-templates'),
  replacePptImage: (id: number, slideIndex: number, prompt: string, expectedRevision: string) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/ppt/slides/${slideIndex}/image`, {
      prompt, expected_revision: expectedRevision,
    }),
  uploadPptTemplate: (form: FormData) =>
    http.post<ApiResponse<PresentationTemplate>>('/agent/ppt-templates', form, {
      timeout: 120_000,
    }),
  deletePptTemplate: (id: number) =>
    http.delete<ApiResponse<null>>(`/agent/ppt-templates/${id}`),
  publish: (id: number, payload: {
    teaching_class_id: number
    title: string
    description: string
    publish_ppt: boolean
    publish_discussions: boolean
    discussion_indices: number[]
    confirmed: boolean
    expected_ppt_revision?: string
    allow_previous_ppt?: boolean
  }) =>
    http.post<ApiResponse<LessonPublication>>(`/agent/runs/${id}/publish`, payload),
  publications: (teachingClassId?: number) =>
    http.get<ApiResponse<LessonPublication[]>>('/agent/publications', {
      params: teachingClassId ? { teaching_class_id: teachingClassId } : undefined,
    }),
  downloadPublicationPpt: (id: number) =>
    http.get<Blob>(`/agent/publications/${id}/ppt`, { responseType: 'blob' }),
  downloadArtifact: (id: number, artifactKey: string, versionId?: string, expectedRevision?: string) =>
    http.get<Blob>(`/agent/runs/${id}/artifacts/${artifactKey}/download`, {
      responseType: 'blob',
      params: { version_id: versionId, expected_revision: expectedRevision },
    }),
  cancel: (id: number) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/cancel`),
  retry: (id: number) =>
    http.post<ApiResponse<AgentRun>>(`/agent/runs/${id}/retry`),
  async stream(id: number, handlers: {
    onSnapshot: (run: AgentRun) => void
    onDone?: () => void
  }) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const response = await fetch(`${baseURL}/agent/runs/${id}/events`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
    })
    if (!response.ok || !response.body) throw new Error('智能任务进度服务暂时不可用')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const block of events) {
        const event = block.match(/^event:\s*(.+)$/m)?.[1]
        const dataLine = block.match(/^data:\s*(.+)$/m)?.[1]
        if (!event || !dataLine) continue
        const data = JSON.parse(dataLine)
        if (event === 'snapshot') handlers.onSnapshot(data)
        if (event === 'done') handlers.onDone?.()
        if (event === 'error') throw new Error(data.message || '智能任务执行失败')
      }
    }
  },
}

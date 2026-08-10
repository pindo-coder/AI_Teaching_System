import { http, type ApiResponse } from './http'

export type AiMediaKind = 'image' | 'audio'

export interface AiMediaAsset {
  id: number
  media_kind: AiMediaKind
  original_filename: string
  mime_type: string
  byte_size: number
  duration_seconds: number | null
  status: string
  created_time: string
}

export interface AiMediaCapabilities {
  image_enabled: boolean
  audio_enabled: boolean
  max_images: number
  max_image_mb: number
  max_audio_mb: number
  max_audio_seconds: number
  retention_hours: number
  user_quota_mb: number
}

export interface AiMediaUploadOptions {
  courseId?: number | null
  chapterId?: number | null
  durationSeconds?: number | null
  signal?: AbortSignal
  onProgress?: (percent: number) => void
}

export const aiMediaApi = {
  capabilities: () =>
    http.get<ApiResponse<AiMediaCapabilities>>('/ai/media/capabilities'),

  uploadAsset(file: File, options: AiMediaUploadOptions = {}) {
    const formData = new FormData()
    formData.append('file', file, file.name)
    if (options.courseId != null) formData.append('course_id', String(options.courseId))
    if (options.chapterId != null) formData.append('chapter_id', String(options.chapterId))
    if (options.durationSeconds != null) {
      formData.append('duration_seconds', String(options.durationSeconds))
    }

    return http.post<ApiResponse<AiMediaAsset>>('/ai/media/assets', formData, {
      timeout: 120_000,
      signal: options.signal,
      onUploadProgress: (event) => {
        if (!options.onProgress || !event.total) return
        options.onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
      },
    })
  },

  deleteAsset: (assetId: number) =>
    http.delete<ApiResponse<AiMediaAsset>>(`/ai/media/assets/${assetId}`),

  transcribeAsset: (assetId: number, signal?: AbortSignal) =>
    http.post<ApiResponse<{ text: string }>>(
      `/ai/media/assets/${assetId}/transcribe`,
      undefined,
      { timeout: 120_000, signal },
    ),
}

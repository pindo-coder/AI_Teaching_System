import { http, type ApiResponse } from './http'

export interface KnowledgeDocument {
  id: number
  source_title: string
  source_type: string
  original_filename: string
  course_id: number
  chapter_id: number | null
  knowledge_point: string | null
  status: 'processing' | 'ready' | 'failed'
  chunk_count: number
  created_time: string
  updated_time: string
}

export const knowledgeApi = {
  list: (courseId?: number) =>
    http.get<ApiResponse<KnowledgeDocument[]>>('/knowledge/documents', {
      params: courseId ? { course_id: courseId } : undefined,
    }),
  upload: (formData: FormData) =>
    http.post<ApiResponse<KnowledgeDocument>>('/knowledge/documents', formData, {
      timeout: 120_000,
    }),
  remove: (id: number) =>
    http.delete<ApiResponse<{ id: number }>>(`/knowledge/documents/${id}`),
  reindex: (id: number) =>
    http.post<ApiResponse<KnowledgeDocument>>(`/knowledge/documents/${id}/reindex`, undefined, {
      timeout: 120_000,
    }),
}

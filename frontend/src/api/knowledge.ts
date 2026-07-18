import { http, type ApiResponse } from './http'

export interface KnowledgeDocument {
  id: number
  source_title: string
  source_type: string
  original_filename: string
  course_id: number
  chapter_id: number | null
  textbook_version_id: number | null
  knowledge_point: string | null
  status: 'processing' | 'ready' | 'failed'
  chunk_count: number
  source_role: 'primary' | 'supplementary'
  access_policy: 'citation_only' | 'full_preview' | 'download'
  calibration_status: 'pending' | 'calibrated' | 'published'
  created_time: string
  updated_time: string
}

export interface DocumentPage {
  id: number
  pdf_page: number
  printed_page_label: string | null
  text: string
  width: number | null
  height: number | null
}

export interface OutlineNode {
  id: number
  parent_id: number | null
  chapter_id: number | null
  node_type: 'chapter' | 'section' | 'knowledge_point' | 'preface' | 'reference'
  title: string
  sort_order: number
  pdf_page_start: number
  pdf_page_end: number
  start_anchor: string | null
  end_anchor: string | null
  retrieval_enabled: boolean
  calibration_status: string
}

export interface PageNumberRangeInput {
  pdf_page_start: number
  pdf_page_end: number
  numbering_style: 'arabic' | 'roman_upper' | 'roman_lower' | 'none'
  printed_start?: string
}

export interface CalibrationPayload {
  version_label: string
  access_policy: 'citation_only' | 'full_preview' | 'download'
  page_number_ranges: PageNumberRangeInput[]
  outline: Array<{
    client_id: string
    parent_client_id: string | null
    chapter_id: number | null
    node_type: OutlineNode['node_type']
    title: string
    sort_order: number
    pdf_page_start: number
    pdf_page_end: number
    start_anchor: string | null
    end_anchor: string | null
    retrieval_enabled: boolean
  }>
}

export const knowledgeApi = {
  list: (courseId?: number) =>
    http.get<ApiResponse<KnowledgeDocument[]>>('/knowledge/documents', {
      params: courseId ? { course_id: courseId } : undefined,
    }),
  detail: (id: number) => http.get<ApiResponse<KnowledgeDocument>>(`/knowledge/documents/${id}`),
  pages: (id: number, page?: number) => http.get<ApiResponse<DocumentPage[]>>(`/knowledge/documents/${id}/pages`, { params: page ? { page } : undefined }),
  outline: (id: number) => http.get<ApiResponse<OutlineNode[]>>(`/knowledge/documents/${id}/outline`),
  calibrationMeta: (id: number) => http.get<ApiResponse<{ version_label: string; access_policy: KnowledgeDocument['access_policy']; page_number_ranges: PageNumberRangeInput[] }>>(`/knowledge/documents/${id}/calibration-meta`),
  fileBlob: (id: number, page?: number) => http.get<Blob>(`/knowledge/documents/${id}/file`, { params: page ? { page } : undefined, responseType: 'blob', timeout: 60_000 }),
  calibrate: (id: number, payload: CalibrationPayload) => http.put<ApiResponse<KnowledgeDocument>>(`/knowledge/documents/${id}/calibration`, payload, { timeout: 180_000 }),
  publish: (id: number) => http.post<ApiResponse<KnowledgeDocument>>(`/knowledge/documents/${id}/publish`),
  citationFeedback: (payload: { document_id?: number; vector_id?: string; feedback_type: string; note?: string; question?: string }) => http.post<ApiResponse<{ id: number }>>('/knowledge/citation-feedback', payload),
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
  autoCalibrate: (id: number) =>
    http.post<ApiResponse<KnowledgeDocument>>(`/knowledge/documents/${id}/auto-calibrate`),
}

import { http, type ApiResponse } from './http'

export interface KnowledgeDocument {
  id: number
  source_title: string
  source_type: string
  original_filename: string
  course_id: number | null
  chapter_id: number | null
  textbook_version_id: number | null
  knowledge_point: string | null
  status: 'processing' | 'ready' | 'failed'
  chunk_count: number
  source_role: 'primary' | 'supplementary'
  material_type: 'central' | 'textbook' | 'local' | 'unclassified'
  publisher: string | null
  published_date: string | null
  source_url: string | null
  applicable_scope: string | null
  owner_user_id: number | null
  review_status: 'pending' | 'published' | 'rejected' | 'archived'
  is_active: boolean
  verified_by: number | null
  verified_time: string | null
  content_hash: string | null
  snapshot_time: string | null
  version_label: string | null
  supersedes_document_id: number | null
  course_ids: number[]
  chapter_ids: number[]
  teaching_class_ids: number[]
  knowledge_tags: string[]
  access_policy: 'citation_only' | 'full_preview' | 'download'
  calibration_status: 'pending' | 'calibrated' | 'published'
  created_time: string
  updated_time: string
}

export interface TextbookVersion {
  id: number
  course_id: number
  version_label: string
  status: 'draft' | 'published'
  is_current: boolean
  created_time: string
  documents: KnowledgeDocument[]
}

export interface MaterialSuggestion {
  course_id: number
  course_name: string
  chapter_id: number | null
  chapter_title: string | null
  score: number
}

export interface MaterialPreviewColumn {
  field: string
  column: string
  confidence: number
}

export interface MaterialPreviewRow {
  row_number: number
  selected: boolean
  source_url: string
  source_title: string
  publisher: string
  published_date: string
  applicable_scope: string
  version_label: string
  knowledge_tags: string[]
  raw_data: Record<string, string>
  errors: string[]
  warnings: string[]
}

export interface MaterialPreviewSheet {
  name: string
  header_row: number
  columns: string[]
  mapping: MaterialPreviewColumn[]
  rows: MaterialPreviewRow[]
}

export interface MaterialBatchPreview {
  filename: string
  sheets: MaterialPreviewSheet[]
}

export interface MaterialBatchItem {
  id: number
  row_number: number
  source_url: string
  source_title: string | null
  publisher: string | null
  published_date: string | null
  applicable_scope: string | null
  version_label: string | null
  knowledge_tags: string[]
  status: string
  error_message: string | null
  document_id: number | null
  raw_data: Record<string, string>
}

export interface MaterialBatch {
  id: number
  original_filename: string | null
  sheet_name: string | null
  status: string
  total_count: number
  completed_count: number
  success_count: number
  failed_count: number
  duplicate_count: number
  course_ids: number[]
  chapter_ids: number[]
  access_policy: string
  created_time: string
  updated_time: string
  items: MaterialBatchItem[]
}

export type MaterialBatchSummary = Omit<MaterialBatch, 'course_ids' | 'chapter_ids' | 'access_policy' | 'items'>

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
  versions: (courseId: number) =>
    http.get<ApiResponse<TextbookVersion[]>>(`/knowledge/courses/${courseId}/versions`),
  activateVersion: (versionId: number) =>
    http.post<ApiResponse<TextbookVersion>>(`/knowledge/versions/${versionId}/activate`),
  materials: (materialType?: KnowledgeDocument['material_type'], reviewStatus?: string) =>
    http.get<ApiResponse<KnowledgeDocument[]>>('/knowledge/materials', {
      params: { ...(materialType ? { material_type: materialType } : {}), ...(reviewStatus ? { review_status: reviewStatus } : {}) },
    }),
  uploadMaterial: (formData: FormData) =>
    http.post<ApiResponse<KnowledgeDocument>>('/knowledge/materials', formData, { timeout: 120_000 }),
  importMaterialUrl: (payload: Record<string, unknown>) =>
    http.post<ApiResponse<KnowledgeDocument>>('/knowledge/materials/url', payload, { timeout: 120_000 }),
  previewMaterialBatch: (file: File) => {
    const payload = new FormData()
    payload.append('file', file)
    return http.post<ApiResponse<MaterialBatchPreview>>('/knowledge/materials/batch/preview', payload, { timeout: 120_000 })
  },
  createMaterialBatch: (payload: Record<string, unknown>) =>
    http.post<ApiResponse<MaterialBatch>>('/knowledge/materials/batches', payload),
  materialBatches: (limit = 30) =>
    http.get<ApiResponse<MaterialBatchSummary[]>>('/knowledge/materials/batches', { params: { limit } }),
  materialBatch: (id: number) =>
    http.get<ApiResponse<MaterialBatch>>(`/knowledge/materials/batches/${id}`),
  retryMaterialBatch: (id: number) =>
    http.post<ApiResponse<MaterialBatch>>(`/knowledge/materials/batches/${id}/retry`),
  materialSuggestions: (id: number) =>
    http.get<ApiResponse<MaterialSuggestion[]>>(`/knowledge/materials/${id}/suggestions`),
  updateMaterialScopes: (id: number, payload: { course_ids: number[]; chapter_ids: number[]; teaching_class_ids: number[]; knowledge_tags: string[] }) =>
    http.put<ApiResponse<KnowledgeDocument>>(`/knowledge/materials/${id}/scopes`, payload),
  publishMaterial: (id: number) =>
    http.post<ApiResponse<KnowledgeDocument>>(`/knowledge/materials/${id}/publish`),
  archiveMaterial: (id: number) =>
    http.post<ApiResponse<KnowledgeDocument>>(`/knowledge/materials/${id}/archive`),
  classifyMaterial: (id: number, payload: { material_type: 'central' | 'textbook' | 'local'; publisher?: string; published_date?: string; applicable_scope?: string }) =>
    http.put<ApiResponse<KnowledgeDocument>>(`/knowledge/materials/${id}/classification`, payload, { timeout: 120_000 }),
}

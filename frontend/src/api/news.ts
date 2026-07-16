import { http, type ApiResponse } from './http'

export interface NewsItem {
  id: number
  title: string
  summary: string | null
  source_name: string
  source_url: string
  article_url: string
  published_time: string | null
  fetched_time: string
}

export interface TextbookRelationItem {
  course_id: number
  chapter_id: number
  chapter_title: string
  score: number
  reason: string
  excerpt: string
  position: string
}

export interface NewsStudyNoteResult {
  note_id: number
  course_id: number
  chapter_id: number
  created: boolean
  appended: boolean
}

export interface NewsSearchData {
  items: NewsItem[]
  total: number
  page: number
  page_size: number
  pages: number
  sources: string[]
}

export const newsApi = {
  list: () => http.get<ApiResponse<NewsItem[]>>('/current-affairs'),
  search: (filters: { q?: string; sources?: string[]; days?: number | null; sort?: 'latest' | 'relevance'; page?: number; pageSize?: number }) => {
    const params = new URLSearchParams()
    if (filters.q) params.set('q', filters.q)
    for (const source of filters.sources || []) params.append('source', source)
    if (filters.days) params.set('days', String(filters.days))
    params.set('sort', filters.sort || 'latest')
    params.set('page', String(filters.page || 1))
    params.set('page_size', String(filters.pageSize || 10))
    return http.get<ApiResponse<NewsSearchData>>('/current-affairs/search', { params })
  },
  refresh: () => http.post<ApiResponse<NewsItem[]>>('/current-affairs/refresh'),
  textbookRelations: (newsId: number, courseId: number) =>
    http.get<ApiResponse<TextbookRelationItem[]>>(`/current-affairs/${newsId}/textbook-relations`, { params: { course_id: courseId } }),
  saveStudyNote: (newsId: number, payload: { chapter_id: number; content: string; textbook_relation: string; mode: 'append' | 'create' }) =>
    http.post<ApiResponse<NewsStudyNoteResult>>(`/current-affairs/${newsId}/study-note`, payload),
}

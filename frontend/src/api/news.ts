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

export interface NewsSummaryStreamHandlers {
  onMeta: (data: { grounded: boolean; model: string; scope: 'news' }) => void
  onChunk: (text: string) => void
  onSources: () => void
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
  textbookRelations: (newsId: number, courseId: number, options: { signal?: AbortSignal } = {}) =>
    http.get<ApiResponse<TextbookRelationItem[]>>(`/current-affairs/${newsId}/textbook-relations`, { params: { course_id: courseId }, signal: options.signal }),
  async summaryStream(newsId: number, handlers: NewsSummaryStreamHandlers, options: { signal?: AbortSignal } = {}) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const response = await fetch(`${baseURL}/current-affairs/${newsId}/ai-summary/stream`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      signal: options.signal,
    })
    if (!response.ok || !response.body) throw new Error(`AI 时政总结暂时不可用（HTTP ${response.status}）`)
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
        if (event === 'meta') handlers.onMeta(data)
        if (event === 'chunk') handlers.onChunk(data.text)
        if (event === 'sources') handlers.onSources()
        if (event === 'error') throw new Error(data.message || 'AI 时政总结生成失败')
      }
    }
  },
  saveStudyNote: (newsId: number, payload: { chapter_id: number; content: string; textbook_relation: string; mode: 'append' | 'create' }) =>
    http.post<ApiResponse<NewsStudyNoteResult>>(`/current-affairs/${newsId}/study-note`, payload),
}

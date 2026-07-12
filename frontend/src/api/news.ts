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

export const newsApi = {
  list: () => http.get<ApiResponse<NewsItem[]>>('/current-affairs'),
  refresh: () => http.post<ApiResponse<NewsItem[]>>('/current-affairs/refresh'),
}

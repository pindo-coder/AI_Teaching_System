import { http, type ApiResponse } from './http'

export interface StudyNote {
  id: number
  user_id: number
  course_id: number
  chapter_id: number
  content: string
  created_time: string
  updated_time: string
  course_name?: string
  chapter_title?: string
}

export interface ReviewItem {
  id: number
  course_id: number
  chapter_id: number
  course_name: string
  chapter_title: string
  review_count: number
  interval_days: number
  next_review_at: string
  last_reviewed_at: string | null
}

export interface StudyChatMessage {
  id: number
  user_id: number
  course_id: number
  chapter_id: number
  role: 'user' | 'assistant'
  content: string
  model: string | null
  sources: Array<{ source_title: string; excerpt: string; position: string }>
  created_time: string
}

export const studyApi = {
  notes: () => http.get<ApiResponse<StudyNote[]>>('/study/notes'),
  note: (chapterId: number) => http.get<ApiResponse<StudyNote | null>>(`/study/notes/${chapterId}`),
  saveNote: (chapterId: number, content: string) => http.put<ApiResponse<StudyNote>>(`/study/notes/${chapterId}`, { content }),
  reviews: () => http.get<ApiResponse<ReviewItem[]>>('/study/reviews/today'),
  activateReview: (chapterId: number) => http.post<ApiResponse<{ id: number; interval_days: number }>>(`/study/reviews/${chapterId}/activate`),
  completeReview: (chapterId: number) => http.post<ApiResponse<{ id: number; interval_days: number }>>(`/study/reviews/${chapterId}/complete`),
  deleteNote: (noteId: number) => http.delete<ApiResponse<{ id: number }>>(`/study/notes/${noteId}`),
  chatHistory: (chapterId: number) => http.get<ApiResponse<StudyChatMessage[]>>(`/study/chat-history/${chapterId}`),
  saveChatHistory: (payload: { course_id: number; chapter_id: number; question: string; answer: string; model: string | null; sources: StudyChatMessage['sources'] }) =>
    http.post<ApiResponse<StudyChatMessage[]>>('/study/chat-history', payload),
}

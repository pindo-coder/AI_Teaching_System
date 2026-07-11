import { http, type ApiResponse } from './http'
import type { Chapter, Course, CourseDetail } from '@/types'

export const courseApi = {
  list: () => http.get<ApiResponse<Course[]>>('/courses'),
  detail: (id: number) => http.get<ApiResponse<CourseDetail>>(`/courses/${id}`),
  create: (payload: { name: string; description?: string }) =>
    http.post<ApiResponse<Course>>('/courses', payload),
  update: (id: number, payload: { name?: string; description?: string }) =>
    http.put<ApiResponse<Course>>(`/courses/${id}`, payload),
  remove: (id: number) => http.delete<ApiResponse<{ id: number }>>(`/courses/${id}`),
  createChapter: (
    courseId: number,
    payload: { title: string; content?: string; sort_order: number },
  ) => http.post<ApiResponse<Chapter>>(`/courses/${courseId}/chapters`, payload),
  updateChapter: (
    chapterId: number,
    payload: { title?: string; content?: string; sort_order?: number },
  ) => http.put<ApiResponse<Chapter>>(`/chapters/${chapterId}`, payload),
  removeChapter: (chapterId: number) =>
    http.delete<ApiResponse<{ id: number }>>(`/chapters/${chapterId}`),
}

import { http, type ApiResponse } from './http'

export interface TeachingNotification {
  id: number
  policy_change_id: number | null
  notification_type: string
  level: 'urgent' | 'important' | 'normal' | 'observe' | string
  title: string
  content: string
  course_ids: number[]
  chapter_ids: number[]
  source_url: string | null
  action_url: string | null
  is_read: boolean
  read_time: string | null
  created_time: string
  updated_time: string
}

export const notificationApi = {
  list(unreadOnly = false, limit = 50) {
    return http.get<ApiResponse<TeachingNotification[]>>('/notifications', {
      params: { unread_only: unreadOnly, limit },
    })
  },
  markRead(id: number) {
    return http.post<ApiResponse<TeachingNotification>>(`/notifications/${id}/read`)
  },
  markAllRead() {
    return http.post<ApiResponse<{ updated: number }>>('/notifications/read-all')
  },
}

import { http, type ApiResponse } from './http'

export interface ClassroomActivity {
  id: number
  teaching_class_id: number | null
  course_id: number
  chapter_id: number
  created_by: number
  question: string
  minutes: number
  status: string
  created_time: string
}

export interface ClassroomResponse {
  id: number
  activity_id: number
  user_id: number
  answer: string
  created_time: string
}

export interface DiscussionAuthor { id: number; name: string; role: string }
export interface DiscussionThread {
  id: number; teaching_class_id: number | null; course_id: number | null; chapter_id: number | null; activity_id: number | null
  title: string; content: string; status: string; is_pinned: boolean; reply_count: number
  last_replied_time: string | null; created_time: string; updated_time: string; author: DiscussionAuthor
}
export interface DiscussionReply {
  id: number; thread_id: number; parent_reply_id: number | null; content: string; status: string
  created_time: string; updated_time: string; author: DiscussionAuthor
}

export const classroomApi = {
  list: () => http.get<ApiResponse<ClassroomActivity[]>>('/classroom/activities'),
  publish: (payload: { teaching_class_id: number; course_id: number; chapter_id: number; question: string; minutes: number }) =>
    http.post<ApiResponse<ClassroomActivity>>('/classroom/activities', payload),
  respond: (activityId: number, answer: string) =>
    http.post<ApiResponse<ClassroomResponse>>(`/classroom/activities/${activityId}/responses`, { answer }),
  discussions: (params?: Record<string, unknown>) =>
    http.get<ApiResponse<DiscussionThread[]>>('/classroom/discussions', { params }),
  createDiscussion: (payload: { teaching_class_id?: number; course_id?: number; chapter_id?: number; activity_id?: number; title: string; content: string }) =>
    http.post<ApiResponse<DiscussionThread>>('/classroom/discussions', payload),
  discussionReplies: (threadId: number) =>
    http.get<ApiResponse<DiscussionReply[]>>(`/classroom/discussions/${threadId}/replies`),
  replyDiscussion: (threadId: number, content: string, parentReplyId?: number) =>
    http.post<ApiResponse<DiscussionReply>>(`/classroom/discussions/${threadId}/replies`, { content, parent_reply_id: parentReplyId }),
  updateDiscussion: (threadId: number, payload: { title?: string; content?: string }) =>
    http.patch<ApiResponse<DiscussionThread>>(`/classroom/discussions/${threadId}`, payload),
  deleteDiscussion: (threadId: number) => http.delete<ApiResponse<{ id: number }>>(`/classroom/discussions/${threadId}`),
  updateReply: (replyId: number, content: string) =>
    http.patch<ApiResponse<DiscussionReply>>(`/classroom/discussions/replies/${replyId}`, { content }),
  deleteReply: (replyId: number) => http.delete<ApiResponse<{ id: number }>>(`/classroom/discussions/replies/${replyId}`),
  pinDiscussion: (threadId: number) => http.post<ApiResponse<DiscussionThread>>(`/classroom/discussions/${threadId}/pin`),
  closeDiscussion: (threadId: number) => http.post<ApiResponse<DiscussionThread>>(`/classroom/discussions/${threadId}/close`),
}

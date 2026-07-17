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

export const classroomApi = {
  list: () => http.get<ApiResponse<ClassroomActivity[]>>('/classroom/activities'),
  publish: (payload: { teaching_class_id: number; course_id: number; chapter_id: number; question: string; minutes: number }) =>
    http.post<ApiResponse<ClassroomActivity>>('/classroom/activities', payload),
  respond: (activityId: number, answer: string) =>
    http.post<ApiResponse<ClassroomResponse>>(`/classroom/activities/${activityId}/responses`, { answer }),
}

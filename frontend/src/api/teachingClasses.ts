import { http, type ApiResponse } from './http'

export interface CourseSubject { id: number; name: string; code: string | null; description: string | null }
export interface AcademicTerm { id: number; name: string; start_date: string; end_date: string; is_current: boolean }
export interface TeachingClass {
  id: number; subject_id: number; subject_name: string; term_id: number; term_name: string
  name: string; code: string; status: 'not_started' | 'active' | 'completed' | 'archived'
  join_code: string; join_code_enabled: boolean; description: string | null; is_default: boolean
  teacher_role: string | null; membership_status: string | null; primary_course_id: number | null
  material_ids: number[]; student_count: number
}
export interface ClassMember { id: number; user_id: number; username: string; identity_no: string | null; status: string; join_method: string; group_id: number | null }
export interface ClassRequest { id: number; user_id: number; username: string; identity_no: string | null; request_type: string; created_time: string }
export interface ClassGroup { id: number; name: string; sort_order: number; user_ids: number[] }
export interface AvailableTeacher { id: number; username: string; identity_no: string | null }

export const teachingClassApi = {
  subjects: () => http.get<ApiResponse<CourseSubject[]>>('/teaching-classes/subjects'),
  createSubject: (payload: { name: string; code?: string; description?: string }) => http.post<ApiResponse<CourseSubject>>('/teaching-classes/subjects', payload),
  terms: () => http.get<ApiResponse<AcademicTerm[]>>('/teaching-classes/terms'),
  availableTeachers: () => http.get<ApiResponse<AvailableTeacher[]>>('/teaching-classes/teachers/available'),
  createTerm: (payload: { name: string; start_date: string; end_date: string; is_current: boolean }) => http.post<ApiResponse<AcademicTerm>>('/teaching-classes/terms', payload),
  list: () => http.get<ApiResponse<TeachingClass[]>>('/teaching-classes'),
  create: (payload: Record<string, unknown>) => http.post<ApiResponse<TeachingClass>>('/teaching-classes', payload),
  join: (joinCode: string) => http.post<ApiResponse<{ status: string; teaching_class_id: number; message: string }>>('/teaching-classes/join', { join_code: joinCode }),
  leave: (classId: number) => http.post<ApiResponse<{ status: string; message: string }>>(`/teaching-classes/${classId}/leave`),
  members: (classId: number) => http.get<ApiResponse<ClassMember[]>>(`/teaching-classes/${classId}/members`),
  requests: (classId: number) => http.get<ApiResponse<ClassRequest[]>>(`/teaching-classes/${classId}/join-requests`),
  reviewRequest: (requestId: number, approved: boolean) => http.post<ApiResponse<{ id: number; status: string }>>(`/teaching-classes/join-requests/${requestId}/review`, { approved }),
  roster: (classId: number, file: File) => { const data = new FormData(); data.append('file', file); return http.post<ApiResponse<Record<string, number>>>(`/teaching-classes/${classId}/roster`, data) },
  groups: (classId: number) => http.get<ApiResponse<ClassGroup[]>>(`/teaching-classes/${classId}/groups`),
  randomGroups: (classId: number, groupCount: number) => http.post<ApiResponse<ClassGroup[]>>(`/teaching-classes/${classId}/groups/random`, { group_count: groupCount, name_prefix: '第' }),
  createGroup: (classId: number, name: string, userIds: number[]) => http.post<ApiResponse<ClassGroup>>(`/teaching-classes/${classId}/groups`, { name, user_ids: userIds }),
  updateStatus: (classId: number, status: TeachingClass['status']) => http.put<ApiResponse<{ id: number; status: string }>>(`/teaching-classes/${classId}/status`, { status }),
  updateJoinCode: (classId: number, payload: { enabled?: boolean; regenerate?: boolean }) => http.put<ApiResponse<{ join_code: string; join_code_enabled: boolean }>>(`/teaching-classes/${classId}/join-code`, payload),
  addTeacher: (classId: number, userId: number) => http.post<ApiResponse<{ id: number; user_id: number }>>(`/teaching-classes/${classId}/teachers`, { user_id: userId }),
  addMaterial: (classId: number, courseId: number, materialRole: 'primary' | 'supplementary') => http.post<ApiResponse<{ id: number; course_id: number; material_role: string }>>(`/teaching-classes/${classId}/materials`, { course_id: courseId, material_role: materialRole }),
}

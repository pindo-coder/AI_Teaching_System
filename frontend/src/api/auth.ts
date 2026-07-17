import { http, type ApiResponse } from './http'
import type { User } from '@/types'

interface TokenData {
  access_token: string
  token_type: string
  user: User
}

export const authApi = {
  register: (payload: { username: string; password: string; role: 'student' | 'teacher'; identity_no: string }) =>
    http.post<ApiResponse<User>>('/auth/register', payload),
  login: (payload: { username: string; password: string }) =>
    http.post<ApiResponse<TokenData>>('/auth/login', payload),
  me: () => http.get<ApiResponse<User>>('/auth/me'),
  pendingTeachers: () => http.get<ApiResponse<User[]>>('/auth/teachers/pending'),
  reviewTeacher: (userId: number, status: 'approved' | 'rejected' | 'disabled', note = '') =>
    http.put<ApiResponse<User>>(`/auth/teachers/${userId}/approval`, { status, note }),
}

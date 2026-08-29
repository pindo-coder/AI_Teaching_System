import { http, type ApiResponse } from './http'
import type { User } from '@/types'

interface TokenData {
  access_token: string
  token_type: string
  user: User
}

export const authApi = {
  register: (payload: { username: string; password: string; role: 'student' | 'teacher'; identity_no: string; email?: string }) =>
    http.post<ApiResponse<User>>('/auth/register', payload),
  login: (payload: { username: string; password: string }) =>
    http.post<ApiResponse<TokenData>>('/auth/login', payload),
  me: () => http.get<ApiResponse<User>>('/auth/me'),
  requestPasswordReset: (identifier: string) =>
    http.post<ApiResponse<{ next_step: 'email' | 'verify_email' | 'admin' }>>('/auth/password-reset/request', { identifier }),
  confirmPasswordReset: (payload: { token?: string; identifier?: string; code?: string; new_password: string }) =>
    http.post<ApiResponse<Record<string, string>>>('/auth/password-reset/confirm', payload),
  changePassword: (new_password: string) =>
    http.post<ApiResponse<Record<string, string>>>('/auth/password/change', { new_password }),
  requestEmailVerification: (email: string) =>
    http.post<ApiResponse<Record<string, string>>>('/auth/email/verification/request', { email }),
  confirmEmailVerification: (email: string, code: string) =>
    http.post<ApiResponse<User>>('/auth/email/verification/confirm', { email, code }),
  users: () => http.get<ApiResponse<User[]>>('/auth/users'),
  pendingPasswordResets: () => http.get<ApiResponse<Array<{ id: number; user_id: number; username: string; email: string | null; requested_at: string; request_ip: string | null }>>>('/auth/password-reset/pending'),
  temporaryPassword: (userId: number) =>
    http.post<ApiResponse<{ user_id: number; temporary_password: string; must_change_password: boolean }>>(`/auth/users/${userId}/temporary-password`),
  pendingTeachers: () => http.get<ApiResponse<User[]>>('/auth/teachers/pending'),
  reviewTeacher: (userId: number, status: 'approved' | 'rejected' | 'disabled', note = '') =>
    http.put<ApiResponse<User>>(`/auth/teachers/${userId}/approval`, { status, note }),
}

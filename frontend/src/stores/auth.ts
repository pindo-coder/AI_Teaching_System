import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import type { User } from '@/types'

function storedUser(): User | null {
  const raw = localStorage.getItem('current_user')
  if (!raw) return null
  try { return JSON.parse(raw) as User } catch { return null }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('access_token') as string | null,
    user: storedUser(),
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    isAdmin: (state) => state.user?.role === 'admin',
    canManageKnowledge: (state) => state.user?.role === 'admin' || state.user?.role === 'teacher',
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await authApi.login({ username, password })
      this.token = data.data.access_token
      this.user = data.data.user
      localStorage.setItem('access_token', this.token)
      localStorage.setItem('current_user', JSON.stringify(this.user))
    },
    async loadCurrentUser() {
      if (!this.token) return
      const { data } = await authApi.me()
      this.user = data.data
      localStorage.setItem('current_user', JSON.stringify(this.user))
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('current_user')
    },
  },
})

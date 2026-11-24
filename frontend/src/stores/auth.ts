import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import { useWorkspaceStore } from '@/stores/workspace'
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
    sessionChecked: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    isAdmin: (state) => state.user?.role === 'admin',
    isTeacher: (state) => state.user?.role === 'teacher' || state.user?.role === 'admin',
    canManageKnowledge: (state) => state.user?.role === 'admin' || state.user?.role === 'teacher',
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await authApi.login({ username, password })
      this.token = data.data.access_token
      this.user = data.data.user
      this.sessionChecked = true
      localStorage.setItem('access_token', this.token)
      localStorage.setItem('current_user', JSON.stringify(this.user))
    },
    async loadCurrentUser() {
      if (!this.token) {
        this.user = null
        this.sessionChecked = true
        return
      }
      const { data } = await authApi.me()
      this.user = data.data
      this.sessionChecked = true
      localStorage.setItem('current_user', JSON.stringify(this.user))
    },
    logout(revokeRemote = true) {
      const activeToken = this.token
      if (revokeRemote && activeToken) {
        void authApi.logout().catch(() => undefined)
      }
      this.token = null
      this.user = null
      this.sessionChecked = false
      localStorage.removeItem('access_token')
      localStorage.removeItem('current_user')
      try {
        useWorkspaceStore().clear()
      } catch {
        // Store may not be active during early bootstrap.
      }
    },
  },
})

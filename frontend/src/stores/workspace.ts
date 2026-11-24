import { defineStore } from 'pinia'
import { learningApi } from '@/api/learning'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import type { DashboardData } from '@/types'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    dashboard: null as DashboardData | null,
    teachingClasses: [] as TeachingClass[],
    loading: false,
    initialized: false,
    error: '' as string,
  }),
  getters: {
    currentCourse: (state) => state.dashboard?.current_course || null,
    currentChapter: (state) => state.dashboard?.current_chapter || null,
    currentClass: (state) =>
      state.teachingClasses.find((item) => item.is_default)
      || state.teachingClasses.find((item) => item.status === 'active')
      || state.teachingClasses[0]
      || null,
  },
  actions: {
    async initialize(force = false) {
      if (this.loading || (this.initialized && !force)) return
      this.loading = true
      this.error = ''
      try {
        const [dashboardResult, classResult] = await Promise.allSettled([
          learningApi.dashboard(),
          teachingClassApi.list(),
        ])
        if (dashboardResult.status === 'fulfilled') this.dashboard = dashboardResult.value.data.data
        if (classResult.status === 'fulfilled') this.teachingClasses = classResult.value.data.data
        if (dashboardResult.status === 'fulfilled' || classResult.status === 'fulfilled') {
          this.initialized = true
        } else {
          this.error = '工作台上下文加载失败，请稍后重试'
        }
      } finally {
        this.loading = false
      }
    },
    clear() {
      this.dashboard = null
      this.teachingClasses = []
      this.initialized = false
      this.error = ''
    },
  },
})


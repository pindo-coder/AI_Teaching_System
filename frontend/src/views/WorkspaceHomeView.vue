<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import StudentTodayView from './DashboardView.vue'
import TeacherWorkspaceView from './TeacherWorkspaceView.vue'
import AdminWorkspaceView from './AdminWorkspaceView.vue'

const auth = useAuthStore()
const workspaceComponent = computed(() => {
  if (auth.user?.role === 'admin') return AdminWorkspaceView
  if (auth.user?.role === 'teacher') return TeacherWorkspaceView
  return StudentTodayView
})
</script>

<template>
  <component :is="workspaceComponent" />
</template>


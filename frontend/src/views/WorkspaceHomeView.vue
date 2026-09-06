<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import DashboardView from './DashboardView.vue'
import AdminWorkspaceView from './AdminWorkspaceView.vue'

const auth = useAuthStore()
const workspaceComponent = computed(() => {
  if (auth.user?.role === 'admin') return AdminWorkspaceView
  return DashboardView
})
</script>

<template>
  <component :is="workspaceComponent" />
</template>

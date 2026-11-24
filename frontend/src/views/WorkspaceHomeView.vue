<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useAuthStore } from '@/stores/auth'

const DashboardView = defineAsyncComponent(() => import('./DashboardView.vue'))
const AdminWorkspaceView = defineAsyncComponent(() => import('./AdminWorkspaceView.vue'))

const auth = useAuthStore()
const workspaceComponent = computed(() => {
  if (auth.user?.role === 'admin') return AdminWorkspaceView
  return DashboardView
})
</script>

<template>
  <component :is="workspaceComponent" />
</template>

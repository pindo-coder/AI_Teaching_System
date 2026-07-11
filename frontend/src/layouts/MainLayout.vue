<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="app-layout">
    <el-aside width="240px" class="sidebar">
      <div class="brand"><span>思政智教</span><small>AI Teaching</small></div>
      <el-menu router :default-active="$route.path">
        <el-menu-item index="/"><span>工作台</span></el-menu-item>
        <el-menu-item index="/courses"><span>课程中心</span></el-menu-item>
        <el-menu-item v-if="auth.canManageKnowledge" index="/knowledge"><span>课程知识库</span></el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div />
        <el-dropdown>
          <span class="user-menu">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
          <template #dropdown><el-dropdown-menu><el-dropdown-item @click="logout">退出登录</el-dropdown-item></el-dropdown-menu></template>
        </el-dropdown>
      </el-header>
      <el-main class="page"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

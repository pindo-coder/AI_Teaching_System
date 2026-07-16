<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import FloatingAiAssistant from '@/components/FloatingAiAssistant.vue'

const auth = useAuthStore()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="app-layout">
    <el-container>
      <el-header class="topbar">
        <router-link to="/" class="brand"><span>思政智教</span><small>AI Teaching</small></router-link>
        <nav class="topbar-links"><router-link to="/courses">课程中心</router-link><router-link to="/assignments">学习任务</router-link><router-link to="/notes">笔记空间</router-link><router-link to="/reviews">今日复习</router-link><router-link to="/interaction">课堂互动</router-link></nav>
        <el-dropdown>
          <span class="user-menu">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
          <template #dropdown><el-dropdown-menu><el-dropdown-item @click="logout">退出登录</el-dropdown-item></el-dropdown-menu></template>
        </el-dropdown>
      </el-header>
      <el-main class="page"><router-view /></el-main>
      <FloatingAiAssistant />
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Reading, Notebook, Trophy } from '@element-plus/icons-vue'
import { learningApi } from '@/api/learning'
import { useAuthStore } from '@/stores/auth'
import type { DashboardData } from '@/types'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(true)
const dashboard = ref<DashboardData | null>(null)
const stages = [
  { title: '预习空间', description: '了解章节结构，提前定位重点问题。', icon: Reading, color: '#246bfd' },
  { title: '课后巩固', description: '回顾课堂内容，形成结构化复习提纲。', icon: Notebook, color: '#18a874' },
  { title: '考前冲刺', description: '梳理重点考点，开展模拟练习。', icon: Trophy, color: '#e39021' },
]

onMounted(async () => {
  try {
    const { data } = await learningApi.dashboard()
    dashboard.value = data.data
  } finally { loading.value = false }
})
</script>

<template>
  <div v-loading="loading">
    <header class="page-header"><div><p class="eyebrow">学习工作台</p><h1>你好，{{ auth.user?.username }}</h1><p>今天也从一节课程、一个知识点开始。</p></div><el-button type="primary" @click="router.push('/courses')">浏览课程</el-button></header>
    <section class="dashboard-grid">
      <el-card shadow="never" class="progress-card">
        <div><span class="muted">综合学习进度</span><strong>{{ dashboard?.overall_progress || 0 }}%</strong></div>
        <el-progress :percentage="dashboard?.overall_progress || 0" :stroke-width="10" :show-text="false" />
      </el-card>
      <el-card shadow="never" class="current-card">
        <span class="muted">当前课程</span><h2>{{ dashboard?.current_course?.name || '尚未开始课程' }}</h2><p>{{ dashboard?.current_chapter?.title || '选择一门课程开启学习' }}</p>
      </el-card>
    </section>
    <div class="section-heading"><div><p class="eyebrow">学习阶段</p><h2>选择你的学习任务</h2></div></div>
    <section class="stage-grid">
      <el-card v-for="stage in stages" :key="stage.title" shadow="hover" class="stage-card" @click="router.push('/courses')">
        <el-icon :size="28" :color="stage.color"><component :is="stage.icon" /></el-icon><h3>{{ stage.title }}</h3><p>{{ stage.description }}</p><el-link type="primary" underline="never">选择课程 →</el-link>
      </el-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
</script>

<template>
  <main class="pending-review-page">
    <section class="pending-review-card">
      <div class="pending-review-icon">AI</div>
      <p class="eyebrow">Teacher verification</p>
      <h1>教师身份审核中</h1>
      <p>工号 {{ auth.user?.identity_no }} 已提交。管理员审核通过后，你将可以创建教学班、上传教材并发布教学任务。</p>
      <el-alert v-if="auth.user?.approval_note" :title="auth.user.approval_note" type="warning" :closable="false" />
      <el-button type="primary" @click="auth.loadCurrentUser()">刷新审核状态</el-button>
      <el-button @click="auth.logout(); location.href='/login'">退出登录</el-button>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    await router.push(typeof route.query.redirect === 'string' ? route.query.redirect : '/')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '登录失败，请稍后重试'))
  } finally { loading.value = false }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-intro"><el-tag effect="dark" round>AI + RAG</el-tag><h1>让思政课程学习<br />更聚焦、更可信</h1><p>围绕课程、教材、知识点和学习阶段提供智能辅助。</p></section>
    <el-card class="auth-card" shadow="never">
      <h2>欢迎回来</h2><p class="muted">登录后继续你的课程学习</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" size="large" placeholder="请输入用户名" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" placeholder="请输入密码" /></el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="full-button" @click="submit">登录</el-button>
      </el-form>
      <p class="auth-switch">还没有账号？<router-link to="/register">立即注册</router-link></p>
    </el-card>
  </main>
</template>

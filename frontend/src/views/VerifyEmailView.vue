<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const success = ref(false)
const form = reactive({ email: typeof route.query.email === 'string' ? route.query.email : '', code: '' })
const rules: FormRules = {
  email: [{ required: true, type: 'email', message: '请输入有效邮箱', trigger: 'blur' }],
  code: [{ required: true, len: 6, pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }],
}

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await authApi.confirmEmailVerification(form.email, form.code)
    if (auth.isAuthenticated) await auth.loadCurrentUser()
    success.value = true
    ElMessage.success('邮箱验证成功')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '验证码无效或已过期'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="simple-auth-page">
    <el-card class="simple-auth-card" shadow="never">
      <template v-if="!success">
        <p class="eyebrow">邮箱验证</p>
        <h1>输入验证码</h1>
        <p class="muted">验证码已发送到你的邮箱，请输入邮件中的 6 位数字验证码。</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
          <el-form-item label="邮箱" prop="email"><el-input v-model="form.email" type="email" autocomplete="email" size="large" /></el-form-item>
          <el-form-item label="验证码" prop="code"><el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位数字" size="large" /></el-form-item>
          <el-button type="primary" size="large" class="full-button" :loading="loading" @click="submit">确认验证</el-button>
        </el-form>
      </template>
      <template v-else>
        <p class="eyebrow">验证成功</p>
        <h1>邮箱已验证</h1>
        <p class="muted">现在可以使用该邮箱找回密码。</p>
        <el-button type="primary" size="large" class="full-button" @click="router.push('/login')">返回登录</el-button>
      </template>
      <p v-if="!success" class="auth-switch"><router-link to="/login">返回登录</router-link><span> · </span><router-link to="/register">注册账号</router-link></p>
    </el-card>
  </main>
</template>

<style scoped>
.simple-auth-page { display: grid; min-height: 100vh; place-items: center; padding: clamp(24px, 6vw, 64px) var(--space-4); background: var(--bg-page); }
.simple-auth-card { width: min(100%, 440px); padding: 28px; border: 1px solid var(--line); border-radius: var(--radius-card); box-shadow: var(--shadow-1); }
h1 { margin: var(--space-1) 0 var(--space-2); color: var(--ink-900); font-size: var(--fs-section); }
.muted { color: var(--ink-600); line-height: 1.6; }
.full-button { width: 100%; }
.auth-switch { margin: var(--space-6) 0 0; color: var(--ink-600); text-align: center; }
</style>

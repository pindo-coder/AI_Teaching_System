<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const requestRef = ref<FormInstance>()
const resetRef = ref<FormInstance>()
const loading = ref(false)
const resetLoading = ref(false)
const sent = ref(false)
const completed = ref(false)
const nextStep = ref<'email' | 'verify_email' | 'admin'>('email')
const form = reactive({ identifier: '', code: '', password: '', confirmPassword: '' })
const requestRules: FormRules = { identifier: [{ required: true, message: '请输入用户名或邮箱', trigger: 'blur' }] }
const validateConfirm = (_rule: unknown, value: string, callback: (error?: Error) => void) => callback(value === form.password ? undefined : new Error('两次输入的密码不一致'))
const resetRules: FormRules = {
  code: [{ required: true, len: 6, pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }],
  password: [{ required: true, min: 8, max: 128, message: '密码长度为 8～128 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

async function requestReset() {
  if (!(await requestRef.value?.validate())) return
  loading.value = true
  try {
    const { data } = await authApi.requestPasswordReset(form.identifier)
    nextStep.value = data.data.next_step
    sent.value = true
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '操作失败，请稍后重试'))
  } finally { loading.value = false }
}

async function confirmReset() {
  if (!(await resetRef.value?.validate())) return
  resetLoading.value = true
  try {
    await authApi.confirmPasswordReset({ identifier: form.identifier, code: form.code, new_password: form.password })
    completed.value = true
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '验证码无效或已过期'))
  } finally { resetLoading.value = false }
}
</script>

<template>
  <main class="simple-auth-page">
    <el-card class="simple-auth-card" shadow="never">
      <template v-if="!sent">
        <p class="eyebrow">账户恢复</p>
        <h1>找回密码</h1>
        <p class="muted">输入用户名或已验证邮箱，我们会发送 6 位密码重置验证码。</p>
        <el-form ref="requestRef" :model="form" :rules="requestRules" label-position="top" @keyup.enter="requestReset">
          <el-form-item label="用户名或邮箱" prop="identifier"><el-input v-model="form.identifier" size="large" autocomplete="username" /></el-form-item>
          <el-button type="primary" size="large" class="full-button" :loading="loading" @click="requestReset">发送验证码</el-button>
        </el-form>
      </template>
      <template v-else-if="completed">
        <p class="eyebrow">操作完成</p>
        <h1>密码已重置</h1>
        <p class="muted">请使用新密码登录，旧登录状态已失效。</p>
        <el-button type="primary" size="large" class="full-button" @click="router.push('/login')">返回登录</el-button>
      </template>
      <template v-else-if="nextStep === 'email'">
        <p class="eyebrow">邮箱验证</p>
        <h1>输入重置验证码</h1>
        <p class="muted">验证码已发送到账号绑定的邮箱，请输入邮件中的 6 位数字并设置新密码。</p>
        <el-form ref="resetRef" :model="form" :rules="resetRules" label-position="top" @keyup.enter="confirmReset">
          <el-form-item label="验证码" prop="code"><el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位数字" size="large" /></el-form-item>
          <el-form-item label="新密码" prop="password"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" size="large" /></el-form-item>
          <el-form-item label="确认新密码" prop="confirmPassword"><el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" size="large" /></el-form-item>
          <el-button type="primary" size="large" class="full-button" :loading="resetLoading" @click="confirmReset">确认重置</el-button>
        </el-form>
      </template>
      <template v-else-if="nextStep === 'verify_email'">
        <p class="eyebrow">邮箱验证</p>
        <h1>请先验证邮箱</h1>
        <p class="muted">验证码已发送到该邮箱。完成邮箱验证后，请返回本页再次申请密码重置。</p>
        <el-button type="primary" size="large" class="full-button" @click="router.push({ path: '/verify-email', query: { email: form.identifier } })">填写邮箱验证码</el-button>
      </template>
      <template v-else>
        <p class="eyebrow">管理员重置</p>
        <h1>请联系管理员</h1>
        <p class="muted">该账号属于未绑定或未验证邮箱的历史账号，请联系管理员生成临时密码。临时密码登录后会强制修改。</p>
      </template>
      <p class="auth-switch"><router-link to="/login">返回登录</router-link><span> · </span><router-link to="/register">注册账号</router-link></p>
    </el-card>
  </main>
</template>

<style scoped>
.simple-auth-page { display: grid; min-height: 100vh; place-items: center; padding: var(--space-4); background: var(--bg-page); }
.simple-auth-card { width: min(100%, 440px); padding: 32px; box-shadow: var(--shadow-2); }
h1 { margin: var(--space-1) 0 var(--space-2); font-size: var(--fs-section); }
.muted { color: var(--ink-600); line-height: 1.6; }
.full-button { width: 100%; }
.auth-switch { margin: var(--space-6) 0 0; color: var(--ink-600); text-align: center; }
</style>

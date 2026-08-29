<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'

const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)
const completed = ref(false)
const form = reactive({ password: '', confirmPassword: '' })
const validateConfirm = (_rule: unknown, value: string, callback: (error?: Error) => void) => callback(value === form.password ? undefined : new Error('两次输入的密码不一致'))
const rules: FormRules = {
  password: [{ required: true, min: 8, max: 128, message: '密码长度为 8～128 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

async function submit() {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) { ElMessage.error('重置链接无效'); return }
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await authApi.confirmPasswordReset({ token, new_password: form.password })
    completed.value = true
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '重置失败，请重新申请链接'))
  } finally { loading.value = false }
}
</script>

<template>
  <main class="simple-auth-page">
    <el-card class="simple-auth-card" shadow="never">
      <template v-if="!completed">
        <p class="eyebrow">账户恢复</p>
        <h1>设置新密码</h1>
        <p class="muted">新密码至少 8 个字符。完成后需要重新登录。</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
          <el-form-item label="新密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" autocomplete="new-password" /></el-form-item>
          <el-form-item label="确认新密码" prop="confirmPassword"><el-input v-model="form.confirmPassword" type="password" show-password size="large" autocomplete="new-password" /></el-form-item>
          <el-button type="primary" size="large" class="full-button" :loading="loading" @click="submit">确认重置</el-button>
        </el-form>
      </template>
      <template v-else>
        <p class="eyebrow">操作完成</p>
        <h1>密码已重置</h1>
        <p class="muted">旧登录状态已失效，请使用新密码登录。</p>
        <el-button type="primary" size="large" class="full-button" @click="router.push('/login')">返回登录</el-button>
      </template>
    </el-card>
  </main>
</template>

<style scoped>
.simple-auth-page { display: grid; min-height: 100vh; place-items: center; padding: var(--space-4); background: var(--bg-page); }
.simple-auth-card { width: min(100%, 440px); padding: 32px; box-shadow: var(--shadow-2); }
h1 { margin: var(--space-1) 0 var(--space-2); font-size: var(--fs-section); }
.muted { color: var(--ink-600); line-height: 1.6; }
.full-button { width: 100%; }
</style>

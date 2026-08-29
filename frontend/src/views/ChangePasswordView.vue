<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ password: '', confirmPassword: '' })
const validateConfirm = (_rule: unknown, value: string, callback: (error?: Error) => void) => callback(value === form.password ? undefined : new Error('两次输入的密码不一致'))
const rules: FormRules = {
  password: [{ required: true, min: 8, max: 128, message: '密码长度为 8～128 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await authApi.changePassword(form.password)
    auth.logout()
    ElMessage.success('密码修改成功，请重新登录')
    await router.push('/login')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '修改失败，请稍后重试'))
  } finally { loading.value = false }
}
</script>

<template>
  <main class="simple-auth-page">
    <el-card class="simple-auth-card" shadow="never">
      <p class="eyebrow">安全设置</p>
      <h1>请修改临时密码</h1>
      <p class="muted">管理员为你生成了临时密码，修改后才能继续使用平台。</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="新密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" autocomplete="new-password" /></el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword"><el-input v-model="form.confirmPassword" type="password" show-password size="large" autocomplete="new-password" /></el-form-item>
        <el-button type="primary" size="large" class="full-button" :loading="loading" @click="submit">保存新密码</el-button>
      </el-form>
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

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import UiCard from '@/components/ui/UiCard.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { getErrorMessage } from '@/utils/error'

const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const verifying = ref(false)
const sent = ref(false)
const form = reactive({ email: auth.user?.email || '', code: '' })
const rules: FormRules = {
  email: [{ required: true, type: 'email', message: '请输入有效邮箱', trigger: 'blur' }],
  code: [{ required: true, len: 6, pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }],
}
const verified = computed(() => Boolean(auth.user?.email_verified_at))

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await authApi.requestEmailVerification(form.email)
    sent.value = true
    await auth.loadCurrentUser()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '发送失败，请稍后重试'))
  } finally { loading.value = false }
}

async function confirmEmail() {
  if (!(await formRef.value?.validateField('code'))) return
  verifying.value = true
  try {
    await authApi.confirmEmailVerification(form.email, form.code)
    sent.value = false
    form.code = ''
    await auth.loadCurrentUser()
    ElMessage.success('邮箱验证成功')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '验证码无效或已过期'))
  } finally { verifying.value = false }
}
</script>

<template>
  <div class="account-page">
    <UiPageHeader eyebrow="ACCOUNT SETTINGS" title="账号设置" description="绑定并验证邮箱后，可以在忘记密码时自助找回账号。" />
    <UiCard class="account-card">
      <template #title><div><p class="eyebrow">RECOVERY EMAIL</p><h2>找回邮箱</h2></div></template>
      <el-alert v-if="verified" type="success" :closable="false" title="邮箱已验证，可用于找回密码" />
      <el-alert v-else-if="sent" type="info" :closable="false" title="验证码邮件已发送，请查收邮箱" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="sent ? confirmEmail() : submit()">
        <el-form-item label="邮箱" prop="email"><el-input v-model="form.email" type="email" autocomplete="email" placeholder="请输入常用邮箱" size="large" :disabled="loading" /></el-form-item>
        <el-form-item v-if="sent" label="验证码" prop="code"><el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位数字" size="large" :disabled="verifying" /></el-form-item>
        <el-button v-if="!sent || verified" type="primary" :loading="loading" @click="submit">{{ verified ? '更换并重新验证' : '发送验证码' }}</el-button>
        <el-button v-if="sent" type="primary" :loading="verifying" @click="confirmEmail">确认验证</el-button>
      </el-form>
      <p class="muted">邮箱地址不会用于登录，只用于安全验证和密码找回。</p>
    </UiCard>
  </div>
</template>

<style scoped>
.account-page { display: grid; gap: var(--space-6); max-width: 760px; }
.account-card { max-width: 520px; }
.account-card h2 { margin: var(--space-1) 0 var(--space-4); font-size: var(--fs-section); }
.account-card .el-form { margin-top: var(--space-5); }
.muted { color: var(--ink-600); line-height: 1.6; }
</style>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, Message } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'
import RecoveryAuthLayout from '@/components/ui/RecoveryAuthLayout.vue'

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

const activeStep = computed<1 | 2 | 3>(() => {
  if (completed.value) return 3
  if (sent.value && nextStep.value === 'email') return 2
  return 1
})
const panelTitle = computed(() => {
  if (!sent.value) return '找回密码'
  if (completed.value) return '密码已重置'
  if (nextStep.value === 'email') return '输入重置验证码'
  if (nextStep.value === 'verify_email') return '请先验证邮箱'
  return '请联系管理员'
})
const panelDescription = computed(() => {
  if (!sent.value) return '输入用户名或邮箱，我们会发送 6 位验证码，帮助你安全恢复账号。'
  if (completed.value) return '新的密码已经生效，旧登录状态已失效。'
  if (nextStep.value === 'email') return '验证码已发送到账号绑定邮箱，请在有效期内完成验证并设置新密码。'
  if (nextStep.value === 'verify_email') return '该账号的邮箱尚未验证，完成邮箱验证后即可再次申请密码重置。'
  return '该账号未绑定或未验证邮箱，请联系管理员生成临时密码。'
})

async function requestReset() {
  let valid = false
  try { valid = await requestRef.value?.validate() ?? false } catch { return }
  if (!valid) return
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
  let valid = false
  try { valid = await resetRef.value?.validate() ?? false } catch { return }
  if (!valid) return
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
  <RecoveryAuthLayout
    :active-step="activeStep"
    :title="panelTitle"
    :description="panelDescription"
    :visual="completed ? 'success' : 'message'"
    :eyebrow="completed ? '操作完成' : nextStep === 'verify_email' ? '邮箱验证' : nextStep === 'admin' ? '管理员重置' : '账户恢复'"
  >
    <template v-if="!sent">
      <el-form ref="requestRef" class="recovery-form" :model="form" :rules="requestRules" label-position="top" @keyup.enter="requestReset">
        <el-form-item label="用户名或邮箱" prop="identifier">
          <el-input v-model="form.identifier" autocomplete="username" placeholder="请输入用户名或已验证邮箱" :prefix-icon="Message" />
        </el-form-item>
        <el-button type="primary" class="recovery-submit" :loading="loading" @click="requestReset">发送验证码</el-button>
      </el-form>
    </template>

    <template v-else-if="completed">
      <div class="recovery-success">
        <span class="recovery-success-mark" aria-hidden="true">✓</span>
        <p>请使用新密码登录，旧登录状态已失效。</p>
        <el-button type="primary" class="recovery-submit" @click="router.push('/login')">返回登录</el-button>
      </div>
    </template>

    <template v-else-if="nextStep === 'email'">
      <p class="recovery-notice">验证码已发送到账号绑定邮箱，请输入邮件中的 6 位数字。</p>
      <el-form ref="resetRef" class="recovery-form" :model="form" :rules="resetRules" label-position="top" @keyup.enter="confirmReset">
        <el-form-item label="邮箱验证码" prop="code">
          <el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位数字" :prefix-icon="Message" />
        </el-form-item>
        <el-form-item label="新密码" prop="password">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="至少 8 个字符" :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" placeholder="再次输入新密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-button type="primary" class="recovery-submit" :loading="resetLoading" @click="confirmReset">确认重置</el-button>
      </el-form>
    </template>

    <template v-else-if="nextStep === 'verify_email'">
      <p class="recovery-notice">验证码已发送到该邮箱。完成邮箱验证后，请返回本页再次申请密码重置。</p>
      <el-button type="primary" class="recovery-submit" @click="router.push({ path: '/verify-email', query: { email: form.identifier } })">填写邮箱验证码</el-button>
    </template>

    <template v-else>
      <p class="recovery-notice"><strong>该账号属于未绑定或未验证邮箱的历史账号。</strong><br />请联系管理员生成临时密码，登录后系统会要求你立即修改。</p>
    </template>
  </RecoveryAuthLayout>
</template>

<style scoped>
.recovery-success :deep(.recovery-submit) { margin-top: 5px; }
</style>

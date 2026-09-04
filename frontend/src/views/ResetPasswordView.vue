<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'
import RecoveryAuthLayout from '@/components/ui/RecoveryAuthLayout.vue'

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
  let valid = false
  try { valid = await formRef.value?.validate() ?? false } catch { return }
  if (!valid) return
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
  <RecoveryAuthLayout
    :active-step="completed ? 3 : 2"
    :eyebrow="completed ? '操作完成' : '安全链接'"
    :title="completed ? '密码已重置' : '创建新密码'"
    :description="completed ? '新的密码已经生效，旧登录状态已失效。' : '请设置至少包含 8 个字符的新密码，建议同时包含字母和数字。'"
    :visual="completed ? 'success' : 'message'"
    rail-title="安全更新密码"
    rail-description="使用一次性安全链接更新密码，保护你的学习资料和账号信息。"
  >
    <template v-if="!completed">
      <el-form ref="formRef" class="recovery-form" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="请输入新密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" placeholder="再次输入新密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-button type="primary" class="recovery-submit" :loading="loading" @click="submit">重置密码</el-button>
      </el-form>
    </template>
    <template v-else>
      <div class="recovery-success">
        <span class="recovery-success-mark" aria-hidden="true">✓</span>
        <p>旧登录状态已失效，请使用新密码登录。</p>
        <el-button type="primary" class="recovery-submit" @click="router.push('/login')">返回登录</el-button>
      </div>
    </template>
  </RecoveryAuthLayout>
</template>

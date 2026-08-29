<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/auth'
import type { User } from '@/types'
import UiCard from '@/components/ui/UiCard.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'

type PendingRequest = { id: number; user_id: number; username: string; email: string | null; requested_at: string; request_ip: string | null }
const loading = ref(true)
const users = ref<User[]>([])
const requests = ref<PendingRequest[]>([])
const selectedUserId = ref<number>()
const temporaryPassword = ref('')

async function load() {
  loading.value = true
  try {
    const [usersResponse, requestsResponse] = await Promise.all([authApi.users(), authApi.pendingPasswordResets()])
    users.value = usersResponse.data.data
    requests.value = requestsResponse.data.data
  } finally { loading.value = false }
}

async function generate(userId: number) {
  selectedUserId.value = userId
  try {
    const { data } = await authApi.temporaryPassword(userId)
    temporaryPassword.value = data.data.temporary_password
    requests.value = requests.value.filter((item) => item.user_id !== userId)
    window.dispatchEvent(new Event('notifications-changed'))
    ElMessage.success('临时密码已生成，请通过安全渠道交给用户')
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '生成临时密码失败')
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="reset-page">
    <UiPageHeader eyebrow="ACCOUNT RECOVERY" title="账号找回" description="处理未绑定或未验证邮箱的历史账号。生成的临时密码只展示一次，用户登录后必须修改。">
      <template #actions><el-button @click="load">刷新列表</el-button></template>
    </UiPageHeader>

    <UiCard>
      <template #title><div><p class="eyebrow">PENDING REQUESTS</p><h2>待人工重置</h2></div></template>
      <el-alert v-if="!requests.length" type="success" :closable="false" title="当前没有待处理请求">
        <template #default>老账号在忘记密码页面输入用户名后，会自动出现在这里。</template>
      </el-alert>
      <div v-else class="request-list">
        <div v-for="item in requests" :key="item.id" class="request-item">
          <div><strong>{{ item.username }}</strong><span>{{ item.email || '未绑定邮箱' }} · 申请于 {{ item.requested_at }}</span></div>
          <el-button type="primary" @click="generate(item.user_id)">生成临时密码</el-button>
        </div>
      </div>
    </UiCard>

    <UiCard>
      <template #title><div><p class="eyebrow">ALL USERS</p><h2>按用户人工重置</h2></div></template>
      <p class="muted">用于用户无法收取验证码邮件等特殊情况。邮箱已验证的用户优先使用自助找回。</p>
      <div class="manual-tools">
        <el-select v-model="selectedUserId" placeholder="选择用户" filterable clearable>
          <el-option v-for="user in users" :key="user.id" :label="`${user.username}（${user.email_verified_at ? '邮箱已验证' : '未验证邮箱'}）`" :value="user.id" />
        </el-select>
        <el-button type="primary" :disabled="!selectedUserId" @click="generate(selectedUserId!)">生成临时密码</el-button>
      </div>
      <el-alert v-if="temporaryPassword" type="warning" :closable="false" title="请立即通过安全渠道交给用户">
        <template #default><code>{{ temporaryPassword }}</code></template>
      </el-alert>
    </UiCard>
  </div>
</template>

<style scoped>
.reset-page { display: grid; gap: var(--space-6); }
h2 { margin: var(--space-1) 0 0; font-size: var(--fs-section); }
.muted { color: var(--ink-600); line-height: 1.6; }
.request-list { display: grid; gap: var(--space-3); }
.request-item { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3); background: var(--surface-muted); border: 1px solid var(--line); border-radius: var(--radius-input); }
.request-item div { display: grid; gap: 4px; }
.request-item span { color: var(--ink-500); font-size: var(--fs-meta); }
.manual-tools { display: flex; flex-wrap: wrap; gap: var(--space-3); margin: var(--space-4) 0; }
.manual-tools .el-select { width: min(100%, 360px); }
</style>

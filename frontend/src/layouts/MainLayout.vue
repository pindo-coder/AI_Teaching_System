<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, Clock, Menu, Search } from '@element-plus/icons-vue'
import AgentDock from '@/components/AgentDock.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import { navigationForRole, type NavigationItem } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { agentApi, type AgentRun } from '@/api/agents'
import { notificationApi, type TeachingNotification } from '@/api/notifications'

const auth = useAuthStore()
const workspace = useWorkspaceStore()
const route = useRoute()
const router = useRouter()
const mobileNavVisible = ref(false)
const messageVisible = ref(false)
const taskVisible = ref(false)
const taskLoading = ref(false)
const agentRuns = ref<AgentRun[]>([])
const notifications = ref<TeachingNotification[]>([])
const notificationLoading = ref(false)
let notificationTimer: number | undefined

const navigationItems = computed(() => navigationForRole(auth.user?.role))
const roleLabel = computed(() => ({ student: '学生', teacher: '教师', admin: '管理员' }[auth.user?.role || 'student']))
const contextTitle = computed(() => workspace.currentCourse?.name || workspace.currentClass?.name || '高校思政课')
const contextDetail = computed(() => {
  if (auth.user?.role === 'student') return workspace.currentChapter?.title || '今日学习'
  return workspace.currentClass?.name || '当前教学空间'
})

function isActive(item: NavigationItem) {
  if (item.path === '/') return route.path === '/'
  return (item.match || [item.path]).some((path) => route.path === path || route.path.startsWith(`${path}/`))
}

function logout() {
  workspace.clear()
  auth.logout()
  router.push('/login')
}

function navigate(path: string) {
  mobileNavVisible.value = false
  router.push(path)
}

onMounted(() => {
  workspace.initialize()
  void loadNotifications()
  notificationTimer = window.setInterval(() => void loadNotifications(), 60_000)
})

onUnmounted(() => {
  if (notificationTimer) window.clearInterval(notificationTimer)
})

const unreadNotificationCount = computed(() => notifications.value.filter((item) => !item.is_read).length)

async function loadNotifications() {
  if (!auth.user) return
  notificationLoading.value = true
  try {
    const response = await notificationApi.list(false, 80)
    notifications.value = response.data.data
  } finally {
    notificationLoading.value = false
  }
}

async function markNotificationRead(item: TeachingNotification) {
  if (item.is_read) return
  try {
    const response = await notificationApi.markRead(item.id)
    const index = notifications.value.findIndex((notification) => notification.id === item.id)
    if (index >= 0) notifications.value[index] = response.data.data
  } catch { /* 消息入口不应阻断主页面操作 */ }
}

async function markAllNotificationsRead() {
  try {
    await notificationApi.markAllRead()
    notifications.value = notifications.value.map((item) => ({ ...item, is_read: true, read_time: new Date().toISOString() }))
  } catch { /* 消息入口不应阻断主页面操作 */ }
}

async function loadAgentRuns() {
  if (auth.user?.role === 'student') return
  taskLoading.value = true
  try {
    const response = await agentApi.list(20)
    agentRuns.value = response.data.data
  } finally {
    taskLoading.value = false
  }
}

function agentStatus(run: AgentRun) {
  const labels: Record<string, string> = {
    queued: '等待执行',
    running: '运行中',
    waiting_confirmation: '等待确认',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[run.status] || run.status
}

function openAgentRun() {
  taskVisible.value = false
  router.push('/lesson-prep')
}

watch(taskVisible, (visible) => {
  if (visible) void loadAgentRuns()
})

watch(() => auth.user?.id, () => {
  void loadNotifications()
})
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar desktop-shell-nav" aria-label="角色主导航">
      <router-link to="/" class="brand" aria-label="返回工作台">
        <span class="brand-mark" aria-hidden="true">思</span>
        <span><strong>思政智教</strong><small>AI TEACHING</small></span>
      </router-link>
      <div class="role-identity">
        <span>{{ roleLabel }}空间</span>
        <strong>{{ auth.user?.username }}</strong>
      </div>
      <nav class="sidebar-navigation">
        <button
          v-for="item in navigationItems"
          :key="item.path"
          type="button"
          :class="{ active: isActive(item) }"
          @click="navigate(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <span>当前角色</span>
        <strong>{{ roleLabel }}</strong>
      </div>
    </aside>

    <div class="app-content">
      <header class="context-topbar">
        <el-button class="mobile-menu-trigger mobile-shell-nav" :icon="Menu" text aria-label="打开主菜单" @click="mobileNavVisible = true" />
        <div class="context-copy">
          <strong>{{ contextTitle }}</strong>
          <span>{{ contextDetail }}</span>
        </div>
        <div class="global-actions" aria-label="全局工具">
          <el-tooltip content="搜索课程与资料">
            <el-button circle text :icon="Search" aria-label="搜索课程与资料" @click="router.push('/courses')" />
          </el-tooltip>
          <el-tooltip content="后台任务">
            <el-button circle text :icon="Clock" aria-label="查看后台任务" @click="taskVisible = true" />
          </el-tooltip>
          <el-tooltip content="消息提醒">
            <el-badge :value="unreadNotificationCount" :hidden="unreadNotificationCount === 0" :max="99" class="notification-badge">
              <el-button circle text :icon="Bell" aria-label="查看消息提醒" @click="messageVisible = true; void loadNotifications()" />
            </el-badge>
          </el-tooltip>
          <el-dropdown>
            <button type="button" class="user-avatar" aria-label="打开用户菜单">{{ auth.user?.username?.slice(0, 1).toUpperCase() }}</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ auth.user?.username }} · {{ roleLabel }}</el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <AgentDock />
      <main class="page"><router-view /></main>
    </div>

    <el-drawer v-model="mobileNavVisible" title="功能导航" direction="ltr" size="min(88vw, 340px)">
      <div class="mobile-brand"><strong>思政智教</strong><span>{{ roleLabel }}空间</span></div>
      <nav class="mobile-navigation" aria-label="移动端主导航">
        <button
          v-for="item in navigationItems"
          :key="item.path"
          type="button"
          :class="{ active: isActive(item) }"
          @click="navigate(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
        </button>
      </nav>
      <el-button class="mobile-logout" plain type="danger" @click="logout">退出登录</el-button>
    </el-drawer>

    <el-drawer v-model="messageVisible" title="消息提醒" size="min(92vw, 420px)">
      <div v-loading="notificationLoading" class="notification-center">
        <div class="notification-toolbar">
          <span>显示最近的教学与权威资料提醒</span>
          <el-button text type="primary" :disabled="unreadNotificationCount === 0" @click="markAllNotificationsRead">全部已读</el-button>
        </div>
        <button
          v-for="item in notifications"
          :key="item.id"
          type="button"
          class="notification-item"
          :class="{ unread: !item.is_read }"
          @click="markNotificationRead(item)"
        >
          <span class="notification-item-head">
            <strong>{{ item.title }}</strong>
            <el-tag size="small" :type="item.level === 'urgent' ? 'danger' : item.level === 'important' ? 'warning' : 'info'">{{ item.level === 'urgent' ? '紧急' : item.level === 'important' ? '重要' : '提醒' }}</el-tag>
          </span>
          <span class="notification-item-content">{{ item.content }}</span>
          <a v-if="item.source_url" class="notification-source" :href="item.source_url" target="_blank" rel="noreferrer" @click.stop="markNotificationRead(item)">查看权威原文 ↗</a>
          <small>{{ new Date(item.created_time).toLocaleString() }}</small>
        </button>
        <div v-if="!notifications.length && !notificationLoading" class="utility-drawer-content">
          <span class="utility-mark"><el-icon><Bell /></el-icon></span>
          <h3>暂无教学提醒</h3>
          <p>已确认的权威资料更新、任务截止和审核结果会集中显示在这里。</p>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="taskVisible" title="后台任务" size="min(92vw, 420px)">
      <div v-loading="taskLoading" class="agent-task-center">
        <template v-if="agentRuns.length">
          <button v-for="run in agentRuns" :key="run.id" type="button" class="agent-task-item" @click="openAgentRun">
            <span>
              <strong>课程备课 #{{ run.id }}</strong>
              <small>{{ new Date(run.updated_time).toLocaleString() }}</small>
            </span>
            <StatusChip
              :label="agentStatus(run)"
              :status="run.status === 'failed' ? 'danger' : run.status === 'completed' ? 'success' : run.status === 'waiting_confirmation' ? 'warning' : 'info'"
            />
          </button>
          <el-button plain type="primary" @click="loadAgentRuns">刷新任务状态</el-button>
        </template>
        <div v-else class="utility-drawer-content">
          <span class="utility-mark"><el-icon><Clock /></el-icon></span>
          <h3>当前没有智能任务记录</h3>
          <p v-if="auth.user?.role === 'student'">学生的学习向导将在后续阶段接入，这里将统一显示需要较长时间完成的任务。</p>
          <p v-else>从课程备课创建任务后，可以离开页面并在这里查看进度。</p>
          <el-button v-if="auth.user?.role !== 'student'" type="primary" @click="openAgentRun">开始课程备课</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  min-width: 0;
  min-height: 100vh;
  background: var(--surface-page);
}

.app-sidebar {
  position: sticky;
  z-index: 120;
  top: 0;
  display: grid;
  height: 100vh;
  grid-template-rows: auto auto 1fr auto;
  gap: var(--space-6);
  padding: var(--space-6) var(--space-3);
  color: #fff;
  background: var(--blue-900);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-2);
  color: #fff;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: var(--authority-red);
  background: #fff;
  border-radius: var(--radius-input);
  font-size: 18px;
  font-weight: var(--fw-bold);
}

.brand > span:last-child,
.context-copy,
.sidebar-navigation button span,
.mobile-navigation button span {
  display: grid;
  min-width: 0;
}

.brand strong { font-size: 18px; }
.brand small { margin-top: 3px; color: rgb(255 255 255 / 62%); font-size: 10px; letter-spacing: .16em; }
.role-identity { display: grid; gap: 3px; margin: 0 var(--space-2); padding: var(--space-3); background: rgb(255 255 255 / 7%); border: 1px solid rgb(255 255 255 / 10%); border-radius: var(--radius-card); }
.role-identity span, .sidebar-footer span { color: rgb(255 255 255 / 60%); font-size: var(--fs-meta); }
.role-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-navigation { display: grid; align-content: start; gap: var(--space-2); }
.sidebar-navigation button, .mobile-navigation button { display: grid; grid-template-columns: 34px minmax(0, 1fr); align-items: center; gap: var(--space-2); width: 100%; padding: 11px 10px; color: rgb(255 255 255 / 72%); background: transparent; border: 0; border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.sidebar-navigation button:hover, .sidebar-navigation button.active { color: #fff; background: rgb(255 255 255 / 12%); }
.sidebar-navigation button.active { box-shadow: inset 3px 0 0 var(--authority-red); }
.sidebar-navigation .el-icon { width: 34px; height: 34px; font-size: 18px; }
.sidebar-navigation small, .mobile-navigation small { margin-top: 2px; color: inherit; font-size: 10px; opacity: .68; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-footer { display: flex; justify-content: space-between; padding: var(--space-3) var(--space-2) 0; border-top: 1px solid rgb(255 255 255 / 12%); font-size: var(--fs-meta); }
.app-content { min-width: 0; }
.context-topbar { position: sticky; z-index: 110; top: 0; display: flex; height: 64px; align-items: center; gap: var(--space-3); padding: 0 var(--page-padding); background: rgb(255 255 255 / 96%); border-bottom: 1px solid var(--line); backdrop-filter: blur(10px); }
.context-copy { gap: 2px; }
.context-copy strong { max-width: min(54vw, 560px); color: var(--ink-900); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.context-copy span { color: var(--ink-400); font-size: var(--fs-meta); }
.global-actions { display: flex; align-items: center; gap: var(--space-1); margin-left: auto; }
.user-avatar { display: grid; width: 34px; height: 34px; margin-left: var(--space-1); place-items: center; color: #fff; background: var(--action-blue); border: 0; border-radius: 50%; cursor: pointer; font-weight: var(--fw-bold); }
.page { width: min(100%, calc(var(--page-max-width) + var(--page-padding) * 2)); min-width: 0; margin: 0 auto; padding: var(--space-8) var(--page-padding) 48px; overflow: visible; }
.mobile-shell-nav { display: none; }
.mobile-brand { display: grid; gap: var(--space-1); margin-bottom: var(--space-6); }
.mobile-brand strong { color: var(--blue-800); font-size: 20px; }
.mobile-brand span { color: var(--ink-400); }
.mobile-navigation { display: grid; gap: var(--space-2); }
.mobile-navigation button { color: var(--ink-600); }
.mobile-navigation button:hover, .mobile-navigation button.active { color: var(--action-blue); background: var(--action-soft); }
.mobile-navigation .el-icon { width: 34px; height: 34px; }
.mobile-logout { margin-top: var(--space-8); }
.utility-drawer-content { display: grid; min-height: 320px; place-items: center; align-content: center; gap: var(--space-3); text-align: center; }
.utility-drawer-content h3, .utility-drawer-content p { max-width: 320px; margin: 0; }
.utility-drawer-content p { color: var(--ink-600); line-height: 1.7; }
.notification-center { display: grid; gap: var(--space-3); }
.notification-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); color: var(--ink-500); font-size: var(--fs-meta); }
.notification-item { display: grid; gap: 8px; width: 100%; padding: 14px; color: var(--ink-800); text-align: left; background: var(--surface-card); border: 1px solid var(--line); border-radius: var(--radius-input); cursor: pointer; }
.notification-item.unread { background: #f3f7ff; border-color: var(--action-line); box-shadow: inset 3px 0 0 var(--action-blue); }
.notification-item:hover { border-color: var(--action-blue); }
.notification-item-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.notification-item-head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notification-item-content { color: var(--ink-600); line-height: 1.6; white-space: pre-line; }
.notification-source { width: fit-content; color: var(--action-blue); font-size: var(--fs-meta); text-decoration: none; }
.notification-item small { color: var(--ink-400); }
.utility-mark { display: grid; width: 48px; height: 48px; place-items: center; color: var(--action-blue); background: var(--action-soft); border-radius: var(--radius-card); font-size: 22px; }
.agent-task-center { display: grid; gap: var(--space-3); min-height: 220px; align-content: start; }
.agent-task-item { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3); color: var(--ink-900); background: var(--surface-card); border: 1px solid var(--line); border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.agent-task-item:hover { background: var(--action-soft); border-color: var(--action-line); }
.agent-task-item > span { display: grid; min-width: 0; gap: var(--space-1); }
.agent-task-item small { color: var(--ink-400); }

@media (max-width: 1023px) {
  .app-shell { display: block; }
  .desktop-shell-nav { display: none; }
  .mobile-shell-nav { display: inline-flex; }
  .context-topbar { padding: 0 var(--space-3); }
  .page { padding-top: var(--space-6); }
}

@media (max-width: 479px) {
  .context-copy strong { max-width: 42vw; }
  .global-actions > :first-child { display: none; }
}
</style>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Bell, Clock, Menu, Message, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AgentDock from '@/components/AgentDock.vue'
import BrandLockup from '@/components/ui/BrandLockup.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import { navigationForRole, type NavigationItem } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { agentApi, type AgentRun } from '@/api/agents'
import { notificationApi, type TeachingNotification } from '@/api/notifications'
import { knowledgeApi } from '@/api/knowledge'
import { authApi } from '@/api/auth'
import { courseApi } from '@/api/courses'
import { newsApi, type NewsItem } from '@/api/news'
import { studyApi, type NoteSearchItem } from '@/api/study'
import type { CourseDetail, LearningStage } from '@/types'
import { formatBeijingDateTime } from '@/utils/time'
import { requestWorkspaceAi } from '@/utils/workspaceAiEvents'
import logoUrl from '@/assets/logo1.svg'

const auth = useAuthStore()
const workspace = useWorkspaceStore()
const route = useRoute()
const router = useRouter()
const mobileNavVisible = ref(false)
const messageVisible = ref(false)
const taskVisible = ref(false)
const taskLoading = ref(false)
const headerSearch = ref('')
const agentRuns = ref<AgentRun[]>([])
const notifications = ref<TeachingNotification[]>([])
const notificationLoading = ref(false)
const actionableCandidateCount = ref(0)
const pendingPasswordResetCount = ref(0)
const headerSearchArea = ref<HTMLElement | null>(null)
const headerSearchOpen = ref(false)
const headerSearchLoading = ref(false)
const headerSearchCourses = ref<CourseDetail[]>([])
const headerSearchNotes = ref<NoteSearchItem[]>([])
const headerSearchNews = ref<NewsItem[]>([])
let headerSearchTimer: number | undefined
let headerSearchSequence = 0
let headerSearchCatalogPromise: Promise<void> | null = null
let notificationTimer: number | undefined

const navigationItems = computed(() => navigationForRole(auth.user?.role))
const roleLabel = computed(() => ({ student: '学生', teacher: '教师', admin: '管理员' }[auth.user?.role || 'student']))
const contextTitle = computed(() => workspace.currentCourse?.name || workspace.currentClass?.name || '高校思政课')
const contextDetail = computed(() => {
  if (auth.user?.role === 'student') return workspace.currentChapter?.title || '今日学习'
  return workspace.currentClass?.name || '当前教学空间'
})
const shouldBindEmail = computed(() => auth.user?.role !== 'admin' && !auth.user?.email_verified_at)

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

const headerSearchQuery = computed(() => headerSearch.value.trim())
const headerSearchGroups = computed(() => [
  {
    key: 'learning',
    label: '教材与专题',
    items: headerLearningSearchItems.value,
  },
  {
    key: 'notes',
    label: '我的笔记',
    items: headerNoteSearchItems.value,
  },
  {
    key: 'news',
    label: '时政资料',
    items: headerNewsSearchItems.value,
  },
].filter((group) => group.items.length))
const headerSearchHasResults = computed(() => headerSearchGroups.value.length > 0)
const headerSearchCanAskAi = computed(() => Boolean(workspace.currentCourse?.id && workspace.currentChapter?.id))
const currentLearningStage = computed<LearningStage>(() => {
  const value = route.params.stage
  return value === 'review' || value === 'exam' ? value : 'preview'
})

interface HeaderSearchItem {
  key: string
  title: string
  description: string
  meta: string
  path?: string
}

const headerLearningSearchItems = computed<HeaderSearchItem[]>(() => {
  const query = headerSearchQuery.value.toLocaleLowerCase()
  if (!query) return []
  const courses: HeaderSearchItem[] = []
  const chapters: HeaderSearchItem[] = []
  for (const course of headerSearchCourses.value) {
    if ([course.name, course.description || ''].some((value) => value.toLocaleLowerCase().includes(query))) {
      courses.push({ key: `course-${course.id}`, title: course.name, description: course.description || '进入教材目录查看全部专题', meta: '教材', path: `/courses/${course.id}` })
    }
    for (const chapter of course.chapters) {
      if ([chapter.title, chapter.content || '', course.name].some((value) => value.toLocaleLowerCase().includes(query))) {
        chapters.push({ key: `chapter-${chapter.id}`, title: chapter.title, description: compactHeaderSearchText(chapter.content || '进入专题学习'), meta: course.name, path: chapterSearchPath(course.id, chapter.id) })
      }
    }
  }
  return [...courses.slice(0, 3), ...chapters.slice(0, 6)]
})
const headerNoteSearchItems = computed<HeaderSearchItem[]>(() => headerSearchNotes.value.slice(0, 5).map((item) => ({
  key: `note-${item.id}`,
  title: item.chapter_title,
  description: compactHeaderSearchText(item.excerpt),
  meta: `${item.course_name} · 笔记`,
  path: chapterSearchPath(item.course_id, item.chapter_id),
})))
const headerNewsSearchItems = computed<HeaderSearchItem[]>(() => headerSearchNews.value.slice(0, 5).map((item) => ({
  key: `news-${item.id}`,
  title: item.title,
  description: compactHeaderSearchText(item.summary || '打开时政资料查看详情'),
  meta: `${item.source_name} · 时政`,
  path: `/current-affairs?q=${encodeURIComponent(item.title)}`,
})))

function compactHeaderSearchText(value: string, limit = 86) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}…` : normalized
}

function chapterSearchPath(courseId: number, chapterId: number) {
  return auth.user?.role === 'student'
    ? `/courses/${courseId}/chapters/${chapterId}/${currentLearningStage.value}`
    : `/courses/${courseId}`
}

async function ensureHeaderSearchCatalog() {
  if (headerSearchCourses.value.length || headerSearchCatalogPromise) return headerSearchCatalogPromise
  headerSearchCatalogPromise = (async () => {
    try {
      const courses = (await courseApi.list()).data.data
      const details = await Promise.all(courses.map(async (course) => {
        try { return (await courseApi.detail(course.id)).data.data }
        catch { return null }
      }))
      headerSearchCourses.value = details.filter((item): item is CourseDetail => Boolean(item))
    } catch {
      headerSearchCourses.value = []
    } finally {
      headerSearchCatalogPromise = null
    }
  })()
  return headerSearchCatalogPromise
}

async function runHeaderSearch() {
  const query = headerSearchQuery.value
  const sequence = ++headerSearchSequence
  if (!query) {
    headerSearchLoading.value = false
    headerSearchNotes.value = []
    headerSearchNews.value = []
    return
  }
  headerSearchLoading.value = true
  const [catalogResult, notesResult, newsResult] = await Promise.allSettled([
    ensureHeaderSearchCatalog(),
    studyApi.semanticSearch(query, workspace.currentCourse?.id),
    newsApi.search({ q: query, sort: 'relevance', days: null, page: 1, pageSize: 5 }),
  ])
  if (sequence !== headerSearchSequence) return
  if (notesResult.status === 'fulfilled') headerSearchNotes.value = notesResult.value.data.data
  else headerSearchNotes.value = []
  if (newsResult.status === 'fulfilled') headerSearchNews.value = newsResult.value.data.data.items
  else headerSearchNews.value = []
  if (catalogResult.status === 'rejected') headerSearchCourses.value = []
  headerSearchLoading.value = false
}

function scheduleHeaderSearch() {
  if (headerSearchTimer) window.clearTimeout(headerSearchTimer)
  headerSearchTimer = window.setTimeout(() => { void runHeaderSearch() }, 220)
}

function askAiFromHeader() {
  const query = headerSearchQuery.value
  const courseId = workspace.currentCourse?.id
  const chapterId = workspace.currentChapter?.id
  if (!query) return
  if (!courseId || !chapterId) {
    ElMessage.info('请先进入一个专题，再让 AI 结合当前教材回答')
    return
  }
  headerSearchOpen.value = false
  headerSearch.value = ''
  const request = {
    courseId,
    chapterId,
    learningStage: currentLearningStage.value,
    taskType: 'question_answer',
    prompt: `请严格依据当前专题教材回答下面的问题，不要脱离教材原文作无依据推断。\n\n我的问题：${query}`,
  } as const
  const dispatch = () => requestWorkspaceAi(request)
  if (route.path === '/notes') {
    void router.push(chapterSearchPath(courseId, chapterId)).then(() => window.setTimeout(dispatch, 120))
  } else dispatch()
}

function selectHeaderSearchResult(item: HeaderSearchItem) {
  headerSearchOpen.value = false
  headerSearch.value = ''
  if (item.path) void router.push(item.path)
}

function submitHeaderSearch() {
  const firstResult = headerSearchGroups.value[0]?.items[0]
  if (firstResult) return selectHeaderSearchResult(firstResult)
  if (headerSearchQuery.value) askAiFromHeader()
}

function handleHeaderSearchOutside(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Node) || !headerSearchArea.value?.contains(target)) headerSearchOpen.value = false
}

onMounted(() => {
  workspace.initialize()
  void loadNotifications()
  window.addEventListener('notifications-changed', loadNotifications)
  document.addEventListener('pointerdown', handleHeaderSearchOutside)
  notificationTimer = window.setInterval(() => void loadNotifications(), 60_000)
})

onUnmounted(() => {
  window.removeEventListener('notifications-changed', loadNotifications)
  document.removeEventListener('pointerdown', handleHeaderSearchOutside)
  if (headerSearchTimer) window.clearTimeout(headerSearchTimer)
  if (notificationTimer) window.clearInterval(notificationTimer)
})

const unreadNotificationCount = computed(() => notifications.value.filter((item) => !item.is_read).length)
const headerBadgeCount = computed(() => auth.user?.role === 'admin'
  ? actionableCandidateCount.value + pendingPasswordResetCount.value
  : unreadNotificationCount.value)
const headerAlertTooltip = computed(() => auth.user?.role === 'admin'
  ? `待处理：资料 ${actionableCandidateCount.value} 条，账号找回 ${pendingPasswordResetCount.value} 条`
  : (unreadNotificationCount.value ? `未读消息：${unreadNotificationCount.value} 条` : '暂无未读消息'))

async function loadNotifications() {
  if (!auth.user) return
  notificationLoading.value = true
  try {
    try {
      const response = await notificationApi.list(false, 80)
      notifications.value = response.data.data
    } catch { /* 提醒接口异常不应阻断管理员账号找回入口 */ }
    if (auth.user?.role === 'admin') {
      const [candidateSummary, resetRequests] = await Promise.all([
        knowledgeApi.candidateDecisionSummary(),
        authApi.pendingPasswordResets(),
      ])
      actionableCandidateCount.value = candidateSummary.data.data.pending_review
      pendingPasswordResetCount.value = resetRequests.data.data.length
    }
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

function openHeaderAlerts() {
  if (auth.user?.role === 'admin') {
    if (pendingPasswordResetCount.value > 0) router.push('/admin/password-resets')
    else router.push('/material-discovery')
  }
  else {
    messageVisible.value = true
    void loadNotifications()
  }
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
      <router-link to="/" class="brand" aria-label="返回思政红芯工作台">
        <BrandLockup title="思政红芯" subtitle="思政智教 · 思政教学平台" compact />
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
        <div ref="headerSearchArea" class="header-search-area">
          <el-input
            v-model="headerSearch"
            class="header-search"
            :prefix-icon="Search"
            placeholder="搜索教材、专题、笔记，或直接问 AI"
            aria-label="搜索教材、专题、笔记，或直接问 AI"
            clearable
            @focus="headerSearchOpen = true"
            @input="scheduleHeaderSearch"
            @keyup.enter="submitHeaderSearch"
            @keydown.esc="headerSearchOpen = false"
          />
          <div v-if="headerSearchOpen" class="header-search-panel" role="dialog" aria-label="全局学习搜索结果" @pointerdown.stop>
            <div v-if="!headerSearchQuery" class="header-search-empty header-search-intro">
              <strong>全局学习指令栏</strong>
              <span>可搜索教材专题、个人笔记和时政资料；没有找到时，可以让 AI 结合当前专题回答。</span>
            </div>
            <div v-else-if="headerSearchLoading" class="header-search-empty">正在检索教材、笔记和时政资料…</div>
            <template v-else>
              <section v-for="group in headerSearchGroups" :key="group.key" class="header-search-group">
                <div class="header-search-group-title"><strong>{{ group.label }}</strong><small>{{ group.items.length }} 条结果</small></div>
                <button
                  v-for="item in group.items"
                  :key="item.key"
                  type="button"
                  class="header-search-result"
                  @pointerdown.prevent
                  @click="selectHeaderSearchResult(item)"
                >
                  <span class="header-search-result-mark" aria-hidden="true">{{ group.key === 'learning' ? '教' : group.key === 'notes' ? '记' : '政' }}</span>
                  <span class="header-search-result-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small><em>{{ item.meta }}</em></span>
                </button>
              </section>
              <button v-if="headerSearchCanAskAi" type="button" class="header-search-ai-result" @pointerdown.prevent @click="askAiFromHeader">
                <span class="header-search-result-mark" aria-hidden="true">AI</span>
                <span><strong>让 AI 助教回答“{{ compactHeaderSearchText(headerSearchQuery, 42) }}”</strong><small>结合当前课程、专题和教材内容生成回答</small></span>
              </button>
              <div v-if="!headerSearchHasResults && !headerSearchCanAskAi" class="header-search-empty">暂未找到相关内容。进入一个专题后，可以让 AI 结合教材回答。</div>
              <div v-else-if="!headerSearchHasResults" class="header-search-empty">暂未找到相关内容，可以让 AI 结合当前专题回答。</div>
            </template>
          </div>
        </div>
        <div class="global-actions" aria-label="全局工具">
          <span class="topbar-divider" aria-hidden="true"></span>
          <el-tooltip content="消息中心">
            <el-badge :value="headerBadgeCount" :hidden="headerBadgeCount === 0" :max="99" class="message-badge">
              <el-button circle text :icon="Message" aria-label="查看消息中心" @click="messageVisible = true; void loadNotifications()" />
            </el-badge>
          </el-tooltip>
          <el-tooltip :content="headerAlertTooltip">
            <el-button circle text :icon="Bell" aria-label="查看待处理提醒" @click="openHeaderAlerts" />
          </el-tooltip>
          <el-dropdown class="user-profile-dropdown">
            <button type="button" class="user-profile-trigger" aria-label="打开用户菜单">
              <span class="user-avatar" aria-hidden="true"><img :src="logoUrl" alt="" /></span>
              <span class="user-profile-copy"><strong>{{ auth.user?.username }}</strong><small>{{ roleLabel }}</small></span>
              <el-icon class="user-profile-arrow"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ auth.user?.username }} · {{ roleLabel }}</el-dropdown-item>
                <el-dropdown-item v-if="auth.user?.role !== 'admin'" @click="router.push('/account')">账号设置</el-dropdown-item>
                <el-dropdown-item @click="taskVisible = true">后台任务</el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <el-alert
        v-if="shouldBindEmail"
        class="email-binding-reminder"
        type="warning"
        :closable="false"
        title="建议绑定并验证邮箱"
        description="绑定邮箱后可以自助找回密码，避免只能联系管理员人工重置。"
        show-icon
      >
        <template #default><el-button text type="warning" @click="router.push('/account')">立即绑定邮箱</el-button></template>
      </el-alert>

      <el-alert
        v-if="auth.user?.role === 'admin' && pendingPasswordResetCount > 0"
        class="password-reset-reminder"
        type="warning"
        :closable="false"
        :title="`有 ${pendingPasswordResetCount} 条账号找回请求待处理`"
        description="老账号用户无法通过邮箱自助找回时，请在账号找回页面生成统一临时密码。"
        show-icon
      >
        <template #default><el-button text type="warning" @click="router.push('/admin/password-resets')">立即处理</el-button></template>
      </el-alert>

      <AgentDock v-if="route.path !== '/notes'" />
      <main class="page" :class="{ 'page--notes': route.path === '/notes' }"><router-view /></main>
    </div>

    <el-drawer v-model="mobileNavVisible" title="功能导航" direction="ltr" size="min(88vw, 340px)">
      <div class="mobile-brand"><BrandLockup title="思政红芯" subtitle="思政智教 · 思政教学平台" compact /><span class="mobile-brand-role">{{ roleLabel }}空间</span></div>
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
          <small>{{ formatBeijingDateTime(item.created_time) }}</small>
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
              <small>{{ formatBeijingDateTime(run.updated_time) }}</small>
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
  color: var(--ink-900);
  background: var(--surface-card);
  border-right: 1px solid var(--line);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-2);
  color: var(--ink-900);
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: var(--brand-primary);
  background: var(--brand-primary-soft);
  border: 1px solid var(--blue-200);
  border-radius: var(--radius-input);
  font-size: 18px;
  font-weight: var(--fw-bold);
}

.sidebar-navigation button span,
.mobile-navigation button span {
  display: grid;
  min-width: 0;
}

.brand :deep(.brand-lockup) { width: 100%; }
.brand :deep(.brand-lockup__copy strong) { color: var(--ink-900); font-size: 16px; }
.brand :deep(.brand-lockup__copy small) { margin-top: 2px; color: var(--ink-400); font-size: 9px; letter-spacing: .04em; }
.role-identity { display: grid; gap: 3px; margin: 0 var(--space-2); padding: var(--space-3); background: var(--surface-muted); border: 1px solid var(--line); border-radius: var(--radius-card); }
.role-identity span, .sidebar-footer span { color: var(--ink-400); font-size: var(--fs-meta); }
.role-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-navigation { display: grid; align-content: start; gap: var(--space-2); }
.sidebar-navigation button, .mobile-navigation button { display: grid; grid-template-columns: 34px minmax(0, 1fr); align-items: center; gap: var(--space-2); width: 100%; padding: 11px 10px; color: var(--ink-600); background: transparent; border: 0; border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.sidebar-navigation button:hover, .sidebar-navigation button.active { color: var(--brand-primary); background: var(--brand-primary-soft); }
.sidebar-navigation button.active { font-weight: var(--fw-medium); }
.sidebar-navigation .el-icon { width: 34px; height: 34px; font-size: 18px; }
.sidebar-navigation small, .mobile-navigation small { margin-top: 2px; color: var(--ink-400); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-footer { display: flex; justify-content: space-between; padding: var(--space-3) var(--space-2) 0; border-top: 1px solid var(--line); font-size: var(--fs-meta); }
.app-content { min-width: 0; }
.email-binding-reminder { margin: var(--space-3) var(--page-padding) 0; }
.password-reset-reminder { margin: var(--space-3) var(--page-padding) 0; }
.context-topbar { position: sticky; z-index: 110; top: 0; display: flex; height: 76px; align-items: center; gap: var(--space-4); padding: 0 var(--page-padding); background: var(--surface-card); border-bottom: 1px solid var(--line); }
.header-search-area { position: relative; min-width: 260px; max-width: 640px; flex: 1 1 520px; }
.header-search { width: 100%; }
.header-search :deep(.el-input__wrapper) { min-height: 48px; padding: 1px 17px; background: #fff0f1; border: 1px solid transparent; border-radius: 14px; box-shadow: none; transition: background .18s ease, border-color .18s ease, box-shadow .18s ease; }
.header-search :deep(.el-input__wrapper:hover) { background: #ffeaec; }
.header-search :deep(.el-input__wrapper.is-focus) { background: #fff; border-color: var(--line-strong); box-shadow: 0 0 0 3px rgb(255 135 135 / 14%); }
.header-search :deep(.el-input__prefix) { color: #61456f; font-size: 24px; }
.header-search :deep(.el-input__inner) { color: var(--ink-900); font-size: 18px; }
.header-search :deep(.el-input__inner::placeholder) { color: #6e6475; opacity: 1; }
.header-search-panel { position: absolute; z-index: 260; top: calc(100% + 8px); left: 0; display: grid; width: min(560px, calc(100vw - 32px)); max-height: min(600px, calc(100vh - 94px)); padding: 10px; overflow-y: auto; background: rgba(255,255,255,.98); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 18px 46px rgb(35 49 73 / 18%); }
.header-search-group { display: grid; gap: 3px; padding: 4px 0 8px; }
.header-search-group + .header-search-group { border-top: 1px solid var(--line); }
.header-search-group-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 8px 4px; color: var(--ink-700); font-size: 12px; }
.header-search-group-title small { color: var(--ink-400); font-size: 10px; font-weight: 400; }
.header-search-result, .header-search-ai-result { display: flex; width: 100%; min-width: 0; align-items: center; gap: 10px; padding: 9px 8px; color: var(--ink-800); text-align: left; background: transparent; border: 0; border-radius: 9px; cursor: pointer; }
.header-search-result:hover, .header-search-ai-result:hover { background: var(--brand-primary-soft); }
.header-search-result-mark { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; color: var(--brand-primary-deep); background: var(--brand-primary-soft); border-radius: 8px; font-size: 11px; font-weight: 800; }
.header-search-result-copy { display: grid; min-width: 0; gap: 2px; }
.header-search-result-copy strong, .header-search-result-copy small, .header-search-result-copy em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.header-search-result-copy strong { color: var(--ink-800); font-size: 12px; }
.header-search-result-copy small { color: var(--ink-500); font-size: 11px; }
.header-search-result-copy em { color: var(--ink-400); font-size: 10px; font-style: normal; }
.header-search-ai-result { margin-top: 4px; background: #f5f8ff; border: 1px solid #d9e3fb; }
.header-search-ai-result > span:last-child { display: grid; min-width: 0; gap: 3px; }
.header-search-ai-result strong { overflow: hidden; color: #3157b7; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.header-search-ai-result small { color: var(--ink-500); font-size: 10px; }
.header-search-empty { padding: 24px 12px; color: var(--ink-500); font-size: 12px; line-height: 1.6; text-align: center; }
.header-search-intro { display: grid; gap: 5px; text-align: left; }
.header-search-intro strong { color: var(--ink-800); font-size: 13px; }
.header-search-intro span { color: var(--ink-500); }
.global-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.topbar-divider { display: block; width: 1px; height: 32px; margin: 0 9px 0 2px; background: var(--line-strong); }
.global-actions :deep(.el-button) { width: 42px; height: 42px; padding: 0; color: #4d3a60; font-size: 22px; }
.global-actions :deep(.el-button:hover), .global-actions :deep(.el-button:focus-visible) { color: var(--brand-primary-deep); background: var(--brand-primary-soft); }
.message-badge :deep(.el-badge__content) { top: 3px; right: 3px; min-width: 8px; height: 8px; padding: 0; background: #f14b8a; border: 2px solid #fff; border-radius: 50%; font-size: 0; }
.user-profile-dropdown { margin-left: var(--space-2); padding-left: var(--space-4); border-left: 1px solid var(--line-strong); }
.user-profile-trigger { display: flex; min-width: 0; align-items: center; gap: 9px; padding: 2px 0 2px 2px; color: var(--ink-900); background: transparent; border: 0; border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.user-profile-trigger:hover .user-avatar { border-color: var(--brand-primary); box-shadow: 0 4px 12px rgb(210 75 75 / 16%); transform: translateY(-1px); }
.user-avatar { display: grid; width: 38px; height: 38px; flex: 0 0 auto; padding: 4px; place-items: center; background: var(--brand-primary-soft); border: 1px solid var(--line-strong); border-radius: 50%; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.user-avatar img { width: 100%; height: 100%; object-fit: contain; }
.user-profile-copy { display: grid; min-width: 72px; gap: 2px; }
.user-profile-copy strong { max-width: 116px; overflow: hidden; font-size: 13px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.user-profile-copy small { color: var(--ink-400); font-size: 11px; line-height: 1.25; }
.user-profile-arrow { margin-left: 3px; color: var(--ink-600); font-size: 16px; transition: transform .18s ease; }
.user-profile-trigger:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 3px; }
.page { width: min(100%, calc(var(--page-max-width) + var(--page-padding) * 2)); min-width: 0; margin: 0 auto; padding: var(--space-8) var(--page-padding) 48px; overflow: visible; }
.page.page--notes { display: flex; width: 100%; max-width: none; height: calc(100vh - 76px); min-height: 0; flex-direction: column; padding: 0; overflow: hidden; }
.mobile-shell-nav { display: none; }
.mobile-brand { display: grid; gap: var(--space-2); margin-bottom: var(--space-6); }
.mobile-brand :deep(.brand-lockup) { width: 100%; }
.mobile-brand-role { color: var(--ink-400); }
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
.notification-item.unread { background: var(--brand-primary-soft); border-color: var(--action-line); box-shadow: inset 3px 0 0 var(--brand-primary); }
.notification-item:hover { border-color: var(--brand-primary); }
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
  .header-search-area { min-width: 0; }
  .header-search :deep(.el-input__inner) { font-size: 15px; }
  .header-search-panel { position: fixed; top: 70px; right: 12px; left: 12px; width: auto; max-height: calc(100vh - 88px); }
  .global-actions { gap: 2px; }
  .global-actions > :first-child { display: none; }
  .user-profile-dropdown { margin-left: 0; padding-left: 4px; }
  .user-profile-copy, .user-profile-arrow { display: none; }
}
</style>

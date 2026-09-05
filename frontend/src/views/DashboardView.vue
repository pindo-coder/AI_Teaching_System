<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  Bell,
  Calendar,
  ChatDotRound,
  Check,
  Collection,
  Connection,
  TrendCharts,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { assignmentApi, type StudentAssignment, type TeacherAssignment } from '@/api/assignments'
import { learningApi } from '@/api/learning'
import { useAuthStore } from '@/stores/auth'
import type { DashboardData, LearningStage } from '@/types'
import { beijingTimestamp, beijingToday, formatBeijingTime } from '@/utils/time'
import { requestWorkspaceAi } from '@/utils/workspaceAiEvents'
import dashboardHomeBackground from '@/assets/dashboard-home-bg.svg'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(true)
const dashboard = ref<DashboardData | null>(null)
const assignments = ref<StudentAssignment[]>([])
const teacherAssignments = ref<TeacherAssignment[]>([])

const stageLabels: Record<LearningStage, string> = { preview: '课前预习', review: '课后巩固', exam: '考前冲刺' }
const stageDescriptions: Record<LearningStage, string> = { preview: '理解章节结构，形成问题意识', review: '梳理观点逻辑，沉淀个人笔记', exam: '聚焦核心考点，完成输出训练' }
const learningStages: LearningStage[] = ['preview', 'review', 'exam']
const isStudent = computed(() => auth.user?.role === 'student')
const allPendingAssignments = computed(() => assignments.value.filter((item) => item.status !== 'completed'))
const pendingAssignments = computed(() => [...allPendingAssignments.value].sort((a, b) => beijingTimestamp(a.due_time) - beijingTimestamp(b.due_time)))
const activeTeacherAssignments = computed(() => teacherAssignments.value.filter((item) => item.status === 'published'))
const latestProgress = computed(() => dashboard.value?.recent_progress[0] || null)
const latestFootprint = computed(() => dashboard.value?.stage_footprints
  .filter((item) => item.last_activity_time)
  .sort((a, b) => beijingTimestamp(b.last_activity_time || '') - beijingTimestamp(a.last_activity_time || ''))[0] || null)
const currentLearningStage = computed(() => latestFootprint.value?.learning_stage || latestProgress.value?.learning_stage || 'preview')
const continuePath = computed(() => {
  const courseId = dashboard.value?.current_course?.id
  const chapterId = dashboard.value?.current_chapter?.id
  return courseId && chapterId ? `/courses/${courseId}/chapters/${chapterId}/${currentLearningStage.value}` : '/courses'
})

function taskPath(task: StudentAssignment) { return `/courses/${task.course_id}/chapters/${task.chapter_id}/${task.learning_stage}` }
function stagePath(stage: LearningStage) {
  const courseId = dashboard.value?.current_course?.id
  const chapterId = dashboard.value?.current_chapter?.id
  return courseId && chapterId ? `/courses/${courseId}/chapters/${chapterId}/${stage}` : '/courses'
}
function stageFootprint(stage: LearningStage) { return dashboard.value?.stage_footprints.find((item) => item.learning_stage === stage) }
function stageStatusClass(stage: LearningStage) { return stageFootprint(stage)?.status.replace('_', '-') || 'not-started' }
function deadlineClass(task: StudentAssignment) {
  if (task.status === 'overdue') return 'overdue'
  return beijingTimestamp(task.due_time) - Date.now() < 24 * 3600 * 1000 ? 'urgent' : ''
}
function dueLabel(value: string) { return formatBeijingTime(value, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
function activityTime(value: string) { return formatBeijingTime(value, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
function activityStageLabel(stage: LearningStage | null) { return stage ? stageLabels[stage] : '学习活动' }
function dateKey(value: string) {
  const timestamp = beijingTimestamp(value)
  if (!Number.isFinite(timestamp)) return ''
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(timestamp))
}

const todayKey = beijingToday()
const calendarCursor = ref(`${todayKey.slice(0, 7)}-01`)
const selectedDate = ref(todayKey)
const calendarMonthLabel = computed(() => {
  const [year, month] = calendarCursor.value.split('-').map(Number)
  return `${year} 年 ${month} 月`
})
const calendarCells = computed(() => {
  const [year, month] = calendarCursor.value.split('-').map(Number)
  const firstDay = new Date(year, month - 1, 1)
  const offset = (firstDay.getDay() + 6) % 7
  const daysInMonth = new Date(year, month, 0).getDate()
  const total = Math.ceil((offset + daysInMonth) / 7) * 7
  return Array.from({ length: total }, (_, index) => {
    const date = new Date(year, month - 1, index - offset + 1)
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    return { key, day: date.getDate(), isCurrentMonth: date.getMonth() === month - 1, isToday: key === todayKey, tasks: pendingAssignments.value.filter((task) => dateKey(task.due_time) === key) }
  })
})
const selectedDayTasks = computed(() => pendingAssignments.value.filter((task) => dateKey(task.due_time) === selectedDate.value))
const recentActivities = computed(() => dashboard.value?.recent_activities.slice(0, 5) || [])

interface SmartRecommendation { title: string; description: string; action: string; actionKind: 'task' | 'continue' | 'plan' | 'chat'; path?: string }
const smartRecommendation = computed<SmartRecommendation>(() => {
  const firstTask = pendingAssignments.value[0]
  if (firstTask) return { title: '先完成最早截止的任务', description: `${firstTask.title} · ${firstTask.chapter_title}，截止 ${dueLabel(firstTask.due_time)}`, action: firstTask.status === 'not_started' ? '开始任务' : '继续任务', actionKind: 'task', path: taskPath(firstTask) }
  const current = stageFootprint(currentLearningStage.value)
  if (dashboard.value?.current_chapter && (!current || current.status === 'not_started')) return { title: `从${stageLabels[currentLearningStage.value]}开始`, description: `当前专题为“${dashboard.value.current_chapter.title}”，还没有形成这一阶段的学习记录。`, action: '进入专题', actionKind: 'continue', path: continuePath.value }
  if (current && current.outputs.length === 0) return { title: '把本章认识整理成笔记', description: current.next_action || '阅读完成后保存一份自己的总结，方便之后复习。', action: '打开笔记', actionKind: 'continue', path: '/notes' }
  if (dashboard.value?.outputs.length) return { title: '回顾已有学习产出', description: `最近已形成 ${dashboard.value.outputs.length} 项学习产出，可以用 AI 帮你安排下一轮复习。`, action: '生成学习计划', actionKind: 'plan' }
  return { title: '选择一个专题开始学习', description: '进入教材目录后，可以从课前预习、课后巩固或考前冲刺开始。', action: '浏览教材专题', actionKind: 'continue', path: '/courses' }
})

function changeCalendarMonth(offset: number) {
  const [year, month] = calendarCursor.value.split('-').map(Number)
  const next = new Date(year, month - 1 + offset, 1)
  calendarCursor.value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-01`
  selectedDate.value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-01`
}
function selectCalendarDay(cell: { key: string; isCurrentMonth: boolean }) { if (cell.isCurrentMonth) selectedDate.value = cell.key }
function runRecommendation() {
  const recommendation = smartRecommendation.value
  if (recommendation.path) { void router.push(recommendation.path); return }
  const courseId = dashboard.value?.current_course?.id
  const chapterId = dashboard.value?.current_chapter?.id
  if (!courseId || !chapterId) { ElMessage.info('请先选择一个教材专题，再让 AI 结合你的学习记录给出建议'); void router.push('/courses'); return }
  if (recommendation.actionKind === 'plan') {
    requestWorkspaceAi({ courseId, chapterId, learningStage: currentLearningStage.value, taskType: 'question_answer', mode: 'agent', autoSend: true, prompt: '请先汇总我最近 7 天真实的学习行为、任务和学习产出，再根据结果给出一份可执行的学习计划。请明确优先顺序、预计用时和下一步行动，不要虚构不存在的学习记录。' })
  } else {
    requestWorkspaceAi({ courseId, chapterId, learningStage: currentLearningStage.value, taskType: 'question_answer', mode: 'chat', autoSend: false, prompt: '请结合当前专题和我的学习记录，告诉我下一步最值得完成的一件事，并说明理由。' })
  }
}

function runAiAction(kind: 'plan' | 'chat') {
  const courseId = dashboard.value?.current_course?.id
  const chapterId = dashboard.value?.current_chapter?.id
  if (!courseId || !chapterId) {
    ElMessage.info('请先选择一个教材专题，再让 AI 结合你的学习记录给出建议')
    void router.push('/courses')
    return
  }
  requestWorkspaceAi({
    courseId,
    chapterId,
    learningStage: currentLearningStage.value,
    taskType: 'question_answer',
    mode: kind === 'plan' ? 'agent' : 'chat',
    autoSend: kind === 'plan',
    prompt: kind === 'plan'
      ? '请先汇总我最近 7 天真实的学习行为、任务和学习产出，再根据结果给出一份可执行的学习计划。请明确优先顺序、预计用时和下一步行动，不要虚构不存在的学习记录。'
      : '请结合当前专题和我的学习记录，告诉我下一步最值得完成的一件事，并说明理由。',
  })
}

const teacherQuickLinks = [
  { title: '任务管理', description: '发布并查看学生完成情况', path: '/assignments', icon: Bell },
  { title: '教材专题', description: '管理教材与专题内容', path: '/courses', icon: Collection },
  { title: '时政要点', description: '检索权威媒体时政内容', path: '/current-affairs', icon: TrendCharts },
  { title: '课堂互动', description: '发布讨论与课堂活动', path: '/interaction', icon: ChatDotRound },
]

onMounted(async () => {
  try {
    const requests: Promise<unknown>[] = [learningApi.dashboard().then(({ data }) => { dashboard.value = data.data })]
    if (isStudent.value) requests.push(assignmentApi.student(false).then(({ data }) => { assignments.value = data.data }))
    else requests.push(assignmentApi.teacher().then(({ data }) => { teacherAssignments.value = data.data }))
    await Promise.allSettled(requests)
  } finally { loading.value = false }
})
</script>

<template>
  <div v-loading="loading" class="dashboard-command-center">
    <template v-if="isStudent">
      <div class="dashboard-student-top-grid">
        <section class="dashboard-student-hero" :style="{ '--dashboard-home-bg': 'url(' + dashboardHomeBackground + ')' }">
          <div class="dashboard-hero-copy"><p class="dashboard-hero-eyebrow">思政红芯 · 今日学习</p><h1>你好，{{ auth.user?.username }}</h1><p class="dashboard-hero-description">从教材出发，沿着专题、任务和笔记继续今天的学习。</p><div class="dashboard-hero-actions"><el-button type="primary" @click="router.push(continuePath)">{{ latestProgress ? '继续当前专题' : '开始专题学习' }}<el-icon><ArrowRight /></el-icon></el-button><el-button plain @click="router.push('/courses')"><el-icon><Collection /></el-icon>浏览教材</el-button></div></div>
          <div class="dashboard-hero-context"><span>当前专题</span><strong>{{ dashboard?.current_chapter?.title || '尚未选择专题' }}</strong><small>{{ dashboard?.current_course?.name || '从教材目录开始你的学习' }}</small><div class="dashboard-hero-progress"><span>总体进度</span><strong>{{ dashboard?.overall_progress || 0 }}%</strong></div></div>
        </section>
        <section class="dashboard-section dashboard-calendar-card"><div class="dashboard-section-heading"><div><p class="dashboard-section-kicker">学习安排</p><h2><el-icon><Calendar /></el-icon>待完成任务</h2></div><el-button text type="primary" @click="router.push('/assignments')">全部</el-button></div><div class="dashboard-calendar-toolbar"><strong>{{ calendarMonthLabel }}</strong><div><el-button text circle aria-label="上个月" @click="changeCalendarMonth(-1)">‹</el-button><el-button text circle aria-label="下个月" @click="changeCalendarMonth(1)">›</el-button></div></div><div class="dashboard-calendar-weekdays"><span v-for="day in ['一', '二', '三', '四', '五', '六', '日']" :key="day">{{ day }}</span></div><div class="dashboard-calendar-grid"><button v-for="cell in calendarCells" :key="cell.key" type="button" class="dashboard-calendar-day" :class="{ muted: !cell.isCurrentMonth, today: cell.isToday, selected: selectedDate === cell.key, 'has-task': cell.tasks.length }" :aria-label="`${cell.key}${cell.tasks.length ? `，${cell.tasks.length} 项任务` : ''}`" @click="selectCalendarDay(cell)"><span>{{ cell.day }}</span><i v-if="cell.tasks.length" aria-hidden="true"></i></button></div><div class="dashboard-selected-day"><div class="dashboard-selected-day-heading"><strong>{{ selectedDate === todayKey ? '今天' : selectedDate.replace(/-/g, '/') }}</strong><span>{{ selectedDayTasks.length }} 项任务</span></div><button v-for="task in selectedDayTasks.slice(0, 2)" :key="task.id" type="button" class="dashboard-calendar-task" @click="router.push(taskPath(task))"><span :class="deadlineClass(task)"></span><div><strong>{{ task.title }}</strong><small>{{ task.chapter_title }} · {{ task.status === 'overdue' ? '已逾期' : '截止 ' + dueLabel(task.due_time) }}</small></div><el-icon><ArrowRight /></el-icon></button><p v-if="!selectedDayTasks.length">这一天没有待完成任务</p></div></section>
      </div>
      <div class="dashboard-student-grid">
        <div class="dashboard-main-column">
          <section class="dashboard-section dashboard-stage-section"><div class="dashboard-section-heading"><div><p class="dashboard-section-kicker">学习路径</p><h2>专题学习</h2></div><el-button text type="primary" @click="router.push('/courses')">查看全部 <el-icon><ArrowRight /></el-icon></el-button></div><div class="dashboard-stage-grid"><button v-for="(stage, index) in learningStages" :key="stage" type="button" class="dashboard-stage-card" :class="[stageStatusClass(stage), { active: currentLearningStage === stage }]" @click="router.push(stagePath(stage))"><span class="dashboard-stage-index">0{{ index + 1 }}</span><span class="dashboard-stage-state"><el-icon v-if="stageFootprint(stage)?.status === 'has_output'"><Check /></el-icon>{{ stageFootprint(stage)?.status_label || '未开始' }}</span><strong>{{ stageLabels[stage] }}</strong><small>{{ stageFootprint(stage)?.outputs[0] || stageDescriptions[stage] }}</small><span class="dashboard-stage-link">进入学习 <el-icon><ArrowRight /></el-icon></span></button></div></section>
          <section class="dashboard-section dashboard-recommendation"><div class="dashboard-recommendation-icon">AI</div><div class="dashboard-recommendation-copy"><p class="dashboard-section-kicker">智能学习建议</p><h2>{{ smartRecommendation.title }}</h2><p>{{ smartRecommendation.description }}</p></div><div class="dashboard-recommendation-actions"><el-button type="primary" @click="runRecommendation">{{ smartRecommendation.action }}<el-icon><ArrowRight /></el-icon></el-button><el-button text type="primary" @click="runAiAction('plan')">生成学习计划</el-button><el-button text @click="runAiAction('chat')">问 AI</el-button></div></section>
        </div>
        <aside class="dashboard-side-column">
          <section class="dashboard-section dashboard-activity-card"><div class="dashboard-section-heading"><div><p class="dashboard-section-kicker">学习足迹</p><h2>近期学习活动</h2></div><span class="dashboard-activity-count">{{ dashboard?.recent_activities.length || 0 }}</span></div><div v-if="recentActivities.length" class="dashboard-activity-list"><article v-for="item in recentActivities" :key="`${item.created_time}-${item.label}`" class="dashboard-activity-item"><span class="dashboard-activity-dot"></span><div><strong>{{ item.label }}</strong><small>{{ activityStageLabel(item.learning_stage) }} · {{ activityTime(item.created_time) }}</small></div></article></div><el-empty v-else :image-size="46" description="完成学习后会显示在这里" /></section>
        </aside>
      </div>
    </template>
    <template v-else>
      <section class="dashboard-teacher-hero"><div><p class="dashboard-hero-eyebrow">思政红芯 · 教学工作台</p><h1>{{ auth.isAdmin ? '让平台教学运行更清晰' : '把教学安排在清晰的节奏里' }}</h1><p>围绕教材专题安排任务与课堂互动，随时掌握教学进展。</p><div class="dashboard-hero-actions"><el-button type="primary" @click="router.push('/assignments')">布置学习任务<el-icon><ArrowRight /></el-icon></el-button><el-button plain @click="router.push('/courses')"><el-icon><Connection /></el-icon>查看教材专题</el-button></div></div><div class="dashboard-teacher-stats"><div><strong>{{ activeTeacherAssignments.length }}</strong><span>进行中任务</span></div><div><strong>{{ dashboard?.recent_activities.length || 0 }}</strong><span>近期教学记录</span></div></div></section>
      <section class="dashboard-section dashboard-teacher-context"><div><p class="dashboard-section-kicker">当前教学内容</p><h2>{{ dashboard?.current_course?.name || '尚未选择教材专题' }}</h2><p>{{ dashboard?.current_chapter?.title || '通过教材专题组织教学任务' }}</p></div><div class="dashboard-teacher-context-status"><span></span><strong>教学组织中</strong><small>任务与专题协同</small></div></section>
      <div class="dashboard-section-heading dashboard-teacher-heading"><div><p class="dashboard-section-kicker">能力矩阵</p><h2>开展教学工作</h2></div><span>教材为主线 · AI 为辅助 · 学习有依据</span></div><section class="dashboard-teacher-links"><article v-for="item in teacherQuickLinks" :key="item.path" @click="router.push(item.path)"><el-icon :size="24"><component :is="item.icon" /></el-icon><h3>{{ item.title }}</h3><p>{{ item.description }}</p><span>立即进入 <el-icon><ArrowRight /></el-icon></span></article></section>
    </template>
  </div>
</template>

<style scoped>
.dashboard-command-center { width: 100%; max-width: 1200px; margin: 0 auto; color: var(--ink-900); }
.dashboard-student-hero, .dashboard-teacher-hero { position: relative; display: grid; overflow: hidden; min-height: 238px; border: 1px solid #f2dadd; border-radius: 14px; box-shadow: 0 10px 28px rgb(116 68 80 / 8%); }
.dashboard-student-hero { grid-template-columns: minmax(0, 1fr) 300px; padding: 30px 34px; background-color: #fff7f7; background-image: linear-gradient(90deg, rgb(255 247 247 / 98%) 0%, rgb(255 247 247 / 92%) 48%, rgb(255 247 247 / 38%) 100%), var(--dashboard-home-bg); background-position: center, right center; background-repeat: no-repeat; background-size: cover, auto 100%; }
.dashboard-hero-copy { position: relative; z-index: 1; max-width: 620px; align-self: center; }.dashboard-hero-eyebrow, .dashboard-section-kicker { margin: 0; color: var(--brand-primary); font-size: 11px; font-weight: 700; letter-spacing: .12em; }.dashboard-hero-copy h1, .dashboard-teacher-hero h1 { margin: 10px 0; color: var(--ink-900); font-size: 32px; line-height: 1.22; }.dashboard-hero-description, .dashboard-teacher-hero p:not(.dashboard-hero-eyebrow) { max-width: 520px; margin: 0; color: var(--ink-600); font-size: 14px; line-height: 1.7; }.dashboard-hero-actions { display: flex; gap: 8px; margin-top: 20px; }.dashboard-hero-actions :deep(.el-button) { margin-left: 0; }.dashboard-hero-actions :deep(.el-icon) { margin-left: 5px; }.dashboard-hero-context { display: flex; flex-direction: column; justify-content: center; align-self: stretch; min-width: 0; padding: 22px; background: rgb(255 255 255 / 80%); border: 1px solid rgb(255 255 255 / 90%); border-radius: 10px; backdrop-filter: blur(5px); }.dashboard-hero-context > span, .dashboard-hero-context small, .dashboard-hero-progress span { color: var(--ink-500); font-size: 11px; }.dashboard-hero-context strong { display: -webkit-box; overflow: hidden; margin: 7px 0 4px; color: var(--ink-900); font-size: 17px; line-height: 1.45; text-overflow: ellipsis; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.dashboard-hero-context small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.dashboard-hero-progress { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-top: auto; padding-top: 17px; border-top: 1px solid #f0e1e2; }.dashboard-hero-progress strong { margin: 0; color: var(--brand-primary); font-size: 25px; }
.dashboard-student-top-grid { display: grid; grid-template-columns: minmax(0, 1.42fr) minmax(310px, .58fr); gap: 16px; align-items: stretch; }.dashboard-student-hero { align-self: stretch; }.dashboard-student-grid { display: grid; grid-template-columns: minmax(0, 1.38fr) minmax(320px, .62fr); gap: 16px; margin-top: 16px; align-items: start; }.dashboard-main-column, .dashboard-side-column { display: grid; gap: 16px; min-width: 0; }.dashboard-section { background: var(--bg-card); border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 4px 16px rgb(76 40 49 / 4%); }.dashboard-stage-section, .dashboard-calendar-card, .dashboard-activity-card { padding: 20px; }.dashboard-section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.dashboard-section-heading h2 { display: flex; align-items: center; gap: 7px; margin: 5px 0 0; color: var(--ink-900); font-size: 19px; }.dashboard-section-heading .el-button { margin: 5px 0 0; padding: 0; }
.dashboard-stage-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }.dashboard-stage-card { position: relative; display: flex; min-width: 0; flex-direction: column; align-items: flex-start; gap: 7px; padding: 16px; color: var(--ink-600); background: #fffafb; border: 1px solid #f0dfe2; border-radius: 8px; cursor: pointer; text-align: left; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }.dashboard-stage-card:hover, .dashboard-stage-card.active { border-color: var(--brand-primary); box-shadow: 0 7px 18px rgb(255 135 135 / 14%); transform: translateY(-2px); }.dashboard-stage-card.has-output { border-top: 3px solid #4f9c72; padding-top: 14px; }.dashboard-stage-card.in-progress { border-top: 3px solid var(--brand-primary); padding-top: 14px; }.dashboard-stage-index { color: #c8a8ad; font-size: 11px; font-weight: 700; letter-spacing: .08em; }.dashboard-stage-state { position: absolute; top: 15px; right: 12px; display: inline-flex; align-items: center; gap: 3px; color: var(--brand-primary); font-size: 10px; }.dashboard-stage-card.has-output .dashboard-stage-state { color: #4f9c72; }.dashboard-stage-card strong { color: var(--ink-900); font-size: 16px; }.dashboard-stage-card small { display: -webkit-box; min-height: 38px; overflow: hidden; color: var(--ink-500); font-size: 12px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.dashboard-stage-link { display: inline-flex; align-items: center; gap: 3px; margin-top: auto; color: var(--brand-primary); font-size: 11px; font-weight: 700; }.dashboard-stage-link .el-icon { font-size: 12px; }
.dashboard-recommendation { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 15px; padding: 17px 20px; background: linear-gradient(110deg, #fff6f6, #fff); border-color: #f2dadd; }.dashboard-recommendation-icon { display: grid; width: 42px; height: 42px; place-items: center; color: #fff; background: var(--brand-primary); border-radius: 11px; font-size: 13px; font-weight: 800; box-shadow: 0 5px 12px rgb(255 135 135 / 23%); }.dashboard-recommendation-copy { min-width: 0; }.dashboard-recommendation-copy h2 { overflow: hidden; margin: 4px 0; color: var(--ink-900); font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }.dashboard-recommendation-copy > p:last-child { overflow: hidden; margin: 0; color: var(--ink-600); font-size: 12px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }.dashboard-recommendation-actions { display: flex; align-items: center; gap: 2px; }.dashboard-recommendation-actions :deep(.el-button) { margin-left: 0; white-space: nowrap; }.dashboard-recommendation-actions :deep(.el-icon) { margin-left: 4px; }
.dashboard-calendar-card { padding-bottom: 15px; }.dashboard-student-top-grid > .dashboard-calendar-card { padding: 14px 16px 12px; }.dashboard-calendar-toolbar { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; color: var(--ink-800); font-size: 13px; }.dashboard-student-top-grid .dashboard-calendar-toolbar { margin-top: 5px; }.dashboard-calendar-toolbar div { display: flex; gap: 1px; }.dashboard-calendar-toolbar :deep(.el-button) { width: 25px; height: 25px; margin-left: 0; padding: 0; color: var(--ink-500); font-size: 19px; }.dashboard-student-top-grid .dashboard-calendar-toolbar :deep(.el-button) { width: 22px; height: 22px; }.dashboard-calendar-weekdays, .dashboard-calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }.dashboard-student-top-grid .dashboard-calendar-weekdays, .dashboard-student-top-grid .dashboard-calendar-grid { gap: 1px; }.dashboard-calendar-weekdays { margin-top: 10px; color: var(--ink-400); font-size: 10px; text-align: center; }.dashboard-student-top-grid .dashboard-calendar-weekdays { margin-top: 4px; }.dashboard-calendar-grid { margin-top: 5px; }.dashboard-student-top-grid .dashboard-calendar-grid { margin-top: 2px; }.dashboard-calendar-day { position: relative; display: grid; width: 100%; aspect-ratio: 1; place-items: center; padding: 0; color: var(--ink-600); background: transparent; border: 0; border-radius: 50%; cursor: pointer; font: inherit; font-size: 11px; }.dashboard-student-top-grid .dashboard-calendar-day { height: 18px; aspect-ratio: auto; }.dashboard-calendar-day:hover, .dashboard-calendar-day.selected { color: var(--brand-primary-deep); background: var(--brand-primary-soft); }.dashboard-calendar-day.muted { color: #c9c6c8; cursor: default; }.dashboard-calendar-day.today { color: #fff; background: var(--brand-primary); font-weight: 700; }.dashboard-calendar-day.today.selected { box-shadow: 0 0 0 3px #ffe0e2; }.dashboard-calendar-day i { position: absolute; right: 24%; bottom: 12%; width: 3px; height: 3px; background: var(--color-warning); border-radius: 50%; }.dashboard-calendar-day.today i { background: #fff; }.dashboard-selected-day { margin-top: 11px; padding-top: 11px; border-top: 1px solid #f0e5e6; }.dashboard-student-top-grid .dashboard-selected-day { max-height: 52px; margin-top: 6px; padding-top: 6px; overflow: hidden; }.dashboard-selected-day-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; }.dashboard-student-top-grid .dashboard-selected-day-heading { margin-bottom: 3px; }.dashboard-selected-day-heading strong { color: var(--ink-800); font-size: 12px; }.dashboard-selected-day-heading span { color: var(--ink-400); font-size: 10px; }.dashboard-selected-day > p { margin: 8px 0 1px; color: var(--ink-400); font-size: 11px; }.dashboard-student-top-grid .dashboard-selected-day > p { margin: 5px 0 1px; }.dashboard-calendar-task { display: grid; grid-template-columns: 5px minmax(0, 1fr) auto; align-items: center; gap: 8px; width: 100%; padding: 7px 0; color: inherit; background: transparent; border: 0; cursor: pointer; text-align: left; }.dashboard-student-top-grid .dashboard-calendar-task { gap: 6px; padding: 3px 0; }.dashboard-calendar-task > span { width: 4px; height: 25px; background: #8bbf9d; border-radius: 2px; }.dashboard-student-top-grid .dashboard-calendar-task > span { height: 19px; }.dashboard-calendar-task > span.urgent { background: var(--color-warning); }.dashboard-calendar-task > span.overdue { background: var(--color-danger); }.dashboard-calendar-task div { min-width: 0; }.dashboard-calendar-task strong, .dashboard-calendar-task small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.dashboard-calendar-task strong { color: var(--ink-800); font-size: 11px; }.dashboard-calendar-task small { margin-top: 2px; color: var(--ink-400); font-size: 10px; }.dashboard-student-top-grid .dashboard-calendar-task strong { font-size: 10px; }.dashboard-student-top-grid .dashboard-calendar-task small { margin-top: 1px; font-size: 9px; }.dashboard-calendar-task > .el-icon { color: var(--ink-400); font-size: 12px; }
.dashboard-activity-card { min-height: 220px; }.dashboard-activity-count { display: grid; min-width: 23px; height: 23px; place-items: center; color: var(--brand-primary); background: var(--brand-primary-soft); border-radius: 50%; font-size: 11px; }.dashboard-activity-list { display: grid; gap: 0; margin-top: 13px; }.dashboard-activity-item { position: relative; display: grid; grid-template-columns: 9px minmax(0, 1fr); gap: 10px; padding: 10px 0; }.dashboard-activity-item:not(:last-child)::after { position: absolute; top: 23px; bottom: -2px; left: 4px; width: 1px; content: ''; background: #f1e1e3; }.dashboard-activity-dot { position: relative; z-index: 1; width: 9px; height: 9px; margin-top: 3px; background: #f6b4b8; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 0 0 1px #f6d9dc; }.dashboard-activity-item strong, .dashboard-activity-item small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.dashboard-activity-item strong { color: var(--ink-800); font-size: 12px; }.dashboard-activity-item small { margin-top: 3px; color: var(--ink-400); font-size: 10px; }.dashboard-activity-card :deep(.el-empty) { padding: 20px 0 8px; }.dashboard-activity-card :deep(.el-empty__description p) { color: var(--ink-400); font-size: 11px; }
.dashboard-teacher-hero { grid-template-columns: minmax(0, 1fr) 280px; align-items: center; padding: 30px 34px; color: #fff; background: linear-gradient(116deg, #922f45, #dc6d78 58%, #efadb0); }.dashboard-teacher-hero h1 { color: #fff; }.dashboard-teacher-hero p:not(.dashboard-hero-eyebrow), .dashboard-teacher-hero .dashboard-hero-eyebrow { color: rgb(255 255 255 / 82%); }.dashboard-teacher-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; }.dashboard-teacher-stats div { display: grid; gap: 4px; padding: 18px 16px; background: rgb(255 255 255 / 14%); border: 1px solid rgb(255 255 255 / 18%); border-radius: 9px; }.dashboard-teacher-stats strong { font-size: 28px; }.dashboard-teacher-stats span { color: rgb(255 255 255 / 76%); font-size: 11px; }.dashboard-teacher-context { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 20px; margin-top: 16px; padding: 19px 22px; }.dashboard-teacher-context h2 { margin: 5px 0 3px; font-size: 18px; }.dashboard-teacher-context p:last-child { margin: 0; color: var(--ink-600); font-size: 13px; }.dashboard-teacher-context-status { display: grid; grid-template-columns: 8px auto; align-items: center; gap: 5px 8px; min-width: 130px; padding: 10px 13px; background: var(--brand-primary-soft); border: 1px solid #f5d5d8; border-radius: 8px; }.dashboard-teacher-context-status span { width: 8px; height: 8px; background: var(--brand-primary); border-radius: 50%; }.dashboard-teacher-context-status strong { color: var(--brand-primary-deep); font-size: 12px; }.dashboard-teacher-context-status small { grid-column: 2; color: var(--ink-400); font-size: 10px; }.dashboard-teacher-heading { margin: 28px 0 13px; align-items: flex-end; }.dashboard-teacher-heading h2 { margin-top: 5px; font-size: 20px; }.dashboard-teacher-heading > span { color: var(--ink-400); font-size: 12px; }.dashboard-teacher-links { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }.dashboard-teacher-links article { padding: 18px; background: var(--bg-card); border: 1px solid var(--line); border-radius: 9px; cursor: pointer; transition: transform .18s ease, box-shadow .18s ease; }.dashboard-teacher-links article:hover { box-shadow: var(--shadow-1); transform: translateY(-2px); }.dashboard-teacher-links .el-icon { color: var(--brand-primary); }.dashboard-teacher-links h3 { margin: 13px 0 6px; font-size: 15px; }.dashboard-teacher-links p { min-height: 36px; margin: 0 0 14px; color: var(--ink-600); font-size: 12px; line-height: 1.55; }.dashboard-teacher-links article > span { display: inline-flex; align-items: center; gap: 3px; color: var(--brand-primary); font-size: 11px; font-weight: 700; }.dashboard-teacher-links article > span .el-icon { font-size: 11px; }
@media (max-width: 1023px) { .dashboard-student-top-grid { grid-template-columns: 1fr; }.dashboard-student-hero { grid-template-columns: minmax(0, 1fr) 260px; }.dashboard-student-grid { grid-template-columns: minmax(0, 1fr) 300px; }.dashboard-stage-grid { grid-template-columns: 1fr; }.dashboard-stage-card small { min-height: auto; }.dashboard-teacher-links { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 767px) { .dashboard-student-hero, .dashboard-teacher-hero { display: block; padding: 24px; background-image: linear-gradient(90deg, rgb(255 247 247 / 96%), rgb(255 247 247 / 80%)), var(--dashboard-home-bg); background-position: center, right bottom; background-size: cover, auto 55%; }.dashboard-hero-copy h1, .dashboard-teacher-hero h1 { font-size: 27px; }.dashboard-hero-context { margin-top: 20px; }.dashboard-student-grid { grid-template-columns: 1fr; }.dashboard-recommendation { grid-template-columns: 38px minmax(0, 1fr); }.dashboard-recommendation-actions { grid-column: 2; flex-wrap: wrap; justify-content: flex-start; }.dashboard-teacher-context { grid-template-columns: 1fr; }.dashboard-teacher-links { grid-template-columns: 1fr; } }
</style>

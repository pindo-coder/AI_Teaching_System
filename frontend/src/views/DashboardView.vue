<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, ChatDotRound, Collection, Connection, Document, Reading, TrendCharts } from '@element-plus/icons-vue'
import { assignmentApi, type StudentAssignment, type TeacherAssignment } from '@/api/assignments'
import { learningApi } from '@/api/learning'
import AiLearningPet from '@/components/AiLearningPet.vue'
import { useAuthStore } from '@/stores/auth'
import type { DashboardData, LearningStage } from '@/types'
import type { AiPetAction, AiPetContext } from '@/types/aiPet'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(true)
const dashboard = ref<DashboardData | null>(null)
const assignments = ref<StudentAssignment[]>([])
const teacherAssignments = ref<TeacherAssignment[]>([])
const stageLabels: Record<LearningStage, string> = { preview: '课前预习', review: '课后巩固', exam: '考前冲刺' }
const stageDescriptions: Record<LearningStage, string> = { preview: '理解章节结构，形成问题意识', review: '梳理观点逻辑，沉淀个人笔记', exam: '聚焦核心考点，完成输出训练' }
const learningStages: LearningStage[] = ['preview', 'review', 'exam']
const allPendingAssignments = computed(() => assignments.value.filter((item) => item.status !== 'completed'))
const pendingAssignments = computed(() => allPendingAssignments.value.slice(0, 3))
const activeTeacherAssignments = computed(() => teacherAssignments.value.filter((item) => item.status === 'published'))
const latestProgress = computed(() => dashboard.value?.recent_progress[0] || null)
const continuePath = computed(() => {
  const progress = latestProgress.value
  return progress ? `/courses/${progress.course_id}/chapters/${progress.chapter_id}/${progress.learning_stage}` : '/courses'
})
const petContext = computed<AiPetContext>(() => {
  const nextTask = allPendingAssignments.value[0]
  const role = auth.user?.role || 'student'
  return {
    role,
    username: auth.user?.username || '',
    chapterTitle: dashboard.value?.current_chapter?.title || null,
    learningStage: latestProgress.value?.learning_stage || null,
    progress: dashboard.value?.overall_progress || 0,
    pendingCount: auth.isTeacher ? activeTeacherAssignments.value.length : allPendingAssignments.value.length,
    overdueCount: auth.isTeacher ? 0 : allPendingAssignments.value.filter((item) => item.status === 'overdue').length,
    continuePath: continuePath.value,
    nextTask: nextTask ? { title: nextTask.title, dueTime: nextTask.due_time, path: taskPath(nextTask) } : null,
  }
})
const quickLinks = computed(() => auth.isTeacher ? [
  { title: '任务管理', description: '发布并查看学生完成情况', path: '/assignments', icon: Bell },
  { title: '教材专题', description: '管理教材与专题内容', path: '/courses', icon: Collection },
  { title: '时政要点', description: '检索权威媒体时政内容', path: '/current-affairs', icon: TrendCharts },
  { title: '课堂互动', description: '发布讨论与课堂活动', path: '/interaction', icon: ChatDotRound },
] : [
  { title: '专题目录', description: '按教材章节选择学习内容', path: '/courses', icon: Collection },
  { title: '我的笔记', description: '整理章节笔记和 AI 问答', path: '/notes', icon: Document },
  { title: '今日复习', description: '根据学习记录完成间隔复习', path: '/reviews', icon: Reading },
  { title: '时政要点', description: '把现实议题关联回教材', path: '/current-affairs', icon: TrendCharts },
])

function taskPath(task: StudentAssignment) { return `/courses/${task.course_id}/chapters/${task.chapter_id}/${task.learning_stage}` }
function stagePath(stage: LearningStage) {
  const progress = latestProgress.value
  return progress ? `/courses/${progress.course_id}/chapters/${progress.chapter_id}/${stage}` : '/courses'
}
function stageProgress(stage: LearningStage) {
  const progress = dashboard.value?.recent_progress.find((item) => item.course_id === latestProgress.value?.course_id && item.chapter_id === latestProgress.value?.chapter_id && item.learning_stage === stage)
  return progress?.progress || 0
}
function handlePetAction(action: AiPetAction) { router.push(action.path) }
function deadlineClass(task: StudentAssignment) {
  if (task.status === 'overdue') return 'overdue'
  return new Date(task.due_time).getTime() - Date.now() < 24 * 3600 * 1000 ? 'urgent' : ''
}
function dueLabel(value: string) { return new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }

onMounted(async () => {
  try {
    const requests: Promise<unknown>[] = [learningApi.dashboard().then(({ data }) => { dashboard.value = data.data })]
    if (auth.isTeacher) requests.push(assignmentApi.teacher().then(({ data }) => { teacherAssignments.value = data.data }))
    else requests.push(assignmentApi.student(false).then(({ data }) => { assignments.value = data.data }))
    await Promise.allSettled(requests)
  } finally { loading.value = false }
})
</script>

<template>
  <div v-loading="loading" class="dashboard-command-center">
    <header class="dashboard-hero dashboard-command-hero">
      <div class="dashboard-hero-copy">
        <div class="dashboard-value-line"><span></span>新时代思想 · AI {{ auth.isTeacher ? '教学' : '学习' }}驾驶舱</div>
        <h1>{{ auth.isTeacher ? '以教材为主线，让每一次教学有迹可循' : `你好，${auth.user?.username}` }}</h1>
        <p>{{ auth.isTeacher ? '围绕教材专题布置任务、组织课堂互动，并通过真实学习行为掌握教学进展。' : '从教材出发，在真实问题中理解新时代中国，让专题、任务、笔记和时政形成一条学习路径。' }}</p>
        <div class="dashboard-hero-actions">
          <el-button type="warning" size="large" @click="router.push(auth.isTeacher ? '/assignments' : continuePath)">{{ auth.isTeacher ? '布置学习任务' : latestProgress ? '继续当前专题' : '选择学习专题' }}</el-button>
          <el-button size="large" plain @click="router.push('/courses')"><el-icon><Connection /></el-icon>教材知识图谱</el-button>
        </div>
        <div class="dashboard-live-context">
          <span><small>{{ auth.isTeacher ? '当前教学内容' : '当前学习专题' }}</small><strong>{{ dashboard?.current_chapter?.title || '尚未选择专题' }}</strong></span>
          <span><small>{{ auth.isTeacher ? '进行中任务' : '待完成任务' }}</small><strong>{{ auth.isTeacher ? activeTeacherAssignments.length : allPendingAssignments.length }} 项</strong></span>
          <span><small>综合进度</small><strong>{{ dashboard?.overall_progress || 0 }}%</strong></span>
        </div>
      </div>
      <AiLearningPet :context="petContext" :loading="loading" @action="handlePetAction" />
    </header>

    <section v-if="!auth.isTeacher" class="dashboard-assignment-window" :class="{ empty: !pendingAssignments.length }">
      <div class="assignment-window-heading"><div><p class="eyebrow">教师布置 · 优先处理</p><h2><el-icon><Bell /></el-icon> 待完成任务 <span>{{ allPendingAssignments.length }}</span></h2><p>完成情况由实际学习行为自动统计，无需手动勾选。</p></div><el-button text type="primary" @click="router.push('/assignments')">查看全部任务 →</el-button></div>
      <div v-if="pendingAssignments.length" class="dashboard-assignment-list">
        <article v-for="task in pendingAssignments" :key="task.id" class="dashboard-assignment-item" :class="deadlineClass(task)">
          <div><span class="assignment-kicker">{{ task.status === 'overdue' ? '已逾期' : task.status === 'in_progress' ? '进行中' : '待开始' }} · {{ stageLabels[task.learning_stage] }}</span><h3>{{ task.title }}</h3><p>{{ task.chapter_title }} · 截止 {{ dueLabel(task.due_time) }}</p></div>
          <div class="assignment-inline-progress"><strong>{{ task.progress_value }}%</strong><el-progress :percentage="task.progress_value" :show-text="false" /></div>
          <el-button type="primary" @click="router.push(taskPath(task))">{{ task.status === 'not_started' ? '开始任务' : '继续完成' }}</el-button>
        </article>
      </div>
      <div v-else class="assignment-empty"><span>目前没有待完成的教师任务</span><el-button type="primary" plain @click="router.push('/courses')">自主选择专题学习</el-button></div>
    </section>

    <section class="dashboard-context-strip">
      <article class="dashboard-current-topic"><div><span class="dashboard-card-kicker">{{ auth.isTeacher ? '当前教学上下文' : '当前学习上下文' }}</span><h2>{{ dashboard?.current_course?.name || '《习近平新时代中国特色社会主义思想概论》' }}</h2><p>{{ dashboard?.current_chapter?.title || (auth.isTeacher ? '通过教材专题组织教学任务' : '尚未选择学习专题') }}</p></div><div class="dashboard-progress-ring" :style="{ '--dashboard-progress': `${dashboard?.overall_progress || 0}%` }"><span>{{ dashboard?.overall_progress || 0 }}%</span></div></article>
      <article class="dashboard-data-card"><span>{{ auth.isTeacher ? '进行中任务' : '待处理任务' }}</span><strong>{{ auth.isTeacher ? activeTeacherAssignments.length : allPendingAssignments.length }}</strong><small>{{ auth.isTeacher ? '进入任务管理查看完成情况' : '按截止时间优先完成' }}</small></article>
      <article class="dashboard-data-card"><span>{{ auth.isTeacher ? '教学记录' : '近期学习记录' }}</span><strong>{{ dashboard?.recent_progress.length || 0 }}</strong><small>由真实学习行为自动形成</small></article>
    </section>

    <section class="dashboard-learning-command">
      <article class="dashboard-learning-path">
        <div class="dashboard-panel-heading"><div><span class="dashboard-card-kicker">专题学习路径</span><h2>{{ auth.isTeacher ? '组织当前章节教学' : '沿着当前章节继续学习' }}</h2></div><el-button text type="primary" @click="router.push('/courses')">切换专题 →</el-button></div>
        <div class="dashboard-stage-rail">
          <button v-for="(stage, index) in learningStages" :key="stage" type="button" class="dashboard-stage-step" :class="{ active: latestProgress?.learning_stage === stage, completed: stageProgress(stage) >= 100 }" @click="router.push(stagePath(stage))">
            <span>0{{ index + 1 }}</span><strong>{{ stageLabels[stage] }}</strong><small>{{ stageDescriptions[stage] }}</small><em>{{ stageProgress(stage) }}%</em>
          </button>
        </div>
      </article>
      <article class="dashboard-ai-insight">
        <span class="dashboard-ai-mark">AI</span>
        <div><span class="dashboard-card-kicker">智能学习建议</span><h2>{{ auth.isTeacher ? '让教学任务与章节目标对齐' : '让下一步学习更明确' }}</h2><p>{{ auth.isTeacher ? '从当前专题发布阅读、AI 辅助或笔记任务，系统将自动汇总学生完成情况。' : allPendingAssignments.length ? '建议先完成教师布置的任务，再回到笔记空间整理本章认识。' : '当前没有待完成任务，可以继续专题学习或整理个人笔记。' }}</p></div>
        <el-button type="primary" @click="router.push(auth.isTeacher ? '/assignments' : allPendingAssignments.length ? '/assignments' : continuePath)">{{ auth.isTeacher ? '管理教学任务' : allPendingAssignments.length ? '查看待办任务' : '继续学习' }}</el-button>
      </article>
    </section>

    <div class="section-heading dashboard-module-heading"><div><p class="eyebrow">能力矩阵</p><h2>{{ auth.isTeacher ? '开展教学工作' : '进入学习空间' }}</h2></div><span>教材为主线 · AI 为辅助 · 学习有依据</span></div>
    <section class="dashboard-quick-grid"><article v-for="item in quickLinks" :key="item.path" @click="router.push(item.path)"><el-icon :size="27"><component :is="item.icon" /></el-icon><h3>{{ item.title }}</h3><p>{{ item.description }}</p><span>立即进入 →</span></article></section>
  </div>
</template>

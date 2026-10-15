<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, Download, Plus, Promotion, Refresh, Search, UserFilled } from '@element-plus/icons-vue'
import {
  assignmentApi,
  type AssignmentCompletionPolicy,
  type AssignmentCompletionRequirement,
  type AssignmentRecipientDetail,
  type AssignmentStudent,
  type AssignmentTaskKind,
  type StudentAssignment,
  type TeacherAssignment,
} from '@/api/assignments'
import { courseApi } from '@/api/courses'
import { aiApi } from '@/api/ai'
import { useAuthStore } from '@/stores/auth'
import type { Chapter, Course, LearningStage } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { teachingClassApi, type ClassGroup, type TeachingClass } from '@/api/teachingClasses'
import { beijingDateTimeLocalValue, beijingLocalToUtcIso, beijingTimestamp, formatBeijingTime } from '@/utils/time'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const loading = ref(true)
const studentTasks = ref<StudentAssignment[]>([])
const teacherTasks = ref<TeacherAssignment[]>([])
const courses = ref<Course[]>([])
const chapters = ref<Chapter[]>([])
const students = ref<AssignmentStudent[]>([])
const teachingClasses = ref<TeachingClass[]>([])
const groups = ref<ClassGroup[]>([])
const dialogVisible = ref(false)
const publishing = ref(false)
const agentExecutionId = ref<number | undefined>()
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailRefreshing = ref(false)
const policyDialogVisible = ref(false)
const policySaving = ref(false)
const requirementDetailVisible = ref(false)
const requirementDetailTask = ref<StudentAssignment | null>(null)
const selectedTask = ref<TeacherAssignment | null>(null)
const taskRecipients = ref<AssignmentRecipientDetail[]>([])
const recipientKeyword = ref('')
const recipientStatus = ref<'all' | 'unfinished' | AssignmentRecipientDetail['status']>('all')
let detailRefreshTimer: number | undefined
const form = reactive({
  teaching_class_id: null as number | null,
  course_id: null as number | null,
  chapter_id: null as number | null,
  learning_stage: 'preview' as LearningStage,
  task_kind: 'reading' as AssignmentTaskKind,
  title: '', description: '', due_time: '',
  target_scope: 'all_students' as 'all_students' | 'selected_students' | 'selected_groups',
  student_ids: [] as number[],
  group_ids: [] as number[],
  requirement_keys: ['reading'] as string[],
  requirement_targets: { reading: 80, ai: 1, note: 30, quiz: 1, discussion: 1, reply: 1, activity: 1 } as Record<string, number>,
  rubric: { items: [] as Array<{ label: string; weight: number; description: string }>, feedback_template: '' },
})
const stageLabels: Record<LearningStage, string> = { preview: '课前预习', review: '课后巩固', exam: '考前冲刺' }
const kindLabels: Record<AssignmentTaskKind, string> = { reading: '教材阅读', ai_assist: 'AI 学习辅助', note: '章节笔记', composite: '组合任务' }
const requirementOptions = [
  { key: 'reading', label: '阅读教材原文', event: 'reading_progress', metric: 'percent', target: 80, unit: '%', stage: 'assignment' },
  { key: 'ai', label: '使用 AI 学习辅助', event: 'ai_assist_used', metric: 'count', target: 1, unit: '次', stage: 'any' },
  { key: 'note', label: '保存个人笔记', event: 'note_saved', metric: 'length', target: 30, unit: '字', stage: 'any' },
  { key: 'quiz', label: '完成复习练习', event: 'quiz_completed', metric: 'count', target: 1, unit: '次', stage: 'any' },
  { key: 'discussion', label: '发布讨论主题', event: 'discussion_created', metric: 'count', target: 1, unit: '次', stage: 'any' },
  { key: 'reply', label: '回复课堂讨论', event: 'discussion_reply_created', metric: 'count', target: 1, unit: '次', stage: 'any' },
  { key: 'activity', label: '提交课堂活动', event: 'activity_submitted', metric: 'count', target: 1, unit: '次', stage: 'any' },
] as const
const policyRequirementKeys = ref<string[]>([])
const policyRequirementTargets = reactive<Record<string, number>>({})
const activeTeacherTasks = computed(() => teacherTasks.value.filter((item) => item.status === 'published'))
const filteredRecipients = computed(() => {
  const keyword = recipientKeyword.value.trim().toLowerCase()
  return taskRecipients.value.filter((item) => {
    const matchesStatus = recipientStatus.value === 'all'
      || (recipientStatus.value === 'unfinished' && item.status !== 'completed')
      || item.status === recipientStatus.value
    const matchesKeyword = !keyword || [item.username, item.identity_no, item.group_name]
      .some((value) => value?.toLowerCase().includes(keyword))
    return matchesStatus && matchesKeyword
  })
})
const recipientCounts = computed(() => ({
  total: taskRecipients.value.length,
  completed: taskRecipients.value.filter((item) => item.status === 'completed').length,
  unfinished: taskRecipients.value.filter((item) => item.status !== 'completed').length,
  overdue: taskRecipients.value.filter((item) => item.status === 'overdue').length,
}))

function taskPath(task: StudentAssignment) { return task.next_path || `/courses/${task.course_id}/chapters/${task.chapter_id}/${task.learning_stage}` }
function formatTime(value: string) { return formatBeijingTime(value, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
function statusLabel(status: StudentAssignment['status']) { return status === 'completed' ? '已完成' : status === 'overdue' ? '已逾期' : status === 'in_progress' ? '进行中' : '未开始' }
function statusTagType(status: AssignmentRecipientDetail['status']) {
  return status === 'completed' ? 'success' : status === 'overdue' ? 'danger' : status === 'in_progress' ? 'warning' : 'primary'
}
function formatActivityTime(value: string | null) {
  return value ? formatTime(value) : '暂无学习记录'
}
function deadlineClass(task: StudentAssignment) {
  if (task.status === 'completed') return 'completed'
  if (task.status === 'overdue') return 'overdue'
  return beijingTimestamp(task.due_time) - Date.now() < 24 * 3600 * 1000 ? 'urgent' : ''
}
function completedRequirementCount(task: StudentAssignment) {
  return task.requirements.filter((item) => item.status === 'completed').length
}
function nextRequirement(task: StudentAssignment) {
  return task.requirements.find((item) => item.status !== 'completed')
}
function openRequirementDetails(task: StudentAssignment) {
  requirementDetailTask.value = task
  requirementDetailVisible.value = true
}
async function load() {
  loading.value = true
  try {
    if (auth.isTeacher) {
      const [taskResponse, courseResponse, classResponse] = await Promise.all([assignmentApi.teacher(), courseApi.list(), teachingClassApi.list()])
      teacherTasks.value = taskResponse.data.data
      courses.value = courseResponse.data.data
      teachingClasses.value = classResponse.data.data.filter((item) => item.status !== 'archived')
    } else studentTasks.value = (await assignmentApi.student(true)).data.data
  } finally { loading.value = false }
}
async function loadChapters() {
  form.chapter_id = null
  chapters.value = form.course_id ? (await courseApi.detail(form.course_id)).data.data.chapters : []
}
watch(() => form.course_id, () => void loadChapters())
watch(() => form.teaching_class_id, async (classId) => {
  form.student_ids = []; form.group_ids = []
  const selected = teachingClasses.value.find((item) => item.id === classId)
  if (selected && !selected.material_ids.includes(form.course_id || -1)) form.course_id = selected.primary_course_id
  if (classId) {
    const [studentResponse, groupResponse] = await Promise.all([assignmentApi.students(classId), teachingClassApi.groups(classId)])
    students.value = studentResponse.data.data; groups.value = groupResponse.data.data
  } else { students.value = []; groups.value = [] }
})
function buildCompletionPolicy(keys: string[], targets: Record<string, number>): AssignmentCompletionPolicy {
  const selected = requirementOptions.filter((item) => keys.includes(item.key))
  const baseWeight = Math.floor(100 / selected.length)
  const remainder = 100 - baseWeight * selected.length
  return {
    mode: 'all_required',
    items: selected.map((item, index) => ({
      key: item.key,
      label: item.label,
      event: item.event,
      metric: item.metric,
      target: Math.max(1, Number(targets[item.key] || item.target)),
      weight: baseWeight + (index < remainder ? 1 : 0),
      required: true,
      stage: item.stage,
      task_types: [],
    } as AssignmentCompletionRequirement)),
  }
}
function syncTaskKind() {
  const keys = form.requirement_keys
  form.task_kind = keys.length > 1 ? 'composite' : keys[0] === 'ai' ? 'ai_assist' : keys[0] === 'note' ? 'note' : keys[0] === 'reading' ? 'reading' : 'composite'
}
watch(() => form.requirement_keys.slice(), syncTaskKind)
function openCreate() {
  dialogVisible.value = true
  if (teachingClasses.value.length && !form.teaching_class_id) form.teaching_class_id = teachingClasses.value[0].id
  const selected = teachingClasses.value.find((item) => item.id === form.teaching_class_id)
  if (selected && !form.course_id) form.course_id = selected.primary_course_id
  if (!form.due_time) {
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000)
    form.due_time = beijingDateTimeLocalValue(tomorrow)
  }
}
async function publish() {
  if (!form.teaching_class_id || !form.course_id || !form.chapter_id || !form.title.trim() || !form.due_time) return ElMessage.warning('请完整填写教学班、教材、章节、任务名称和截止时间')
  if (form.target_scope === 'selected_students' && !form.student_ids.length) return ElMessage.warning('请选择至少一名学生')
  if (form.target_scope === 'selected_groups' && !form.group_ids.length) return ElMessage.warning('请选择至少一个学习小组')
  if (!form.requirement_keys.length) return ElMessage.warning('请至少选择一个可验证的完成条件')
  const dueTime = beijingLocalToUtcIso(form.due_time)
  if (!dueTime) return ElMessage.warning('请选择有效的截止时间')
  const executionId = agentExecutionId.value
  publishing.value = true
  try {
    await assignmentApi.create({
      ...form,
      agent_execution_id: executionId,
      course_id: form.course_id,
      chapter_id: form.chapter_id,
      due_time: dueTime,
      completion_policy: buildCompletionPolicy(form.requirement_keys, form.requirement_targets),
    })
    await finishAgentPublish()
  } catch (error: unknown) {
    // A timed-out response or another tab's submission may already have saved
    // the assignment. Confirm the durable result instead of publishing again.
    if (executionId) {
      try {
        const execution = (await aiApi.workspaceAgentExecution(executionId)).data.data
        if (execution.result.saved_resources?.some((item) => item.kind === 'assignment')) {
          await finishAgentPublish()
          return
        }
      } catch { /* Keep the editable draft when the saved result is unknown. */ }
    }
    ElMessage.error(getErrorMessage(error, '发布结果尚未确认，请核对任务列表后再试'))
  }
  finally { publishing.value = false }
}
async function finishAgentPublish() {
  dialogVisible.value = false
  agentExecutionId.value = undefined
  window.dispatchEvent(new Event('agent-handoff-saved'))
  form.title = ''; form.description = ''; form.student_ids = []; form.group_ids = []; form.rubric = { items: [], feedback_template: '' }
  // A list refresh failure must not turn a successful publish into "failed".
  try { await load() } catch { ElMessage.warning('发布已成功，任务列表暂未刷新，请稍后刷新查看') }
  ElMessage.success('学习任务已发布')
}
async function applyAgentDraft() {
  const encoded = route.query.agent_draft
  if (!encoded || typeof encoded !== 'string' || !auth.isTeacher) return
  try {
    const payload = JSON.parse(decodeURIComponent(encoded)) as {
      draft?: Partial<typeof form> | null
      rubric?: typeof form.rubric | null
      execution_id?: number
    }
    if (payload.draft) {
      Object.assign(form, payload.draft)
      for (const option of requirementOptions) {
        if (!form.requirement_targets[option.key]) form.requirement_targets[option.key] = option.target
      }
      const legacyKind = payload.draft.task_kind
      if (legacyKind === 'reading') form.requirement_keys = ['reading']
      if (legacyKind === 'ai_assist') form.requirement_keys = ['ai']
      if (legacyKind === 'note') form.requirement_keys = ['note']
    }
    if (payload.rubric) form.rubric = payload.rubric
    agentExecutionId.value = payload.draft ? payload.execution_id : undefined
    await nextTick()
    if (payload.draft?.chapter_id) form.chapter_id = payload.draft.chapter_id
    openCreate()
    ElMessage.success(payload.rubric ? '已带入 Agent 量规草案，请确认后发布' : '已带入 Agent 任务草案，请确认后发布')
    void router.replace({ path: '/assignments', query: {} })
  } catch {
    ElMessage.warning('Agent 草案读取失败，请重新生成')
  }
}
async function cancelTask(task: TeacherAssignment) {
  await ElMessageBox.confirm(`撤回“${task.title}”后，学生端将不再显示该任务。`, '撤回任务', { type: 'warning' })
  await assignmentApi.cancel(task.id)
  await load()
  ElMessage.success('任务已撤回')
}
function stopDetailRefresh() {
  if (detailRefreshTimer !== undefined) window.clearInterval(detailRefreshTimer)
  detailRefreshTimer = undefined
}
async function loadRecipientDetails(silent = false) {
  if (!selectedTask.value) return
  if (silent) detailRefreshing.value = true
  else detailLoading.value = true
  try {
    taskRecipients.value = (await assignmentApi.recipients(selectedTask.value.id)).data.data
  } catch (error: unknown) {
    if (!silent) ElMessage.error(getErrorMessage(error, '任务完成详情加载失败'))
  } finally {
    detailLoading.value = false
    detailRefreshing.value = false
  }
}
async function openTaskDetails(task: TeacherAssignment) {
  selectedTask.value = task
  recipientKeyword.value = ''
  recipientStatus.value = 'all'
  detailVisible.value = true
  await loadRecipientDetails()
}
function openPolicyEditor(task: TeacherAssignment) {
  selectedTask.value = task
  const items = task.completion_policy?.items || []
  policyRequirementKeys.value = items.length ? items.map((item) => item.key) : [
    task.task_kind === 'ai_assist' ? 'ai' : task.task_kind === 'note' ? 'note' : 'reading',
  ]
  for (const option of requirementOptions) {
    policyRequirementTargets[option.key] = items.find((item) => item.key === option.key)?.target || option.target
  }
  policyDialogVisible.value = true
}
async function saveCompletionPolicy() {
  if (!selectedTask.value) return
  if (!policyRequirementKeys.value.length) return ElMessage.warning('请至少选择一个完成条件')
  policySaving.value = true
  try {
    await assignmentApi.updateCompletionPolicy(
      selectedTask.value.id,
      buildCompletionPolicy(policyRequirementKeys.value, policyRequirementTargets),
    )
    policyDialogVisible.value = false
    await load()
    ElMessage.success('完成条件已更新，所有学生进度已重新统计')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '完成条件更新失败'))
  } finally {
    policySaving.value = false
  }
}
function csvCell(value: string | number | null) {
  let text = value === null ? '' : String(value)
  if (/^[=+\-@]/.test(text)) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}
function exportUnfinishedRecipients() {
  if (!selectedTask.value) return
  const rows = taskRecipients.value.filter((item) => item.status !== 'completed')
  if (!rows.length) return ElMessage.info('当前没有未完成学生')
  const content = [
    ['姓名', '学号', '小组', '状态', '完成进度', '最后学习时间'],
    ...rows.map((item) => [
      item.username,
      item.identity_no || '',
      item.group_name || '',
      statusLabel(item.status),
      `${item.progress_value}%`,
      formatActivityTime(item.last_activity_time),
    ]),
  ].map((row) => row.map(csvCell).join(',')).join('\r\n')
  const blob = new Blob([`\uFEFF${content}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${selectedTask.value.title.replace(/[\\/:*?"<>|]/g, '_')}-未完成名单.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
watch(detailVisible, (visible) => {
  stopDetailRefresh()
  if (visible) detailRefreshTimer = window.setInterval(() => void loadRecipientDetails(true), 30_000)
})
function refreshLearningEvidence() {
  if (!auth.isTeacher) void load().catch(() => ElMessage.warning('任务进度刷新失败，可重新进入页面查看'))
}
onMounted(async () => {
  window.addEventListener('learning-evidence-updated', refreshLearningEvidence)
  await load(); await applyAgentDraft()
})
watch(() => route.query.agent_draft, (value) => { if (value) void applyAgentDraft() })
onBeforeUnmount(() => {
  stopDetailRefresh()
  window.removeEventListener('learning-evidence-updated', refreshLearningEvidence)
})
</script>

<template>
  <div v-loading="loading" class="assignment-page">
    <header class="page-header"><div><p class="eyebrow">{{ auth.isTeacher ? '教学任务管理' : '我的学习任务' }}</p><h1>{{ auth.isTeacher ? '布置并跟踪学习任务' : '按时完成教师布置的任务' }}</h1><p>{{ auth.isTeacher ? '任务与教材章节关联，学生完成指定学习产出后自动更新进度。' : '任务进度由阅读、AI学习、笔记和练习等实际行为自动统计。' }}</p></div><el-button v-if="auth.isTeacher" type="primary" size="large" :icon="Plus" @click="openCreate">发布任务</el-button></header>

    <template v-if="!auth.isTeacher">
      <section class="student-assignment-list">
        <article v-for="task in studentTasks" :key="task.id" class="student-assignment-card" :class="deadlineClass(task)">
          <div class="student-task-content">
            <div class="assignment-status-line"><el-tag :type="task.status === 'completed' ? 'success' : task.status === 'overdue' ? 'danger' : task.status === 'in_progress' ? 'warning' : 'primary'">{{ statusLabel(task.status) }}</el-tag><span>{{ stageLabels[task.learning_stage] }} · {{ kindLabels[task.task_kind] }}</span></div>
            <h2>{{ task.title }}</h2>
            <p class="student-task-description">{{ task.description || `完成“${task.chapter_title}”相关学习任务。` }}</p>
            <div class="assignment-meta"><span>{{ task.course_name }} · {{ task.chapter_title }}</span><strong>截止 {{ formatTime(task.due_time) }}</strong><span>教师：{{ task.teacher_name }}</span></div>
          </div>
          <div class="student-task-progress">
            <div class="student-task-progress-heading"><span>任务进度</span><strong>{{ task.progress_value }}%</strong></div>
            <el-progress :percentage="task.progress_value" :status="task.status === 'completed' ? 'success' : undefined" :show-text="false" />
            <button v-if="task.requirements.length" class="requirement-summary" type="button" @click="openRequirementDetails(task)">
              <span><strong>{{ completedRequirementCount(task) }}/{{ task.requirements.length }}</strong> 项完成条件已达标</span>
              <em>查看详情</em>
            </button>
            <small v-if="nextRequirement(task)" class="next-requirement">下一项：{{ nextRequirement(task)?.evidence_summary }}</small>
            <small v-else-if="task.requirements.length" class="next-requirement completed">全部完成条件均已达标</small>
          </div>
          <div class="student-task-action">
            <el-button v-if="task.status !== 'completed'" type="primary" :icon="Promotion" @click="router.push(taskPath(task))">{{ task.status === 'not_started' ? '开始任务' : '继续完成' }}</el-button>
            <el-button v-else plain @click="openRequirementDetails(task)">完成详情</el-button>
          </div>
        </article>
        <el-empty v-if="!studentTasks.length" description="目前没有教师布置的学习任务" />
      </section>
    </template>

    <template v-else>
      <section class="teacher-assignment-summary"><div><strong>{{ activeTeacherTasks.length }}</strong><span>进行中的任务</span></div><div><strong>{{ activeTeacherTasks.reduce((sum, item) => sum + item.total_count, 0) }}</strong><span>任务接收人次</span></div><div><strong>{{ activeTeacherTasks.reduce((sum, item) => sum + item.completed_count, 0) }}</strong><span>已完成人次</span></div><div><strong>{{ activeTeacherTasks.reduce((sum, item) => sum + item.overdue_count, 0) }}</strong><span>逾期人次</span></div></section>
      <section class="teacher-assignment-list">
        <el-card v-for="task in teacherTasks" :key="task.id" shadow="never" class="teacher-assignment-card" :class="{ cancelled: task.status === 'cancelled' }">
          <div class="assignment-status-line"><el-tag :type="task.status === 'published' ? 'success' : 'info'">{{ task.status === 'published' ? '已发布' : '已撤回' }}</el-tag><span>{{ stageLabels[task.learning_stage] }} · {{ kindLabels[task.task_kind] }}</span></div>
          <h2>{{ task.title }}</h2><p>{{ task.course_name }} · {{ task.chapter_title }}</p><p class="muted">{{ task.description || '未填写补充要求' }}</p>
          <div v-if="task.completion_policy?.items.length" class="teacher-policy-tags"><span v-for="item in task.completion_policy.items" :key="item.key">{{ item.label }} ≥ {{ item.target }}{{ item.metric === 'percent' ? '%' : item.metric === 'length' ? '字' : '次' }}</span></div>
          <div class="teacher-task-metrics"><span>完成 <strong>{{ task.completed_count }}/{{ task.total_count }}</strong></span><span>进行中 <strong>{{ task.in_progress_count }}</strong></span><span>逾期 <strong>{{ task.overdue_count }}</strong></span><span><el-icon><Calendar /></el-icon> {{ formatTime(task.due_time) }}</span></div>
          <div class="teacher-task-actions">
            <el-button :icon="UserFilled" type="primary" plain @click="openTaskDetails(task)">查看完成详情</el-button>
            <el-button v-if="task.status === 'published'" @click="openPolicyEditor(task)">调整完成条件</el-button>
            <el-button v-if="task.status === 'published'" type="danger" plain @click="cancelTask(task)">撤回任务</el-button>
          </div>
        </el-card>
        <el-empty v-if="!teacherTasks.length" description="尚未发布学习任务" />
      </section>
    </template>

    <el-dialog v-model="requirementDetailVisible" title="任务完成详情" width="min(620px, 92vw)" class="student-requirement-dialog">
      <div v-if="requirementDetailTask" class="student-requirement-detail">
        <header>
          <div><strong>{{ requirementDetailTask.title }}</strong><span>{{ requirementDetailTask.course_name }} · {{ requirementDetailTask.chapter_title }}</span></div>
          <b>{{ requirementDetailTask.progress_value }}%</b>
        </header>
        <div class="assignment-requirements">
          <div v-for="item in requirementDetailTask.requirements" :key="item.key" class="assignment-requirement" :class="item.status">
            <span class="requirement-mark">{{ item.status === 'completed' ? '✓' : item.status === 'in_progress' ? '◐' : '○' }}</span>
            <div><strong>{{ item.label }}</strong><small>{{ item.evidence_summary }}</small></div>
            <span>{{ item.progress_value }}%</span>
          </div>
        </div>
      </div>
      <template #footer><el-button @click="requirementDetailVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" title="发布学习任务" width="680px">
      <el-form label-position="top" class="assignment-form">
        <el-form-item label="所属教学班"><el-select v-model="form.teaching_class_id" style="width:100%" placeholder="任务必须发布到具体教学班"><el-option v-for="item in teachingClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" /></el-select></el-form-item>
        <div class="assignment-form-grid"><el-form-item label="教材"><el-select v-model="form.course_id" style="width:100%"><el-option v-for="course in courses.filter((item) => teachingClasses.find((klass) => klass.id === form.teaching_class_id)?.material_ids.includes(item.id))" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item><el-form-item label="专题章节"><el-select v-model="form.chapter_id" filterable style="width:100%"><el-option v-for="chapter in chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item></div>
        <el-form-item label="学习阶段"><el-select v-model="form.learning_stage" style="width:100%"><el-option label="课前预习" value="preview" /><el-option label="课后巩固" value="review" /><el-option label="考前冲刺" value="exam" /></el-select></el-form-item>
        <el-form-item label="完成条件（所选项目全部达标后任务才完成）">
          <el-checkbox-group v-model="form.requirement_keys" class="requirement-picker">
            <label v-for="item in requirementOptions" :key="item.key" class="requirement-picker-item">
              <el-checkbox :value="item.key">{{ item.label }}</el-checkbox>
              <span v-if="form.requirement_keys.includes(item.key)" class="requirement-target">达到 <el-input-number v-model="form.requirement_targets[item.key]" :min="1" :max="item.metric === 'percent' ? 100 : 30000" size="small" controls-position="right" /> {{ item.unit }}</span>
            </label>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="任务名称"><el-input v-model="form.title" maxlength="160" show-word-limit placeholder="例如：完成第十七章课后巩固" /></el-form-item>
        <el-form-item label="任务要求"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="3000" show-word-limit placeholder="说明学习重点和具体要求" /></el-form-item>
        <section v-if="form.rubric.items.length" class="assignment-rubric-editor">
          <div class="assignment-rubric-heading"><strong>Agent 生成的批改量规（发布前确认）</strong><span>总权重：{{ form.rubric.items.reduce((sum, item) => sum + Number(item.weight || 0), 0) }}%</span></div>
          <div v-for="(item, index) in form.rubric.items" :key="index" class="assignment-rubric-row">
            <el-input v-model="item.label" placeholder="评分维度" />
            <el-input-number v-model="item.weight" :min="0" :max="100" controls-position="right" />
            <el-input v-model="item.description" placeholder="评分说明" />
          </div>
          <el-form-item label="反馈模板"><el-input v-model="form.rubric.feedback_template" type="textarea" :rows="2" /></el-form-item>
        </section>
        <div class="assignment-form-grid"><el-form-item label="截止时间"><el-date-picker v-model="form.due_time" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width:100%" /></el-form-item><el-form-item label="发布对象"><el-radio-group v-model="form.target_scope"><el-radio-button value="all_students">全班</el-radio-button><el-radio-button value="selected_groups">指定小组</el-radio-button><el-radio-button value="selected_students">指定学生</el-radio-button></el-radio-group></el-form-item></div>
        <el-form-item v-if="form.target_scope === 'selected_students'" label="选择学生"><el-select v-model="form.student_ids" multiple filterable collapse-tags style="width:100%"><el-option v-for="student in students" :key="student.id" :label="`${student.username}${student.identity_no ? ` · ${student.identity_no}` : ''}`" :value="student.id" /></el-select></el-form-item>
        <el-form-item v-if="form.target_scope === 'selected_groups'" label="选择学习小组"><el-select v-model="form.group_ids" multiple collapse-tags style="width:100%"><el-option v-for="group in groups" :key="group.id" :label="`${group.name}（${group.user_ids.length}人）`" :value="group.id" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="publishing" @click="publish">发布任务</el-button></template>
    </el-dialog>

    <el-dialog v-model="policyDialogVisible" title="调整任务完成条件" width="620px">
      <p class="policy-dialog-tip">保存后会按真实学习记录重新统计所有学生进度；任务描述本身不再作为完成依据。</p>
      <el-checkbox-group v-model="policyRequirementKeys" class="requirement-picker">
        <label v-for="item in requirementOptions" :key="item.key" class="requirement-picker-item">
          <el-checkbox :value="item.key">{{ item.label }}</el-checkbox>
          <span v-if="policyRequirementKeys.includes(item.key)" class="requirement-target">达到 <el-input-number v-model="policyRequirementTargets[item.key]" :min="1" :max="item.metric === 'percent' ? 100 : 30000" size="small" controls-position="right" /> {{ item.unit }}</span>
        </label>
      </el-checkbox-group>
      <template #footer><el-button @click="policyDialogVisible = false">取消</el-button><el-button type="primary" :loading="policySaving" @click="saveCompletionPolicy">保存并重新统计</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" size="min(920px, 96vw)" class="assignment-detail-drawer">
      <template #header>
        <div class="assignment-detail-heading">
          <span class="assignment-detail-kicker">任务完成详情</span>
          <strong>{{ selectedTask?.title }}</strong>
          <small>{{ selectedTask?.course_name }} · {{ selectedTask?.chapter_title }} · 每 30 秒自动更新</small>
        </div>
      </template>
      <div v-loading="detailLoading" class="assignment-detail-body">
        <section class="recipient-summary">
          <button :class="{ active: recipientStatus === 'all' }" @click="recipientStatus = 'all'"><strong>{{ recipientCounts.total }}</strong><span>全部学生</span></button>
          <button :class="{ active: recipientStatus === 'unfinished' }" @click="recipientStatus = 'unfinished'"><strong>{{ recipientCounts.unfinished }}</strong><span>未完成</span></button>
          <button :class="{ active: recipientStatus === 'completed' }" @click="recipientStatus = 'completed'"><strong>{{ recipientCounts.completed }}</strong><span>已完成</span></button>
          <button :class="{ active: recipientStatus === 'overdue' }" @click="recipientStatus = 'overdue'"><strong>{{ recipientCounts.overdue }}</strong><span>已逾期</span></button>
        </section>
        <div class="recipient-toolbar">
          <el-input v-model="recipientKeyword" :prefix-icon="Search" clearable placeholder="搜索姓名、学号或小组" />
          <div>
            <el-button :icon="Refresh" :loading="detailRefreshing" @click="loadRecipientDetails(true)">刷新</el-button>
            <el-button :icon="Download" @click="exportUnfinishedRecipients">导出未完成名单</el-button>
          </div>
        </div>
        <el-table :data="filteredRecipients" stripe class="recipient-table">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div v-if="row.requirements.length" class="recipient-requirements">
                <div v-for="item in row.requirements" :key="item.key"><el-tag size="small" :type="item.status === 'completed' ? 'success' : item.status === 'in_progress' ? 'warning' : 'info'">{{ item.status === 'completed' ? '已完成' : item.status === 'in_progress' ? '进行中' : '未开始' }}</el-tag><strong>{{ item.label }}</strong><span>{{ item.evidence_summary }}</span></div>
              </div>
              <p v-else class="recipient-privacy-note">该历史任务沿用原有单项统计规则。</p>
            </template>
          </el-table-column>
          <el-table-column label="学生" min-width="150">
            <template #default="{ row }"><div class="recipient-student"><strong>{{ row.username }}</strong><span>{{ row.identity_no || '未填写学号' }}</span></div></template>
          </el-table-column>
          <el-table-column prop="group_name" label="小组" min-width="110">
            <template #default="{ row }">{{ row.group_name || '未分组' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }"><el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="进度" min-width="160">
            <template #default="{ row }"><el-progress :percentage="row.progress_value" :status="row.status === 'completed' ? 'success' : undefined" /></template>
          </el-table-column>
          <el-table-column label="最后学习时间" min-width="150">
            <template #default="{ row }">{{ formatActivityTime(row.last_activity_time) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!detailLoading && !filteredRecipients.length" description="没有符合当前条件的学生" />
        <p class="recipient-privacy-note">仅展示任务完成依据与进度，不展示学生私人笔记正文或 AI 对话内容。</p>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.student-assignment-card {
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px) 116px;
  height: 220px;
  min-height: 220px;
  align-items: stretch;
  overflow: hidden;
}

.student-task-content,
.student-task-progress,
.student-task-action {
  min-width: 0;
}

.student-task-content {
  display: flex;
  flex-direction: column;
}

.student-task-content h2 {
  margin: 10px 0 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.student-task-description {
  display: -webkit-box;
  min-height: 42px;
  overflow: hidden;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.student-task-content .assignment-meta {
  margin-top: auto;
}

.student-task-content .assignment-meta span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.student-task-progress {
  display: flex;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  border-right: 1px solid var(--line-soft);
  border-left: 1px solid var(--line-soft);
}

.student-task-progress-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--ink-400);
  font-size: var(--fs-meta);
}

.student-task-progress-heading strong {
  color: var(--ink-700);
  font-size: 18px;
}

.requirement-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  width: 100%;
  margin-top: 4px;
  padding: 9px 11px;
  color: var(--ink-500);
  background: var(--bg-page);
  border: 0;
  border-radius: var(--radius-input);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.requirement-summary:hover {
  background: var(--blue-50);
}

.requirement-summary strong {
  color: var(--ink-800);
}

.requirement-summary em {
  flex: 0 0 auto;
  color: var(--blue-600);
  font-size: var(--fs-meta);
  font-style: normal;
}

.next-requirement {
  overflow: hidden;
  color: var(--ink-400);
  font-size: var(--fs-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.next-requirement.completed {
  color: var(--green-600, #16a36a);
}

.student-task-action {
  display: flex;
  align-items: center;
  justify-content: center;
}

.student-task-action .el-button {
  width: 100%;
  margin: 0;
}

.student-requirement-detail {
  display: grid;
  gap: var(--space-4);
}

.student-requirement-detail > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3);
  background: var(--bg-page);
  border-radius: var(--radius-input);
}

.student-requirement-detail > header div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.student-requirement-detail > header strong,
.student-requirement-detail > header span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.student-requirement-detail > header span {
  color: var(--ink-400);
  font-size: var(--fs-meta);
}

.student-requirement-detail > header b {
  color: var(--green-600, #16a36a);
  font-size: 24px;
}

.assignment-requirements,
.recipient-requirements,
.requirement-picker {
  display: grid;
  gap: var(--space-2);
}

.assignment-requirements {
  padding: var(--space-3) 0;
  border-top: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line-soft);
}

.assignment-requirement {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-500);
}

.assignment-requirement.completed,
.assignment-requirement.completed .requirement-mark {
  color: var(--green-600, #16a36a);
}

.assignment-requirement div,
.assignment-requirement small {
  display: grid;
}

.assignment-requirement small {
  margin-top: 2px;
  color: var(--ink-400);
  font-weight: var(--fw-regular);
}

.requirement-picker-item {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-page);
  border-radius: var(--radius-input);
}

.requirement-target {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-500);
  font-size: var(--fs-meta);
}

.requirement-target .el-input-number {
  width: 100px;
}

.teacher-policy-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.teacher-policy-tags span {
  padding: 4px 9px;
  color: var(--blue-700);
  background: var(--blue-50);
  border-radius: 999px;
  font-size: var(--fs-meta);
}

.policy-dialog-tip {
  margin: 0 0 var(--space-3);
  color: var(--ink-500);
}

.recipient-requirements {
  padding: var(--space-3) var(--space-6);
}

.recipient-requirements > div {
  display: grid;
  grid-template-columns: 72px 150px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-3);
}

.recipient-requirements span {
  color: var(--ink-400);
}

.teacher-task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.assignment-detail-heading {
  display: grid;
  min-width: 0;
  gap: 3px;
  padding-right: var(--space-6);
}

.assignment-detail-heading strong {
  color: var(--ink-900);
  font-size: 18px;
  overflow-wrap: anywhere;
}

.assignment-detail-heading small {
  color: var(--ink-400);
}

.assignment-detail-kicker {
  color: var(--blue-600);
  font-size: var(--fs-meta);
  font-weight: var(--fw-bold);
  letter-spacing: .08em;
}

.assignment-detail-body {
  display: grid;
  gap: var(--space-4);
}

.recipient-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-2);
}

.recipient-summary button {
  display: grid;
  gap: 3px;
  padding: var(--space-3);
  color: var(--ink-600);
  background: var(--bg-page);
  border: 1px solid transparent;
  border-radius: var(--radius-input);
  cursor: pointer;
  text-align: left;
}

.recipient-summary button:hover,
.recipient-summary button.active {
  color: var(--blue-800);
  background: var(--blue-50);
  border-color: var(--blue-200);
}

.recipient-summary strong {
  font-size: 22px;
}

.recipient-summary span {
  font-size: var(--fs-meta);
}

.recipient-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.recipient-toolbar > .el-input {
  max-width: 340px;
}

.recipient-toolbar > div {
  display: flex;
  gap: var(--space-2);
}

.recipient-student {
  display: grid;
  gap: 2px;
}

.recipient-student span,
.recipient-privacy-note {
  color: var(--ink-400);
  font-size: var(--fs-meta);
}

.recipient-privacy-note {
  margin: 0;
  padding: var(--space-3);
  background: var(--bg-page);
  border-radius: var(--radius-input);
}

@media (max-width: 767px) {
  .student-assignment-card {
    grid-template-columns: 1fr;
    height: auto;
    min-height: 0;
  }

  .student-task-progress {
    padding: var(--space-3) 0;
    border-top: 1px solid var(--line-soft);
    border-right: 0;
    border-bottom: 1px solid var(--line-soft);
    border-left: 0;
  }

  .recipient-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .recipient-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .recipient-toolbar > .el-input {
    max-width: none;
  }

  .recipient-toolbar > div {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .recipient-toolbar .el-button {
    width: 100%;
    margin: 0;
  }
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, Download, Plus, Promotion, Refresh, Search, UserFilled } from '@element-plus/icons-vue'
import {
  assignmentApi,
  type AssignmentRecipientDetail,
  type AssignmentStudent,
  type AssignmentTaskKind,
  type StudentAssignment,
  type TeacherAssignment,
} from '@/api/assignments'
import { courseApi } from '@/api/courses'
import { useAuthStore } from '@/stores/auth'
import type { Chapter, Course, LearningStage } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { teachingClassApi, type ClassGroup, type TeachingClass } from '@/api/teachingClasses'

const auth = useAuthStore()
const router = useRouter()
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
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailRefreshing = ref(false)
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
})
const stageLabels: Record<LearningStage, string> = { preview: '课前预习', review: '课后巩固', exam: '考前冲刺' }
const kindLabels: Record<AssignmentTaskKind, string> = { reading: '教材阅读', ai_assist: 'AI 学习辅助', note: '章节笔记' }
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

function taskPath(task: StudentAssignment) { return `/courses/${task.course_id}/chapters/${task.chapter_id}/${task.learning_stage}` }
function formatTime(value: string) { return new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
function statusLabel(status: StudentAssignment['status']) { return status === 'completed' ? '已完成' : status === 'overdue' ? '已逾期' : status === 'in_progress' ? '进行中' : '未开始' }
function statusTagType(status: AssignmentRecipientDetail['status']) {
  return status === 'completed' ? 'success' : status === 'overdue' ? 'danger' : status === 'in_progress' ? 'warning' : 'primary'
}
function formatActivityTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '暂无学习记录'
}
function deadlineClass(task: StudentAssignment) {
  if (task.status === 'completed') return 'completed'
  if (task.status === 'overdue') return 'overdue'
  return new Date(task.due_time).getTime() - Date.now() < 24 * 3600 * 1000 ? 'urgent' : ''
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
watch(() => form.learning_stage, (stage) => { if (form.task_kind === 'note' && stage !== 'review') form.task_kind = 'reading' })
function openCreate() {
  dialogVisible.value = true
  if (teachingClasses.value.length && !form.teaching_class_id) form.teaching_class_id = teachingClasses.value[0].id
  const selected = teachingClasses.value.find((item) => item.id === form.teaching_class_id)
  if (selected && !form.course_id) form.course_id = selected.primary_course_id
  if (!form.due_time) {
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000)
    form.due_time = tomorrow.toISOString().slice(0, 16)
  }
}
async function publish() {
  if (!form.teaching_class_id || !form.course_id || !form.chapter_id || !form.title.trim() || !form.due_time) return ElMessage.warning('请完整填写教学班、教材、章节、任务名称和截止时间')
  if (form.target_scope === 'selected_students' && !form.student_ids.length) return ElMessage.warning('请选择至少一名学生')
  if (form.target_scope === 'selected_groups' && !form.group_ids.length) return ElMessage.warning('请选择至少一个学习小组')
  publishing.value = true
  try {
    await assignmentApi.create({ ...form, course_id: form.course_id, chapter_id: form.chapter_id, due_time: `${form.due_time}:00` })
    dialogVisible.value = false
    form.title = ''; form.description = ''; form.student_ids = []; form.group_ids = []
    await load()
    ElMessage.success('学习任务已发布')
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '任务发布失败')) }
  finally { publishing.value = false }
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
onMounted(load)
onBeforeUnmount(stopDetailRefresh)
</script>

<template>
  <div v-loading="loading" class="assignment-page">
    <header class="page-header"><div><p class="eyebrow">{{ auth.isTeacher ? '教学任务管理' : '我的学习任务' }}</p><h1>{{ auth.isTeacher ? '布置并跟踪学习任务' : '按时完成教师布置的任务' }}</h1><p>{{ auth.isTeacher ? '任务与教材章节任务点关联，学生完成学习行为后自动更新进度。' : '任务进度由阅读、AI学习、笔记和练习等实际行为自动统计。' }}</p></div><el-button v-if="auth.isTeacher" type="primary" size="large" :icon="Plus" @click="openCreate">发布任务</el-button></header>

    <template v-if="!auth.isTeacher">
      <section class="student-assignment-list">
        <article v-for="task in studentTasks" :key="task.id" class="student-assignment-card" :class="deadlineClass(task)">
          <div class="assignment-status-line"><el-tag :type="task.status === 'completed' ? 'success' : task.status === 'overdue' ? 'danger' : task.status === 'in_progress' ? 'warning' : 'primary'">{{ statusLabel(task.status) }}</el-tag><span>{{ stageLabels[task.learning_stage] }} · {{ kindLabels[task.task_kind] }}</span></div>
          <h2>{{ task.title }}</h2><p>{{ task.description || `完成“${task.chapter_title}”相关学习任务。` }}</p>
          <div class="assignment-meta"><span>{{ task.course_name }} · {{ task.chapter_title }}</span><strong>截止 {{ formatTime(task.due_time) }}</strong><span>教师：{{ task.teacher_name }}</span></div>
          <el-progress :percentage="task.progress_value" :status="task.status === 'completed' ? 'success' : undefined" />
          <el-button v-if="task.status !== 'completed'" type="primary" :icon="Promotion" @click="router.push(taskPath(task))">{{ task.status === 'not_started' ? '开始任务' : '继续完成' }}</el-button>
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
          <div class="teacher-task-metrics"><span>完成 <strong>{{ task.completed_count }}/{{ task.total_count }}</strong></span><span>进行中 <strong>{{ task.in_progress_count }}</strong></span><span>逾期 <strong>{{ task.overdue_count }}</strong></span><span><el-icon><Calendar /></el-icon> {{ formatTime(task.due_time) }}</span></div>
          <div class="teacher-task-actions">
            <el-button :icon="UserFilled" type="primary" plain @click="openTaskDetails(task)">查看完成详情</el-button>
            <el-button v-if="task.status === 'published'" type="danger" plain @click="cancelTask(task)">撤回任务</el-button>
          </div>
        </el-card>
        <el-empty v-if="!teacherTasks.length" description="尚未发布学习任务" />
      </section>
    </template>

    <el-dialog v-model="dialogVisible" title="发布学习任务" width="680px">
      <el-form label-position="top" class="assignment-form">
        <el-form-item label="所属教学班"><el-select v-model="form.teaching_class_id" style="width:100%" placeholder="任务必须发布到具体教学班"><el-option v-for="item in teachingClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" /></el-select></el-form-item>
        <div class="assignment-form-grid"><el-form-item label="教材"><el-select v-model="form.course_id" style="width:100%"><el-option v-for="course in courses.filter((item) => teachingClasses.find((klass) => klass.id === form.teaching_class_id)?.material_ids.includes(item.id))" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item><el-form-item label="专题章节"><el-select v-model="form.chapter_id" filterable style="width:100%"><el-option v-for="chapter in chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item></div>
        <div class="assignment-form-grid"><el-form-item label="学习阶段"><el-select v-model="form.learning_stage" style="width:100%"><el-option label="课前预习" value="preview" /><el-option label="课后巩固" value="review" /><el-option label="考前冲刺" value="exam" /></el-select></el-form-item><el-form-item label="完成条件"><el-select v-model="form.task_kind" style="width:100%"><el-option v-for="(label, value) in kindLabels" :key="value" :label="label" :value="value" :disabled="value === 'note' && form.learning_stage !== 'review'" /></el-select></el-form-item></div>
        <el-form-item label="任务名称"><el-input v-model="form.title" maxlength="160" show-word-limit placeholder="例如：完成第十七章课后巩固" /></el-form-item>
        <el-form-item label="任务要求"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="3000" show-word-limit placeholder="说明学习重点和具体要求" /></el-form-item>
        <div class="assignment-form-grid"><el-form-item label="截止时间"><el-date-picker v-model="form.due_time" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width:100%" /></el-form-item><el-form-item label="发布对象"><el-radio-group v-model="form.target_scope"><el-radio-button value="all_students">全班</el-radio-button><el-radio-button value="selected_groups">指定小组</el-radio-button><el-radio-button value="selected_students">指定学生</el-radio-button></el-radio-group></el-form-item></div>
        <el-form-item v-if="form.target_scope === 'selected_students'" label="选择学生"><el-select v-model="form.student_ids" multiple filterable collapse-tags style="width:100%"><el-option v-for="student in students" :key="student.id" :label="`${student.username}${student.identity_no ? ` · ${student.identity_no}` : ''}`" :value="student.id" /></el-select></el-form-item>
        <el-form-item v-if="form.target_scope === 'selected_groups'" label="选择学习小组"><el-select v-model="form.group_ids" multiple collapse-tags style="width:100%"><el-option v-for="group in groups" :key="group.id" :label="`${group.name}（${group.user_ids.length}人）`" :value="group.id" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="publishing" @click="publish">发布任务</el-button></template>
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

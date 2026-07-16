<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, Plus, Promotion } from '@element-plus/icons-vue'
import { assignmentApi, type AssignmentStudent, type AssignmentTaskKind, type StudentAssignment, type TeacherAssignment } from '@/api/assignments'
import { courseApi } from '@/api/courses'
import { useAuthStore } from '@/stores/auth'
import type { Chapter, Course, LearningStage } from '@/types'
import { getErrorMessage } from '@/utils/error'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(true)
const studentTasks = ref<StudentAssignment[]>([])
const teacherTasks = ref<TeacherAssignment[]>([])
const courses = ref<Course[]>([])
const chapters = ref<Chapter[]>([])
const students = ref<AssignmentStudent[]>([])
const dialogVisible = ref(false)
const publishing = ref(false)
const form = reactive({
  course_id: null as number | null,
  chapter_id: null as number | null,
  learning_stage: 'preview' as LearningStage,
  task_kind: 'reading' as AssignmentTaskKind,
  title: '', description: '', due_time: '',
  target_scope: 'all_students' as 'all_students' | 'selected_students',
  student_ids: [] as number[],
})
const stageLabels: Record<LearningStage, string> = { preview: '课前预习', review: '课后巩固', exam: '考前冲刺' }
const kindLabels: Record<AssignmentTaskKind, string> = { reading: '教材阅读', ai_assist: 'AI 学习辅助', note: '章节笔记' }
const activeTeacherTasks = computed(() => teacherTasks.value.filter((item) => item.status === 'published'))

function taskPath(task: StudentAssignment) { return `/courses/${task.course_id}/chapters/${task.chapter_id}/${task.learning_stage}` }
function formatTime(value: string) { return new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
function statusLabel(status: StudentAssignment['status']) { return status === 'completed' ? '已完成' : status === 'overdue' ? '已逾期' : status === 'in_progress' ? '进行中' : '未开始' }
function deadlineClass(task: StudentAssignment) {
  if (task.status === 'completed') return 'completed'
  if (task.status === 'overdue') return 'overdue'
  return new Date(task.due_time).getTime() - Date.now() < 24 * 3600 * 1000 ? 'urgent' : ''
}
async function load() {
  loading.value = true
  try {
    if (auth.isTeacher) {
      const [taskResponse, courseResponse, studentResponse] = await Promise.all([assignmentApi.teacher(), courseApi.list(), assignmentApi.students()])
      teacherTasks.value = taskResponse.data.data
      courses.value = courseResponse.data.data
      students.value = studentResponse.data.data
    } else studentTasks.value = (await assignmentApi.student(true)).data.data
  } finally { loading.value = false }
}
async function loadChapters() {
  form.chapter_id = null
  chapters.value = form.course_id ? (await courseApi.detail(form.course_id)).data.data.chapters : []
}
watch(() => form.course_id, () => void loadChapters())
watch(() => form.learning_stage, (stage) => { if (form.task_kind === 'note' && stage !== 'review') form.task_kind = 'reading' })
function openCreate() {
  dialogVisible.value = true
  if (courses.value.length && !form.course_id) form.course_id = courses.value[0].id
  if (!form.due_time) {
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000)
    form.due_time = tomorrow.toISOString().slice(0, 16)
  }
}
async function publish() {
  if (!form.course_id || !form.chapter_id || !form.title.trim() || !form.due_time) return ElMessage.warning('请完整填写教材、章节、任务名称和截止时间')
  if (form.target_scope === 'selected_students' && !form.student_ids.length) return ElMessage.warning('请选择至少一名学生')
  publishing.value = true
  try {
    await assignmentApi.create({ ...form, course_id: form.course_id, chapter_id: form.chapter_id, due_time: `${form.due_time}:00` })
    dialogVisible.value = false
    form.title = ''; form.description = ''; form.student_ids = []
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
onMounted(load)
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
          <el-button v-if="task.status === 'published'" type="danger" plain @click="cancelTask(task)">撤回任务</el-button>
        </el-card>
        <el-empty v-if="!teacherTasks.length" description="尚未发布学习任务" />
      </section>
    </template>

    <el-dialog v-model="dialogVisible" title="发布学习任务" width="680px">
      <el-form label-position="top" class="assignment-form">
        <div class="assignment-form-grid"><el-form-item label="教材"><el-select v-model="form.course_id" style="width:100%"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item><el-form-item label="专题章节"><el-select v-model="form.chapter_id" filterable style="width:100%"><el-option v-for="chapter in chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item></div>
        <div class="assignment-form-grid"><el-form-item label="学习阶段"><el-select v-model="form.learning_stage" style="width:100%"><el-option label="课前预习" value="preview" /><el-option label="课后巩固" value="review" /><el-option label="考前冲刺" value="exam" /></el-select></el-form-item><el-form-item label="完成条件"><el-select v-model="form.task_kind" style="width:100%"><el-option v-for="(label, value) in kindLabels" :key="value" :label="label" :value="value" :disabled="value === 'note' && form.learning_stage !== 'review'" /></el-select></el-form-item></div>
        <el-form-item label="任务名称"><el-input v-model="form.title" maxlength="160" show-word-limit placeholder="例如：完成第十七章课后巩固" /></el-form-item>
        <el-form-item label="任务要求"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="3000" show-word-limit placeholder="说明学习重点和具体要求" /></el-form-item>
        <div class="assignment-form-grid"><el-form-item label="截止时间"><el-date-picker v-model="form.due_time" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width:100%" /></el-form-item><el-form-item label="发布对象"><el-radio-group v-model="form.target_scope"><el-radio-button value="all_students">全部学生</el-radio-button><el-radio-button value="selected_students">指定学生</el-radio-button></el-radio-group></el-form-item></div>
        <el-form-item v-if="form.target_scope === 'selected_students'" label="选择学生"><el-select v-model="form.student_ids" multiple filterable collapse-tags style="width:100%"><el-option v-for="student in students" :key="student.id" :label="`${student.username}${student.identity_no ? ` · ${student.identity_no}` : ''}`" :value="student.id" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="publishing" @click="publish">发布任务</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, ChatDotRound, Collection, Connection, EditPen, Reading, TrendCharts, UploadFilled } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { courseApi } from '@/api/courses'
import { useAuthStore } from '@/stores/auth'
import type { Course, CourseDetail } from '@/types'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const courses = ref<Course[]>([])
const textbook = ref<CourseDetail | null>(null)
const dialogVisible = ref(false)
const editDialogVisible = ref(false)
const submitting = ref(false)
const editSubmitting = ref(false)
const editingCourse = ref<Course | null>(null)
const selectedFile = ref<File | null>(null)
const uploadKey = ref(0)
const form = reactive({ name: '', description: '' })
const editForm = reactive({ description: '' })
const overviewStats = computed(() => [
  { label: '教材专题', value: textbook.value?.chapters.length || 0, unit: '章', icon: Collection },
  { label: '学习阶段', value: 3, unit: '阶', icon: Reading },
  { label: 'AI 助学场景', value: 5, unit: '项', icon: ChatDotRound },
])
const moduleCards = [
  { index: '01', kicker: '理论学习主线', title: '专题学习', desc: '沿教材章节进入预习、巩固、冲刺三段式学习，让理论脉络清晰可循。', action: '进入专题', icon: Reading, path: '', tone: 'blue' },
  { index: '02', kicker: '理论联系实际', title: '时政要点', desc: '从权威媒体信息出发，定位教材观点与现实议题之间的内在联系。', action: '关联时政', icon: TrendCharts, path: '/current-affairs', tone: 'red' },
  { index: '03', kicker: '观点交流实践', title: '课堂互动', desc: '通过讨论、问答和观点辨析，把知识理解转化为课堂表达与思考。', action: '参与互动', icon: Connection, path: '/interaction', tone: 'cyan' },
]

async function loadCourses() {
  loading.value = true
  try {
    courses.value = (await courseApi.list()).data.data
    textbook.value = courses.value[0] ? (await courseApi.detail(courses.value[0].id)).data.data : null
  } finally { loading.value = false }
}
async function createCourse() {
  if (!form.name.trim()) return ElMessage.warning('请输入课程名称')
  submitting.value = true
  try {
    if (selectedFile.value) {
      const payload = new FormData()
      payload.append('name', form.name.trim())
      payload.append('description', form.description)
      payload.append('file', selectedFile.value)
      await courseApi.importCourse(payload)
    } else {
      await courseApi.create(form)
    }
    ElMessage.success(selectedFile.value ? '教材导入成功，专题和知识库已自动建立' : '教材创建成功')
    dialogVisible.value = false
    form.name = ''; form.description = ''
    selectedFile.value = null
    uploadKey.value += 1
    await loadCourses()
  } catch (error: any) {
    const detail = error?.response?.data?.detail || error?.response?.data?.message
    ElMessage.error(detail || '教材导入失败，请检查文件格式、大小和网络连接')
  } finally { submitting.value = false }
}
function handleFileChange(uploadFile: UploadFile) {
  const file = uploadFile.raw || null
  if (file && file.size > 100 * 1024 * 1024) {
    ElMessage.error('教材文件不能超过 100MB')
    selectedFile.value = null
    uploadKey.value += 1
    return
  }
  selectedFile.value = file
}
function handleFileRemove() { selectedFile.value = null }
function openDescriptionEditor(course: Course) {
  editingCourse.value = course
  editForm.description = course.description || ''
  editDialogVisible.value = true
}
async function updateDescription() {
  if (!editingCourse.value) return
  editSubmitting.value = true
  try {
    await courseApi.update(editingCourse.value.id, { description: editForm.description.trim() || null })
    ElMessage.success('教材简介已更新')
    editDialogVisible.value = false
    await loadCourses()
  } catch (error: any) {
    const detail = error?.response?.data?.detail || error?.response?.data?.message
    ElMessage.error(detail || '教材简介更新失败，请稍后重试')
  } finally { editSubmitting.value = false }
}
function openModule(path: string) {
  if (path) return router.push(path)
  if (textbook.value) router.push(`/courses/${textbook.value.id}`)
}
onMounted(loadCourses)
</script>

<template>
  <div class="course-overview-page">
    <header class="course-command-hero">
      <div class="course-hero-grid"></div>
      <div class="course-command-copy">
        <div class="course-value-line"><span></span>新时代思想 · AI 智能教学空间</div>
        <div class="course-hero-tags"><span>教材主线</span><span>权威资料</span><span>智能助学</span></div>
        <h1>读懂新时代<br><em>构建思想知识坐标</em></h1>
        <p>以《习近平新时代中国特色社会主义思想概论》为理论主线，把专题学习、时政关联与课堂互动组织成一条有依据、有情境、有反馈的学习路径。</p>
        <div class="course-hero-actions">
          <el-button type="warning" size="large" :disabled="!textbook" @click="textbook && router.push(`/courses/${textbook.id}`)">进入专题目录 <el-icon><ArrowRight /></el-icon></el-button>
          <el-button size="large" plain @click="router.push('/current-affairs')">查看时政要点</el-button>
        </div>
        <div class="course-overview-stats">
          <div v-for="item in overviewStats" :key="item.label" class="course-overview-stat">
            <el-icon><component :is="item.icon" /></el-icon>
            <div><strong>{{ item.value }}<small>{{ item.unit }}</small></strong><span>{{ item.label }}</span></div>
          </div>
        </div>
      </div>

      <div class="course-intelligence-map" aria-label="课程智能知识导航示意图">
        <div class="intelligence-map-heading"><span>THEORY · KNOWLEDGE MAP</span><strong>理论知识智能导航</strong></div>
        <div class="intelligence-orbit orbit-one"></div>
        <div class="intelligence-orbit orbit-two"></div>
        <div class="intelligence-axis axis-horizontal"></div>
        <div class="intelligence-axis axis-vertical"></div>
        <div class="intelligence-core"><span>AI</span><strong>思想坐标</strong><small>教材为本 · 智能助学</small></div>
        <button type="button" class="intelligence-node node-theory" :disabled="!textbook" @click="openModule('')"><span>01</span><strong>专题学习</strong><small>理论主线</small></button>
        <button type="button" class="intelligence-node node-affairs" @click="openModule('/current-affairs')"><span>02</span><strong>时政关联</strong><small>现实坐标</small></button>
        <button type="button" class="intelligence-node node-classroom" @click="openModule('/interaction')"><span>03</span><strong>课堂互动</strong><small>实践表达</small></button>
        <span class="intelligence-pulse pulse-one"></span><span class="intelligence-pulse pulse-two"></span><span class="intelligence-pulse pulse-three"></span>
        <div class="intelligence-map-caption"><span></span>AI 围绕教材与当前专题提供学习支持</div>
      </div>
    </header>

    <section class="course-path-section">
      <div class="course-section-intro"><div><p class="eyebrow">三位一体 · 教学路径</p><h2>从理论认知走向现实理解</h2></div><p>以教材观点为圆心，让知识学习、现实观察与课堂表达相互支撑。</p></div>
      <div class="course-path-grid">
        <article v-for="item in moduleCards" :key="item.title" class="course-path-card" :class="`tone-${item.tone}`" role="button" tabindex="0" @click="openModule(item.path)" @keydown.enter="openModule(item.path)">
          <div class="path-card-top"><span>{{ item.index }}</span><small>{{ item.kicker }}</small><el-icon><component :is="item.icon" /></el-icon></div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
          <div class="path-card-action">{{ item.action }} <el-icon><ArrowRight /></el-icon></div>
        </article>
      </div>
    </section>

    <section class="course-textbook-section">
      <div class="course-textbook-heading"><div><p class="eyebrow">教材主线 · 智能组织</p><h2>沿着理论脉络进入专题学习</h2><p>每一本教材都以专题为基本学习单元，并与知识检索、学习阶段和 AI 辅助保持同一上下文。</p></div><el-button v-if="auth.isAdmin" type="primary" size="large" @click="dialogVisible = true"><el-icon><UploadFilled /></el-icon>导入教材</el-button></div>
      <div v-loading="loading" class="course-library-grid">
        <article v-for="course in courses" :key="course.id" class="course-library-card" role="button" tabindex="0" @click="router.push(`/courses/${course.id}`)" @keydown.enter="router.push(`/courses/${course.id}`)">
          <div class="course-book-mark"><span>TEXTBOOK</span><strong>{{ String(course.id).padStart(2, '0') }}</strong><small>思想理论教材</small></div>
          <div class="course-library-content">
            <div class="course-card-heading"><div class="course-index"><span></span>核心教材</div><el-button v-if="auth.isAdmin" class="course-description-edit" text type="primary" :icon="EditPen" @click.stop="openDescriptionEditor(course)">修改简介</el-button></div>
            <h2>{{ course.name }}</h2>
            <p>{{ course.description || '管理员尚未补充教材简介，可进入专题目录查看已识别的章节内容。' }}</p>
            <div class="course-library-footer"><span><el-icon><Collection /></el-icon>专题化内容组织</span><strong>查看专题目录 <el-icon><ArrowRight /></el-icon></strong></div>
          </div>
          <div class="course-card-watermark">思政<br>AI</div>
        </article>
        <el-empty v-if="!loading && !courses.length" description="暂无教材课程，请联系管理员创建" />
      </div>
    </section>
    <el-dialog v-model="dialogVisible" title="导入教材" width="560px">
      <el-form label-position="top"><el-form-item label="教材名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="教材简介"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item><el-form-item label="上传教材并自动建专题"><el-upload :key="uploadKey" drag :auto-upload="false" :limit="1" accept=".pdf,.txt,.md,.markdown" :on-change="handleFileChange" :on-remove="handleFileRemove"><el-icon class="el-icon--upload"><UploadFilled /></el-icon><div class="el-upload__text">拖拽教材资料到此处，或<em>点击选择</em></div><template #tip><div class="el-upload__tip">支持 PDF、TXT、Markdown，系统会自动识别章节并建立专题和知识库；不选择也可以先创建教材。</div></template></el-upload></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="createCourse">导入并自动建专题</el-button></template>
    </el-dialog>
    <el-dialog v-model="editDialogVisible" title="修改教材简介" width="560px">
      <el-form label-position="top">
        <el-form-item label="教材名称"><el-input :model-value="editingCourse?.name || ''" disabled /></el-form-item>
        <el-form-item label="教材简介"><el-input v-model="editForm.description" type="textarea" :rows="6" maxlength="2000" show-word-limit placeholder="请输入教材定位、主要内容和学习目标；留空可清除现有简介。" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editDialogVisible = false">取消</el-button><el-button type="primary" :loading="editSubmitting" @click="updateDescription">保存简介</el-button></template>
    </el-dialog>
  </div>
</template>

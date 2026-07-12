<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Collection, Connection, Reading, TrendCharts, UploadFilled } from '@element-plus/icons-vue'
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
const submitting = ref(false)
const selectedFile = ref<File | null>(null)
const uploadKey = ref(0)
const form = reactive({ name: '', description: '' })
const overviewStats = computed(() => [
  { label: '教材专题', value: textbook.value?.chapters.length || 0, icon: Collection },
  { label: '学习阶段', value: 3, icon: Reading },
  { label: 'AI 场景', value: 5, icon: ChatDotRound },
])
const moduleCards = [
  { title: '专题学习', desc: '按教材专题进入预习、巩固、冲刺三段式学习。', icon: Reading, path: '' },
  { title: '时政要点', desc: '围绕近期重大主题做教材知识关联和课堂导入。', icon: TrendCharts, path: '/current-affairs' },
  { title: '课堂互动', desc: '生成讨论题、随堂问答、观点辨析和小组活动。', icon: Connection, path: '/interaction' },
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
function openModule(path: string) {
  if (path) return router.push(path)
  if (textbook.value) router.push(`/courses/${textbook.value.id}`)
}
onMounted(loadCourses)
</script>

<template>
  <div>
    <header class="overview-hero">
      <div>
        <p class="eyebrow">课程总览</p>
        <h1>《习近平新时代中国特色社会主义思想概论》智能教学空间</h1>
        <p>课程中心保留为总入口，内部围绕一本教材组织专题学习、时政关联、课堂互动，并在导入教材时同步建立知识库。</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" :disabled="!textbook" @click="textbook && router.push(`/courses/${textbook.id}`)">进入专题目录</el-button>
          <el-button size="large" @click="router.push('/current-affairs')">查看时政要点</el-button>
        </div>
      </div>
      <div class="overview-stat-panel">
        <div v-for="item in overviewStats" :key="item.label" class="overview-stat">
          <el-icon :size="24"><component :is="item.icon" /></el-icon>
          <strong>{{ item.value }}</strong>
          <span>{{ item.label }}</span>
        </div>
      </div>
    </header>

    <section class="module-grid">
      <el-card v-for="item in moduleCards" :key="item.title" shadow="hover" class="module-card" @click="openModule(item.path)">
        <el-icon :size="26"><component :is="item.icon" /></el-icon>
        <h3>{{ item.title }}</h3>
        <p>{{ item.desc }}</p>
      </el-card>
    </section>

    <div class="section-heading"><div><p class="eyebrow">教材专题</p><h2>按内容组织学习</h2></div><el-button v-if="auth.isAdmin" type="primary" @click="dialogVisible = true">导入教材</el-button></div>
    <div v-loading="loading" class="course-grid compact-course-grid">
      <el-card v-for="course in courses" :key="course.id" shadow="hover" class="course-card" @click="router.push(`/courses/${course.id}`)">
        <div class="course-index">教材 {{ String(course.id).padStart(2, '0') }}</div><h2>{{ course.name }}</h2><p>{{ course.description || '暂无简介' }}</p><el-link type="primary" underline="never">查看专题 →</el-link>
      </el-card>
      <el-empty v-if="!loading && !courses.length" description="暂无教材课程，请联系管理员创建" />
    </div>
    <el-dialog v-model="dialogVisible" title="导入教材" width="560px">
      <el-form label-position="top"><el-form-item label="教材名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="教材简介"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item><el-form-item label="上传教材并自动建专题"><el-upload :key="uploadKey" drag :auto-upload="false" :limit="1" accept=".pdf,.txt,.md,.markdown" :on-change="handleFileChange" :on-remove="handleFileRemove"><el-icon class="el-icon--upload"><UploadFilled /></el-icon><div class="el-upload__text">拖拽教材资料到此处，或<em>点击选择</em></div><template #tip><div class="el-upload__tip">支持 PDF、TXT、Markdown，系统会自动识别章节并建立专题和知识库；不选择也可以先创建教材。</div></template></el-upload></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="createCourse">导入并自动建专题</el-button></template>
    </el-dialog>
  </div>
</template>

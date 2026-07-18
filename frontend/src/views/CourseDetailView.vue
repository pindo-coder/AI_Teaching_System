<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CirclePlus, Clock, Delete, DocumentChecked, Setting, UploadFilled } from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import { knowledgeApi, type KnowledgeDocument, type TextbookVersion } from '@/api/knowledge'
import { useAuthStore } from '@/stores/auth'
import type { CourseDetail, LearningStage } from '@/types'
import { textbookPreview } from '@/utils/textbookText'
import KnowledgeGraph from '@/components/KnowledgeGraph.vue'
import { getErrorMessage } from '@/utils/error'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const courseId = computed(() => Number(route.params.id))
const course = ref<CourseDetail | null>(null)
const loading = ref(false)
const dialogVisible = ref(false)
const calibrationDialogVisible = ref(false)
const replacementDialogVisible = ref(false)
const versionDialogVisible = ref(false)
const versionsLoading = ref(false)
const activatingVersionId = ref<number | null>(null)
const versions = ref<TextbookVersion[]>([])
const replacementUploading = ref(false)
const replacementFile = ref<File | null>(null)
const replacementFileInput = ref<HTMLInputElement>()
const documents = ref<KnowledgeDocument[]>([])
const form = reactive({ title: '', content: '', sort_order: 0 })
const replacementForm = reactive({
  source_title: '',
  version_label: `OCR 修订版 ${new Date().toISOString().slice(0, 10)}`,
  access_policy: 'full_preview' as KnowledgeDocument['access_policy'],
})
const canManageCitations = computed(() => ['teacher', 'admin'].includes(auth.user?.role || ''))
const calibrationSummary = computed(() => {
  if (!documents.value.length) return '尚未导入可校准的教材文件'
  const published = documents.value.filter((item) => item.calibration_status === 'published').length
  const pending = documents.value.length - published
  return pending ? `${pending} 份资料待校准或发布` : `${published} 份资料已完成校准发布`
})

async function loadCourse() {
  loading.value = true
  try {
    const [courseResult, documentResult] = await Promise.all([
      courseApi.detail(courseId.value),
      canManageCitations.value ? knowledgeApi.list(courseId.value) : Promise.resolve(null),
    ])
    course.value = courseResult.data.data
    documents.value = documentResult?.data.data || []
  } finally { loading.value = false }
}
function openCalibration() {
  if (!documents.value.length) {
    replacementDialogVisible.value = true
    return
  }
  if (documents.value.length === 1) return router.push(`/knowledge/documents/${documents.value[0].id}/calibrate`)
  calibrationDialogVisible.value = true
}
function openReplacementUpload() {
  replacementDialogVisible.value = true
}
async function openVersionManager() {
  versionDialogVisible.value = true
  versionsLoading.value = true
  try {
    versions.value = (await knowledgeApi.versions(courseId.value)).data.data
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材版本加载失败'))
  } finally { versionsLoading.value = false }
}
function versionCanActivate(version: TextbookVersion) {
  return version.status === 'published' && version.documents.some(
    (item) => item.status === 'ready' && item.calibration_status === 'published',
  )
}
function formatVersionTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
async function activateVersion(version: TextbookVersion) {
  if (version.is_current || !versionCanActivate(version)) return
  const confirmed = await ElMessageBox.confirm(
    `切换到“${version.version_label}”后，学生和 AI 将立即使用该版本的教材依据。历史版本仍会保留，是否继续？`,
    '切换当前教材版本',
    { type: 'warning', confirmButtonText: '确认切换', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  activatingVersionId.value = version.id
  try {
    await knowledgeApi.activateVersion(version.id)
    ElMessage.success(`已切换到“${version.version_label}”`)
    versions.value = (await knowledgeApi.versions(courseId.value)).data.data
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材版本切换失败'))
  } finally { activatingVersionId.value = null }
}
function chooseReplacementFile(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] || null
  if (file && file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    ElMessage.error('新主教材仅支持 PDF 文件')
    target.value = ''
    replacementFile.value = null
    return
  }
  if (file && file.size > 100 * 1024 * 1024) {
    ElMessage.error('教材文件不能超过 100 MB')
    target.value = ''
    replacementFile.value = null
    return
  }
  replacementFile.value = file
  if (file && !replacementForm.source_title.trim()) {
    replacementForm.source_title = file.name.replace(/\.pdf$/i, '')
  }
}
async function uploadReplacement() {
  if (!replacementFile.value) return ElMessage.warning('请选择带文字层的 OCR PDF 教材')
  if (!replacementForm.source_title.trim()) return ElMessage.warning('请填写资料标题')
  if (!replacementForm.version_label.trim()) return ElMessage.warning('请填写不重复的教材版本标识')
  const payload = new FormData()
  payload.append('file', replacementFile.value)
  payload.append('source_title', replacementForm.source_title.trim())
  payload.append('course_id', String(courseId.value))
  payload.append('version_label', replacementForm.version_label.trim())
  payload.append('source_role', 'primary')
  payload.append('access_policy', replacementForm.access_policy)
  payload.append('auto_calibrate', 'true')
  replacementUploading.value = true
  try {
    const response = await knowledgeApi.upload(payload)
    const document = response.data.data
    ElMessage.success('新教材已上传，系统已生成待确认的章节边界')
    replacementDialogVisible.value = false
    replacementFile.value = null
    if (replacementFileInput.value) replacementFileInput.value.value = ''
    documents.value = (await knowledgeApi.list(courseId.value)).data.data
    await router.push(`/knowledge/documents/${document.id}/calibrate`)
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '新教材上传失败'))
  } finally {
    replacementUploading.value = false
  }
}
function calibrationLabel(status: KnowledgeDocument['calibration_status']) {
  return status === 'published' ? '已发布' : status === 'calibrated' ? '已校准待发布' : '待校准'
}
async function deleteKnowledgeDocument(item: KnowledgeDocument) {
  const confirmed = await ElMessageBox.confirm(
    `确定删除“${item.source_title}”吗？文件、校准结构和向量索引将一并删除，但不会影响课程专题、笔记和学习记录。`,
    '删除教材资料',
    { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  try {
    await knowledgeApi.remove(item.id)
    documents.value = documents.value.filter((document) => document.id !== item.id)
    ElMessage.success('教材资料已删除')
    if (!documents.value.length) calibrationDialogVisible.value = false
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材资料删除失败'))
  }
}
async function createChapter() {
  if (!form.title.trim()) return ElMessage.warning('请输入章节标题')
  await courseApi.createChapter(courseId.value, form)
  ElMessage.success('章节创建成功'); dialogVisible.value = false
  form.title = ''; form.content = ''; form.sort_order = 0
  await loadCourse()
}
async function startLearning(chapterId: number, stage: LearningStage) {
  await router.push(`/courses/${courseId.value}/chapters/${chapterId}/${stage}`)
}
async function deleteCourse() {
  const confirmed = await ElMessageBox.confirm(
    `删除“${course.value?.name || '这本教材'}”后，相关专题、学习记录和知识库资料也将一并删除，是否继续？`,
    '删除教材',
    { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  await courseApi.remove(courseId.value)
  ElMessage.success('教材已删除')
  await router.push('/courses')
}
async function handleManagementCommand(command: 'history' | 'upload' | 'calibration' | 'chapter' | 'delete') {
  if (command === 'history') await openVersionManager()
  else if (command === 'upload') openReplacementUpload()
  else if (command === 'calibration') openCalibration()
  else if (command === 'chapter') dialogVisible.value = true
  else if (command === 'delete') await deleteCourse()
}
onMounted(loadCourse)
</script>

<template>
  <div v-loading="loading">
    <div class="course-breadcrumb"><el-button link @click="$router.push('/courses')">课程中心</el-button><span>/</span><span>{{ course?.name || '教材详情' }}</span></div>
    <header class="course-hero course-detail-hero"><div class="course-hero-copy"><p class="eyebrow">高校思政课 · 教材空间</p><h1>{{ course?.name }}</h1><div class="course-meta"><span>专题 {{ course?.chapters.length || 0 }}</span><span>学习阶段 3 个</span><span>AI 辅助学习</span></div><div class="course-intro-card"><div class="intro-heading"><strong>课程介绍</strong><span>围绕教材专题开展学习</span></div><p>{{ course?.description || '围绕教材内容，结合预习、课后巩固和考前冲刺，形成连续的学习辅助。' }}</p></div></div><div class="course-hero-visual"><div class="hero-orbit"></div><div class="hero-metric metric-top"><strong>{{ course?.chapters.length || 0 }}</strong><span>教材专题</span></div><div class="hero-metric metric-left"><strong>3</strong><span>学习阶段</span></div><div class="hero-metric metric-right"><strong>AI</strong><span>学习辅助</span></div><div class="hero-core">思政<br>AI</div></div><div v-if="canManageCitations" class="hero-admin-actions"><el-dropdown trigger="click" popper-class="course-management-dropdown" @command="handleManagementCommand"><el-button class="hero-management-button" type="primary" :icon="Setting">教材管理<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="auth.isAdmin" command="history" :icon="Clock">历史版本</el-dropdown-item><el-dropdown-item command="upload" :icon="UploadFilled">上传新版教材</el-dropdown-item><el-dropdown-item command="calibration" :icon="DocumentChecked">教材引用校准</el-dropdown-item><el-dropdown-item v-if="auth.isAdmin" command="chapter" :icon="CirclePlus" divided>添加专题</el-dropdown-item><el-dropdown-item v-if="auth.isAdmin" command="delete" :icon="Delete" class="management-danger-item" divided>删除教材</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></header>
    <nav class="course-tabs" aria-label="教材内容导航"><a href="#overview">内容概览</a><a href="#chapters">专题章节</a><a href="#learning-path">学习路径</a></nav>
    <section class="course-tools"><el-card shadow="hover" class="course-tool-card" @click="router.push('/current-affairs')"><span class="tool-kicker">关联教材</span><h3>时政要点</h3><p>从现实议题回到教材知识，查看当前时政学习内容。</p><el-link type="primary" :underline="false">进入时政要点 →</el-link></el-card><el-card shadow="hover" class="course-tool-card" @click="router.push('/interaction')"><span class="tool-kicker">课堂场景</span><h3>课堂互动</h3><p>围绕当前教材专题生成讨论题、随堂问答和观点辨析。</p><el-link type="primary" :underline="false">进入课堂互动 →</el-link></el-card><el-card v-if="canManageCitations" shadow="hover" class="course-tool-card" @click="openCalibration"><span class="tool-kicker">教师与管理员工具</span><h3>教材引用校准</h3><p>{{ calibrationSummary }}</p><el-link type="primary" :underline="false">校准章节与页码 →</el-link></el-card></section>
    <KnowledgeGraph v-if="course" id="overview" :course-name="course.name" :chapters="course.chapters" @learn="(chapterId) => startLearning(chapterId, 'preview')" />
    <div class="course-detail-layout">
      <main>
        <div class="section-heading course-section-heading"><div><p class="eyebrow">专题目录</p><h2>按教材内容开展学习</h2></div><span class="muted">选择专题开始学习</span></div>
        <section id="chapters" class="chapter-list">
          <el-card v-for="chapter in course?.chapters" :key="chapter.id" shadow="never" class="chapter-card">
            <div class="chapter-number">{{ String(chapter.sort_order || chapter.id).padStart(2, '0') }}</div>
            <div class="chapter-main"><div class="chapter-label">专题 {{ String(chapter.sort_order || chapter.id).padStart(2, '0') }}</div><h3>{{ chapter.title }}</h3><p class="chapter-content-preview">{{ textbookPreview(chapter.content) || '本专题内容待完善' }}</p></div>
            <div class="chapter-actions"><el-button size="small" @click="startLearning(chapter.id, 'preview')">预习</el-button><el-button size="small" @click="startLearning(chapter.id, 'review')">巩固</el-button><el-button size="small" @click="startLearning(chapter.id, 'exam')">冲刺</el-button></div>
          </el-card>
          <el-empty v-if="course && !course.chapters.length" description="当前教材暂未添加专题" />
        </section>
      </main>
      <aside id="learning-path" class="course-side-column">
        <el-card shadow="never" class="course-side-card"><p class="eyebrow">学习路径</p><h3>循序渐进掌握教材</h3><div class="path-item"><span class="path-index">1</span><div><strong>预习空间</strong><p>先了解专题内容，形成问题意识。</p></div></div><div class="path-item"><span class="path-index">2</span><div><strong>课后巩固</strong><p>梳理知识结构，完成学习总结。</p></div></div><div class="path-item"><span class="path-index">3</span><div><strong>考前冲刺</strong><p>通过模拟问题检验掌握情况。</p></div></div></el-card>
        <el-card shadow="never" class="course-side-card course-note-card"><p class="eyebrow">学习提示</p><p>进入任一专题后，可在当前页面使用 AI 辅助完成总结、复习提纲和模拟题。</p></el-card>
      </aside>
    </div>
    <el-dialog v-model="dialogVisible" title="添加专题" width="560px"><el-form label-position="top"><el-form-item label="专题标题" required><el-input v-model="form.title" /></el-form-item><el-form-item label="专题内容"><el-input v-model="form.content" type="textarea" :rows="5" /></el-form-item><el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" /></el-form-item></el-form><template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="createChapter">保存</el-button></template></el-dialog>
    <el-dialog v-model="calibrationDialogVisible" title="选择需要校准的教材资料" width="680px">
      <div class="calibration-document-list"><div v-for="item in documents" :key="item.id" class="calibration-document-item" role="button" tabindex="0" @click="router.push(`/knowledge/documents/${item.id}/calibrate`)" @keydown.enter="router.push(`/knowledge/documents/${item.id}/calibrate`)"><div><strong>{{ item.source_title }}</strong><span>{{ item.original_filename }}</span></div><div class="calibration-document-actions"><el-tag :type="item.calibration_status === 'published' ? 'success' : item.calibration_status === 'calibrated' ? 'primary' : 'warning'">{{ calibrationLabel(item.calibration_status) }}</el-tag><el-button link type="danger" @click.stop="deleteKnowledgeDocument(item)">删除</el-button></div></div></div>
      <template #footer><el-button type="primary" plain @click="calibrationDialogVisible = false; openReplacementUpload()">上传 OCR 新版本</el-button><el-button @click="calibrationDialogVisible = false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="versionDialogVisible" title="教材历史版本" width="760px">
      <el-alert title="版本切换规则" type="info" :closable="false" show-icon>只有完成校准并发布的版本才能设为当前版本。切换后 AI 与学生立即使用所选版本，其他历史版本不会删除。</el-alert>
      <div v-loading="versionsLoading" class="textbook-version-list">
        <article v-for="version in versions" :key="version.id" :class="['textbook-version-card', { current: version.is_current }]">
          <div class="textbook-version-heading"><div><div class="version-title-row"><h3>{{ version.version_label }}</h3><el-tag v-if="version.is_current" type="success">当前使用</el-tag><el-tag v-else :type="version.status === 'published' ? 'primary' : 'warning'">{{ version.status === 'published' ? '历史已发布' : '草稿' }}</el-tag></div><p>创建于 {{ formatVersionTime(version.created_time) }} · {{ version.documents.length }} 份资料</p></div><el-button v-if="version.is_current" disabled>当前版本</el-button><el-button v-else-if="versionCanActivate(version)" type="primary" :loading="activatingVersionId === version.id" @click="activateVersion(version)">设为当前版本</el-button><el-button v-else disabled>校准发布后可切换</el-button></div>
          <div class="version-document-list"><div v-for="item in version.documents" :key="item.id"><div><strong>{{ item.source_title }}</strong><span>{{ item.original_filename }}</span></div><div><el-tag size="small" :type="item.calibration_status === 'published' ? 'success' : item.calibration_status === 'calibrated' ? 'primary' : 'warning'">{{ calibrationLabel(item.calibration_status) }}</el-tag><el-button link type="primary" @click="router.push(`/knowledge/documents/${item.id}/calibrate`)">查看校准</el-button></div></div><el-empty v-if="!version.documents.length" :image-size="48" description="该版本暂无资料" /></div>
        </article>
        <el-empty v-if="!versionsLoading && !versions.length" description="暂无教材历史版本" />
      </div>
      <template #footer><el-button type="primary" plain @click="versionDialogVisible = false; openReplacementUpload()">上传新版本</el-button><el-button @click="versionDialogVisible = false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="replacementDialogVisible" title="上传 OCR 新教材版本" width="620px" :close-on-click-modal="!replacementUploading">
      <el-alert title="安全替换知识库" type="info" :closable="false" show-icon>
        新文件会先进入“待校准”状态。完成章节、页码核对并发布后，AI 才会切换到新版本；当前教材、专题、笔记和旧知识库不会被删除。
      </el-alert>
      <el-form label-position="top" class="replacement-upload-form">
        <el-form-item label="OCR 教材 PDF" required>
          <input ref="replacementFileInput" class="file-input" type="file" accept=".pdf,application/pdf" @change="chooseReplacementFile" />
          <div class="replacement-file-hint">请选择具有可复制文字层的 PDF，单个文件不超过 100 MB。</div>
        </el-form-item>
        <el-form-item label="资料标题" required><el-input v-model="replacementForm.source_title" maxlength="255" placeholder="如：《习概》2023版 OCR课本" /></el-form-item>
        <el-form-item label="教材版本标识" required><el-input v-model="replacementForm.version_label" maxlength="100" placeholder="必须与已有版本不同" /><div class="replacement-file-hint">版本标识用于安全区分新旧知识库，请勿填写已经存在的名称。</div></el-form-item>
        <el-form-item label="原文访问权限"><el-radio-group v-model="replacementForm.access_policy"><el-radio-button value="citation_only">仅引用页</el-radio-button><el-radio-button value="full_preview">全文预览</el-radio-button><el-radio-button value="download">允许下载</el-radio-button></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="replacementUploading" @click="replacementDialogVisible = false">取消</el-button><el-button type="primary" :loading="replacementUploading" @click="uploadReplacement">上传并生成校准草稿</el-button></template>
    </el-dialog>
  </div>
</template>

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
import { beijingToday, formatBeijingDateTime } from '@/utils/time'
import logoUrl from '@/assets/logo1.svg'
import learningHeroBackground from '@/assets/learning-hero-reference.png'

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
  version_label: `OCR 修订版 ${beijingToday()}`,
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
  return formatBeijingDateTime(value)
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
onMounted(async () => {
  await loadCourse()
  if (route.query.panel === 'versions' && canManageCitations.value) await openVersionManager()
})
</script>

<template>
  <div v-loading="loading">
    <div class="course-breadcrumb"><el-button link @click="$router.push('/courses')">课程中心</el-button><span>/</span><span>{{ course?.name || '教材详情' }}</span></div>
    <header class="course-detail-learning-hero" :style="{ backgroundImage: `url(${learningHeroBackground})` }">
      <div class="course-detail-hero-logo-wrap">
        <img class="course-detail-hero-logo" :src="logoUrl" alt="思政红芯" />
      </div>
      <div class="course-detail-hero-copy">
        <p class="course-detail-hero-textbook">{{ course?.name || '习近平新时代中国特色社会主义思想概论' }}</p>
        <p class="course-detail-hero-topic">专题学习</p>
        <div class="course-detail-hero-meta">
          <span>{{ course?.chapters.length || 0 }} 个教材专题</span>
          <span>预习 · 巩固 · 冲刺</span>
          <div v-if="canManageCitations" class="course-hero-actions">
            <el-dropdown trigger="click" popper-class="course-management-dropdown" @command="handleManagementCommand">
              <el-button class="hero-management-button" :icon="Setting">教材管理<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown><el-dropdown-menu><el-dropdown-item v-if="auth.isAdmin" command="history" :icon="Clock">历史版本</el-dropdown-item><el-dropdown-item command="upload" :icon="UploadFilled">上传新版教材</el-dropdown-item><el-dropdown-item command="calibration" :icon="DocumentChecked">教材引用校准</el-dropdown-item><el-dropdown-item v-if="auth.isAdmin" command="chapter" :icon="CirclePlus" divided>添加专题</el-dropdown-item><el-dropdown-item v-if="auth.isAdmin" command="delete" :icon="Delete" class="management-danger-item" divided>删除教材</el-dropdown-item></el-dropdown-menu></template>
            </el-dropdown>
          </div>
        </div>
      </div>
    </header>
    <section id="overview" class="course-overview-workspace">
      <div class="course-overview-graph-column">
        <KnowledgeGraph v-if="course" :course-name="course.name" :chapters="course.chapters" @learn="(chapterId) => startLearning(chapterId, 'preview')" />
      </div>
      <aside id="learning-path" class="course-overview-path-column" aria-label="学习路径">
        <el-card shadow="never" class="course-side-card course-learning-path-card">
          <template #header><div class="course-path-heading">学习路径</div></template>
          <div class="course-path-list">
            <div class="path-item"><span class="path-index">01</span><strong>预习空间</strong></div>
            <div class="path-item"><span class="path-index">02</span><strong>课后巩固</strong></div>
            <div class="path-item"><span class="path-index">03</span><strong>专题冲刺</strong></div>
          </div>
        </el-card>
      </aside>
    </section>
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

<style scoped>
.course-breadcrumb {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  color: var(--ink-400);
  font-size: var(--fs-aux);
}

.course-detail-learning-hero {
  position: relative;
  display: grid;
  grid-template-columns: 94px minmax(0, 1fr);
  align-items: center;
  gap: 26px;
  min-height: 164px;
  margin: 0;
  padding: 20px 32px;
  overflow: hidden;
  color: #251c20;
  background-color: #fff7f2;
  background-position: center;
  background-repeat: no-repeat;
  background-size: cover;
  border: 1px solid #f3d5d0;
  border-radius: 20px;
  box-shadow: 0 12px 26px rgba(98, 46, 48, .14);
}

.course-detail-hero-logo-wrap,
.course-detail-hero-copy {
  position: relative;
  z-index: 1;
}

.course-detail-hero-logo-wrap {
  display: grid;
  place-items: center;
  align-self: stretch;
}

.course-detail-hero-logo {
  display: block;
  width: 86px;
  height: 98px;
  object-fit: contain;
}

.course-detail-hero-copy {
  min-width: 0;
}

.course-detail-hero-textbook {
  margin: 0;
  color: #ed2028;
  font-size: clamp(22px, 2.2vw, 36px);
  font-weight: 760;
  letter-spacing: .01em;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.course-detail-hero-topic {
  margin: 8px 0 0;
  color: #201b1d;
  font-size: clamp(16px, 1.5vw, 22px);
  font-weight: 600;
  line-height: 1.45;
}

.course-detail-hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: 10px;
  color: #725d61;
  font-size: 13px;
  line-height: 1.5;
}

.course-detail-hero-meta > span {
  padding: 4px 10px;
  color: #b52329;
  background: rgba(255, 238, 233, .86);
  border: 1px solid rgba(224, 91, 85, .28);
  border-radius: 999px;
  font-weight: 700;
}

.course-hero-actions {
  display: flex;
  margin-left: auto;
}

.hero-management-button {
  color: #b52329;
  background: rgba(255, 250, 247, .8);
  border-color: rgba(224, 91, 85, .35);
}

.course-overview-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  align-items: start;
  gap: 18px;
  margin-top: 18px;
}

.course-overview-graph-column {
  min-width: 0;
}

.course-overview-graph-column :deep(.knowledge-graph-card) {
  margin-top: 0;
  border-radius: 18px;
}

.course-overview-graph-column :deep(.knowledge-graph-heading) {
  align-items: center;
  padding: 16px 20px 12px;
}

.course-overview-graph-column :deep(.knowledge-graph-heading .eyebrow) {
  display: none;
}

.course-overview-graph-column :deep(.knowledge-graph-heading h2) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 4px;
  color: #f04b5d;
  font-size: 21px;
}

.course-overview-graph-column :deep(.knowledge-graph-title-icon) {
  color: #f04b5d;
  font-size: 20px;
}

.course-overview-graph-column :deep(.knowledge-graph-heading p) {
  font-size: 11px;
}

.course-overview-graph-column :deep(.knowledge-graph-stage),
.course-overview-graph-column :deep(.knowledge-overview),
.course-overview-graph-column :deep(.knowledge-radial) {
  min-height: 460px;
}

.course-overview-graph-column :deep(.knowledge-overview) {
  min-width: 0;
}

.course-overview-graph-column :deep(.course-knowledge-core) {
  width: 148px;
  height: 148px;
  padding: 16px;
}

.course-overview-graph-column :deep(.course-knowledge-core strong) {
  font-size: 16px;
}

.course-overview-graph-column :deep(.chapter-bubble) {
  width: 80px;
  min-height: 80px;
  padding: 8px;
  border-width: 1px;
  border-radius: 50%;
}

.course-overview-graph-column :deep(.chapter-bubble strong) {
  font-size: 15px;
}

.course-overview-graph-column :deep(.chapter-bubble span) {
  -webkit-line-clamp: 2;
  font-size: 10px;
  line-height: 1.25;
}

.course-overview-graph-column :deep(.knowledge-graph-footer) {
  padding: 10px 18px;
  font-size: 11px;
}

.course-overview-path-column {
  min-width: 0;
}

.course-detail-layout {
  display: block;
  margin-top: 18px;
}

.course-learning-path-card {
  border: 1px solid #eee5ec;
  border-radius: 16px;
  box-shadow: 0 8px 20px rgba(48, 33, 62, .07);
}

.course-learning-path-card :deep(.el-card__header) {
  padding: 17px 20px 14px;
  border-bottom: 0;
}

.course-learning-path-card :deep(.el-card__body) {
  padding: 0 16px 18px;
}

.course-path-heading {
  color: #281936;
  font-size: 21px;
  font-weight: 700;
}

.course-path-list {
  display: grid;
  gap: 12px;
}

.course-learning-path-card .path-item {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 72px;
  margin: 0;
  padding: 10px 14px;
  background: #fff0f1;
  border: 0;
  border-left: 5px solid #ff2346;
  border-radius: 0 11px 11px 0;
}

.course-learning-path-card .path-index {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  color: #ef3650;
  background: #fff;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 700;
}

.course-learning-path-card .path-item strong {
  color: #5a3944;
  font-size: 16px;
}

.course-section-heading {
  margin: 26px 0 var(--space-4);
}

.chapter-list {
  display: grid;
  gap: var(--space-3);
}

.chapter-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}

.chapter-card :deep(.el-card__body) {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
}

.chapter-number {
  color: var(--blue-600);
  font-size: var(--fs-section);
  font-weight: var(--fw-bold);
}

.chapter-main {
  min-width: 0;
}

.chapter-label {
  margin-bottom: var(--space-1);
  color: var(--blue-600);
  font-size: var(--fs-meta);
  font-weight: var(--fw-bold);
  letter-spacing: 0.08em;
}

.chapter-main h3 {
  margin: 0 0 var(--space-2);
  color: var(--ink-900);
  font-size: var(--fs-card-title);
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: normal;
}

.chapter-main p {
  margin: 0;
  color: var(--ink-600);
  font-size: var(--fs-aux);
  line-height: 1.7;
}

.chapter-actions {
  display: flex;
  gap: var(--space-2);
  white-space: nowrap;
}

.chapter-actions :deep(.el-button) {
  margin-left: 0;
}

:deep(.el-dialog) {
  max-width: calc(100vw - 32px);
}

@media (max-width: 1023px) {
  .course-overview-workspace {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 767px) {
  .course-detail-learning-hero {
    grid-template-columns: 70px minmax(0, 1fr);
    gap: 22px;
    padding: 22px 20px;
  }

  .course-detail-hero-logo { width: 66px; height: 80px; }
  .course-detail-hero-textbook { font-size: 24px; }
  .course-detail-hero-topic { font-size: 16px; }
  .course-detail-hero-meta { margin-top: 10px; }

  .course-overview-graph-column :deep(.knowledge-graph-stage),
  .course-overview-graph-column :deep(.knowledge-overview),
  .course-overview-graph-column :deep(.knowledge-radial) {
    min-height: 400px;
  }

  .chapter-card :deep(.el-card__body) {
    grid-template-columns: auto minmax(0, 1fr);
    align-items: start;
    gap: var(--space-3);
    padding: var(--space-4);
  }

  .chapter-number {
    grid-column: 1;
    grid-row: 1;
    display: grid;
    width: 36px;
    height: 36px;
    place-items: center;
    background: var(--blue-50);
    border-radius: var(--radius-input);
    font-size: var(--fs-aux);
  }

  .chapter-main {
    grid-column: 2;
    grid-row: 1;
  }

  .chapter-actions {
    grid-column: 1 / -1;
    grid-row: 2;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
  }

  .chapter-actions :deep(.el-button) {
    width: 100%;
    min-width: 0;
    padding-inline: var(--space-2);
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 389px) {
  .course-detail-learning-hero {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .course-detail-hero-logo-wrap {
    justify-items: start;
  }

  .course-detail-hero-meta .course-hero-actions {
    width: 100%;
    margin-left: 0;
  }
}
</style>

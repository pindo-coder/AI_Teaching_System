<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Collection, Connection, DocumentChecked, Link, Refresh, Search, UploadFilled,
} from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import {
  knowledgeApi, type KnowledgeDocument, type MaterialSuggestion,
} from '@/api/knowledge'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import type { CourseDetail } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

type MaterialTab = 'central' | 'textbook' | 'local' | 'unclassified'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const uploading = ref(false)
const activeTab = ref<MaterialTab>('central')
const documents = ref<KnowledgeDocument[]>([])
const courses = ref<CourseDetail[]>([])
const teachingClasses = ref<TeachingClass[]>([])
const keyword = ref('')
const statusFilter = ref('')
const uploadVisible = ref(false)
const relationVisible = ref(false)
const classifyVisible = ref(false)
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement>()
const activeDocument = ref<KnowledgeDocument | null>(null)
const suggestions = ref<MaterialSuggestion[]>([])
const suggestionLoading = ref(false)

const uploadForm = reactive({
  source_mode: 'file' as 'file' | 'url', source_title: '', publisher: '', published_date: '',
  source_url: '', applicable_scope: '', version_label: '', supersedes_document_id: undefined as number | undefined,
  access_policy: 'full_preview' as KnowledgeDocument['access_policy'], course_ids: [] as number[],
  chapter_ids: [] as number[], teaching_class_ids: [] as number[], knowledge_tags_text: '',
})
const scopeForm = reactive({ course_ids: [] as number[], chapter_ids: [] as number[], teaching_class_ids: [] as number[], knowledge_tags_text: '' })
const classifyForm = reactive({ material_type: 'central' as 'central' | 'textbook' | 'local', publisher: '', published_date: '', applicable_scope: '' })

const tabMeta: Record<MaterialTab, { label: string; description: string }> = {
  central: { label: '中央材料', description: '经管理员核验发布的中央文件、重要讲话与权威文献' },
  textbook: { label: '教材正文', description: '沿用现有教材版本、专题拆分、页码校准与原页引用' },
  local: { label: '地方材料', description: '按教学班使用的地方实践材料与教学补充资料' },
  unclassified: { label: '待分类', description: '升级前的补充资料，需管理员确认资料层级后才能参与新检索' },
}

const allChapters = computed(() => courses.value
  .filter((course) => uploadForm.course_ids.includes(course.id))
  .flatMap((course) => course.chapters.map((chapter) => ({ ...chapter, courseName: course.name }))))
const scopeChapters = computed(() => courses.value
  .filter((course) => scopeForm.course_ids.includes(course.id))
  .flatMap((course) => course.chapters.map((chapter) => ({ ...chapter, courseName: course.name }))))
const filteredDocuments = computed(() => documents.value.filter((item) => {
  if (item.material_type !== activeTab.value) return false
  if (statusFilter.value && item.review_status !== statusFilter.value) return false
  const term = keyword.value.trim().toLowerCase()
  if (!term) return true
  return [item.source_title, item.publisher, item.original_filename, item.applicable_scope, ...item.knowledge_tags]
    .filter(Boolean).some((value) => String(value).toLowerCase().includes(term))
}))
const counts = computed(() => ({
  central: documents.value.filter((item) => item.material_type === 'central').length,
  textbook: documents.value.filter((item) => item.material_type === 'textbook').length,
  local: documents.value.filter((item) => item.material_type === 'local').length,
  unclassified: documents.value.filter((item) => item.material_type === 'unclassified').length,
}))

async function loadData() {
  loading.value = true
  try {
    const [materialResponse, courseResponse, classResponse] = await Promise.all([
      knowledgeApi.materials(), courseApi.list(), teachingClassApi.list(),
    ])
    documents.value = materialResponse.data.data
    courses.value = await Promise.all(courseResponse.data.data.map(async (item) => (await courseApi.detail(item.id)).data.data))
    teachingClasses.value = classResponse.data.data
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '资料中心加载失败'))
  } finally { loading.value = false }
}

function resetUpload() {
  Object.assign(uploadForm, {
    source_mode: 'file', source_title: '', publisher: '', published_date: '', source_url: '',
    applicable_scope: '', version_label: '', supersedes_document_id: undefined,
    access_policy: 'full_preview', course_ids: [], chapter_ids: [], teaching_class_ids: [], knowledge_tags_text: '',
  })
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function openUpload() {
  resetUpload()
  uploadVisible.value = true
}

function chooseFile(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
  if (selectedFile.value && !uploadForm.source_title) uploadForm.source_title = selectedFile.value.name.replace(/\.[^.]+$/, '')
}

function tags(value: string) { return value.split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean) }

async function submitUpload() {
  if (!uploadForm.source_title.trim() || !uploadForm.publisher.trim() || !uploadForm.published_date) return ElMessage.warning('请填写标题、来源单位和发布日期')
  if (activeTab.value === 'central' && !auth.isAdmin) return ElMessage.error('只有管理员可以导入中央材料')
  if (activeTab.value === 'local' && !uploadForm.course_ids.length && !uploadForm.chapter_ids.length) return ElMessage.warning('地方材料至少需要关联一本教材或一个专题')
  if (activeTab.value === 'local' && !auth.isAdmin && !uploadForm.teaching_class_ids.length) return ElMessage.warning('教师上传地方材料必须选择自己的教学班')
  if (uploadForm.source_mode === 'file' && !selectedFile.value) return ElMessage.warning('请选择资料文件')
  if (uploadForm.source_mode === 'url' && !uploadForm.source_url.trim()) return ElMessage.warning('请输入权威原文网址')
  uploading.value = true
  try {
    let document: KnowledgeDocument
    const common = {
      source_title: uploadForm.source_title.trim(), publisher: uploadForm.publisher.trim(),
      published_date: uploadForm.published_date, applicable_scope: uploadForm.applicable_scope.trim() || undefined,
      version_label: uploadForm.version_label.trim() || undefined, supersedes_document_id: uploadForm.supersedes_document_id,
      access_policy: uploadForm.access_policy, course_ids: uploadForm.course_ids,
      chapter_ids: uploadForm.chapter_ids, knowledge_tags: tags(uploadForm.knowledge_tags_text),
    }
    if (uploadForm.source_mode === 'url') {
      document = (await knowledgeApi.importMaterialUrl({ ...common, source_url: uploadForm.source_url.trim() })).data.data
    } else {
      const payload = new FormData()
      payload.append('file', selectedFile.value!)
      payload.append('material_type', activeTab.value)
      Object.entries(common).forEach(([key, value]) => {
        if (value === undefined) return
        payload.append(key, Array.isArray(value) ? JSON.stringify(value) : String(value))
      })
      payload.append('teaching_class_ids', JSON.stringify(uploadForm.teaching_class_ids))
      document = (await knowledgeApi.uploadMaterial(payload)).data.data
    }
    ElMessage.success(activeTab.value === 'central' ? '原文已入库，请确认关联后发布' : '地方材料已加入所选教学班')
    uploadVisible.value = false
    await loadData()
    if (activeTab.value === 'central') await openRelations(document)
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '资料导入失败'))
  } finally { uploading.value = false }
}

async function openRelations(document: KnowledgeDocument) {
  activeDocument.value = document
  Object.assign(scopeForm, {
    course_ids: [...document.course_ids], chapter_ids: [...document.chapter_ids],
    teaching_class_ids: [...document.teaching_class_ids], knowledge_tags_text: document.knowledge_tags.join('、'),
  })
  relationVisible.value = true
  suggestions.value = []
  suggestionLoading.value = true
  try { suggestions.value = (await knowledgeApi.materialSuggestions(document.id)).data.data }
  catch (error: unknown) { ElMessage.warning(getErrorMessage(error, '暂未生成关联建议，可手动选择')) }
  finally { suggestionLoading.value = false }
}

function adoptSuggestion(item: MaterialSuggestion) {
  if (!scopeForm.course_ids.includes(item.course_id)) scopeForm.course_ids.push(item.course_id)
  if (item.chapter_id && !scopeForm.chapter_ids.includes(item.chapter_id)) scopeForm.chapter_ids.push(item.chapter_id)
}

async function saveScopes() {
  if (!activeDocument.value) return
  if (activeDocument.value.material_type === 'central' && !scopeForm.course_ids.length) return ElMessage.warning('中央材料至少需要关联一本教材')
  try {
    await knowledgeApi.updateMaterialScopes(activeDocument.value.id, {
      course_ids: scopeForm.course_ids, chapter_ids: scopeForm.chapter_ids,
      teaching_class_ids: scopeForm.teaching_class_ids, knowledge_tags: tags(scopeForm.knowledge_tags_text),
    })
    ElMessage.success('适用范围已确认')
    relationVisible.value = false
    await loadData()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '适用范围保存失败')) }
}

async function publish(document: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(`发布“${document.source_title}”后将进入AI权威检索，是否继续？`, '发布资料', { type: 'warning' })
    await knowledgeApi.publishMaterial(document.id)
    ElMessage.success('资料已发布')
    await loadData()
  } catch (error: unknown) {
    if (error !== 'cancel') ElMessage.error(getErrorMessage(error, '发布失败'))
  }
}

async function archiveDocument(document: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(`归档后“${document.source_title}”不再参与新回答，但历史引用仍可核对。`, '归档资料', { type: 'warning' })
    await knowledgeApi.archiveMaterial(document.id)
    ElMessage.success('资料已归档')
    await loadData()
  } catch (error: unknown) { if (error !== 'cancel') ElMessage.error(getErrorMessage(error, '归档失败')) }
}

async function removeDocument(document: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(`确定删除未发布资料“${document.source_title}”及其索引吗？`, '删除资料', { type: 'warning' })
    await knowledgeApi.remove(document.id)
    ElMessage.success('资料已删除')
    await loadData()
  } catch (error: unknown) { if (error !== 'cancel') ElMessage.error(getErrorMessage(error, '删除失败')) }
}

async function reindex(document: KnowledgeDocument) {
  try { await knowledgeApi.reindex(document.id); ElMessage.success('索引已重建'); await loadData() }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '重建索引失败')) }
}

function openClassification(document: KnowledgeDocument) {
  activeDocument.value = document
  Object.assign(classifyForm, { material_type: 'central', publisher: '', published_date: '', applicable_scope: '' })
  classifyVisible.value = true
}

async function classify() {
  if (!activeDocument.value) return
  try {
    await knowledgeApi.classifyMaterial(activeDocument.value.id, {
      material_type: classifyForm.material_type, publisher: classifyForm.publisher || undefined,
      published_date: classifyForm.published_date || undefined, applicable_scope: classifyForm.applicable_scope || undefined,
    })
    ElMessage.success('资料分类已确认')
    classifyVisible.value = false
    await loadData()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '分类失败')) }
}

function courseName(id: number | null) { return courses.value.find((item) => item.id === id)?.name || (id ? `教材 ${id}` : '多教材资料') }
function statusLabel(value: string) { return ({ pending: '待确认', published: '已发布', archived: '已归档', rejected: '已驳回' } as Record<string, string>)[value] || value }
function statusType(value: string) { return value === 'published' ? 'success' : value === 'archived' ? 'info' : 'warning' }
function materialLabel(value: string) { return ({ central: '中央材料', textbook: '教材正文', local: '地方材料', unclassified: '待分类' } as Record<string, string>)[value] || value }
function canManageMaterial(document: KnowledgeDocument) { return auth.isAdmin || document.owner_user_id === auth.user?.id }
function canEditScopes(document: KnowledgeDocument) { return document.material_type === 'local' ? canManageMaterial(document) : document.material_type === 'central' && auth.isAdmin }
function canReindex(document: KnowledgeDocument) { return document.material_type === 'textbook' || canManageMaterial(document) }
function openExternal(url: string) { window.open(url, '_blank', 'noopener,noreferrer') }

onMounted(loadData)
</script>

<template>
  <div class="material-center-page">
    <header class="material-center-hero">
      <div><p class="eyebrow">AUTHORITY MATERIAL CENTER</p><h1>思政教学资料中心</h1><p>以中央材料校准方向、以教材正文组织学习、以地方材料联系实践。所有AI引用均来自可核验原文。</p><div class="material-priority"><span class="central">中央材料</span><i>›</i><span class="textbook">教材正文</span><i>›</i><span class="local">地方材料</span></div></div>
      <div class="material-hero-metrics"><article><strong>{{ counts.central }}</strong><span>中央材料</span></article><article><strong>{{ counts.textbook }}</strong><span>教材文档</span></article><article><strong>{{ counts.local }}</strong><span>地方材料</span></article></div>
    </header>

    <section class="material-command-bar">
      <div class="material-tabs">
        <button v-for="tab in (['central', 'textbook', 'local'] as MaterialTab[])" :key="tab" :class="{ active: activeTab === tab }" @click="activeTab = tab; statusFilter = ''"><span>{{ tabMeta[tab].label }}</span><small>{{ counts[tab] }}</small></button>
        <button v-if="auth.isAdmin && counts.unclassified" :class="{ active: activeTab === 'unclassified' }" @click="activeTab = 'unclassified'; statusFilter = ''"><span>待分类</span><small>{{ counts.unclassified }}</small></button>
      </div>
      <div class="material-actions">
        <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索标题、来源或知识点" />
        <el-select v-model="statusFilter" clearable placeholder="全部状态"><el-option label="待确认" value="pending" /><el-option label="已发布" value="published" /><el-option label="已归档" value="archived" /></el-select>
        <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        <el-button v-if="activeTab === 'central' && auth.isAdmin" type="primary" :icon="UploadFilled" @click="openUpload">导入中央材料</el-button>
        <el-button v-if="activeTab === 'local'" type="primary" :icon="UploadFilled" @click="openUpload">导入地方材料</el-button>
        <el-button v-if="activeTab === 'textbook'" type="primary" :icon="DocumentChecked" @click="router.push('/courses')">进入教材管理</el-button>
      </div>
    </section>

    <section class="material-section-heading"><div><p class="eyebrow">{{ tabMeta[activeTab].label }}</p><h2>{{ tabMeta[activeTab].description }}</h2></div><span v-if="activeTab === 'central'">相关性达标后中央材料优先，但不会脱离当前专题</span><span v-else-if="activeTab === 'local'">教师资料默认仅对所选教学班生效</span><span v-else-if="activeTab === 'textbook'">当前版本与原页校准规则保持不变</span></section>

    <div v-loading="loading" class="material-list">
      <article v-for="item in filteredDocuments" :key="item.id" class="material-card" :class="`material-card-${item.material_type}`">
        <div class="material-card-marker"><span>{{ materialLabel(item.material_type) }}</span><strong>{{ String(item.id).padStart(2, '0') }}</strong></div>
        <div class="material-card-main">
          <div class="material-card-title"><div><h3>{{ item.source_title }}</h3><p>{{ item.publisher || courseName(item.course_id) }}<template v-if="item.published_date"> · {{ item.published_date }}</template></p></div><el-tag :type="statusType(item.review_status)">{{ statusLabel(item.review_status) }}</el-tag></div>
          <p class="material-scope-copy">{{ item.applicable_scope || (item.material_type === 'textbook' ? '当前教材版本与专题范围' : '尚未填写适用范围') }}</p>
          <div class="material-chips"><span v-for="tag in item.knowledge_tags" :key="tag">{{ tag }}</span><span v-if="item.course_ids.length">已关联 {{ item.course_ids.length }} 本教材</span><span v-if="item.chapter_ids.length">{{ item.chapter_ids.length }} 个专题</span><span v-if="item.teaching_class_ids.length">{{ item.teaching_class_ids.length }} 个教学班</span><span>原文分块 {{ item.chunk_count }}</span></div>
        </div>
        <div class="material-card-ops">
          <el-button v-if="item.source_url" link type="primary" :icon="Link" @click="openExternal(item.source_url)">查看原文</el-button>
          <el-button v-if="canEditScopes(item)" link type="primary" :icon="Connection" @click="openRelations(item)">关联范围</el-button>
          <el-button v-if="item.material_type === 'central' && item.review_status === 'pending' && auth.isAdmin" link type="success" @click="publish(item)">确认发布</el-button>
          <el-button v-if="item.material_type === 'textbook' && item.source_type === 'pdf'" link type="primary" @click="router.push(`/knowledge/documents/${item.id}/calibrate`)">引用校准</el-button>
          <el-button v-if="item.material_type === 'textbook'" link @click="router.push(`/courses/${item.course_id}`)">版本管理</el-button>
          <el-button v-if="item.material_type === 'unclassified' && auth.isAdmin" link type="warning" @click="openClassification(item)">确认分类</el-button>
          <el-button v-if="canReindex(item)" link @click="reindex(item)">重建索引</el-button>
          <el-button v-if="item.review_status === 'published' && item.material_type !== 'textbook' && canManageMaterial(item)" link type="warning" :icon="Collection" @click="archiveDocument(item)">归档</el-button>
          <el-button v-if="item.review_status !== 'published' && item.material_type !== 'textbook' && canManageMaterial(item)" link type="danger" @click="removeDocument(item)">删除</el-button>
        </div>
      </article>
      <el-empty v-if="!loading && !filteredDocuments.length" description="当前分类暂无资料" />
    </div>

    <el-dialog v-model="uploadVisible" :title="activeTab === 'central' ? '导入中央材料' : '导入地方材料'" width="760px" destroy-on-close>
      <el-alert v-if="activeTab === 'central'" title="上传后不会立即参与检索，需要确认教材与专题关联后由管理员发布。" type="info" :closable="false" show-icon />
      <el-form label-position="top" class="material-upload-form">
        <el-form-item v-if="activeTab === 'central'" label="导入方式"><el-radio-group v-model="uploadForm.source_mode"><el-radio-button value="file">上传文件</el-radio-button><el-radio-button value="url">权威网页</el-radio-button></el-radio-group></el-form-item>
        <el-form-item v-if="uploadForm.source_mode === 'file'" label="原始资料文件" required><input ref="fileInput" class="file-input" type="file" accept=".pdf,.txt,.md,.markdown" @change="chooseFile" /></el-form-item>
        <el-form-item v-else label="权威原文 HTTPS 地址" required><el-input v-model="uploadForm.source_url" placeholder="https://..." /></el-form-item>
        <div class="material-form-grid"><el-form-item label="资料标题" required><el-input v-model="uploadForm.source_title" maxlength="255" /></el-form-item><el-form-item label="发布机关 / 来源单位" required><el-input v-model="uploadForm.publisher" maxlength="255" /></el-form-item></div>
        <div class="material-form-grid"><el-form-item label="发布日期" required><el-date-picker v-model="uploadForm.published_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item><el-form-item label="版本标识"><el-input v-model="uploadForm.version_label" placeholder="如：2026年7月版" /></el-form-item></div>
        <el-form-item label="适用范围"><el-input v-model="uploadForm.applicable_scope" maxlength="500" placeholder="如：新时代党的建设专题；山东省高校实践案例" /></el-form-item>
        <el-form-item label="关联教材"><el-select v-model="uploadForm.course_ids" multiple filterable style="width:100%"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item>
        <el-form-item label="关联专题"><el-select v-model="uploadForm.chapter_ids" multiple filterable style="width:100%"><el-option v-for="chapter in allChapters" :key="chapter.id" :label="`${chapter.courseName} · ${chapter.title}`" :value="chapter.id" /></el-select></el-form-item>
        <el-form-item v-if="activeTab === 'local'" label="使用教学班" :required="!auth.isAdmin"><el-select v-model="uploadForm.teaching_class_ids" multiple filterable style="width:100%"><el-option v-for="item in teachingClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" /></el-select><div class="form-tip">管理员不选择教学班时可作为当前教材的公共地方材料；教师必须选择自己管理的教学班。</div></el-form-item>
        <el-form-item label="知识点标签"><el-input v-model="uploadForm.knowledge_tags_text" placeholder="使用逗号分隔，如：全过程人民民主、全面从严治党" /></el-form-item>
        <el-form-item label="原文访问权限"><el-radio-group v-model="uploadForm.access_policy"><el-radio-button value="citation_only">仅引用页</el-radio-button><el-radio-button value="full_preview">全文预览</el-radio-button><el-radio-button value="download">允许下载</el-radio-button></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="uploadVisible = false">取消</el-button><el-button type="primary" :loading="uploading" @click="submitUpload">{{ activeTab === 'central' ? '入库并生成关联建议' : '导入教学班资料' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="relationVisible" title="确认资料关联范围" width="820px" destroy-on-close>
      <div v-if="activeDocument" class="scope-dialog-heading"><strong>{{ activeDocument.source_title }}</strong><span>系统只提供关联建议，最终范围必须由管理者确认。</span></div>
      <section class="suggestion-panel" v-loading="suggestionLoading"><div class="suggestion-title"><strong>智能关联建议</strong><span>点击采纳后仍可继续调整</span></div><div class="suggestion-list"><button v-for="item in suggestions" :key="`${item.course_id}-${item.chapter_id}`" type="button" @click="adoptSuggestion(item)"><span>{{ item.course_name }}</span><strong>{{ item.chapter_title || '全教材' }}</strong><small>匹配度 {{ Math.round(item.score * 100) }}%</small></button><el-empty v-if="!suggestionLoading && !suggestions.length" :image-size="50" description="暂无可靠建议，请手动选择" /></div></section>
      <el-form label-position="top"><el-form-item label="确认适用教材"><el-select v-model="scopeForm.course_ids" multiple filterable style="width:100%"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item><el-form-item label="确认适用专题"><el-select v-model="scopeForm.chapter_ids" multiple filterable style="width:100%"><el-option v-for="chapter in scopeChapters" :key="chapter.id" :label="`${chapter.courseName} · ${chapter.title}`" :value="chapter.id" /></el-select></el-form-item><el-form-item v-if="activeDocument?.material_type === 'local'" label="使用教学班"><el-select v-model="scopeForm.teaching_class_ids" multiple style="width:100%"><el-option v-for="item in teachingClasses" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="知识点标签"><el-input v-model="scopeForm.knowledge_tags_text" /></el-form-item></el-form>
      <template #footer><el-button @click="relationVisible = false">取消</el-button><el-button type="primary" @click="saveScopes">确认关联范围</el-button></template>
    </el-dialog>

    <el-dialog v-model="classifyVisible" title="确认历史资料分类" width="560px"><el-alert title="分类后将重建索引；中央或地方材料仍需确认适用范围后才能正式发布。" type="warning" :closable="false" show-icon /><el-form label-position="top"><el-form-item label="资料类型"><el-select v-model="classifyForm.material_type" style="width:100%"><el-option label="中央材料" value="central" /><el-option label="教材正文" value="textbook" /><el-option label="地方材料" value="local" /></el-select></el-form-item><el-form-item label="发布机关 / 来源单位"><el-input v-model="classifyForm.publisher" /></el-form-item><el-form-item label="发布日期"><el-date-picker v-model="classifyForm.published_date" value-format="YYYY-MM-DD" type="date" style="width:100%" /></el-form-item><el-form-item label="适用范围"><el-input v-model="classifyForm.applicable_scope" /></el-form-item></el-form><template #footer><el-button @click="classifyVisible = false">取消</el-button><el-button type="primary" @click="classify">确认分类并重建索引</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.material-center-page{display:grid;gap:24px}.material-center-hero{display:grid;grid-template-columns:minmax(0,1fr) 420px;gap:40px;padding:48px 54px;color:#fff;background:radial-gradient(circle at 88% 12%,rgba(103,236,244,.28),transparent 30%),linear-gradient(120deg,#183f98,#286ac9 52%,#168a91);border-radius:28px;box-shadow:0 24px 55px rgba(18,58,128,.2)}.material-center-hero h1{margin:7px 0 12px;font-size:42px}.material-center-hero p{max-width:760px;color:#dceaff;line-height:1.8}.material-priority{display:flex;align-items:center;gap:10px;margin-top:22px}.material-priority span{padding:7px 14px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.25);border-radius:999px}.material-priority .central{color:#ffe1dc}.material-priority .textbook{color:#dce8ff}.material-priority .local{color:#d8ffec}.material-priority i{color:#b9d7ff;font-size:22px}.material-hero-metrics{display:grid;grid-template-columns:repeat(3,1fr);align-content:center;gap:12px}.material-hero-metrics article{display:grid;place-items:center;min-height:126px;background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.22);border-radius:20px;backdrop-filter:blur(10px)}.material-hero-metrics strong{font-size:34px}.material-hero-metrics span{color:#dceaff}.material-command-bar{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:12px;background:#fff;border:1px solid #dde6f3;border-radius:18px;box-shadow:0 12px 30px rgba(35,63,112,.08)}.material-tabs{display:flex;gap:6px}.material-tabs button{display:flex;align-items:center;gap:8px;padding:12px 17px;color:#53647c;background:transparent;border:0;border-radius:12px;cursor:pointer}.material-tabs button.active{color:#fff;background:linear-gradient(120deg,#245bc5,#4970db);box-shadow:0 8px 18px rgba(38,88,190,.22)}.material-tabs small{display:grid;min-width:22px;height:22px;place-items:center;background:rgba(125,145,180,.14);border-radius:50%}.material-actions{display:flex;align-items:center;gap:9px}.material-actions .el-input{width:260px}.material-actions .el-select{width:126px}.material-section-heading{display:flex;align-items:flex-end;justify-content:space-between}.material-section-heading h2{margin:5px 0 0;font-size:25px}.material-section-heading>span{color:#77879e}.material-list{display:grid;gap:14px;min-height:180px}.material-card{display:grid;grid-template-columns:112px minmax(0,1fr) 180px;gap:22px;align-items:center;min-height:170px;padding:22px;background:#fff;border:1px solid #dfe7f2;border-radius:20px;box-shadow:0 12px 32px rgba(30,56,102,.07)}.material-card-marker{display:grid;height:118px;place-items:center;align-content:center;gap:8px;color:#fff;background:linear-gradient(145deg,#9e2943,#d2594e);border-radius:18px}.material-card-textbook .material-card-marker{background:linear-gradient(145deg,#2558bd,#4f78d9)}.material-card-local .material-card-marker{background:linear-gradient(145deg,#16806e,#3cac84)}.material-card-unclassified .material-card-marker{background:linear-gradient(145deg,#6c7789,#9aa4b4)}.material-card-marker span{font-size:12px}.material-card-marker strong{font-size:30px}.material-card-title{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.material-card-title h3{margin:0 0 6px;font-size:21px}.material-card-title p,.material-scope-copy{margin:0;color:#73839a}.material-scope-copy{margin-top:15px}.material-chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}.material-chips span{padding:5px 9px;color:#55708f;background:#f1f5fa;border-radius:7px;font-size:12px}.material-card-ops{display:grid;justify-items:start;gap:2px;padding-left:10px;border-left:1px solid #e6ebf2}.material-upload-form{margin-top:18px}.material-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.form-tip{margin-top:5px;color:#8794a7;font-size:12px}.scope-dialog-heading{display:flex;flex-direction:column;gap:4px;margin-bottom:16px;padding:15px 17px;background:#f3f7fd;border-radius:12px}.scope-dialog-heading span{color:#73839b}.suggestion-panel{margin-bottom:18px;padding:16px;background:linear-gradient(135deg,#f5f8ff,#f2fbfb);border:1px solid #dce7f5;border-radius:14px}.suggestion-title{display:flex;justify-content:space-between}.suggestion-title span{color:#7a899e}.suggestion-list{display:flex;gap:9px;overflow-x:auto;margin-top:12px}.suggestion-list button{display:grid;min-width:170px;gap:4px;padding:11px;text-align:left;background:#fff;border:1px solid #d5e0ef;border-radius:10px;cursor:pointer}.suggestion-list button:hover{border-color:#4a7ddb}.suggestion-list span,.suggestion-list small{color:#74859c}.suggestion-list strong{color:#243a5d}.file-input{width:100%;padding:10px;background:#f7f9fc;border:1px solid #d8e0eb;border-radius:8px}
@media(max-width:1180px){.material-center-hero{grid-template-columns:1fr}.material-command-bar{align-items:stretch;flex-direction:column}.material-actions{flex-wrap:wrap}.material-card{grid-template-columns:100px minmax(0,1fr)}.material-card-ops{grid-column:1/-1;display:flex;flex-wrap:wrap;border-top:1px solid #e6ebf2;border-left:0;padding-top:12px}}@media(max-width:720px){.material-center-hero{padding:32px 24px}.material-center-hero h1{font-size:32px}.material-hero-metrics{grid-template-columns:1fr 1fr}.material-command-bar,.material-tabs,.material-actions{align-items:stretch;flex-direction:column}.material-actions .el-input,.material-actions .el-select{width:100%}.material-card{grid-template-columns:1fr}.material-card-marker{height:80px}.material-card-ops{grid-column:auto}.material-form-grid{grid-template-columns:1fr}}
</style>

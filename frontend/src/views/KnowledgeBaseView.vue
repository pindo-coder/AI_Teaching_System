<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Clock, Collection, Connection, DocumentChecked, Link, Refresh, Search, UploadFilled,
} from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import {
  knowledgeApi, type KnowledgeDocument, type MaterialBatch, type MaterialBatchPreview,
  type MaterialBatchSummary, type MaterialPreviewRow, type MaterialSuggestion,
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
const batchVisible = ref(false)
const batchLoading = ref(false)
const batchStep = ref<'upload' | 'preview' | 'processing'>('upload')
const batchSourceMode = ref<'file' | 'text'>('file')
const batchUrlText = ref('')
const batchFile = ref<File | null>(null)
const batchPreview = ref<MaterialBatchPreview | null>(null)
const batchSheetName = ref('')
const batchRows = ref<MaterialPreviewRow[]>([])
const batchResult = ref<MaterialBatch | null>(null)
const taskCenterVisible = ref(false)
const taskLoading = ref(false)
const batchTasks = ref<MaterialBatchSummary[]>([])
const knownBatchStatuses = new Map<number, string>()
let taskHistoryInitialized = false
let batchPollTimer: number | undefined
let taskPollTimer: number | undefined
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
const batchForm = reactive({ course_ids: [] as number[], chapter_ids: [] as number[], access_policy: 'full_preview', publisher: '', applicable_scope: '', knowledge_tags_text: '' })
const batchMapping = reactive<Record<string, string>>({})
const mappingFields = [
  ['source_url', '原文网址'], ['source_title', '材料标题'], ['publisher', '发布机关'],
  ['published_date', '发布日期'], ['applicable_scope', '适用范围'],
  ['version_label', '版本标识'], ['knowledge_tags', '知识点标签'],
]

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
const currentBatchSheet = computed(() => batchPreview.value?.sheets.find((item) => item.name === batchSheetName.value) || null)
const batchChapters = computed(() => courses.value
  .filter((course) => batchForm.course_ids.includes(course.id))
  .flatMap((course) => course.chapters.map((chapter) => ({ ...chapter, courseName: course.name }))))
const selectedBatchRows = computed(() => batchRows.value.filter((item) => item.selected && !item.errors.length))
const batchIssueCount = computed(() => batchRows.value.filter((item) => item.errors.length || item.warnings.length).length)
const activeBatchCount = computed(() => batchTasks.value.filter((item) => ['queued', 'processing'].includes(item.status)).length)
const BATCH_MAX_ITEMS = 500

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

function openBatchImport() {
  batchVisible.value = true
  batchStep.value = 'upload'
  batchFile.value = null
  batchSourceMode.value = 'file'
  batchUrlText.value = ''
  batchPreview.value = null
  batchSheetName.value = ''
  batchRows.value = []
  batchResult.value = null
  Object.assign(batchForm, { course_ids: [], chapter_ids: [], access_policy: 'full_preview', publisher: '', applicable_scope: '', knowledge_tags_text: '' })
}

function chooseBatchFile(event: Event) {
  batchFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

function normalizePreviewDate(value: string) {
  const matched = value.trim().match(/(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})/)
  if (matched) return `${matched[1]}-${matched[2].padStart(2, '0')}-${matched[3].padStart(2, '0')}`
  return /^20\d{2}-\d{2}-\d{2}$/.test(value.trim().slice(0, 10)) ? value.trim().slice(0, 10) : ''
}

function validateBatchRow(row: MaterialPreviewRow) {
  const errors: string[] = []
  if (!/^https:\/\/[^\s]+$/i.test(row.source_url.trim())) errors.push('网址必须是 HTTPS 地址')
  const preserved: string[] = row.warnings.filter((item) => item === '文件内重复网址')
  if (!row.source_title.trim()) preserved.push('标题将尝试从网页识别')
  if (!row.publisher.trim()) preserved.push('发布机关将尝试从网页识别')
  row.published_date = normalizePreviewDate(row.published_date)
  if (!row.published_date) preserved.push('日期将尝试从网页识别')
  row.errors = errors
  row.warnings = [...new Set(preserved)]
}

function loadBatchSheet(name: string) {
  const sheet = batchPreview.value?.sheets.find((item) => item.name === name)
  if (!sheet) return
  batchSheetName.value = name
  Object.keys(batchMapping).forEach((key) => delete batchMapping[key])
  sheet.mapping.forEach((item) => { batchMapping[item.field] = item.column })
  batchRows.value = sheet.rows.map((item) => ({ ...item, knowledge_tags: [...item.knowledge_tags], errors: [...item.errors], warnings: [...item.warnings], raw_data: { ...item.raw_data } }))
}

function applyBatchMapping() {
  for (const row of batchRows.value) {
    for (const [field] of mappingFields) {
      const column = batchMapping[field]
      if (!column) continue
      const value = row.raw_data[column] || ''
      if (field === 'knowledge_tags') row.knowledge_tags = tags(value)
      else (row as unknown as Record<string, unknown>)[field] = value
    }
    validateBatchRow(row)
  }
  ElMessage.success('字段映射已重新应用')
}

async function previewBatch() {
  if (batchSourceMode.value === 'text') {
    const urls = batchUrlText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
    if (!urls.length) return ElMessage.warning('请粘贴至少一个网址')
    if (urls.length > BATCH_MAX_ITEMS) return ElMessage.warning(`单个批次最多导入${BATCH_MAX_ITEMS}条网址`)
    batchPreview.value = {
      filename: '粘贴网址',
      sheets: [{
        name: '网址列表', header_row: 0, columns: ['原文网址'],
        mapping: [{ field: 'source_url', column: '原文网址', confidence: 1 }],
        rows: urls.map((url, index) => ({
          row_number: index + 1, selected: /^https:\/\/[^\s]+$/i.test(url), source_url: url,
          source_title: '', publisher: '', published_date: '', applicable_scope: '', version_label: '',
          knowledge_tags: [], raw_data: { 原文网址: url },
          errors: /^https:\/\/[^\s]+$/i.test(url) ? [] : ['网址必须是 HTTPS 地址'],
          warnings: ['标题将尝试从网页识别', '发布机关将尝试从网页识别', '日期将尝试从网页识别'],
        })),
      }],
    }
    loadBatchSheet('网址列表')
    batchStep.value = 'preview'
    return
  }
  if (!batchFile.value) return ElMessage.warning('请选择 CSV 或 Excel 文件')
  batchLoading.value = true
  try {
    batchPreview.value = (await knowledgeApi.previewMaterialBatch(batchFile.value)).data.data
    loadBatchSheet(batchPreview.value.sheets[0].name)
    batchStep.value = 'preview'
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '批量文件解析失败')) }
  finally { batchLoading.value = false }
}

function applyBatchDefaults() {
  for (const row of batchRows.value.filter((item) => item.selected)) {
    if (batchForm.publisher.trim()) row.publisher = batchForm.publisher.trim()
    if (batchForm.applicable_scope.trim()) row.applicable_scope = batchForm.applicable_scope.trim()
    if (batchForm.knowledge_tags_text.trim()) row.knowledge_tags = [...new Set([...row.knowledge_tags, ...tags(batchForm.knowledge_tags_text)])]
    validateBatchRow(row)
  }
  ElMessage.success('批量设置已应用到选中行')
}

function removeBatchRow(index: number) { batchRows.value.splice(index, 1) }
function updateRowTags(row: MaterialPreviewRow, value: string) { row.knowledge_tags = tags(value) }
function batchStatusLabel(value: string) { return ({ queued: '等待处理', processing: '正在抓取', pending_review: '待审核', failed: '抓取失败', duplicate: '内容重复', completed: '处理完成' } as Record<string, string>)[value] || value }

async function submitBatch() {
  batchRows.value.forEach(validateBatchRow)
  const rows = selectedBatchRows.value
  if (!rows.length) return ElMessage.warning('请至少选择一条完整且有效的数据')
  if (rows.length > BATCH_MAX_ITEMS) return ElMessage.warning(`单个批次最多导入${BATCH_MAX_ITEMS}条网址`)
  batchLoading.value = true
  try {
    batchResult.value = (await knowledgeApi.createMaterialBatch({
      original_filename: batchPreview.value?.filename, sheet_name: batchSheetName.value,
      access_policy: batchForm.access_policy, course_ids: batchForm.course_ids,
      chapter_ids: batchForm.chapter_ids,
      items: rows.map((row) => ({
        row_number: row.row_number, source_url: row.source_url.trim(), source_title: row.source_title.trim() || undefined,
        publisher: row.publisher.trim() || undefined, published_date: row.published_date || undefined,
        applicable_scope: row.applicable_scope.trim() || undefined, version_label: row.version_label.trim() || undefined,
        knowledge_tags: row.knowledge_tags, raw_data: row.raw_data,
      })),
    })).data.data
    batchStep.value = 'processing'
    batchVisible.value = false
    taskCenterVisible.value = true
    await loadBatchTasks()
    ElMessage.success('任务已转入后台，可以离开当前页面')
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '批量任务创建失败')) }
  finally { batchLoading.value = false }
}

function batchProgress(item: MaterialBatch | MaterialBatchSummary) {
  return Math.round(item.completed_count / Math.max(1, item.total_count) * 100)
}

function taskStatusType(value: string) {
  return value === 'completed' ? 'success' : value === 'failed' ? 'danger' : value === 'processing' ? 'primary' : 'warning'
}

function formatTaskTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function scheduleTaskPoll() {
  if (taskPollTimer) window.clearTimeout(taskPollTimer)
  if (!activeBatchCount.value) return
  taskPollTimer = window.setTimeout(() => loadBatchTasks(true), 3000)
}

async function loadBatchTasks(notifyCompletion = false) {
  if (!auth.isAdmin) return
  taskLoading.value = true
  try {
    const tasks = (await knowledgeApi.materialBatches()).data.data
    if (notifyCompletion && taskHistoryInitialized) {
      for (const item of tasks) {
        const previous = knownBatchStatuses.get(item.id)
        if (previous && ['queued', 'processing'].includes(previous) && item.status === 'completed') {
          ElMessage.success(`后台导入任务 #${item.id} 已完成`)
          await loadData()
        }
      }
    }
    batchTasks.value = tasks
    knownBatchStatuses.clear()
    tasks.forEach((item) => knownBatchStatuses.set(item.id, item.status))
    taskHistoryInitialized = true
  } catch (error: unknown) {
    if (taskCenterVisible.value) ElMessage.warning(getErrorMessage(error, '后台任务暂时无法刷新'))
  } finally {
    taskLoading.value = false
    scheduleTaskPoll()
  }
}

async function openTaskCenter() {
  taskCenterVisible.value = true
  await loadBatchTasks()
}

async function openBatchTask(item: MaterialBatchSummary) {
  try {
    batchResult.value = (await knowledgeApi.materialBatch(item.id)).data.data
    batchStep.value = 'processing'
    batchVisible.value = true
    scheduleBatchPoll()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '任务详情加载失败'))
  }
}

function scheduleBatchPoll() {
  if (batchPollTimer) window.clearTimeout(batchPollTimer)
  if (!batchResult.value || batchResult.value.status === 'completed' || batchResult.value.status === 'failed') return
  batchPollTimer = window.setTimeout(pollBatch, 1500)
}

async function pollBatch() {
  if (!batchResult.value) return
  try {
    batchResult.value = (await knowledgeApi.materialBatch(batchResult.value.id)).data.data
    if (batchResult.value.status === 'completed') await loadData()
  } catch (error: unknown) { ElMessage.warning(getErrorMessage(error, '任务进度暂时无法刷新')) }
  scheduleBatchPoll()
}

async function retryBatch() {
  if (!batchResult.value) return
  try {
    batchResult.value = (await knowledgeApi.retryMaterialBatch(batchResult.value.id)).data.data
    await loadBatchTasks()
    scheduleBatchPoll()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '重试失败')) }
}

async function reviewBatchDocument(documentId: number | null) {
  if (!documentId) return
  await loadData()
  const document = documents.value.find((item) => item.id === documentId)
  if (document) await openRelations(document)
  else ElMessage.warning('资料列表尚未同步，请稍后刷新')
}

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

onMounted(async () => {
  await loadData()
  await loadBatchTasks()
})
onBeforeUnmount(() => {
  if (batchPollTimer) window.clearTimeout(batchPollTimer)
  if (taskPollTimer) window.clearTimeout(taskPollTimer)
})
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
        <el-badge v-if="activeTab === 'central' && auth.isAdmin" :value="activeBatchCount" :hidden="activeBatchCount === 0" type="warning">
          <el-button :icon="Clock" @click="openTaskCenter">后台任务</el-button>
        </el-badge>
        <el-button v-if="activeTab === 'central' && auth.isAdmin" :icon="UploadFilled" @click="openBatchImport">批量网址导入</el-button>
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

    <el-drawer v-model="taskCenterVisible" title="后台导入任务" size="560px" class="material-task-drawer">
      <div class="task-center-heading">
        <div><strong>中央材料导入记录</strong><span>任务由服务器持续处理，关闭页面不会中断</span></div>
        <el-button :icon="Refresh" :loading="taskLoading" circle @click="loadBatchTasks()" />
      </div>
      <div v-loading="taskLoading" class="task-center-list">
        <button v-for="item in batchTasks" :key="item.id" type="button" class="task-center-card" @click="openBatchTask(item)">
          <div class="task-card-title">
            <div><strong>批次 #{{ item.id }}</strong><span>{{ item.original_filename || '粘贴网址' }}<template v-if="item.sheet_name"> · {{ item.sheet_name }}</template></span></div>
            <el-tag :type="taskStatusType(item.status)">{{ batchStatusLabel(item.status) }}</el-tag>
          </div>
          <el-progress :percentage="batchProgress(item)" :status="item.status === 'completed' ? 'success' : item.status === 'failed' ? 'exception' : undefined" />
          <div class="task-card-metrics">
            <span>{{ item.completed_count }} / {{ item.total_count }} 已处理</span>
            <span>{{ item.success_count }} 待审核</span>
            <span v-if="item.failed_count" class="failed">{{ item.failed_count }} 失败</span>
            <span>{{ formatTaskTime(item.created_time) }}</span>
          </div>
        </button>
        <el-empty v-if="!taskLoading && !batchTasks.length" description="暂无后台导入任务" />
      </div>
    </el-drawer>

    <el-dialog v-model="batchVisible" title="批量导入中央材料网址" width="94%" top="4vh" destroy-on-close class="material-batch-dialog">
      <el-steps :active="batchStep === 'upload' ? 0 : batchStep === 'preview' ? 1 : 2" finish-status="success" simple>
        <el-step title="上传表格" /><el-step title="预览与清洗" /><el-step title="抓取与审核" />
      </el-steps>

      <section v-if="batchStep === 'upload'" class="batch-upload-stage">
        <div class="batch-drop-card">
          <strong>批量提供中央材料网址</strong>
          <el-radio-group v-model="batchSourceMode"><el-radio-button value="file">CSV / Excel</el-radio-button><el-radio-button value="text">粘贴网址</el-radio-button></el-radio-group>
          <p>系统会自动识别标题、网址、发布机关和发布时间，单批最多 {{ BATCH_MAX_ITEMS }} 条。确认后转入后台处理，可随时离开页面。</p>
          <template v-if="batchSourceMode === 'file'"><input class="file-input" type="file" accept=".csv,.xlsx,.xls" @change="chooseBatchFile" /><span v-if="batchFile">已选择：{{ batchFile.name }}</span></template>
          <el-input v-else v-model="batchUrlText" type="textarea" :rows="10" placeholder="每行一个 HTTPS 原文网址" />
        </div>
      </section>

      <template v-else-if="batchStep === 'preview'">
        <section class="batch-preview-toolbar">
          <div><strong>{{ batchPreview?.filename }}</strong><span>共 {{ batchRows.length }} 行 · 已选 {{ selectedBatchRows.length }} 行 · {{ batchIssueCount }} 行需检查</span></div>
          <el-select v-model="batchSheetName" @change="loadBatchSheet" style="width:220px"><el-option v-for="sheet in batchPreview?.sheets" :key="sheet.name" :label="`${sheet.name}（表头第${sheet.header_row}行）`" :value="sheet.name" /></el-select>
        </section>

        <section class="batch-mapping-panel">
          <div class="batch-panel-title"><div><strong>字段映射</strong><span>系统已自动识别，可手动纠正后重新应用</span></div><el-button size="small" type="primary" plain @click="applyBatchMapping">重新应用映射</el-button></div>
          <div class="batch-mapping-grid"><label v-for="field in mappingFields" :key="field[0]"><span>{{ field[1] }}</span><el-select v-model="batchMapping[field[0]]" clearable placeholder="忽略此字段"><el-option v-for="column in currentBatchSheet?.columns" :key="column" :label="column" :value="column" /></el-select></label></div>
        </section>

        <section class="batch-default-panel">
          <div class="batch-panel-title"><div><strong>批量设置</strong><span>只应用到已选中的数据行</span></div><el-button size="small" @click="applyBatchDefaults">应用到选中行</el-button></div>
          <div class="batch-default-grid"><el-input v-model="batchForm.publisher" clearable placeholder="统一发布机关（可选）" /><el-input v-model="batchForm.applicable_scope" clearable placeholder="统一适用范围（可选）" /><el-input v-model="batchForm.knowledge_tags_text" clearable placeholder="追加知识点标签（逗号分隔）" /></div>
          <div class="batch-default-grid"><el-select v-model="batchForm.course_ids" multiple filterable placeholder="预关联教材（可选）"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select><el-select v-model="batchForm.chapter_ids" multiple filterable placeholder="预关联专题（可选）"><el-option v-for="chapter in batchChapters" :key="chapter.id" :label="`${chapter.courseName} · ${chapter.title}`" :value="chapter.id" /></el-select><el-select v-model="batchForm.access_policy"><el-option label="全文预览" value="full_preview" /><el-option label="仅引用页" value="citation_only" /><el-option label="允许下载" value="download" /></el-select></div>
        </section>

        <div class="batch-table-wrap">
          <el-table :data="batchRows" border height="430px" row-key="row_number">
            <el-table-column label="导入" width="65" fixed><template #default="{ row }"><el-checkbox v-model="row.selected" :disabled="row.errors.length > 0" /></template></el-table-column>
            <el-table-column label="原行" prop="row_number" width="70" />
            <el-table-column label="材料标题" min-width="220"><template #default="{ row }"><el-input v-model="row.source_title" @change="validateBatchRow(row)" /></template></el-table-column>
            <el-table-column label="原文网址" min-width="300"><template #default="{ row }"><el-input v-model="row.source_url" @change="validateBatchRow(row)" /></template></el-table-column>
            <el-table-column label="发布机关" min-width="180"><template #default="{ row }"><el-input v-model="row.publisher" @change="validateBatchRow(row)" /></template></el-table-column>
            <el-table-column label="发布日期" width="170"><template #default="{ row }"><el-date-picker v-model="row.published_date" type="date" value-format="YYYY-MM-DD" style="width:145px" @change="validateBatchRow(row)" /></template></el-table-column>
            <el-table-column label="适用范围" min-width="180"><template #default="{ row }"><el-input v-model="row.applicable_scope" /></template></el-table-column>
            <el-table-column label="知识点" min-width="190"><template #default="{ row }"><el-input :model-value="row.knowledge_tags.join('、')" @update:model-value="updateRowTags(row, $event)" /></template></el-table-column>
            <el-table-column label="数据状态" width="200" fixed="right"><template #default="{ row }"><el-tag v-if="!row.errors.length && !row.warnings.length" type="success">可导入</el-tag><el-tag v-for="error in row.errors" :key="error" type="danger" class="batch-issue-tag">{{ error }}</el-tag><el-tag v-for="warning in row.warnings" :key="warning" type="warning" class="batch-issue-tag">{{ warning }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="75" fixed="right"><template #default="{ $index }"><el-button link type="danger" @click="removeBatchRow($index)">移除</el-button></template></el-table-column>
          </el-table>
        </div>
      </template>

      <section v-else-if="batchResult" class="batch-result-stage">
        <div class="batch-progress-card"><div><strong>批次 #{{ batchResult.id }} · {{ batchStatusLabel(batchResult.status) }}</strong><span>{{ batchResult.completed_count }} / {{ batchResult.total_count }} 已处理 · 可关闭窗口在后台继续</span></div><el-progress :percentage="batchProgress(batchResult)" :status="batchResult.status === 'completed' ? 'success' : batchResult.status === 'failed' ? 'exception' : undefined" /></div>
        <div class="batch-result-metrics"><article><strong>{{ batchResult.success_count }}</strong><span>待审核</span></article><article><strong>{{ batchResult.failed_count }}</strong><span>失败</span></article><article><strong>{{ batchResult.duplicate_count }}</strong><span>重复</span></article></div>
        <el-table :data="batchResult.items" border height="430px"><el-table-column label="原行" prop="row_number" width="70" /><el-table-column label="标题" prop="source_title" min-width="220" /><el-table-column label="网址" prop="source_url" min-width="300" show-overflow-tooltip /><el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="row.status === 'pending_review' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">{{ batchStatusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column label="说明" prop="error_message" min-width="220" /><el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="row.document_id" link type="primary" @click="reviewBatchDocument(row.document_id)">审核关联</el-button></template></el-table-column></el-table>
      </section>

      <template #footer>
        <el-button @click="batchVisible = false">关闭</el-button>
        <el-button v-if="batchStep === 'upload'" type="primary" :loading="batchLoading" @click="previewBatch">解析并预览</el-button>
        <template v-else-if="batchStep === 'preview'"><el-button @click="batchStep = 'upload'">重新选择文件</el-button><el-button type="primary" :loading="batchLoading" @click="submitBatch">导入选中 {{ selectedBatchRows.length }} 条</el-button></template>
        <el-button v-else-if="batchResult?.failed_count" type="warning" @click="retryBatch">重试失败项</el-button>
      </template>
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
.material-center-page{display:grid;gap:24px}.material-center-hero{display:grid;grid-template-columns:minmax(0,1fr) 420px;gap:40px;padding:48px 54px;color:#fff;background:radial-gradient(circle at 88% 12%,rgba(103,236,244,.28),transparent 30%),linear-gradient(120deg,#183f98,#286ac9 52%,#168a91);border-radius:28px;box-shadow:0 24px 55px rgba(18,58,128,.2)}.material-center-hero h1{margin:7px 0 12px;font-size:42px}.material-center-hero p{max-width:760px;color:#dceaff;line-height:1.8}.material-priority{display:flex;align-items:center;gap:10px;margin-top:22px}.material-priority span{padding:7px 14px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.25);border-radius:999px}.material-priority .central{color:#ffe1dc}.material-priority .textbook{color:#dce8ff}.material-priority .local{color:#d8ffec}.material-priority i{color:#b9d7ff;font-size:22px}.material-hero-metrics{display:grid;grid-template-columns:repeat(3,1fr);align-content:center;gap:12px}.material-hero-metrics article{display:grid;place-items:center;min-height:126px;background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.22);border-radius:20px;backdrop-filter:blur(10px)}.material-hero-metrics strong{font-size:34px}.material-hero-metrics span{color:#dceaff}.material-command-bar{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:12px;background:#fff;border:1px solid #dde6f3;border-radius:18px;box-shadow:0 12px 30px rgba(35,63,112,.08)}.material-tabs{display:flex;gap:6px}.material-tabs button{display:flex;align-items:center;gap:8px;padding:12px 17px;color:#53647c;background:transparent;border:0;border-radius:12px;cursor:pointer}.material-tabs button.active{color:#fff;background:linear-gradient(120deg,#245bc5,#4970db);box-shadow:0 8px 18px rgba(38,88,190,.22)}.material-tabs small{display:grid;min-width:22px;height:22px;place-items:center;background:rgba(125,145,180,.14);border-radius:50%}.material-actions{display:flex;align-items:center;gap:9px}.material-actions .el-input{width:260px}.material-actions .el-select{width:126px}.material-section-heading{display:flex;align-items:flex-end;justify-content:space-between}.material-section-heading h2{margin:5px 0 0;font-size:25px}.material-section-heading>span{color:#77879e}.material-list{display:grid;gap:14px;min-height:180px}.material-card{display:grid;grid-template-columns:112px minmax(0,1fr) 180px;gap:22px;align-items:center;min-height:170px;padding:22px;background:#fff;border:1px solid #dfe7f2;border-radius:20px;box-shadow:0 12px 32px rgba(30,56,102,.07)}.material-card-marker{display:grid;height:118px;place-items:center;align-content:center;gap:8px;color:#fff;background:linear-gradient(145deg,#9e2943,#d2594e);border-radius:18px}.material-card-textbook .material-card-marker{background:linear-gradient(145deg,#2558bd,#4f78d9)}.material-card-local .material-card-marker{background:linear-gradient(145deg,#16806e,#3cac84)}.material-card-unclassified .material-card-marker{background:linear-gradient(145deg,#6c7789,#9aa4b4)}.material-card-marker span{font-size:12px}.material-card-marker strong{font-size:30px}.material-card-title{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.material-card-title h3{margin:0 0 6px;font-size:21px}.material-card-title p,.material-scope-copy{margin:0;color:#73839a}.material-scope-copy{margin-top:15px}.material-chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}.material-chips span{padding:5px 9px;color:#55708f;background:#f1f5fa;border-radius:7px;font-size:12px}.material-card-ops{display:grid;justify-items:start;gap:2px;padding-left:10px;border-left:1px solid #e6ebf2}.material-upload-form{margin-top:18px}.material-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.form-tip{margin-top:5px;color:#8794a7;font-size:12px}.scope-dialog-heading{display:flex;flex-direction:column;gap:4px;margin-bottom:16px;padding:15px 17px;background:#f3f7fd;border-radius:12px}.scope-dialog-heading span{color:#73839b}.suggestion-panel{margin-bottom:18px;padding:16px;background:linear-gradient(135deg,#f5f8ff,#f2fbfb);border:1px solid #dce7f5;border-radius:14px}.suggestion-title{display:flex;justify-content:space-between}.suggestion-title span{color:#7a899e}.suggestion-list{display:flex;gap:9px;overflow-x:auto;margin-top:12px}.suggestion-list button{display:grid;min-width:170px;gap:4px;padding:11px;text-align:left;background:#fff;border:1px solid #d5e0ef;border-radius:10px;cursor:pointer}.suggestion-list button:hover{border-color:#4a7ddb}.suggestion-list span,.suggestion-list small{color:#74859c}.suggestion-list strong{color:#243a5d}.file-input{width:100%;padding:10px;background:#f7f9fc;border:1px solid #d8e0eb;border-radius:8px}.batch-upload-stage{display:grid;place-items:center;min-height:420px}.batch-drop-card{display:grid;width:min(680px,100%);gap:14px;padding:42px;background:linear-gradient(135deg,#f4f8ff,#f1fbfb);border:1px dashed #7ea6dc;border-radius:20px;text-align:center}.batch-drop-card strong{font-size:24px;color:#243b63}.batch-drop-card p,.batch-drop-card span{color:#708099}.batch-preview-toolbar,.batch-panel-title,.batch-progress-card>div{display:flex;align-items:center;justify-content:space-between;gap:18px}.batch-preview-toolbar{margin:18px 0 12px}.batch-preview-toolbar>div,.batch-panel-title>div,.batch-progress-card>div{display:grid;gap:4px}.batch-preview-toolbar span,.batch-panel-title span,.batch-progress-card span{color:#7b899d;font-size:13px}.batch-mapping-panel,.batch-default-panel,.batch-progress-card{margin-bottom:12px;padding:14px 16px;background:#f7f9fd;border:1px solid #dfe7f2;border-radius:14px}.batch-mapping-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-top:12px}.batch-mapping-grid label{display:grid;gap:5px}.batch-mapping-grid label>span{color:#63728a;font-size:12px}.batch-default-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:11px}.batch-table-wrap{border-radius:12px;overflow:hidden}.batch-issue-tag{display:block;width:max-content;max-width:170px;margin:3px 0;overflow:hidden;text-overflow:ellipsis}.batch-result-stage{display:grid;gap:12px;margin-top:18px}.batch-progress-card{display:grid;grid-template-columns:280px 1fr;align-items:center}.batch-result-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.batch-result-metrics article{display:grid;place-items:center;padding:16px;background:#f5f8fc;border:1px solid #dfe7f2;border-radius:12px}.batch-result-metrics strong{font-size:26px;color:#245bc5}.batch-result-metrics span{color:#77869c}.task-center-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding:16px;background:linear-gradient(135deg,#eef4ff,#ecfbfa);border:1px solid #dce7f3;border-radius:16px}.task-center-heading>div{display:grid;gap:5px}.task-center-heading strong{font-size:18px;color:#233b62}.task-center-heading span{color:#75849a;font-size:13px}.task-center-list{display:grid;gap:12px;min-height:240px}.task-center-card{display:grid;width:100%;gap:13px;padding:17px;text-align:left;background:#fff;border:1px solid #dfe7f2;border-radius:16px;box-shadow:0 8px 22px rgba(37,66,115,.06);cursor:pointer}.task-center-card:hover{border-color:#73a0e5;transform:translateY(-1px)}.task-card-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.task-card-title>div{display:grid;gap:4px}.task-card-title strong{color:#253c61}.task-card-title span,.task-card-metrics{color:#77869b;font-size:12px}.task-card-metrics{display:flex;flex-wrap:wrap;gap:8px 15px}.task-card-metrics .failed{color:#d94c4c}
@media(max-width:1180px){.material-center-hero{grid-template-columns:1fr}.material-command-bar{align-items:stretch;flex-direction:column}.material-actions{flex-wrap:wrap}.material-card{grid-template-columns:100px minmax(0,1fr)}.material-card-ops{grid-column:1/-1;display:flex;flex-wrap:wrap;border-top:1px solid #e6ebf2;border-left:0;padding-top:12px}.batch-mapping-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){.material-center-hero{padding:32px 24px}.material-center-hero h1{font-size:32px}.material-hero-metrics{grid-template-columns:1fr 1fr}.material-command-bar,.material-tabs,.material-actions{align-items:stretch;flex-direction:column}.material-actions .el-input,.material-actions .el-select{width:100%}.material-card{grid-template-columns:1fr}.material-card-marker{height:80px}.material-card-ops{grid-column:auto}.material-form-grid,.batch-mapping-grid,.batch-default-grid,.batch-progress-card{grid-template-columns:1fr}.batch-preview-toolbar{align-items:stretch;flex-direction:column}}
</style>

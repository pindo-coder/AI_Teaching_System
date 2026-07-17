<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import { knowledgeApi, type KnowledgeDocument } from '@/api/knowledge'
import type { CourseDetail } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { useRouter } from 'vue-router'

const loading = ref(false)
const router = useRouter()
const uploading = ref(false)
const documents = ref<KnowledgeDocument[]>([])
const courses = ref<CourseDetail[]>([])
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement>()
const form = reactive({ source_title: '', course_id: undefined as number | undefined, chapter_id: undefined as number | undefined, knowledge_point: '', version_label: '当前版', source_role: 'primary' as 'primary' | 'supplementary', access_policy: 'full_preview' as 'citation_only' | 'full_preview' | 'download' })
const selectedCourse = computed(() => courses.value.find((item) => item.id === form.course_id))

async function loadData() {
  loading.value = true
  try {
    const courseList = (await courseApi.list()).data.data
    courses.value = await Promise.all(courseList.map(async (item) => (await courseApi.detail(item.id)).data.data))
    documents.value = (await knowledgeApi.list()).data.data
  } finally { loading.value = false }
}
function chooseFile(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
  if (selectedFile.value && !form.source_title) form.source_title = selectedFile.value.name.replace(/\.[^.]+$/, '')
}
async function upload() {
  if (!selectedFile.value || !form.source_title.trim() || !form.course_id) return ElMessage.warning('请选择文件、教材并填写资料标题')
  const payload = new FormData()
  payload.append('file', selectedFile.value)
  payload.append('source_title', form.source_title.trim())
  payload.append('course_id', String(form.course_id))
  if (form.chapter_id) payload.append('chapter_id', String(form.chapter_id))
  if (form.knowledge_point.trim()) payload.append('knowledge_point', form.knowledge_point.trim())
  payload.append('version_label', form.version_label.trim() || '当前版')
  payload.append('source_role', form.source_role)
  payload.append('access_policy', form.access_policy)
  uploading.value = true
  try {
    await knowledgeApi.upload(payload)
    ElMessage.success('资料已上传，请进入校准工作台确认章节与页码后发布')
    selectedFile.value = null; form.source_title = ''; form.knowledge_point = ''; form.chapter_id = undefined
    if (fileInput.value) fileInput.value.value = ''
    documents.value = (await knowledgeApi.list()).data.data
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '资料上传失败'))
  } finally { uploading.value = false }
}
async function remove(document: KnowledgeDocument) {
  await ElMessageBox.confirm(`确定删除“${document.source_title}”及其向量索引吗？`, '删除资料', { type: 'warning' })
  await knowledgeApi.remove(document.id)
  ElMessage.success('资料已删除')
  documents.value = documents.value.filter((item) => item.id !== document.id)
}
async function reindex(document: KnowledgeDocument) {
  await knowledgeApi.reindex(document.id)
  ElMessage.success('重新索引成功')
  documents.value = (await knowledgeApi.list()).data.data
}
function courseName(id: number) { return courses.value.find((item) => item.id === id)?.name || `教材 ${id}` }
function chapterName(courseId: number, chapterId: number | null) { return chapterId ? courses.value.find((item) => item.id === courseId)?.chapters.find((item) => item.id === chapterId)?.title || `专题 ${chapterId}` : '全教材' }
onMounted(loadData)
</script>

<template>
  <div>
    <header class="page-header"><div><p class="eyebrow">Knowledge Base</p><h1>教材知识库</h1><p>上传教材、讲义与权威资料，让 AI 回答始终围绕本课程内容。</p></div></header>
    <el-card shadow="never" class="upload-panel">
      <div class="upload-title"><el-icon :size="28"><UploadFilled /></el-icon><div><h2>上传教材资料</h2><p>支持可复制文本的 PDF、TXT、Markdown，单个文件不超过 100 MB。</p></div></div>
      <el-form label-position="top" class="upload-form">
        <el-form-item label="资料文件" required><input ref="fileInput" class="file-input" type="file" accept=".pdf,.txt,.md,.markdown" @change="chooseFile" /></el-form-item>
        <el-form-item label="资料标题" required><el-input v-model="form.source_title" maxlength="255" /></el-form-item>
        <el-form-item label="所属教材" required><el-select v-model="form.course_id" placeholder="请选择教材" filterable @change="form.chapter_id = undefined"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item>
        <el-form-item label="关联专题"><el-select v-model="form.chapter_id" placeholder="不选择则属于全教材" clearable><el-option v-for="chapter in selectedCourse?.chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item>
        <el-form-item label="知识点"><el-input v-model="form.knowledge_point" placeholder="可选，如：马克思主义中国化时代化" /></el-form-item>
        <div class="assignment-form-grid"><el-form-item label="教材版本"><el-input v-model="form.version_label" placeholder="如：2023 年版" /></el-form-item><el-form-item label="资料角色"><el-select v-model="form.source_role"><el-option label="主教材依据" value="primary" /><el-option label="补充资料依据" value="supplementary" /></el-select></el-form-item></div>
        <el-form-item label="访问权限"><el-radio-group v-model="form.access_policy"><el-radio-button value="citation_only">仅引用页</el-radio-button><el-radio-button value="full_preview">全文预览</el-radio-button><el-radio-button value="download">允许下载</el-radio-button></el-radio-group></el-form-item>
      </el-form>
      <el-button type="primary" :loading="uploading" @click="upload">上传并建立索引</el-button>
    </el-card>
    <div class="section-heading"><div><p class="eyebrow">已入库资料</p><h2>文档列表</h2></div></div>
    <el-table v-loading="loading" :data="documents" class="knowledge-table">
      <el-table-column label="资料"><template #default="scope"><strong>{{ scope.row.source_title }}</strong><div class="table-subtitle">{{ scope.row.original_filename }}</div></template></el-table-column>
      <el-table-column label="教材 / 专题" min-width="220"><template #default="scope"><span>{{ courseName(scope.row.course_id) }}</span><div class="table-subtitle">{{ chapterName(scope.row.course_id, scope.row.chapter_id) }}</div></template></el-table-column>
      <el-table-column prop="source_type" label="类型" width="90" />
      <el-table-column label="校准状态" width="130"><template #default="scope"><el-tag :type="scope.row.calibration_status === 'published' ? 'success' : scope.row.calibration_status === 'calibrated' ? 'primary' : 'warning'">{{ scope.row.calibration_status }}</el-tag></template></el-table-column>
      <el-table-column prop="chunk_count" label="分块" width="80" />
      <el-table-column label="操作" width="250" fixed="right"><template #default="scope"><el-button link type="primary" @click="router.push(`/knowledge/documents/${scope.row.id}/calibrate`)">校准结构</el-button><el-button link @click="reindex(scope.row)">重建索引</el-button><el-button link type="danger" @click="remove(scope.row)">删除</el-button></template></el-table-column>
      <template #empty><el-empty description="尚未上传教材资料" /></template>
    </el-table>
  </div>
</template>

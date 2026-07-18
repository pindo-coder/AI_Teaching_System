<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CirclePlus, Delete, Select } from '@element-plus/icons-vue'
import { knowledgeApi, type KnowledgeDocument, type DocumentPage, type OutlineNode, type PageNumberRangeInput } from '@/api/knowledge'
import { courseApi } from '@/api/courses'
import type { Chapter } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

type EditableNode = Omit<OutlineNode, 'id' | 'parent_id' | 'calibration_status'> & {
  client_id: string
  parent_client_id: string | null
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const documentId = Number(route.params.documentId)
const loading = ref(true)
const saving = ref(false)
const publishing = ref(false)
const autoSplitting = ref(false)
const deleting = ref(false)
const document = ref<KnowledgeDocument | null>(null)
const chapters = ref<Chapter[]>([])
const pages = ref<DocumentPage[]>([])
const nodes = ref<EditableNode[]>([])
const selectedClientId = ref('')
const selectedPage = ref(1)
const pdfUrl = ref('')
const pdfLoading = ref(false)
let pdfRequestId = 0
const versionLabel = ref('当前版')
const accessPolicy = ref<'citation_only' | 'full_preview' | 'download'>('full_preview')
const pageRanges = ref<PageNumberRangeInput[]>([])

const selectedNode = computed(() => nodes.value.find((item) => item.client_id === selectedClientId.value) || null)
const selectedPageData = computed(() => pages.value.find((item) => item.pdf_page === selectedPage.value) || null)
const pdfPageUrl = computed(() => pdfUrl.value ? `${pdfUrl.value}#page=1&toolbar=1&navpanes=0&view=FitH` : '')
const maxPage = computed(() => pages.value.at(-1)?.pdf_page || 1)
const canPublish = computed(() => auth.user?.role === 'admin' && document.value?.calibration_status === 'calibrated')

function revokePdf() { if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value); pdfUrl.value = '' }

async function loadPdfPage(page: number) {
  const requestId = ++pdfRequestId
  pdfLoading.value = true
  try {
    const result = await knowledgeApi.fileBlob(documentId, page)
    if (requestId !== pdfRequestId) return
    revokePdf()
    pdfUrl.value = URL.createObjectURL(result.data)
  } catch (error: unknown) {
    if (requestId === pdfRequestId) ElMessage.error(getErrorMessage(error, `PDF 第 ${page} 页加载失败`))
  } finally {
    if (requestId === pdfRequestId) pdfLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const detail = (await knowledgeApi.detail(documentId)).data.data
    document.value = detail
    accessPolicy.value = detail.access_policy
    const [pageResult, outlineResult, courseResult, metaResult] = await Promise.all([
      knowledgeApi.pages(documentId), knowledgeApi.outline(documentId), courseApi.detail(detail.course_id), knowledgeApi.calibrationMeta(documentId),
    ])
    pages.value = pageResult.data.data
    chapters.value = courseResult.data.data.chapters
    versionLabel.value = metaResult.data.data.version_label
    accessPolicy.value = metaResult.data.data.access_policy
    pageRanges.value = metaResult.data.data.page_number_ranges
    const idMap = new Map(outlineResult.data.data.map((item) => [item.id, `node-${item.id}`]))
    nodes.value = outlineResult.data.data.map((item) => ({
      client_id: idMap.get(item.id)!, parent_client_id: item.parent_id ? idMap.get(item.parent_id) || null : null,
      chapter_id: item.chapter_id, node_type: item.node_type, title: item.title, sort_order: item.sort_order,
      pdf_page_start: item.pdf_page_start, pdf_page_end: item.pdf_page_end, start_anchor: item.start_anchor,
      end_anchor: item.end_anchor, retrieval_enabled: item.retrieval_enabled,
    }))
    selectedClientId.value = nodes.value[0]?.client_id || ''
    selectedPage.value = nodes.value[0]?.pdf_page_start || 1
    await loadPdfPage(selectedPage.value)
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材校准数据加载失败'))
  } finally { loading.value = false }
}

function selectNode(node: EditableNode) {
  selectedClientId.value = node.client_id
  selectedPage.value = node.pdf_page_start
}

function addNode(type: EditableNode['node_type'] = 'section') {
  const parent = selectedNode.value
  const id = `new-${Date.now()}-${nodes.value.length}`
  const node: EditableNode = reactive({
    client_id: id, parent_client_id: parent?.client_id || null, chapter_id: parent?.chapter_id || null,
    node_type: type, title: type === 'knowledge_point' ? '新知识点' : '新节', sort_order: nodes.value.length,
    pdf_page_start: selectedPage.value, pdf_page_end: selectedPage.value, start_anchor: null, end_anchor: null,
    retrieval_enabled: true,
  })
  nodes.value.push(node); selectedClientId.value = id
}

async function removeNode() {
  const current = selectedNode.value
  if (!current) return
  const hasChildren = nodes.value.some((item) => item.parent_client_id === current.client_id)
  if (hasChildren) return ElMessage.warning('请先删除该节点下的子节点')
  await ElMessageBox.confirm(`删除结构节点“${current.title}”？`, '确认删除', { type: 'warning' })
  nodes.value = nodes.value.filter((item) => item.client_id !== current.client_id)
  selectedClientId.value = nodes.value[0]?.client_id || ''
}

function useSelectionAsAnchor(kind: 'start' | 'end') {
  const selection = window.getSelection()?.toString().trim()
  if (!selection || !selectedNode.value) return ElMessage.warning('请先在右侧本页文字中选择一段原文')
  if (kind === 'start') selectedNode.value.start_anchor = selection.slice(0, 500)
  else selectedNode.value.end_anchor = selection.slice(-500)
  ElMessage.success(kind === 'start' ? '已设置正文起点' : '已设置正文终点')
}

function addPageRange() {
  pageRanges.value.push({ pdf_page_start: 1, pdf_page_end: maxPage.value, numbering_style: 'arabic', printed_start: '1' })
}

async function save() {
  if (!nodes.value.length) return ElMessage.warning('至少保留一个可检索的教材结构节点')
  saving.value = true
  try {
    document.value = (await knowledgeApi.calibrate(documentId, {
      version_label: versionLabel.value.trim() || '当前版', access_policy: accessPolicy.value,
      page_number_ranges: pageRanges.value, outline: nodes.value,
    })).data.data
    ElMessage.success('校准已保存，当前教材向量已按新边界局部重建')
    await load()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '保存校准失败'))
  } finally { saving.value = false }
}

async function publish() {
  publishing.value = true
  try { document.value = (await knowledgeApi.publish(documentId)).data.data; ElMessage.success('教材版本已发布') }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '发布失败')) }
  finally { publishing.value = false }
}

async function autoSplit() {
  const confirmed = await ElMessageBox.confirm(
    '系统将重新识别章节首页并覆盖当前尚未保存的结构调整，是否继续？',
    '重新自动拆分',
    { type: 'warning', confirmButtonText: '重新拆分', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  autoSplitting.value = true
  try {
    await knowledgeApi.autoCalibrate(documentId)
    ElMessage.success('已重新生成章节边界，请核对后保存')
    await load()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '自动拆分失败'))
  } finally { autoSplitting.value = false }
}

async function deleteDocument() {
  const confirmed = await ElMessageBox.confirm(
    `确定删除“${document.value?.source_title || '这份教材资料'}”吗？文件、校准结构和向量索引将一并删除。`,
    '删除教材资料',
    { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed || !document.value) return
  deleting.value = true
  try {
    const courseId = document.value.course_id
    await knowledgeApi.remove(documentId)
    ElMessage.success('教材资料已删除')
    await router.replace(`/courses/${courseId}`)
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材资料删除失败'))
  } finally { deleting.value = false }
}

onMounted(load)
onBeforeUnmount(revokePdf)
watch(selectedPage, (page, previous) => { if (!loading.value && page !== previous) loadPdfPage(page) })
</script>

<template>
  <div v-loading="loading" class="calibration-page">
    <header class="calibration-header">
      <el-button text :icon="ArrowLeft" @click="router.back()">返回知识库</el-button>
      <div><p class="eyebrow">Textbook Calibration</p><h1>{{ document?.source_title || '教材校准工作台' }}</h1><p>确认章节边界、印刷页码和正文锚点，AI 引用将精确到原始页与知识点。</p></div>
      <div class="calibration-header__actions"><el-tag :type="document?.calibration_status === 'published' ? 'success' : 'warning'">{{ document?.calibration_status }}</el-tag><el-button :loading="autoSplitting" @click="autoSplit">重新自动拆分</el-button><el-button type="primary" :loading="saving" :icon="Select" @click="save">保存并重建索引</el-button><el-button v-if="auth.user?.role === 'admin'" :disabled="!canPublish" :loading="publishing" @click="publish">发布版本</el-button><el-button type="danger" plain :loading="deleting" :icon="Delete" @click="deleteDocument">删除资料</el-button></div>
    </header>

    <section class="calibration-settings">
      <el-input v-model="versionLabel" placeholder="版本名称，如：2023 年版" />
      <el-select v-model="accessPolicy"><el-option label="引用页可见" value="citation_only" /><el-option label="允许全文预览" value="full_preview" /><el-option label="允许下载" value="download" /></el-select>
      <el-button @click="addPageRange">添加印刷页码区段</el-button>
      <div v-for="(range, index) in pageRanges" :key="index" class="page-range-row"><span>PDF</span><el-input-number v-model="range.pdf_page_start" :min="1" :max="maxPage" /><span>至</span><el-input-number v-model="range.pdf_page_end" :min="range.pdf_page_start" :max="maxPage" /><el-select v-model="range.numbering_style"><el-option label="阿拉伯数字" value="arabic" /><el-option label="大写罗马" value="roman_upper" /><el-option label="小写罗马" value="roman_lower" /><el-option label="无印刷页码" value="none" /></el-select><el-input v-model="range.printed_start" placeholder="起始印刷页" /><el-button text type="danger" :icon="Delete" @click="pageRanges.splice(index, 1)" /></div>
    </section>

    <main class="calibration-workbench">
      <aside class="calibration-outline">
        <div class="panel-title"><div><span>01</span><strong>教材结构</strong></div><el-dropdown @command="addNode"><el-button size="small" :icon="CirclePlus">添加</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="chapter">章</el-dropdown-item><el-dropdown-item command="section">节</el-dropdown-item><el-dropdown-item command="knowledge_point">知识点</el-dropdown-item><el-dropdown-item command="preface">前言</el-dropdown-item><el-dropdown-item command="reference">参考文献</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        <div class="outline-list"><button v-for="node in nodes" :key="node.client_id" :class="['outline-node', { active: node.client_id === selectedClientId }]" :style="{ paddingLeft: `${16 + (node.parent_client_id ? 18 : 0)}px` }" @click="selectNode(node)"><span>{{ node.node_type === 'chapter' ? '章' : node.node_type === 'section' ? '节' : node.node_type === 'knowledge_point' ? '点' : '附' }}</span><div><strong>{{ node.title }}</strong><small>PDF {{ node.pdf_page_start }}–{{ node.pdf_page_end }}</small></div></button></div>
      </aside>

      <section v-loading="pdfLoading" class="calibration-pdf">
        <div class="panel-title"><div><span>02</span><strong>PDF 原页</strong></div><div class="page-stepper"><el-button size="small" :disabled="selectedPage <= 1" @click="selectedPage--">上一页</el-button><el-input-number v-model="selectedPage" :min="1" :max="maxPage" controls-position="right" /><el-button size="small" :disabled="selectedPage >= maxPage" @click="selectedPage++">下一页</el-button></div></div>
        <iframe v-if="pdfPageUrl" :key="selectedPage" :src="pdfPageUrl" title="教材 PDF"></iframe>
      </section>

      <aside class="calibration-properties">
        <div class="panel-title"><div><span>03</span><strong>节点属性与文字锚点</strong></div></div>
        <template v-if="selectedNode">
          <el-form label-position="top">
            <el-form-item label="节点标题"><el-input v-model="selectedNode.title" /></el-form-item>
            <el-form-item label="节点类型"><el-select v-model="selectedNode.node_type"><el-option label="章" value="chapter" /><el-option label="节" value="section" /><el-option label="知识点" value="knowledge_point" /><el-option label="前言" value="preface" /><el-option label="参考文献" value="reference" /></el-select></el-form-item>
            <el-form-item label="关联专题"><el-select v-model="selectedNode.chapter_id" clearable><el-option v-for="chapter in chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item>
            <el-form-item label="父级节点"><el-select v-model="selectedNode.parent_client_id" clearable><el-option v-for="node in nodes.filter((item) => item.client_id !== selectedNode?.client_id)" :key="node.client_id" :label="node.title" :value="node.client_id" /></el-select></el-form-item>
            <el-form-item label="PDF 页范围"><div class="page-pair"><el-input-number v-model="selectedNode.pdf_page_start" :min="1" :max="maxPage" /><span>—</span><el-input-number v-model="selectedNode.pdf_page_end" :min="selectedNode.pdf_page_start" :max="maxPage" /></div></el-form-item>
            <el-form-item><el-checkbox v-model="selectedNode.retrieval_enabled">纳入 AI 检索</el-checkbox></el-form-item>
          </el-form>
          <div class="anchor-tools"><strong>本页文字（可拖选）</strong><p>{{ selectedPageData?.text || '该页未提取到可检索文字' }}</p><div><el-button size="small" @click="useSelectionAsAnchor('start')">设为正文起点</el-button><el-button size="small" @click="useSelectionAsAnchor('end')">设为正文终点</el-button></div></div>
          <el-button plain type="danger" :icon="Delete" @click="removeNode">删除当前节点</el-button>
        </template>
        <el-empty v-else description="请选择或添加结构节点" />
      </aside>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Promotion, Search, RefreshRight, Notebook, ArrowDown, Document, Close } from '@element-plus/icons-vue'
import { studyApi, type NoteRelatedData, type NoteSearchItem, type StudyChatMessage, type StudyNote } from '@/api/study'
import { renderTeachingDocument } from '@/utils/richText'
import { aiApi, type AiSource } from '@/api/ai'
import { getErrorMessage } from '@/utils/error'
import NoteRichEditor from '@/components/NoteRichEditor.vue'
import { notePlainText, sanitizeNoteHtml } from '@/utils/noteContent'
import { courseApi } from '@/api/courses'
import type { Chapter, Course } from '@/types'
import PdfCitationViewer from '@/components/PdfCitationViewer.vue'
import { formatBeijingDate } from '@/utils/time'

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const saving = ref(false)
const notes = ref<StudyNote[]>([])
const query = ref('')
const selectedId = ref<number | null>(null)
const editorContent = ref('')
const mode = ref<'edit' | 'preview'>('edit')
type QuickActionTask = 'note_polish' | 'note_expand' | 'note_outline' | 'note_knowledge_structure' | 'note_real_significance' | 'note_concept_compare'
const directoryDropdownVisible = ref(false)
const topicPrompt = ref('')
const modificationPrompt = ref('')
const wordLength = ref(1000)
const noteStyle = ref('通俗易懂')
const contentDepth = ref('适中')
type ChatMessage = StudyChatMessage & { pending?: boolean; quickAction?: QuickActionTask; quickLabel?: string; quickSource?: string }
const chatMessages = ref<ChatMessage[]>([])
const chatQuestion = ref('')
const chatLoading = ref(false)
const chatScroll = ref<HTMLElement | null>(null)
const writingCompareVisible = ref(false)
const writingCompareSource = ref('')
const writingCompareResult = ref('')
const semanticResults = ref<NoteSearchItem[]>([])
const related = ref<NoteRelatedData>({ related_notes: [], textbook_chunks: [], status: 'ready', message: '' })
const relatedLoading = ref(false)
const relatedVisible = ref(false)
const richEditor = ref<InstanceType<typeof NoteRichEditor> | null>(null)
const previewContent = ref<HTMLElement | null>(null)
const viewFontScale = ref(Number(localStorage.getItem('notes_font_scale')) || 1)
const viewLineHeight = ref(Number(localStorage.getItem('notes_line_height')) || 1.9)
const formatBarOpen = ref(localStorage.getItem('notes_format_bar_open') === 'true')
const createDialogVisible = ref(false)
const courses = ref<Course[]>([])
const createCourseId = ref<number | null>(null)
const availableChapters = ref<Chapter[]>([])
const createChapterId = ref<number | null>(null)
const createLoading = ref(false)
const citationVisible = ref(false)
const selectedSource = ref<AiSource | null>(null)
const saveStatus = ref<'saved' | 'unsaved' | 'saving' | 'error'>('saved')
const lastSavedContent = ref('')
let autosaveTimer: ReturnType<typeof setTimeout> | undefined

const replaceTasks: QuickActionTask[] = ['note_polish']
type DiffRow = { type: 'same' | 'remove' | 'add' | 'change'; original?: string; result?: string }
function cleanGeneratedText(value: string) {
  return value.replace(/```[\s\S]*?```/g, (block) => block.replace(/```[^\n]*\n?/g, '')).replace(/^#{1,6}\s*/gm, '').replace(/\*\*(.*?)\*\*/g, '$1').trim()
}
function splitChineseUnits(value: string) {
  return cleanGeneratedText(value).split(/(?<=[。！？；!?;])\s*|\n+/).map((item) => item.trim()).filter(Boolean)
}
function buildDiffRows(source: string, result: string): DiffRow[] {
  const left = splitChineseUnits(source)
  const right = splitChineseUnits(result)
  const rows: DiffRow[] = []
  let i = 0; let j = 0
  while (i < left.length || j < right.length) {
    if (left[i] === right[j]) { rows.push({ type: 'same', original: left[i] }); i++; j++; continue }
    const nextLeft = right[j] ? left.indexOf(right[j], i + 1) : -1
    const nextRight = left[i] ? right.indexOf(left[i], j + 1) : -1
    if (nextLeft < 0 && nextRight < 0) { rows.push({ type: 'change', original: left[i], result: right[j] }); i++; j++; continue }
    if (nextLeft >= 0 && (nextRight < 0 || nextLeft - i <= nextRight - j)) { rows.push({ type: 'remove', original: left[i] }); i++; continue }
    rows.push({ type: 'add', result: right[j] }); j++
  }
  return rows
}

function openCitation(source: AiSource) {
  if (source.source_type === 'pdf' && source.document_id && source.pdf_page_start) { selectedSource.value = source; citationVisible.value = true }
  else if (source.source_url) window.open(source.source_url, '_blank', 'noopener,noreferrer')
}
function sourceTagType(source: AiSource) { return source.material_type === 'central' ? 'danger' : source.material_type === 'textbook' ? 'primary' : 'success' }

const filteredNotes = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return notes.value
  return notes.value.filter((item) => `${item.course_name} ${item.chapter_title} ${item.content}`.toLowerCase().includes(keyword))
})
const selected = computed(() => notes.value.find((item) => item.id === selectedId.value) || null)
const renderedContent = computed(() => sanitizeNoteHtml(editorContent.value))
const wordCount = computed(() => notePlainText(editorContent.value).replace(/\s/g, '').length)
const saveStatusLabel = computed(() => ({ saved: '已自动保存', unsaved: '等待自动保存', saving: '正在保存…', error: '自动保存失败' }[saveStatus.value]))
const noteOutline = computed(() => {
  if (!editorContent.value) return []
  const document = new DOMParser().parseFromString(editorContent.value, 'text/html')
  return Array.from(document.querySelectorAll('h2, h3')).map((item, index) => ({
    index,
    level: item.tagName.toLowerCase(),
    title: item.textContent?.trim() || `未命名标题 ${index + 1}`,
  }))
})
const workspaceStyle = computed(() => ({ gridTemplateColumns: 'minmax(0, 1fr)' }))

async function load() {
  loading.value = true
  try {
    notes.value = (await studyApi.notes()).data.data
    const requestedChapterId = Number(route.query.chapter_id)
    const requested = Number.isFinite(requestedChapterId) ? notes.value.find((item) => item.chapter_id === requestedChapterId) : null
    if (requested) selectNote(requested)
    if (!selected.value && notes.value.length) selectNote(notes.value[0])
  } finally { loading.value = false }
}
function selectNote(note: StudyNote) {
  if (selected.value && editorContent.value !== lastSavedContent.value) void save(true)
  if (autosaveTimer) clearTimeout(autosaveTimer)
  quickActionMessageId.value = null
  quickActionTask.value = null
  quickActionSource.value = ''
  quickActionTitle.value = ''
  selectedId.value = note.id
  const content = sanitizeNoteHtml(note.content)
  lastSavedContent.value = content
  editorContent.value = content
  topicPrompt.value = note.chapter_title || ''
  saveStatus.value = 'saved'
  mode.value = 'edit'
  relatedVisible.value = false
  void loadChatHistory(note.chapter_id)
  void loadRelated(note.chapter_id)
}
function toggleDirectory() { directoryDropdownVisible.value = !directoryDropdownVisible.value }
function closeDirectory() { directoryDropdownVisible.value = false }
async function loadChatHistory(chapterId: number) {
  chatMessages.value = []
  try { chatMessages.value = (await studyApi.chatHistory(chapterId)).data.data } catch { ElMessage.warning('AI 对话历史暂时无法加载') }
  await scrollChatToBottom()
}
async function loadRelated(chapterId: number) {
  relatedLoading.value = true
  try { related.value = (await studyApi.related(chapterId)).data.data }
  catch { related.value = { related_notes: [], textbook_chunks: [], status: 'error', message: '教材关联加载失败，请检查网络或 Embedding 服务后重试。' } }
  finally { relatedLoading.value = false }
}
async function scrollChatToBottom() {
  await nextTick()
  if (chatScroll.value) chatScroll.value.scrollTop = chatScroll.value.scrollHeight
}
function scheduleAutosave() {
  if (autosaveTimer) clearTimeout(autosaveTimer)
  if (!selected.value || editorContent.value === lastSavedContent.value) return
  autosaveTimer = setTimeout(() => { void save(true) }, 1800)
}
async function save(silent = false) {
  if (!selected.value || saving.value) return
  if (editorContent.value === lastSavedContent.value) {
    saveStatus.value = 'saved'
    if (!silent) ElMessage.success('笔记内容已保存')
    return
  }
  const noteToSave = selected.value
  const contentToSave = editorContent.value
  saving.value = true
  saveStatus.value = 'saving'
  try {
    const saved = (await studyApi.saveNote(noteToSave.chapter_id, contentToSave)).data.data
    Object.assign(noteToSave, saved)
    if (selected.value?.id === noteToSave.id) {
      lastSavedContent.value = sanitizeNoteHtml(saved.content)
      saveStatus.value = editorContent.value === lastSavedContent.value ? 'saved' : 'unsaved'
    }
    if (!silent) {
      await loadRelated(noteToSave.chapter_id)
      ElMessage.success('笔记已保存')
    }
  } catch (error: unknown) {
    if (selected.value?.id === noteToSave.id) saveStatus.value = 'error'
    if (!silent) ElMessage.error(getErrorMessage(error, '笔记保存失败'))
  } finally {
    saving.value = false
    if (editorContent.value !== lastSavedContent.value) scheduleAutosave()
  }
}
async function semanticSearch() {
  const keyword = query.value.trim()
  if (!keyword) return semanticResults.value = []
  try { semanticResults.value = (await studyApi.semanticSearch(keyword)).data.data } catch { semanticResults.value = [] }
}
async function openCreateDialog() {
  createDialogVisible.value = true
  if (!courses.value.length) courses.value = (await courseApi.list()).data.data
  if (courses.value.length && !createCourseId.value) createCourseId.value = courses.value[0].id
  await loadCreateChapters()
}
async function loadCreateChapters() {
  createChapterId.value = null
  availableChapters.value = createCourseId.value ? (await courseApi.detail(createCourseId.value)).data.data.chapters : []
}
async function createOrOpenNote() {
  if (!createChapterId.value) return ElMessage.warning('请选择专题章节')
  const existing = notes.value.find((item) => item.chapter_id === createChapterId.value)
  if (existing) {
    selectNote(existing); createDialogVisible.value = false; ElMessage.info('该专题已有笔记，已为你打开'); return
  }
  createLoading.value = true
  try {
    const created = (await studyApi.saveNote(createChapterId.value, '<p><br></p>')).data.data
    await load()
    const note = notes.value.find((item) => item.id === created.id)
    if (note) selectNote(note)
    createDialogVisible.value = false
    ElMessage.success('章节笔记已创建，可以开始整理')
  } finally { createLoading.value = false }
}
async function scrollToOutline(index: number) {
  await nextTick()
  if (mode.value === 'edit') richEditor.value?.scrollToHeading(index)
  else previewContent.value?.querySelectorAll<HTMLElement>('h2, h3')[index]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
function setViewPreference(kind: 'font' | 'line', value: number) {
  if (kind === 'font') { viewFontScale.value = value; localStorage.setItem('notes_font_scale', String(value)) }
  else { viewLineHeight.value = value; localStorage.setItem('notes_line_height', String(value)) }
}
async function exportNote(format: 'markdown' | 'docx') {
  if (!selected.value) return
  const response = await studyApi.exportNote(selected.value.chapter_id, format)
  const link = document.createElement('a')
  link.href = URL.createObjectURL(response.data)
  link.download = `${selected.value.chapter_title}-学习笔记.${format === 'markdown' ? 'md' : 'docx'}`
  link.click(); URL.revokeObjectURL(link.href)
}
function handleEditorAction(command: string) {
  if (command === 'export-markdown') void exportNote('markdown')
  else if (command === 'export-docx') void exportNote('docx')
  else if (command === 'toggle-format') {
    formatBarOpen.value = !formatBarOpen.value
    localStorage.setItem('notes_format_bar_open', String(formatBarOpen.value))
  }
  else if (command === 'return' && selected.value) void router.push(`/courses/${selected.value.course_id}/chapters/${selected.value.chapter_id}/review`)
  else if (command === 'delete') void remove()
}
async function clearChat() {
  if (!selected.value) return
  await ElMessageBox.confirm('清空后将无法恢复本章问答记录，是否继续？', '清空本章会话', { type: 'warning' })
  await studyApi.clearChatHistory(selected.value.chapter_id)
  chatMessages.value = []
  ElMessage.success('本章会话已清空')
}
const quickActions = [
  ['note_polish', '润色表达'], ['note_expand', '扩写观点'], ['note_outline', '复习提纲'],
  ['note_knowledge_structure', '知识结构'], ['note_real_significance', '现实意义'], ['note_concept_compare', '易混概念'],
] as const
const quickActionMessageId = ref<number | null>(null)
function useQuickPrompt(taskType: QuickActionTask, label: string) {
  if (!selected.value) return ElMessage.warning('请先选择一篇专题笔记')
  const prompts: Record<typeof quickActions[number][0], string> = {
    note_polish: '请润色当前笔记的表达，保持原意和论证结构，不补充教材外事实。',
    note_expand: '请基于当前笔记和本专题教材，补充观点逻辑与关键概念，并标明新增内容。',
    note_outline: '请把当前笔记整理成层级清晰的复习提纲，保留核心观点和概念关系。',
    note_knowledge_structure: '请根据当前笔记梳理章节知识结构，用清晰的层级和关系说明呈现。',
    note_real_significance: '请结合本专题教材说明当前笔记涉及理论的现实意义，不延伸到教材外事实。',
    note_concept_compare: '请辨析当前笔记中容易混淆的概念，给出简明对比和记忆提示。',
  }
  const detail = modificationPrompt.value.trim()
  chatQuestion.value = `${prompts[taskType] || `请帮我完成“${label}”任务。`}${detail ? `\n补充要求：${detail}` : ''}`
  const plainContent = notePlainText(editorContent.value)
  quickActionMessageId.value = null
  quickActionSource.value = plainContent
  quickActionTitle.value = label
  quickActionTask.value = taskType
}
async function runQuickAction(taskType: QuickActionTask, label: string) {
  useQuickPrompt(taskType, label)
  await askAi()
}
const quickActionTask = ref<QuickActionTask | null>(null)
const quickActionTitle = ref('')
const quickActionSource = ref('')
const quickActionMessage = computed(() => chatMessages.value.find((message) => message.id === quickActionMessageId.value) || null)
const canReplaceResult = computed(() => !!quickActionMessage.value?.quickAction && replaceTasks.includes(quickActionMessage.value.quickAction))
const writingDiffRows = computed(() => {
  const message = quickActionMessage.value
  if (!message || !message.quickAction || !replaceTasks.includes(message.quickAction)) return []
  return buildDiffRows(message.quickSource || '', message.content || '').filter((row) => row.type !== 'same')
})
function openWritingCompare(message: ChatMessage) {
  quickActionMessageId.value = message.id
  quickActionTitle.value = message.quickLabel || 'AI 操作'
  writingCompareSource.value = message.quickSource || quickActionSource.value
  writingCompareResult.value = message.content
  writingCompareVisible.value = true
}
function dismissWritingResult() {
  quickActionMessageId.value = null
  quickActionTask.value = null
  quickActionTitle.value = ''
  quickActionSource.value = ''
  writingCompareVisible.value = false
}
function applyWriting(message: ChatMessage, action: 'replace' | 'append') {
  if (!message.content) return
  const generated = sanitizeNoteHtml(renderTeachingDocument(message.content))
  editorContent.value = action === 'replace' ? generated : `${editorContent.value}${generated}`
  mode.value = 'edit'
  ElMessage.success(action === 'replace' ? '已替换到编辑区，请确认后保存' : '已插入笔记末尾，请确认后保存')
  dismissWritingResult()
}
async function generateFromWorkbench() {
  if (!selected.value) return ElMessage.warning('请先从顶部“我的笔记”选择一个专题')
  const detail = modificationPrompt.value.trim()
  if (!detail && !editorContent.value.trim()) return ElMessage.warning('请填写想要整理的内容或修改要求')
  useQuickPrompt('note_polish', '润色表达')
  await askAi()
}
async function remove() {
  if (!selected.value) return
  await ElMessageBox.confirm(`确定删除“${selected.value.chapter_title}”的学习笔记吗？`, '删除笔记', { type: 'warning' })
  await studyApi.deleteNote(selected.value.id)
  if (autosaveTimer) clearTimeout(autosaveTimer)
  selectedId.value = null
  editorContent.value = ''
  chatMessages.value = []
  await load()
  ElMessage.success('笔记已删除')
}
async function askAi() {
  const note = selected.value
  const question = chatQuestion.value.trim()
  if (!note) return ElMessage.warning('请先选择一篇专题笔记')
  if (!question) return ElMessage.warning('请输入想向 AI 请教的问题')
  const selectedQuickTask = quickActionTask.value
  const selectedQuickLabel = quickActionTitle.value
  const selectedQuickSource = quickActionSource.value || notePlainText(editorContent.value)
  const temporaryUser: ChatMessage = { id: -Date.now(), user_id: 0, course_id: note.course_id, chapter_id: note.chapter_id, role: 'user', content: question, model: null, sources: [], created_time: new Date().toISOString(), pending: true }
  const temporaryAssistant: ChatMessage = { id: temporaryUser.id - 1, user_id: 0, course_id: note.course_id, chapter_id: note.chapter_id, role: 'assistant', content: '', model: null, sources: [], created_time: new Date().toISOString(), pending: true, quickAction: selectedQuickTask || undefined, quickLabel: selectedQuickLabel || undefined, quickSource: selectedQuickSource }
  chatMessages.value.push(temporaryUser, temporaryAssistant)
  quickActionMessageId.value = temporaryAssistant.id
  quickActionTask.value = null
  chatQuestion.value = ''
  chatLoading.value = true
  await scrollChatToBottom()
  try {
    const noteExcerpt = notePlainText(editorContent.value).slice(0, 6000)
    const history = chatMessages.value.slice(-8, -2).map((item) => `${item.role === 'user' ? '学生' : 'AI'}：${item.content}`).join('\n')
    const prompt = `用户正在整理“${topicPrompt.value.trim() || note.chapter_title || '当前专题'}”的学习笔记。请依据当前专题教材资料，以教材化、清晰的表达回答问题；如资料不足请明确说明。${noteStyle.value ? `\n表达风格：${noteStyle.value}` : ''}${contentDepth.value ? `\n内容深度：${contentDepth.value}` : ''}${wordLength.value ? `\n目标字数：约 ${wordLength.value} 字` : ''}\n\n用户笔记参考：\n${noteExcerpt || '暂无笔记内容'}\n\n本章最近会话（仅用于承接追问）：\n${history || '无'}\n\n用户问题：${question}`
    await aiApi.assistStream({ course_id: note.course_id, chapter_id: note.chapter_id, learning_stage: 'review', task_type: selectedQuickTask || 'question_answer', question: prompt }, {
      onMeta: (meta) => { temporaryAssistant.model = meta.model },
      onChunk: (text) => { temporaryAssistant.content += text; void scrollChatToBottom() },
      onSources: (sources: AiSource[]) => { temporaryAssistant.sources = sources },
    })
    const quickMetadata = new Map(chatMessages.value.filter((message) => message.quickAction).map((message) => [message.id, { quickAction: message.quickAction, quickLabel: message.quickLabel, quickSource: message.quickSource }]))
    const savedHistory = (await studyApi.saveChatHistory({
      course_id: note.course_id, chapter_id: note.chapter_id, question,
      answer: temporaryAssistant.content, model: temporaryAssistant.model, sources: temporaryAssistant.sources,
    })).data.data
    const savedAssistant = [...savedHistory].reverse().find((message) => message.role === 'assistant')
    chatMessages.value = savedHistory.map((message) => {
      const metadata = quickMetadata.get(message.id)
      if (metadata) return { ...message, ...metadata }
      return message.id === savedAssistant?.id && selectedQuickTask
        ? { ...message, quickAction: selectedQuickTask, quickLabel: selectedQuickLabel, quickSource: selectedQuickSource }
        : message
    })
    if (savedAssistant) quickActionMessageId.value = savedAssistant.id
  } catch (error: unknown) {
    temporaryAssistant.content = `生成失败：${getErrorMessage(error, 'AI 暂时无法回答，请稍后重试')}`
  } finally {
    chatLoading.value = false
    await scrollChatToBottom()
  }
}
function onEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && formatBarOpen.value) {
    formatBarOpen.value = false
    localStorage.setItem('notes_format_bar_open', 'false')
  }
}
onMounted(() => { window.addEventListener('keydown', onEscape); void load() })
watch(editorContent, (value) => {
  if (!selected.value || value === lastSavedContent.value) return
  saveStatus.value = 'unsaved'
  scheduleAutosave()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onEscape)
  if (autosaveTimer) clearTimeout(autosaveTimer)
})
</script>

<template>
  <div v-loading="loading" class="notes-page-replica">
    <header class="notes-page-header">
      <div class="notes-page-heading"><span class="eyebrow">NOTE REVIEW</span><h1>笔记复习</h1><p>{{ selected?.chapter_title || '整理你的教材理解，留下可复习的知识线索。' }}</p></div>
      <el-input v-model="query" class="notes-page-search" :prefix-icon="Search" clearable placeholder="搜索任何内容" @input="semanticSearch" />
      <div class="notes-page-actions">
        <div class="notes-directory-menu">
          <el-button plain @click="toggleDirectory">我的笔记 <el-icon><ArrowDown /></el-icon></el-button>
          <div v-if="directoryDropdownVisible" class="notes-directory-dropdown">
            <header><strong>我的笔记</strong><el-button text :icon="Close" aria-label="关闭笔记目录" @click="closeDirectory" /></header>
            <button v-for="note in filteredNotes" :key="note.id" type="button" :class="{ active: note.id === selectedId }" @click="selectNote(note); closeDirectory()"><strong>{{ note.chapter_title }}</strong></button>
            <el-empty v-if="!filteredNotes.length" :image-size="42" description="暂无笔记" />
          </div>
        </div>
        <el-button class="notes-review-entry" plain @click="router.push('/reviews')"><el-icon><RefreshRight /></el-icon>今日复习</el-button>
        <el-button type="primary" @click="openCreateDialog">＋ 新建章节笔记</el-button>
      </div>
    </header>

    <section class="notes-replica-layout">
      <aside class="notes-generation-panel notes-generation-panel--slim" aria-label="笔记生成工作台">
        <header class="notes-generation-heading"><div><h2>专题笔记工作台</h2></div><el-button text :icon="Document" title="查看当前依据" @click="relatedVisible = true" /></header>
        <div class="notes-form-field"><label for="note-topic">笔记主题 <em>*</em></label><el-input id="note-topic" v-model="topicPrompt" maxlength="120" placeholder="例如：新时代坚持和发展中国特色社会主义" /></div>
        <div class="notes-form-field"><label for="note-request">修改要求</label><el-input id="note-request" v-model="modificationPrompt" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="例如：压缩第二段，保留核心观点，语气更简洁。" /></div>
        <div class="notes-form-grid">
          <div class="notes-form-field"><label>目标字数</label><el-input-number v-model="wordLength" :min="200" :max="5000" :step="100" controls-position="right" /></div>
          <div class="notes-form-field"><label>表达风格</label><el-select v-model="noteStyle"><el-option label="通俗易懂" value="通俗易懂" /><el-option label="严谨简洁" value="严谨简洁" /><el-option label="复习提纲" value="复习提纲" /></el-select></div>
        </div>
        <el-button class="notes-generate-button" type="primary" :loading="chatLoading" @click="generateFromWorkbench">生成笔记建议</el-button>
        <section class="notes-quick-panel"><header><strong>快捷响应</strong></header><div class="notes-quick-grid"><button v-for="[task, label] in quickActions" :key="task" type="button" :disabled="chatLoading" :class="{ active: quickActionTask === task }" @click="runQuickAction(task, label)"><el-icon><MagicStick /></el-icon><span>{{ label }}</span></button></div></section>
      </aside>

      <main class="notes-editor-stage">
        <template v-if="selected">
          <header class="notes-editor-topbar">
            <el-select class="notes-chapter-select" :model-value="selected.chapter_id" disabled>
              <el-option :label="selected.chapter_title" :value="selected.chapter_id" />
            </el-select>
            <div class="notes-toolbar-group">
              <button type="button" title="改写" @click="runQuickAction('note_polish', '改写')">✎ 改写</button>
              <button type="button" title="总结" @click="runQuickAction('note_outline', '总结')">✦ 总结</button>
              <el-dropdown trigger="click">
                <button type="button" class="toolbar-size-button" title="字号">字号⌄</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="size in [14, 16, 18, 20, 24]" :key="size" @click="richEditor?.setFontSize(size)">{{ size }} px</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <button type="button" class="toolbar-highlight-button" title="高亮" @mousedown.prevent @click="richEditor?.highlight('#ffd7d7')"><span></span>高亮</button>
              <button type="button" title="加粗" @mousedown.prevent @click="richEditor?.command('bold')">B</button>
              <button type="button" title="斜体（选中文字后点击，或先点击再输入）" aria-label="斜体" @mousedown.prevent @click="richEditor?.toggleItalic()"><em>I</em></button>
              <button type="button" title="下划线" @mousedown.prevent @click="richEditor?.command('underline')"><u>U</u></button>
              <button type="button" title="无序列表" @mousedown.prevent @click="richEditor?.command('insertUnorderedList')">列表</button>
              <el-dropdown trigger="click" @command="handleEditorAction">
                <button type="button" title="更多工具">···</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="export-docx">导出 Word</el-dropdown-item>
                    <el-dropdown-item command="export-markdown">导出 Markdown</el-dropdown-item>
                    <el-dropdown-item divided command="toggle-format">{{ formatBarOpen ? '收起格式工具' : '打开格式工具' }}</el-dropdown-item>
                    <el-dropdown-item command="return">返回当前专题</el-dropdown-item>
                    <el-dropdown-item divided command="delete">删除当前笔记</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </header>
          <section v-if="formatBarOpen" class="note-format-ribbon notes-format-ribbon-replica"><div class="ribbon-group"><span>文字</span><div @mousedown.prevent><button @click="richEditor?.command('removeFormat')">清除格式</button><button @click="richEditor?.setBlock('h2')">标题</button><button @click="richEditor?.setBlock('p')">正文</button></div></div><div class="ribbon-preferences"><el-select :model-value="viewFontScale" size="small" @change="(value: number) => setViewPreference('font', value)"><el-option label="标准字号" :value="1" /><el-option label="大字号" :value="1.12" /></el-select><el-select :model-value="viewLineHeight" size="small" @change="(value: number) => setViewPreference('line', value)"><el-option label="标准行距" :value="1.9" /><el-option label="宽松行距" :value="2.2" /></el-select></div></section>
          <div class="notes-editor-canvas"><NoteRichEditor v-if="mode === 'edit'" ref="richEditor" v-model="editorContent" :font-scale="viewFontScale" :line-height="viewLineHeight" /><article v-else ref="previewContent" class="note-preview rich-note-content" :style="{ fontSize: `${16 * viewFontScale}px`, lineHeight: String(viewLineHeight) }" v-html="renderedContent"></article></div>
          <section v-if="quickActionMessage || chatLoading" class="notes-result-card"><header><div><span>生成结果</span><strong>{{ quickActionMessage?.quickLabel || quickActionTitle || '当前专题建议' }}</strong></div><span v-if="chatLoading" class="notes-result-status">正在生成</span><span v-else>请核对教材依据</span></header><div v-if="chatLoading && !quickActionMessage?.content" class="result-loading"><i></i><i></i><i></i></div><template v-else-if="quickActionMessage"><div v-if="canReplaceResult" class="notes-diff-view"><p class="notes-diff-hint">仅显示发生变化的句子，未变化内容已隐藏</p><div v-for="(row, index) in writingDiffRows" :key="`${row.type}-${index}`" class="notes-diff-row" :class="`is-${row.type}`"><span class="notes-diff-badge">{{ row.type === 'remove' ? '原文' : row.type === 'add' ? '新增' : '修改前' }}</span><p v-if="row.original">{{ row.original }}</p><span v-if="row.type === 'change'" class="notes-diff-arrow">→</span><p v-if="row.result" class="notes-diff-new">{{ row.result }}</p></div><el-empty v-if="!writingDiffRows.length" :image-size="42" description="未检测到明显变化" /></div><article v-else class="teaching-document notes-result-document" v-html="renderTeachingDocument(quickActionMessage.content)"></article><footer><el-button size="small" @click="openWritingCompare(quickActionMessage)">查看完整对比</el-button><el-button v-if="canReplaceResult" size="small" type="primary" @click="applyWriting(quickActionMessage, 'replace')">接受修改</el-button><el-button size="small" @click="applyWriting(quickActionMessage, 'append')">插入文末</el-button><el-button text size="small" @click="dismissWritingResult">放弃</el-button></footer></template></section>
          <footer class="notes-editor-footer"><span :class="`save-state ${saveStatus}`">{{ wordCount }} 字 · {{ saveStatusLabel }}</span><div><el-button text @click="mode = mode === 'edit' ? 'preview' : 'edit'">{{ mode === 'edit' ? '预览' : '继续编辑' }}</el-button><el-button @click="exportNote('docx')"><el-icon><Document /></el-icon> 导出 Word</el-button><el-button type="primary" :loading="saving" :disabled="saveStatus === 'saved'" @click="save()">保存</el-button></div></footer>
        </template>
        <section v-else class="notes-empty-editor"><el-icon :size="38"><Notebook /></el-icon><h2>选择一个专题开始整理</h2><p>从顶部“我的笔记”打开已有笔记，或创建一篇新的章节笔记。</p><el-button type="primary" @click="openCreateDialog">新建章节笔记</el-button></section>
      </main>
    </section>
    <el-dialog v-model="createDialogVisible" title="新建章节笔记" width="480px">
      <el-form label-position="top"><el-form-item label="选择教材"><el-select v-model="createCourseId" style="width:100%" @change="loadCreateChapters"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item><el-form-item label="选择专题章节"><el-select v-model="createChapterId" filterable style="width:100%" placeholder="请选择需要整理的章节"><el-option v-for="chapter in availableChapters" :key="chapter.id" :label="`${chapter.title}${notes.some((note) => note.chapter_id === chapter.id) ? '（已有笔记）' : ''}`" :value="chapter.id" /></el-select></el-form-item></el-form><p class="create-note-hint">每个专题保留一篇个人主笔记；如果已经创建，系统会直接打开原笔记。</p><template #footer><el-button @click="createDialogVisible = false">取消</el-button><el-button type="primary" :loading="createLoading" @click="createOrOpenNote">创建并编辑</el-button></template>
    </el-dialog>
    <el-dialog v-model="writingCompareVisible" :title="`${quickActionTitle || 'AI 操作'} · 修改前后对比`" width="min(94vw, 1180px)" top="6vh">
      <div class="writing-compare-grid"><section><header><strong>原始笔记</strong><span>{{ writingCompareSource.length }} 字</span></header><article>{{ writingCompareSource }}</article></section><section><header><strong>AI 建议结果</strong><span>{{ writingCompareResult.length }} 字</span></header><article class="teaching-document" v-html="renderTeachingDocument(writingCompareResult)"></article></section></div>
      <template #footer><el-button @click="writingCompareVisible = false">继续修改</el-button><el-button v-if="quickActionMessage" @click="applyWriting(quickActionMessage, 'append'); writingCompareVisible = false">插入文末</el-button><el-button v-if="quickActionMessage && canReplaceResult" type="primary" @click="applyWriting(quickActionMessage, 'replace'); writingCompareVisible = false">接受修改</el-button></template>
    </el-dialog>
    <el-drawer v-model="relatedVisible" title="当前依据" direction="rtl" size="380px">
      <div class="related-panel notes-related-drawer-body" v-loading="relatedLoading">
        <div class="related-status" :class="related.status"><span>{{ related.status === 'vector' ? '向量关联' : related.status === 'chapter_fallback' ? '章节正文关联' : related.status === 'error' ? '关联失败' : '关联提示' }}</span><el-button v-if="selected" text size="small" :icon="RefreshRight" @click="loadRelated(selected.chapter_id)">重新关联</el-button></div>
        <p class="toolbox-hint">{{ related.message || '保存笔记后，可在这里查看语义相关的教材段落。' }}</p>
        <article v-for="item in related.textbook_chunks" :key="`${item.source_title}-${item.position}`"><span>{{ item.position }}</span><strong>{{ item.source_title }}</strong><p>{{ item.excerpt }}</p></article>
        <h3 v-if="related.related_notes.length">相关章节笔记</h3><button v-for="item in related.related_notes" :key="item.id" class="related-note-link" @click="selectNote(notes.find((note) => note.id === item.id) || notes[0]); relatedVisible = false"><strong>{{ item.chapter_title }}</strong><span>{{ item.excerpt }}</span></button>
        <el-empty v-if="!relatedLoading && !related.textbook_chunks.length && !related.related_notes.length" :image-size="58" description="暂无可展示的关联依据" />
      </div>
    </el-drawer>
    <PdfCitationViewer v-model:visible="citationVisible" :source="selectedSource" />
  </div>
</template>

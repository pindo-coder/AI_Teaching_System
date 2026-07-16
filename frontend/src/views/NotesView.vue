<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Delete, EditPen, MagicStick, Promotion, Reading, Search, Download, RefreshRight, Operation, Notebook, Brush, Connection, ArrowLeftBold, ArrowRightBold } from '@element-plus/icons-vue'
import { studyApi, type NoteRelatedData, type NoteSearchItem, type StudyChatMessage, type StudyNote } from '@/api/study'
import { renderTeachingDocument } from '@/utils/richText'
import { aiApi, type AiSource } from '@/api/ai'
import { getErrorMessage } from '@/utils/error'
import NoteRichEditor from '@/components/NoteRichEditor.vue'
import { notePlainText, sanitizeNoteHtml } from '@/utils/noteContent'
import { courseApi } from '@/api/courses'
import type { Chapter, Course } from '@/types'

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const saving = ref(false)
const notes = ref<StudyNote[]>([])
const query = ref('')
const selectedId = ref<number | null>(null)
const editorContent = ref('')
const mode = ref<'edit' | 'preview'>('edit')
type ChatMessage = StudyChatMessage & { pending?: boolean }
const chatMessages = ref<ChatMessage[]>([])
const chatQuestion = ref('')
const chatLoading = ref(false)
const chatScroll = ref<HTMLElement | null>(null)
const semanticResults = ref<NoteSearchItem[]>([])
const related = ref<NoteRelatedData>({ related_notes: [], textbook_chunks: [], status: 'ready', message: '' })
const relatedLoading = ref(false)
const writingLoading = ref(false)
const writingResult = ref('')
const writingTitle = ref('')
type ToolPanel = 'index' | 'writing' | 'format' | 'related'
const activeTool = ref<ToolPanel>('index')
const toolboxOpen = ref(localStorage.getItem('notes_toolbox_open') !== 'false')
const splitWorkspace = ref<HTMLElement | null>(null)
const editorRatio = ref(Math.min(72, Math.max(48, Number(localStorage.getItem('notes_editor_ratio')) || 64)))
const aiCollapsed = ref(localStorage.getItem('notes_ai_collapsed') === 'true')
const richEditor = ref<InstanceType<typeof NoteRichEditor> | null>(null)
const viewFontScale = ref(Number(localStorage.getItem('notes_font_scale')) || 1)
const viewLineHeight = ref(Number(localStorage.getItem('notes_line_height')) || 1.9)
const formatBarOpen = ref(localStorage.getItem('notes_format_bar_open') === 'true')
const createDialogVisible = ref(false)
const courses = ref<Course[]>([])
const createCourseId = ref<number | null>(null)
const availableChapters = ref<Chapter[]>([])
const createChapterId = ref<number | null>(null)
const createLoading = ref(false)

const filteredNotes = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return notes.value
  return notes.value.filter((item) => `${item.course_name} ${item.chapter_title} ${item.content}`.toLowerCase().includes(keyword))
})
const selected = computed(() => notes.value.find((item) => item.id === selectedId.value) || null)
const renderedContent = computed(() => sanitizeNoteHtml(editorContent.value))
const wordCount = computed(() => notePlainText(editorContent.value).replace(/\s/g, '').length)
const workspaceStyle = computed(() => aiCollapsed.value
  ? { gridTemplateColumns: 'minmax(0, 1fr)' }
  : { gridTemplateColumns: `minmax(420px, ${editorRatio.value}fr) 8px minmax(320px, ${100 - editorRatio.value}fr)` })

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
  selectedId.value = note.id
  editorContent.value = sanitizeNoteHtml(note.content)
  mode.value = 'edit'
  void loadChatHistory(note.chapter_id)
  void loadRelated(note.chapter_id)
}
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
async function save() {
  if (!selected.value) return
  saving.value = true
  try {
    const saved = (await studyApi.saveNote(selected.value.chapter_id, editorContent.value)).data.data
    Object.assign(selected.value, saved)
    await loadRelated(selected.value.chapter_id)
    ElMessage.success('笔记已保存')
  } finally { saving.value = false }
}
async function semanticSearch() {
  const keyword = query.value.trim()
  if (!keyword) return semanticResults.value = []
  try { semanticResults.value = (await studyApi.semanticSearch(keyword)).data.data } catch { semanticResults.value = [] }
}
function toggleTool(tool: ToolPanel) {
  if (tool === 'format') {
    formatBarOpen.value = !formatBarOpen.value
    toolboxOpen.value = false
    activeTool.value = 'format'
    localStorage.setItem('notes_format_bar_open', String(formatBarOpen.value))
    localStorage.setItem('notes_toolbox_open', 'false')
    return
  }
  formatBarOpen.value = false
  if (activeTool.value === tool) toolboxOpen.value = !toolboxOpen.value
  else { activeTool.value = tool; toolboxOpen.value = true }
  localStorage.setItem('notes_toolbox_open', String(toolboxOpen.value))
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
function setToolboxOpen(value: boolean) {
  toolboxOpen.value = value
  localStorage.setItem('notes_toolbox_open', String(value))
}
function setAiCollapsed(value: boolean) {
  aiCollapsed.value = value
  localStorage.setItem('notes_ai_collapsed', String(value))
}
function startResize(event: PointerEvent) {
  if (aiCollapsed.value || !splitWorkspace.value) return
  event.preventDefault()
  const move = (pointer: PointerEvent) => {
    const rect = splitWorkspace.value!.getBoundingClientRect()
    const minEditor = Math.min(520, rect.width * .48)
    const minAi = Math.min(360, rect.width * .34)
    const editorWidth = Math.min(rect.width - minAi, Math.max(minEditor, pointer.clientX - rect.left))
    editorRatio.value = Math.round(editorWidth / rect.width * 1000) / 10
  }
  const stop = () => {
    localStorage.setItem('notes_editor_ratio', String(editorRatio.value))
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
}
function resetSplit() { editorRatio.value = 64; localStorage.setItem('notes_editor_ratio', '64') }
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
async function clearChat() {
  if (!selected.value) return
  await ElMessageBox.confirm('清空后将无法恢复本章问答记录，是否继续？', '清空本章会话', { type: 'warning' })
  await studyApi.clearChatHistory(selected.value.chapter_id)
  chatMessages.value = []
  ElMessage.success('本章会话已清空')
}
const writingActions = [
  ['note_polish', '润色表达'], ['note_expand', '扩写观点'], ['note_outline', '复习提纲'],
  ['note_knowledge_structure', '知识结构'], ['note_real_significance', '现实意义'], ['note_concept_compare', '易混概念'],
] as const
async function runWriting(taskType: typeof writingActions[number][0], label: string) {
  const note = selected.value
  if (!note) return
  const plainContent = notePlainText(editorContent.value)
  if (!plainContent) return ElMessage.warning('请先写下笔记内容，再使用 AI 写作辅助')
  writingLoading.value = true; writingResult.value = ''; writingTitle.value = label
  const prompt = `以下是学生围绕“${note.chapter_title}”整理的个人笔记。请完成“${label}”任务；只能使用当前专题教材与这份笔记的信息，不得补充其他章节或教材外事实。\n\n个人笔记：\n${plainContent.slice(0, 9000)}`
  try {
    await aiApi.assistStream({ course_id: note.course_id, chapter_id: note.chapter_id, learning_stage: 'review', task_type: taskType, question: prompt }, {
      onMeta: () => {}, onSources: () => {}, onChunk: (text) => { writingResult.value += text },
    })
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, 'AI 写作暂时不可用')) } finally { writingLoading.value = false }
}
function applyWriting(action: 'replace' | 'append') {
  if (!writingResult.value) return
  const generated = sanitizeNoteHtml(renderTeachingDocument(writingResult.value))
  editorContent.value = action === 'replace' ? generated : `${editorContent.value}${generated}`
  mode.value = 'edit'; ElMessage.success(action === 'replace' ? '已替换到编辑区，请确认后保存' : '已插入笔记末尾，请确认后保存')
}
async function remove() {
  if (!selected.value) return
  await ElMessageBox.confirm(`确定删除“${selected.value.chapter_title}”的学习笔记吗？`, '删除笔记', { type: 'warning' })
  await studyApi.deleteNote(selected.value.id)
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
  const temporaryUser: ChatMessage = { id: -Date.now(), user_id: 0, course_id: note.course_id, chapter_id: note.chapter_id, role: 'user', content: question, model: null, sources: [], created_time: new Date().toISOString(), pending: true }
  const temporaryAssistant: ChatMessage = { id: temporaryUser.id - 1, user_id: 0, course_id: note.course_id, chapter_id: note.chapter_id, role: 'assistant', content: '', model: null, sources: [], created_time: new Date().toISOString(), pending: true }
  chatMessages.value.push(temporaryUser, temporaryAssistant)
  chatQuestion.value = ''
  chatLoading.value = true
  await scrollChatToBottom()
  try {
    const noteExcerpt = notePlainText(editorContent.value).slice(0, 6000)
    const history = chatMessages.value.slice(-8, -2).map((item) => `${item.role === 'user' ? '学生' : 'AI'}：${item.content}`).join('\n')
    const prompt = `用户正在整理“${note.chapter_title || '当前专题'}”的学习笔记。请依据当前专题教材资料，以教材化、清晰的表达回答问题；如资料不足请明确说明。\n\n用户笔记参考：\n${noteExcerpt || '暂无笔记内容'}\n\n本章最近会话（仅用于承接追问）：\n${history || '无'}\n\n用户问题：${question}`
    await aiApi.assistStream({ course_id: note.course_id, chapter_id: note.chapter_id, learning_stage: 'review', task_type: 'question_answer', question: prompt }, {
      onMeta: (meta) => { temporaryAssistant.model = meta.model },
      onChunk: (text) => { temporaryAssistant.content += text; void scrollChatToBottom() },
      onSources: (sources: AiSource[]) => { temporaryAssistant.sources = sources },
    })
    chatMessages.value = (await studyApi.saveChatHistory({
      course_id: note.course_id, chapter_id: note.chapter_id, question,
      answer: temporaryAssistant.content, model: temporaryAssistant.model, sources: temporaryAssistant.sources,
    })).data.data
  } catch (error: unknown) {
    temporaryAssistant.content = `生成失败：${getErrorMessage(error, 'AI 暂时无法回答，请稍后重试')}`
  } finally {
    chatLoading.value = false
    await scrollChatToBottom()
  }
}
function onEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && toolboxOpen.value) { toolboxOpen.value = false; localStorage.setItem('notes_toolbox_open', 'false') }
}
onMounted(() => { window.addEventListener('keydown', onEscape); void load() })
onBeforeUnmount(() => window.removeEventListener('keydown', onEscape))
</script>

<template>
  <div v-loading="loading" class="notes-knowledge-desk">
    <header class="notes-hero notes-command-hero">
      <div class="notes-hero-grid"></div>
      <div class="notes-command-copy">
        <div class="notes-value-line"><span></span>个人知识沉淀 · AI 学习书房</div>
        <div class="notes-hero-tags"><span>教材为本</span><span>自主建构</span><span>智能关联</span></div>
        <h1>把理论读进来<br><em>把自己的理解写下来</em></h1>
        <p>围绕教材专题整理观点、标记疑问、关联原文，并让 AI 对话与间隔复习延续每一次思考。</p>
        <div class="notes-hero-actions">
          <el-button type="warning" size="large" @click="openCreateDialog">＋ 新建章节笔记</el-button>
          <el-button size="large" plain @click="router.push('/reviews')"><el-icon><Reading /></el-icon>进入今日复习</el-button>
        </div>
        <div class="notes-live-context">
          <div><el-icon><Collection /></el-icon><span><small>专题笔记</small><strong>{{ notes.length }} 篇</strong></span></div>
          <div><el-icon><EditPen /></el-icon><span><small>当前状态</small><strong>{{ selected ? `${wordCount} 字` : '等待落笔' }}</strong></span></div>
          <div><el-icon><MagicStick /></el-icon><span><small>AI 上下文</small><strong>{{ selected ? '已锁定当前专题' : '选择专题后启用' }}</strong></span></div>
        </div>
      </div>
      <div class="notes-knowledge-loop" aria-label="教材、笔记、AI 对话与复习的知识沉淀回路">
        <div class="notes-loop-heading"><span>PERSONAL KNOWLEDGE LOOP</span><strong>个人知识沉淀回路</strong></div>
        <div class="notes-loop-orbit loop-outer"></div><div class="notes-loop-orbit loop-inner"></div>
        <div class="notes-loop-core"><span>NOTE</span><strong>思想笔记</strong><small>理解 · 表达 · 反思</small></div>
        <div class="notes-loop-node loop-reading"><el-icon><Reading /></el-icon><strong>教材阅读</strong><small>找到理论依据</small></div>
        <div class="notes-loop-node loop-writing"><el-icon><EditPen /></el-icon><strong>笔记沉淀</strong><small>形成个人理解</small></div>
        <div class="notes-loop-node loop-ai"><el-icon><MagicStick /></el-icon><strong>AI 对话</strong><small>追问与关联</small></div>
        <div class="notes-loop-node loop-review"><el-icon><RefreshRight /></el-icon><strong>间隔复习</strong><small>巩固知识结构</small></div>
        <span class="notes-loop-pulse pulse-a"></span><span class="notes-loop-pulse pulse-b"></span><span class="notes-loop-pulse pulse-c"></span>
        <div class="notes-loop-caption"><span></span>{{ selected ? selected.chapter_title : '选择专题，开始建立属于自己的知识体系' }}</div>
      </div>
    </header>
    <div class="notes-studio-intro"><div><p class="eyebrow">Knowledge Workspace</p><h2>专题笔记工作台</h2></div><span>工具栏管理专题、AI 写作、格式和教材关联 · 拖动中线可调整编辑区与 AI 区宽度</span></div>
    <section class="notes-studio" :class="{ 'toolbox-open': toolboxOpen }">
      <nav class="notes-tool-rail" aria-label="笔记工具">
        <button class="toolbox-brand" :class="{ active: toolboxOpen }" title="展开或收起笔记工具" @click="setToolboxOpen(!toolboxOpen)"><el-icon><Operation /></el-icon><span>工具</span></button>
        <el-tooltip content="专题索引" placement="right"><button :class="{ active: toolboxOpen && activeTool === 'index' }" @click="toggleTool('index')"><el-icon><Notebook /></el-icon><span>专题</span></button></el-tooltip>
        <el-tooltip content="AI 写作" placement="right"><button :class="{ active: toolboxOpen && activeTool === 'writing' }" @click="toggleTool('writing')"><el-icon><MagicStick /></el-icon><span>AI写作</span></button></el-tooltip>
        <el-tooltip content="文字格式与阅读偏好" placement="right"><button :class="{ active: formatBarOpen }" @click="toggleTool('format')"><el-icon><Brush /></el-icon><span>格式</span></button></el-tooltip>
        <el-tooltip content="教材关联" placement="right"><button :class="{ active: toolboxOpen && activeTool === 'related' }" @click="toggleTool('related')"><el-icon><Connection /></el-icon><span>关联</span></button></el-tooltip>
      </nav>

      <aside class="notes-toolbox" :class="{ open: toolboxOpen }">
        <header><div><span>笔记工具</span><h2>{{ activeTool === 'index' ? '专题索引' : activeTool === 'writing' ? 'AI 写作辅助' : activeTool === 'format' ? '文字与阅读设置' : '教材关联' }}</h2></div><button title="收起工具栏" @click="setToolboxOpen(false)"><el-icon><ArrowLeftBold /></el-icon></button></header>

        <section v-if="activeTool === 'index'" class="toolbox-section notes-index-panel">
          <el-button class="create-note-button" type="primary" @click="openCreateDialog">＋ 新建章节笔记</el-button>
          <el-input v-model="query" :prefix-icon="Search" clearable placeholder="搜索专题或笔记内容" @input="semanticSearch" />
          <p class="toolbox-hint">支持语义搜索，例如输入“全过程人民民主”。</p>
          <div v-if="semanticResults.length" class="toolbox-search-results"><strong>语义相关</strong><button v-for="item in semanticResults" :key="item.id" @click="selectNote(notes.find((note) => note.id === item.id) || notes[0])"><span>{{ item.chapter_title }}</span><small>{{ item.excerpt }}</small></button></div>
          <div class="notes-index-list"><button v-for="note in filteredNotes" :key="note.id" :class="{ active: selectedId === note.id }" @click="selectNote(note)"><span>{{ note.course_name }}</span><strong>{{ note.chapter_title }}</strong><small>{{ new Date(note.updated_time).toLocaleDateString('zh-CN') }}</small></button><el-empty v-if="!filteredNotes.length" :image-size="50" description="暂无匹配笔记" /></div>
        </section>

        <section v-else-if="activeTool === 'writing'" class="toolbox-section ai-writing-panel">
          <p class="toolbox-hint">AI 只使用当前专题教材和个人笔记，生成后由你决定是否写入正文。</p>
          <button v-for="[task, label] in writingActions" :key="task" class="writing-action" :disabled="writingLoading" @click="runWriting(task, label)"><el-icon><MagicStick /></el-icon><span><strong>{{ label }}</strong><small>{{ task === 'note_polish' ? '优化语句但不改变原意' : task === 'note_expand' ? '补充观点逻辑和教材概念' : task === 'note_outline' ? '压缩为层级清晰的复习材料' : task === 'note_knowledge_structure' ? '整理章节知识关系' : task === 'note_real_significance' ? '补充教材范围内的现实分析' : '辨析容易混淆的概念' }}</small></span></button>
          <section v-if="writingResult || writingLoading" class="toolbox-writing-result"><header><strong>{{ writingTitle }}结果</strong><span v-if="writingLoading">生成中…</span></header><article class="teaching-document" v-html="renderTeachingDocument(writingResult)"></article><footer v-if="!writingLoading"><el-button size="small" @click="applyWriting('append')">插入文末</el-button><el-button size="small" type="primary" @click="applyWriting('replace')">替换正文</el-button></footer></section>
        </section>

        <section v-else-if="activeTool === 'format'" class="toolbox-section format-panel">
          <p class="format-label">文字样式</p>
          <div class="format-grid" @mousedown.prevent><el-button @click="richEditor?.command('bold')"><strong>B</strong> 加粗</el-button><el-button @click="richEditor?.command('italic')"><em>I</em> 斜体</el-button><el-button @click="richEditor?.command('underline')"><u>U</u> 下划线</el-button><el-button @click="richEditor?.command('removeFormat')">清除格式</el-button></div>
          <p class="format-label">段落结构</p>
          <div class="format-grid" @mousedown.prevent><el-button @click="richEditor?.setBlock('h2')">一级标题</el-button><el-button @click="richEditor?.setBlock('h3')">二级标题</el-button><el-button @click="richEditor?.setBlock('p')">正文</el-button><el-button @click="richEditor?.command('insertOrderedList')">编号列表</el-button><el-button @click="richEditor?.command('insertUnorderedList')">项目列表</el-button></div>
          <p class="format-label">选中文字字号</p>
          <div class="font-size-row" @mousedown.prevent><button v-for="size in [14, 16, 18, 20, 24]" :key="size" @click="richEditor?.setFontSize(size)">{{ size }}</button></div>
          <p class="format-label">记号笔</p>
          <div class="highlight-row" @mousedown.prevent><button title="黄色重点" style="--highlight: #fff1a8" @click="richEditor?.highlight('#fff1a8')"></button><button title="蓝色概念" style="--highlight: #cde4ff" @click="richEditor?.highlight('#cde4ff')"></button><button title="绿色意义" style="--highlight: #d3f3dc" @click="richEditor?.highlight('#d3f3dc')"></button><button title="红色易错" style="--highlight: #ffd7d7" @click="richEditor?.highlight('#ffd7d7')"></button></div>
          <el-divider>个人阅读偏好</el-divider>
          <label class="preference-row"><span>整体显示字号</span><el-select :model-value="viewFontScale" size="small" @change="(value: number) => setViewPreference('font', value)"><el-option label="较小" :value="0.9" /><el-option label="标准" :value="1" /><el-option label="较大" :value="1.12" /><el-option label="特大" :value="1.25" /></el-select></label>
          <label class="preference-row"><span>行间距</span><el-select :model-value="viewLineHeight" size="small" @change="(value: number) => setViewPreference('line', value)"><el-option label="紧凑" :value="1.6" /><el-option label="标准" :value="1.9" /><el-option label="宽松" :value="2.2" /></el-select></label>
        </section>

        <section v-else class="toolbox-section related-panel" v-loading="relatedLoading">
          <div class="related-status" :class="related.status"><span>{{ related.status === 'vector' ? '向量关联' : related.status === 'chapter_fallback' ? '章节正文关联' : related.status === 'error' ? '关联失败' : '关联提示' }}</span><el-button v-if="selected" text size="small" :icon="RefreshRight" @click="loadRelated(selected.chapter_id)">重新关联</el-button></div>
          <p class="toolbox-hint">{{ related.message || '保存笔记后，可在这里查看语义相关的教材段落。' }}</p>
          <article v-for="item in related.textbook_chunks" :key="`${item.source_title}-${item.position}`"><span>{{ item.position }}</span><strong>{{ item.source_title }}</strong><p>{{ item.excerpt }}</p></article>
          <h3 v-if="related.related_notes.length">相关章节笔记</h3><button v-for="item in related.related_notes" :key="item.id" class="related-note-link" @click="selectNote(notes.find((note) => note.id === item.id) || notes[0])"><strong>{{ item.chapter_title }}</strong><span>{{ item.excerpt }}</span></button>
        </section>
      </aside>

      <section ref="splitWorkspace" class="notes-workspace" :class="{ 'ai-collapsed': aiCollapsed }" :style="workspaceStyle">
        <main class="note-editor-panel">
          <template v-if="selected">
            <header class="note-editor-heading"><div><span>{{ selected.course_name }}</span><h2>{{ selected.chapter_title }}</h2></div><div class="note-editor-actions"><el-button-group><el-button :type="mode === 'edit' ? 'primary' : 'default'" :icon="EditPen" @click="mode = 'edit'">编辑</el-button><el-button :type="mode === 'preview' ? 'primary' : 'default'" @click="mode = 'preview'">预览</el-button></el-button-group><el-dropdown @command="exportNote"><el-button :icon="Download">导出</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="markdown">Markdown</el-dropdown-item><el-dropdown-item command="docx">Word</el-dropdown-item></el-dropdown-menu></template></el-dropdown><el-button v-if="aiCollapsed" :icon="ArrowLeftBold" @click="setAiCollapsed(false)">打开 AI</el-button><el-button :icon="Reading" @click="router.push(`/courses/${selected.course_id}/chapters/${selected.chapter_id}/review`)">返回专题</el-button></div></header>
            <section v-if="formatBarOpen" class="note-format-ribbon">
              <div class="ribbon-group"><span>文字</span><div @mousedown.prevent><button title="加粗" @click="richEditor?.command('bold')"><strong>B</strong></button><button title="斜体" @click="richEditor?.command('italic')"><em>I</em></button><button title="下划线" @click="richEditor?.command('underline')"><u>U</u></button><button title="清除格式" @click="richEditor?.command('removeFormat')">清除</button></div></div>
              <div class="ribbon-group"><span>段落</span><div @mousedown.prevent><button @click="richEditor?.setBlock('h2')">标题1</button><button @click="richEditor?.setBlock('h3')">标题2</button><button @click="richEditor?.setBlock('p')">正文</button><button @click="richEditor?.command('insertOrderedList')">编号</button><button @click="richEditor?.command('insertUnorderedList')">列表</button></div></div>
              <div class="ribbon-group"><span>字号</span><div @mousedown.prevent><button v-for="size in [14, 16, 18, 20, 24]" :key="size" @click="richEditor?.setFontSize(size)">{{ size }}</button></div></div>
              <div class="ribbon-group"><span>记号笔</span><div class="ribbon-highlights" @mousedown.prevent><button title="黄色重点" style="--highlight: #fff1a8" @click="richEditor?.highlight('#fff1a8')"></button><button title="蓝色概念" style="--highlight: #cde4ff" @click="richEditor?.highlight('#cde4ff')"></button><button title="绿色意义" style="--highlight: #d3f3dc" @click="richEditor?.highlight('#d3f3dc')"></button><button title="红色易错" style="--highlight: #ffd7d7" @click="richEditor?.highlight('#ffd7d7')"></button></div></div>
              <div class="ribbon-preferences"><el-select :model-value="viewFontScale" size="small" @change="(value: number) => setViewPreference('font', value)"><el-option label="小字号" :value="0.9" /><el-option label="标准字号" :value="1" /><el-option label="大字号" :value="1.12" /><el-option label="特大字号" :value="1.25" /></el-select><el-select :model-value="viewLineHeight" size="small" @change="(value: number) => setViewPreference('line', value)"><el-option label="紧凑行距" :value="1.6" /><el-option label="标准行距" :value="1.9" /><el-option label="宽松行距" :value="2.2" /></el-select></div>
            </section>
            <NoteRichEditor v-if="mode === 'edit'" ref="richEditor" v-model="editorContent" :font-scale="viewFontScale" :line-height="viewLineHeight" />
            <article v-else class="note-preview rich-note-content" :style="{ fontSize: `${16 * viewFontScale}px`, lineHeight: String(viewLineHeight) }" v-html="renderedContent"></article>
            <footer class="note-editor-footer"><span>{{ wordCount }} 字 · 仅本人可见 · 格式自动保留</span><div><el-button type="danger" plain :icon="Delete" @click="remove">删除</el-button><el-button type="primary" :loading="saving" @click="save">保存笔记</el-button></div></footer>
          </template>
          <section v-else class="notes-empty-editor">
            <div class="empty-editor-mark"><el-icon><Notebook /></el-icon><span>01</span></div>
            <p class="eyebrow">Start Your Knowledge Archive</p>
            <h2>从一个教材专题开始，建立你的第一篇思想笔记</h2>
            <p>选择专题后，可以自由编辑与标记内容，也可以调用 AI 写作、教材关联和章节对话。</p>
            <el-button type="primary" size="large" @click="openCreateDialog">＋ 新建章节笔记</el-button>
            <div class="empty-editor-steps"><span><strong>01</strong>选择教材专题</span><span><strong>02</strong>整理个人理解</span><span><strong>03</strong>关联 AI 与复习</span></div>
          </section>
        </main>

        <div v-if="!aiCollapsed" class="notes-splitter" role="separator" aria-label="拖动调整笔记和 AI 区宽度" @pointerdown="startResize" @dblclick="resetSplit"><span></span></div>

        <aside v-if="!aiCollapsed" class="notes-ai-panel">
          <template v-if="selected">
            <header class="notes-ai-heading"><div class="ai-icon"><el-icon :size="21"><MagicStick /></el-icon></div><div><h2>笔记 AI 助手</h2><p>本章会话 · 自动承接最近追问</p></div><el-tooltip content="收起 AI 区"><el-button text :icon="ArrowRightBold" @click="setAiCollapsed(true)" /></el-tooltip><el-button text :icon="RefreshRight" @click="clearChat">清空</el-button></header>
            <div ref="chatScroll" class="notes-chat-history"><el-empty v-if="!chatMessages.length && !chatLoading" :image-size="64" description="在这里提问，历史会自动保存" /><article v-for="message in chatMessages" :key="message.id" class="notes-chat-message" :class="message.role"><span class="chat-role">{{ message.role === 'user' ? '我' : 'AI' }}</span><div class="chat-bubble"><span v-if="message.role === 'user'">{{ message.content }}</span><template v-else><article class="teaching-document" v-html="renderTeachingDocument(message.content)"></article><span v-if="message.pending && chatLoading" class="stream-cursor" aria-label="正在生成"></span><div v-if="message.sources.length" class="answer-sources chat-sources"><div class="source-heading"><strong>教材依据</strong><span v-if="message.model">{{ message.model }}</span></div><div v-for="(source, index) in message.sources" :key="`${message.id}-${index}`" class="source-item"><div class="source-title"><span>[{{ index + 1 }}] {{ source.source_title }}</span><el-tag size="small" type="info">{{ source.position }}</el-tag></div><p>{{ source.excerpt }}</p></div></div></template></div></article></div>
            <div class="notes-chat-input"><el-input v-model="chatQuestion" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="结合当前笔记向 AI 提问……" @keydown.ctrl.enter="askAi" /><el-button type="primary" :icon="Promotion" :loading="chatLoading" @click="askAi">发送</el-button></div>
          </template>
          <section v-else class="notes-empty-ai">
            <div class="empty-ai-core"><el-icon><MagicStick /></el-icon><span>AI</span></div>
            <small>CHAPTER AI CONTEXT</small>
            <h3>选择笔记后开启专题对话</h3>
            <p>AI 将围绕当前专题教材、你的笔记和最近会话回答，不会混入其他章节内容。</p>
            <div><span>教材依据</span><span>连续追问</span><span>历史保存</span></div>
          </section>
        </aside>
      </section>
    </section>
    <el-dialog v-model="createDialogVisible" title="新建章节笔记" width="480px">
      <el-form label-position="top"><el-form-item label="选择教材"><el-select v-model="createCourseId" style="width:100%" @change="loadCreateChapters"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select></el-form-item><el-form-item label="选择专题章节"><el-select v-model="createChapterId" filterable style="width:100%" placeholder="请选择需要整理的章节"><el-option v-for="chapter in availableChapters" :key="chapter.id" :label="`${chapter.title}${notes.some((note) => note.chapter_id === chapter.id) ? '（已有笔记）' : ''}`" :value="chapter.id" /></el-select></el-form-item></el-form><p class="create-note-hint">每个专题保留一篇个人主笔记；如果已经创建，系统会直接打开原笔记。</p><template #footer><el-button @click="createDialogVisible = false">取消</el-button><el-button type="primary" :loading="createLoading" @click="createOrOpenNote">创建并编辑</el-button></template>
    </el-dialog>
  </div>
</template>

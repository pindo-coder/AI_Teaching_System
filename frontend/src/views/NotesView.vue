<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Delete, EditPen, MagicStick, Promotion, Reading, Search, Download, RefreshRight } from '@element-plus/icons-vue'
import { studyApi, type NoteRelatedData, type NoteSearchItem, type StudyChatMessage, type StudyNote } from '@/api/study'
import { renderTeachingDocument } from '@/utils/richText'
import { aiApi, type AiSource } from '@/api/ai'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
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
const related = ref<NoteRelatedData>({ related_notes: [], textbook_chunks: [] })
const writingLoading = ref(false)
const writingResult = ref('')
const writingTitle = ref('')

const filteredNotes = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return notes.value
  return notes.value.filter((item) => `${item.course_name} ${item.chapter_title} ${item.content}`.toLowerCase().includes(keyword))
})
const selected = computed(() => notes.value.find((item) => item.id === selectedId.value) || null)
const renderedContent = computed(() => renderTeachingDocument(editorContent.value))
const wordCount = computed(() => editorContent.value.replace(/\s/g, '').length)

async function load() {
  loading.value = true
  try {
    notes.value = (await studyApi.notes()).data.data
    if (!selected.value && notes.value.length) selectNote(notes.value[0])
  } finally { loading.value = false }
}
function selectNote(note: StudyNote) {
  selectedId.value = note.id
  editorContent.value = note.content
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
  try { related.value = (await studyApi.related(chapterId)).data.data } catch { related.value = { related_notes: [], textbook_chunks: [] } }
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
  if (!editorContent.value.trim()) return ElMessage.warning('请先写下笔记内容，再使用 AI 写作辅助')
  writingLoading.value = true; writingResult.value = ''; writingTitle.value = label
  const prompt = `以下是学生围绕“${note.chapter_title}”整理的个人笔记。请完成“${label}”任务；只能使用当前专题教材与这份笔记的信息，不得补充其他章节或教材外事实。\n\n个人笔记：\n${editorContent.value.slice(0, 9000)}`
  try {
    await aiApi.assistStream({ course_id: note.course_id, chapter_id: note.chapter_id, learning_stage: 'review', task_type: taskType, question: prompt }, {
      onMeta: () => {}, onSources: () => {}, onChunk: (text) => { writingResult.value += text },
    })
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, 'AI 写作暂时不可用')) } finally { writingLoading.value = false }
}
function applyWriting(action: 'replace' | 'append') {
  if (!writingResult.value) return
  editorContent.value = action === 'replace' ? writingResult.value : `${editorContent.value.trim()}\n\n${writingResult.value}`.trim()
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
    const noteExcerpt = editorContent.value.trim().slice(0, 6000)
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
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <header class="notes-hero"><div><p class="eyebrow">Personal Notes</p><h1>我的笔记空间</h1><p>把每个专题的理解沉淀为自己的知识体系，并与间隔复习持续联动。</p></div><div class="notes-stat"><el-icon :size="25"><Collection /></el-icon><strong>{{ notes.length }}</strong><span>专题笔记</span></div></header>
    <section class="notes-navigator">
      <div class="notes-navigator-heading"><div><p class="eyebrow">专题索引</p><h2>选择要继续整理的笔记</h2></div><el-input v-model="query" :prefix-icon="Search" clearable placeholder="语义搜索：如“全过程人民民主”" @input="semanticSearch" /></div>
      <div class="notes-chip-list"><button v-for="note in filteredNotes" :key="note.id" :class="{ active: selectedId === note.id }" @click="selectNote(note)"><span>{{ note.course_name }}</span><strong>{{ note.chapter_title }}</strong><small>{{ new Date(note.updated_time).toLocaleDateString('zh-CN') }}</small></button><el-empty v-if="!filteredNotes.length" :image-size="54" :description="notes.length ? '没有匹配的笔记' : '请先在专题巩固页面保存笔记'" /></div>
      <div v-if="semanticResults.length" class="semantic-results"><span>语义相关笔记</span><button v-for="item in semanticResults" :key="item.id" @click="selectNote(notes.find((note) => note.id === item.id) || notes[0])"><strong>{{ item.chapter_title }}</strong><small>{{ item.excerpt }}</small></button></div>
    </section>
    <section class="notes-workspace">
      <main class="note-editor-panel">
        <template v-if="selected">
          <header class="note-editor-heading"><div><span>{{ selected.course_name }}</span><h2>{{ selected.chapter_title }}</h2></div><div class="note-editor-actions"><el-button-group><el-button :type="mode === 'edit' ? 'primary' : 'default'" :icon="EditPen" @click="mode = 'edit'">编辑</el-button><el-button :type="mode === 'preview' ? 'primary' : 'default'" @click="mode = 'preview'">预览</el-button></el-button-group><el-dropdown @command="exportNote"><el-button :icon="Download">导出</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="markdown">Markdown</el-dropdown-item><el-dropdown-item command="docx">Word</el-dropdown-item></el-dropdown-menu></template></el-dropdown><el-button :icon="Reading" @click="router.push(`/courses/${selected.course_id}/chapters/${selected.chapter_id}/review`)">返回专题</el-button></div></header>
          <div class="note-writing-toolbar"><span>AI 写作辅助</span><el-button v-for="[task, label] in writingActions" :key="task" size="small" :loading="writingLoading && writingTitle === label" @click="runWriting(task, label)">{{ label }}</el-button></div>
          <el-input v-if="mode === 'edit'" v-model="editorContent" class="note-editor-input" type="textarea" :rows="20" maxlength="10000" placeholder="按照章节主旨、核心观点、概念关系和现实意义整理笔记……" />
          <article v-else class="note-preview teaching-document" v-html="renderedContent"></article>
          <section v-if="writingResult || writingLoading" class="writing-result"><header><strong>{{ writingTitle }}结果</strong><span v-if="writingLoading">正在生成…</span><div v-else><el-button size="small" @click="applyWriting('append')">插入文末</el-button><el-button size="small" type="primary" @click="applyWriting('replace')">替换正文</el-button></div></header><article class="teaching-document" v-html="renderTeachingDocument(writingResult)"></article></section>
          <footer class="note-editor-footer"><span>{{ wordCount }} 字 · 仅本人可见</span><div><el-button type="danger" plain :icon="Delete" @click="remove">删除</el-button><el-button type="primary" :loading="saving" @click="save">保存笔记</el-button></div></footer>
        </template>
        <el-empty v-else description="从左侧选择一篇专题笔记" />
      </main>
      <aside class="notes-ai-panel">
        <template v-if="selected">
          <header class="notes-ai-heading"><div class="ai-icon"><el-icon :size="21"><MagicStick /></el-icon></div><div><h2>笔记 AI 助手</h2><p>本章会话 · 自动承接最近追问</p></div><el-button text :icon="RefreshRight" @click="clearChat">清空</el-button></header>
          <section class="note-related"><strong>相关教材知识点</strong><p v-if="!related.textbook_chunks.length">保存笔记后可查看关联教材段落。</p><article v-for="item in related.textbook_chunks" :key="`${item.source_title}-${item.position}`"><span>{{ item.position }}</span><p>{{ item.excerpt }}</p></article><strong v-if="related.related_notes.length">相关章节笔记</strong><button v-for="item in related.related_notes" :key="item.id" @click="selectNote(notes.find((note) => note.id === item.id) || notes[0])">{{ item.chapter_title }} · {{ item.excerpt }}</button></section>
          <div ref="chatScroll" class="notes-chat-history"><el-empty v-if="!chatMessages.length && !chatLoading" :image-size="64" description="在这里提问，历史会自动保存" /><article v-for="message in chatMessages" :key="message.id" class="notes-chat-message" :class="message.role"><span class="chat-role">{{ message.role === 'user' ? '我' : 'AI' }}</span><div class="chat-bubble"><span v-if="message.role === 'user'">{{ message.content }}</span><template v-else><article class="teaching-document" v-html="renderTeachingDocument(message.content)"></article><span v-if="message.pending && chatLoading" class="stream-cursor" aria-label="正在生成"></span><div v-if="message.sources.length" class="answer-sources chat-sources"><div class="source-heading"><strong>教材依据</strong><span v-if="message.model">{{ message.model }}</span></div><div v-for="(source, index) in message.sources" :key="`${message.id}-${index}`" class="source-item"><div class="source-title"><span>[{{ index + 1 }}] {{ source.source_title }}</span><el-tag size="small" type="info">{{ source.position }}</el-tag></div><p>{{ source.excerpt }}</p></div></div></template></div></article></div>
          <div class="notes-chat-input"><el-input v-model="chatQuestion" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="结合当前笔记向 AI 提问……" @keydown.ctrl.enter="askAi" /><el-button type="primary" :icon="Promotion" :loading="chatLoading" @click="askAi">发送</el-button></div>
        </template>
        <el-empty v-else description="选择笔记后即可开始对话" />
      </aside>
    </section>
  </div>
</template>

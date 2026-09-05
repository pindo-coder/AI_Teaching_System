<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Collection, Connection, EditPen, Reading, Search, TrendCharts, UploadFilled } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { courseApi } from '@/api/courses'
import { newsApi, type NewsItem } from '@/api/news'
import { studyApi, type NoteSearchItem } from '@/api/study'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import type { Course, CourseDetail } from '@/types'
import learningSearchBackground from '@/assets/learning-search-bg.svg'
import aiAssistantRobot from '@/assets/ai-assistant-robot.svg'
import { requestWorkspaceAi } from '@/utils/workspaceAiEvents'

const auth = useAuthStore()
const workspace = useWorkspaceStore()
const router = useRouter()
const loading = ref(false)
const courses = ref<Course[]>([])
const textbook = ref<CourseDetail | null>(null)
const dialogVisible = ref(false)
const editDialogVisible = ref(false)
const submitting = ref(false)
const editSubmitting = ref(false)
const editingCourse = ref<Course | null>(null)
const selectedFile = ref<File | null>(null)
const searchQuery = ref('')
const searchOpen = ref(false)
const searchLoading = ref(false)
const searchDetails = ref<CourseDetail[]>([])
const searchNotes = ref<NoteSearchItem[]>([])
const searchNews = ref<NewsItem[]>([])
const searchArea = ref<HTMLElement | null>(null)
const aiSuggestionIndex = ref(0)
const uploadKey = ref(0)
const form = reactive({ name: '', description: '' })
const editForm = reactive({ description: '' })
const overviewStats = computed(() => [
  { label: '教材专题', value: textbook.value?.chapters.length || 0, unit: '章', icon: Collection },
  { label: '学习阶段', value: 3, unit: '阶', icon: Reading },
  { label: 'AI 助学场景', value: 5, unit: '项', icon: ChatDotRound },
])
const moduleCards = [
  { index: '01', title: '专题学习', desc: '沿教材章节进入预习、巩固、冲刺三段式学习，让理论脉络清晰可循。', action: '继续学习', icon: Reading, path: '' },
  { index: '02', title: '时政要点', desc: '从权威媒体信息出发，定位教材观点与现实议题之间的内在联系。', action: '查看更多', icon: TrendCharts, path: '/current-affairs' },
  { index: '03', title: '课堂互动', desc: '通过讨论、问答和观点辨析，把知识理解转化为课堂表达与思考。', action: '查看更多', icon: Connection, path: '/interaction' },
]
const filteredCourses = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return courses.value
  return courses.value.filter((course) => [course.name, course.description || ''].some((value) => value.toLocaleLowerCase().includes(query)))
})
const searchQueryText = computed(() => searchQuery.value.trim())
interface CourseSearchItem {
  key: string
  title: string
  description: string
  meta: string
  path?: string
}
const searchLearningItems = computed<CourseSearchItem[]>(() => {
  const query = searchQueryText.value.toLocaleLowerCase()
  if (!query) return []
  const coursesResult: CourseSearchItem[] = []
  const chaptersResult: CourseSearchItem[] = []
  for (const course of searchDetails.value) {
    if ([course.name, course.description || ''].some((value) => value.toLocaleLowerCase().includes(query))) {
      coursesResult.push({ key: `course-${course.id}`, title: course.name, description: course.description || '进入教材目录查看全部专题', meta: '教材', path: `/courses/${course.id}` })
    }
    for (const chapter of course.chapters) {
      if ([chapter.title, chapter.content || '', course.name].some((value) => value.toLocaleLowerCase().includes(query))) {
        chaptersResult.push({
          key: `chapter-${chapter.id}`,
          title: chapter.title,
          description: compactSearchText(chapter.content || '进入专题学习'),
          meta: course.name,
          path: auth.user?.role === 'student' ? `/courses/${course.id}/chapters/${chapter.id}/preview` : `/courses/${course.id}`,
        })
      }
    }
  }
  return [...coursesResult.slice(0, 3), ...chaptersResult.slice(0, 6)]
})
const searchNoteItems = computed<CourseSearchItem[]>(() => searchNotes.value.slice(0, 5).map((item) => ({
  key: `note-${item.id}`,
  title: item.chapter_title,
  description: compactSearchText(item.excerpt),
  meta: `${item.course_name} · 笔记`,
  path: auth.user?.role === 'student' ? `/courses/${item.course_id}/chapters/${item.chapter_id}/preview` : `/courses/${item.course_id}`,
})))
const searchNewsItems = computed<CourseSearchItem[]>(() => searchNews.value.slice(0, 5).map((item) => ({
  key: `news-${item.id}`,
  title: item.title,
  description: compactSearchText(item.summary || '打开时政资料查看详情'),
  meta: `${item.source_name} · 时政`,
  path: `/current-affairs?q=${encodeURIComponent(item.title)}`,
})))
const searchGroups = computed(() => [
  { key: 'learning', label: '教材与专题', items: searchLearningItems.value },
  { key: 'notes', label: '我的笔记', items: searchNoteItems.value },
  { key: 'news', label: '时政资料', items: searchNewsItems.value },
].filter((group) => group.items.length))
const searchHasResults = computed(() => searchGroups.value.length > 0)
const searchCanAskAi = computed(() => Boolean((workspace.currentCourse?.id || textbook.value?.id) && (workspace.currentChapter?.id || textbook.value?.chapters[0]?.id)))
const aiSuggestions = ['我们来写一篇……', '一起整理学习思路……', '现在开始巩固知识……']
const aiSuggestion = computed(() => aiSuggestions[aiSuggestionIndex.value] || aiSuggestions[0])

async function loadCourses() {
  loading.value = true
  try {
    courses.value = (await courseApi.list()).data.data
    textbook.value = courses.value[0] ? (await courseApi.detail(courses.value[0].id)).data.data : null
    searchDetails.value = textbook.value ? [textbook.value] : []
  } finally { loading.value = false }
}

function compactSearchText(value: string, limit = 86) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}…` : normalized
}

let searchCatalogPromise: Promise<void> | null = null
let searchTimer: number | undefined
let searchSequence = 0
async function ensureSearchCatalog() {
  if (searchDetails.value.length >= courses.value.length || searchCatalogPromise) return searchCatalogPromise
  searchCatalogPromise = (async () => {
    try {
      const details = await Promise.all(courses.value.map(async (course) => {
        try { return (await courseApi.detail(course.id)).data.data }
        catch { return null }
      }))
      searchDetails.value = details.filter((item): item is CourseDetail => Boolean(item))
    } finally {
      searchCatalogPromise = null
    }
  })()
  return searchCatalogPromise
}
async function runCourseSearch() {
  const query = searchQueryText.value
  const sequence = ++searchSequence
  if (!query) {
    searchLoading.value = false
    searchNotes.value = []
    searchNews.value = []
    return
  }
  searchLoading.value = true
  const [catalogResult, notesResult, newsResult] = await Promise.allSettled([
    ensureSearchCatalog(),
    studyApi.semanticSearch(query),
    newsApi.search({ q: query, sort: 'relevance', days: null, page: 1, pageSize: 5 }),
  ])
  if (sequence !== searchSequence) return
  if (notesResult.status === 'fulfilled') searchNotes.value = notesResult.value.data.data
  else searchNotes.value = []
  if (newsResult.status === 'fulfilled') searchNews.value = newsResult.value.data.data.items
  else searchNews.value = []
  if (catalogResult.status === 'rejected') searchDetails.value = []
  searchLoading.value = false
}
function scheduleCourseSearch() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { void runCourseSearch() }, 220)
}
function openCourseSearch() {
  searchOpen.value = true
  if (searchQueryText.value && !searchLoading.value) void runCourseSearch()
}
function selectCourseSearchResult(item: CourseSearchItem) {
  searchOpen.value = false
  searchQuery.value = ''
  if (item.path) void router.push(item.path)
}
function applySearchPrompt(value: string) {
  searchQuery.value = value
  searchOpen.value = true
  void runCourseSearch()
}
function handleCourseSearchOutside(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Node) || !searchArea.value?.contains(target)) searchOpen.value = false
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
function openDescriptionEditor(course: Course) {
  editingCourse.value = course
  editForm.description = course.description || ''
  editDialogVisible.value = true
}
async function updateDescription() {
  if (!editingCourse.value) return
  editSubmitting.value = true
  try {
    await courseApi.update(editingCourse.value.id, { description: editForm.description.trim() || null })
    ElMessage.success('教材简介已更新')
    editDialogVisible.value = false
    await loadCourses()
  } catch (error: any) {
    const detail = error?.response?.data?.detail || error?.response?.data?.message
    ElMessage.error(detail || '教材简介更新失败，请稍后重试')
  } finally { editSubmitting.value = false }
}
function openModule(path: string) {
  if (path) return router.push(path)
  if (textbook.value) router.push(`/courses/${textbook.value.id}`)
}
async function submitSearch() {
  if (!searchQueryText.value) return
  if (!searchHasResults.value && !searchLoading.value) await runCourseSearch()
  const firstResult = searchGroups.value[0]?.items[0]
  if (firstResult) return selectCourseSearchResult(firstResult)
  const match = filteredCourses.value[0]
  if (match) void router.push(`/courses/${match.id}`)
}
function rotateAiSuggestion() {
  aiSuggestionIndex.value = (aiSuggestionIndex.value + 1) % aiSuggestions.length
}
function requestHomeAi(mode: 'chat' | 'agent', prompt: string) {
  const courseId = workspace.currentCourse?.id || textbook.value?.id
  let chapterId = workspace.currentChapter?.id && workspace.currentCourse?.id === courseId
    ? workspace.currentChapter.id
    : null
  if (!chapterId && textbook.value && textbook.value.id === courseId) chapterId = textbook.value.chapters[0]?.id || null
  if (!courseId || !chapterId) {
    ElMessage.info('请先导入教材并选择一个专题，再调用 AI 助手')
    return
  }
  requestWorkspaceAi({
    courseId,
    chapterId,
    learningStage: 'preview',
    taskType: 'question_answer',
    mode,
    autoSend: true,
    prompt,
  })
}
onMounted(() => {
  void loadCourses()
  document.addEventListener('pointerdown', handleCourseSearchOutside)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', handleCourseSearchOutside)
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="course-overview-page">
    <section class="learning-home-top">
      <section class="learning-home-hero" :style="{ backgroundImage: `url(${learningSearchBackground})` }">
        <div class="learning-home-copy">
          <p class="learning-home-eyebrow">高校思政课 · 教材空间</p>
          <h1>你好，有什么可以帮助你的吗？</h1>
          <p>从教材专题出发，开始预习、巩固和冲刺学习。</p>
          <div ref="searchArea" class="learning-home-search-wrap">
            <el-input v-model="searchQuery" class="learning-home-search" :prefix-icon="Search" placeholder="搜索教材和专题" clearable @focus="openCourseSearch" @input="scheduleCourseSearch" @keyup.enter="submitSearch" @keydown.esc="searchOpen = false" />
            <div v-if="searchOpen" class="learning-home-search-panel" role="dialog" aria-label="学习内容搜索结果" @pointerdown.stop>
              <div v-if="!searchQueryText" class="learning-home-search-empty learning-home-search-intro">
                <strong>快速查找学习内容</strong>
                <span>支持模糊搜索教材、专题、笔记和时政资料</span>
                <div class="learning-home-search-prompts">
                  <button type="button" @pointerdown.prevent @click="applySearchPrompt('核心概念')">核心概念</button>
                  <button type="button" @pointerdown.prevent @click="applySearchPrompt('中国式现代化')">中国式现代化</button>
                  <button type="button" @pointerdown.prevent @click="applySearchPrompt('专题')">专题</button>
                </div>
              </div>
              <div v-else-if="searchLoading" class="learning-home-search-empty">正在检索教材、笔记和时政资料…</div>
              <template v-else>
                <section v-for="group in searchGroups" :key="group.key" class="learning-home-search-group">
                  <div class="learning-home-search-group-title"><strong>{{ group.label }}</strong><small>{{ group.items.length }} 条结果</small></div>
                  <button v-for="item in group.items" :key="item.key" type="button" class="learning-home-search-result" @pointerdown.prevent @click="selectCourseSearchResult(item)">
                    <span class="learning-home-search-result-mark" aria-hidden="true">{{ group.key === 'learning' ? '教' : group.key === 'notes' ? '记' : '政' }}</span>
                    <span class="learning-home-search-result-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small><em>{{ item.meta }}</em></span>
                  </button>
                </section>
                <button v-if="searchCanAskAi" type="button" class="learning-home-search-ai" @pointerdown.prevent @click="requestHomeAi('chat', `请结合当前教材和专题回答：${searchQueryText}`)">
                  <span class="learning-home-search-result-mark" aria-hidden="true">AI</span>
                  <span><strong>让 AI 助教回答“{{ compactSearchText(searchQueryText, 42) }}”</strong><small>结合教材内容生成学习解答</small></span>
                </button>
                <div v-if="!searchHasResults && !searchCanAskAi" class="learning-home-search-empty">暂未找到相关内容，请换个关键词试试。</div>
              </template>
            </div>
          </div>
          <div class="learning-home-tags"><button type="button" @click="searchQuery = '核心'; submitSearch()">核心概念</button><button type="button" @click="openModule('/current-affairs')">时政新闻</button><button type="button" @click="searchQuery = '专题'; submitSearch()">专题概览</button></div>
        </div>
        <div class="learning-home-robot"><img :src="aiAssistantRobot" alt="AI 学习助手" /><span>AI 学习助手</span></div>
      </section>
      <article class="learning-home-ai-card">
        <span class="learning-home-ai-label">人工智能助手</span>
        <h2>{{ aiSuggestion }}</h2>
        <button type="button" @click="requestHomeAi('agent', '请先读取我最近的学习记录、章节活动和已有学习产出，再结合当前教材专题，为我总结近期学习情况，并给出下一步可执行的学习计划。')"><i class="blue"><el-icon><Reading /></el-icon></i><span>学习计划</span></button>
        <button type="button" @click="router.push('/notes')"><i class="yellow"><el-icon><EditPen /></el-icon></i><span>学习笔记</span></button>
        <button type="button" @click="requestHomeAi('chat', '请围绕当前教材专题引导我进行一次专题反思：先提出 3 个由浅入深的问题，再根据我的回答追问，并始终以教材观点为依据。')"><i class="purple"><el-icon><TrendCharts /></el-icon></i><span>专题反思</span></button>
        <button type="button" class="learning-home-ai-refresh" @click="rotateAiSuggestion"><span>换个建议</span><b>›</b></button>
      </article>
    </section>
    <div class="learning-tools-heading"><h2>学习工具</h2></div>
    <section class="learning-home-content">
      <article v-for="item in moduleCards" :key="item.title" class="learning-home-tool-card" @click="openModule(item.path)"><span class="learning-home-tool-title" :class="`tone-${item.index}`">{{ item.index }} | {{ item.title }}</span><p>{{ item.desc }}</p><span class="learning-home-tool-action">{{ item.action }} <b>›</b></span></article>
    </section>

    <section class="course-textbook-section learning-textbook-center">
      <div class="learning-textbook-heading"><h2>教材中心</h2><el-button v-if="auth.isAdmin" text @click="dialogVisible = true">⋮</el-button></div>
      <div v-loading="loading" class="course-library-grid">
        <article v-for="course in filteredCourses" :key="course.id" class="learning-textbook-row" role="button" tabindex="0" @click="router.push(`/courses/${course.id}`)" @keydown.enter="router.push(`/courses/${course.id}`)">
          <span class="learning-textbook-mark"><el-icon><Reading /></el-icon></span>
          <div class="learning-textbook-copy"><h3>{{ course.name }}</h3><p>{{ course.description || '进入教材查看专题目录和学习内容' }}</p></div>
          <div class="learning-textbook-action">查看章节目录 <b>›</b></div>
        </article>
        <el-empty v-if="!loading && !filteredCourses.length" description="暂无教材课程，请联系管理员创建" />
      </div>
    </section>
    <el-dialog v-model="dialogVisible" title="导入教材" width="560px">
      <el-form label-position="top"><el-form-item label="教材名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="教材简介"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item><el-form-item label="上传教材并自动建专题"><el-upload :key="uploadKey" drag :auto-upload="false" :limit="1" accept=".pdf,.txt,.md,.markdown" :on-change="handleFileChange" :on-remove="handleFileRemove"><el-icon class="el-icon--upload"><UploadFilled /></el-icon><div class="el-upload__text">拖拽教材资料到此处，或<em>点击选择</em></div><template #tip><div class="el-upload__tip">支持 PDF、TXT、Markdown，系统会自动识别章节并建立专题和知识库；不选择也可以先创建教材。</div></template></el-upload></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="createCourse">导入并自动建专题</el-button></template>
    </el-dialog>
    <el-dialog v-model="editDialogVisible" title="修改教材简介" width="560px">
      <el-form label-position="top">
        <el-form-item label="教材名称"><el-input :model-value="editingCourse?.name || ''" disabled /></el-form-item>
        <el-form-item label="教材简介"><el-input v-model="editForm.description" type="textarea" :rows="6" maxlength="2000" show-word-limit placeholder="请输入教材定位、主要内容和学习目标；留空可清除现有简介。" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editDialogVisible = false">取消</el-button><el-button type="primary" :loading="editSubmitting" @click="updateDescription">保存简介</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.learning-home-hero { display: grid; grid-template-columns: minmax(0, 1fr) 220px; align-items: center; min-height: 330px; padding: 42px 54px; overflow: hidden; background: linear-gradient(115deg, #fffed0 0%, #ffd9bd 48%, #ff637b 100%); border: 1px solid #f7c4cb; border-radius: 24px; }
.learning-home-copy { max-width: 760px; }.learning-home-eyebrow { margin: 0; color: #665070; font-size: 16px; font-weight: 700; letter-spacing: .08em; }.learning-home-copy h1 { margin: 16px 0 8px; color: #241832; font-size: clamp(30px, 3.2vw, 46px); line-height: 1.2; }.learning-home-copy > p:not(.learning-home-eyebrow) { margin: 0; color: #614d6c; font-size: 16px; }.learning-home-search { max-width: 720px; margin-top: 28px; }.learning-home-search :deep(.el-input__wrapper) { min-height: 58px; padding: 0 20px; background: #fff; border: 0; border-radius: 999px; box-shadow: 0 8px 20px rgba(210,105,113,.14); }.learning-home-search :deep(.el-input__inner) { font-size: 17px; }.learning-home-tags { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 18px; }.learning-home-tags button { padding: 10px 24px; color: #654c76; background: rgba(255,255,255,.74); border: 1px solid rgba(255,255,255,.85); border-radius: 999px; cursor: pointer; font: inherit; }.learning-home-robot { display: grid; justify-items: center; align-content: center; color: #fff; font-size: 13px; font-weight: 700; }.learning-home-robot img { width: 205px; max-height: 230px; object-fit: contain; filter: drop-shadow(0 12px 12px rgba(207,80,103,.16)); }.learning-home-content { display: grid; grid-template-columns: 1.1fr repeat(3, 1fr); gap: 18px; }.learning-home-ai-card, .learning-home-tool-card, .course-textbook-section { background: #fff; border: 1px solid #eee5ec; border-radius: 16px; box-shadow: 0 6px 16px rgba(48,33,62,.07); }.learning-home-ai-card { display: grid; gap: 8px; padding: 22px 24px; }.learning-home-ai-label { justify-self: start; padding: 8px 18px; color: #fff; background: #ff1e2f; border-radius: 10px; }.learning-home-ai-card h2 { margin: 8px 0 5px; color: #30203b; font-size: 21px; }.learning-home-ai-card button { display: flex; align-items: center; gap: 13px; padding: 4px 0; color: #6e5a7c; background: transparent; border: 0; cursor: pointer; font: inherit; font-size: 15px; text-align: left; }.learning-home-ai-card i { display: grid; width: 32px; height: 32px; place-items: center; color: #fff; border-radius: 50%; font-style: normal; }.learning-home-ai-card i.blue { background: #70baff; }.learning-home-ai-card i.yellow { background: #ffc65a; }.learning-home-ai-card i.purple { background: #789dff; }.learning-home-tool-card { display: grid; align-content: space-between; min-height: 190px; padding: 22px; cursor: pointer; transition: transform .18s ease, box-shadow .18s ease; }.learning-home-tool-card:hover { transform: translateY(-3px); box-shadow: 0 12px 24px rgba(48,33,62,.12); }.learning-home-tool-title { justify-self: start; padding: 8px 14px; border-radius: 12px; font-size: 16px; font-weight: 700; }.learning-home-tool-title.tone-01 { color: #cdbb09; background: #fff9e8; }.learning-home-tool-title.tone-02 { color: #ff4f99; background: #fff0f7; }.learning-home-tool-title.tone-03 { color: #caa900; background: #fff9e8; }.learning-home-tool-card p { margin: 18px 0; color: #695878; line-height: 1.65; }.learning-home-tool-action { color: #735a83; font-size: 15px; }.learning-home-tool-action b { display: inline-grid; width: 28px; height: 28px; margin-left: 6px; place-items: center; color: #fff; background: #ff4b4f; border-radius: 50%; font-size: 24px; line-height: 1; }
@media (max-width: 1050px) { .learning-home-content { grid-template-columns: repeat(2, 1fr); }.learning-home-ai-card { grid-column: 1 / -1; } } @media (max-width: 700px) { .learning-home-hero { grid-template-columns: 1fr; padding: 30px 24px; }.learning-home-robot { margin-top: 12px; }.learning-home-robot img { width: 160px; max-height: 180px; }.learning-home-content { grid-template-columns: 1fr; }.learning-home-ai-card { grid-column: auto; } }
</style>

<style scoped>
.course-overview-page { max-width: 1440px; }
.learning-home-top { display: grid; grid-template-columns: minmax(0, 1fr) minmax(270px, .34fr); gap: 18px; align-items: stretch; }
.learning-home-hero { min-height: 250px; padding: 30px 38px; overflow: visible; border-radius: 18px; }
.learning-home-copy h1 { margin: 10px 0 6px; font-size: clamp(26px, 2.6vw, 36px); }
.learning-home-copy > p:not(.learning-home-eyebrow) { font-size: 14px; }
.learning-home-search-wrap { position: relative; z-index: 8; max-width: 610px; margin-top: 18px; }
.learning-home-search { max-width: none; margin-top: 0; }
.learning-home-search :deep(.el-input__wrapper) { min-height: 44px; padding-right: 16px; padding-left: 16px; }
.learning-home-search :deep(.el-input__inner) { font-size: 15px; }
.learning-home-search-panel { position: absolute; z-index: 30; top: calc(100% + 8px); left: 0; display: grid; width: min(560px, calc(100vw - 48px)); max-height: min(360px, calc(100vh - 170px)); padding: 10px; overflow-y: auto; background: rgb(255 255 255 / 98%); border: 1px solid #f0dfe2; border-radius: 14px; box-shadow: 0 18px 42px rgb(80 48 68 / 18%); }
.learning-home-search-empty { padding: 20px 12px; color: #7d6b82; font-size: 12px; line-height: 1.6; text-align: center; }
.learning-home-search-intro { display: grid; gap: 5px; text-align: left; }
.learning-home-search-intro strong { color: #30203b; font-size: 13px; }
.learning-home-search-intro span { color: #7d6b82; }
.learning-home-search-prompts { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 8px; }
.learning-home-search-prompts button { padding: 6px 10px; color: #a6354d; background: #fff0f1; border: 1px solid #f5cbd1; border-radius: 999px; cursor: pointer; font: inherit; font-size: 11px; }
.learning-home-search-prompts button:hover { background: #ffe2e6; border-color: #f08c9b; }
.learning-home-search-group { display: grid; gap: 3px; padding: 4px 0 8px; }
.learning-home-search-group + .learning-home-search-group { border-top: 1px solid #f1e4e8; }
.learning-home-search-group-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 8px 4px; color: #51384f; font-size: 12px; }
.learning-home-search-group-title small { color: #a08e9f; font-size: 10px; font-weight: 400; }
.learning-home-search-result, .learning-home-search-ai { display: flex; width: 100%; min-width: 0; align-items: center; gap: 10px; padding: 9px 8px; color: #47374b; text-align: left; background: transparent; border: 0; border-radius: 9px; cursor: pointer; }
.learning-home-search-result:hover, .learning-home-search-ai:hover { background: #fff0f1; }
.learning-home-search-result-mark { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; color: #b52345; background: #ffe6e9; border-radius: 8px; font-size: 11px; font-weight: 800; }
.learning-home-search-result-copy { display: grid; min-width: 0; gap: 2px; }
.learning-home-search-result-copy strong, .learning-home-search-result-copy small, .learning-home-search-result-copy em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.learning-home-search-result-copy strong { color: #3b2943; font-size: 12px; }
.learning-home-search-result-copy small { color: #7d6b82; font-size: 11px; }
.learning-home-search-result-copy em { color: #a08e9f; font-size: 10px; font-style: normal; }
.learning-home-search-ai { margin-top: 4px; background: #fff7f4; border: 1px solid #f3d7d4; }
.learning-home-search-ai > span:last-child { display: grid; min-width: 0; gap: 3px; }
.learning-home-search-ai strong { overflow: hidden; color: #a6354d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.learning-home-search-ai small { color: #7d6b82; font-size: 10px; }
.learning-home-tags { gap: 10px; margin-top: 12px; }
.learning-home-tags button { padding: 7px 18px; font-size: 13px; }
.learning-home-robot img { width: 150px; max-height: 185px; object-fit: contain; }
.learning-home-robot { font-size: 12px; }
.learning-home-top .learning-home-ai-card { position: relative; min-height: 250px; padding-bottom: 52px; }
.learning-home-content { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.learning-home-ai-card { gap: 5px; padding: 18px 20px; }
.learning-home-ai-label { padding: 6px 14px; font-size: 13px; }
.learning-home-ai-card h2 { margin: 6px 0 2px; font-size: 18px; }
.learning-home-ai-card button { gap: 10px; font-size: 13px; }
.learning-home-ai-card i { width: 28px; height: 28px; }
.learning-home-ai-refresh { position: absolute; right: 18px; bottom: 18px; display: inline-flex; align-items: center; gap: 9px; padding: 5px 7px 5px 13px !important; color: #735a83 !important; border: 1px solid #eee5ec !important; border-radius: 999px; font-size: 13px !important; }
.learning-home-ai-refresh b { display: inline-grid; width: 22px; height: 22px; place-items: center; color: #fff; background: #ff1e3b; border-radius: 50%; font-size: 20px; line-height: 1; }
.learning-tools-heading { margin: 26px 0 12px; }
.learning-tools-heading h2 { margin: 0; color: #241832; font-size: 28px; line-height: 1.2; }
.learning-home-tool-card { min-height: 150px; padding: 18px; }
.learning-home-tool-title { padding: 6px 11px; font-size: 13px; }
.learning-home-tool-card p { margin: 12px 0; font-size: 13px; line-height: 1.55; }
.learning-home-tool-action { font-size: 13px; }
.learning-home-tool-action b { width: 24px; height: 24px; font-size: 20px; }
.learning-textbook-center { padding: 20px 22px; }
.learning-textbook-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px dashed #eadfe7; }
.learning-textbook-heading h2 { margin: 0; color: #281936; font-size: 24px; }
.learning-textbook-heading .el-button { width: 38px; height: 38px; color: #6d557d; border: 1px solid #eee5ec; border-radius: 12px; font-size: 23px; }
.learning-textbook-center .course-library-grid { display: grid; gap: 10px; }
.learning-textbook-row { display: flex; align-items: center; gap: 16px; min-height: 82px; padding: 14px 18px; background: #fff; border: 1px solid #eee5ec; border-radius: 14px; cursor: pointer; transition: transform .18s ease, box-shadow .18s ease; }
.learning-textbook-row:hover { transform: translateY(-2px); box-shadow: 0 8px 18px rgba(48,33,62,.1); }
.learning-textbook-mark { display: grid; width: 48px; height: 48px; flex: 0 0 48px; place-items: center; color: #fff; background: linear-gradient(145deg, #ff4b63, #ff7890); border-radius: 12px; font-size: 23px; }
.learning-textbook-row:nth-child(2) .learning-textbook-mark { background: linear-gradient(145deg, #8fb9f5, #9fc5fa); }
.learning-textbook-copy { min-width: 0; flex: 1; }.learning-textbook-copy h3 { overflow: hidden; margin: 0 0 4px; color: #2f203c; font-size: 17px; text-overflow: ellipsis; white-space: nowrap; }.learning-textbook-copy p { overflow: hidden; margin: 0; color: #806b8d; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.learning-textbook-action { display: flex; align-items: center; flex: 0 0 auto; color: #735a83; font-size: 15px; }.learning-textbook-action b { display: inline-grid; width: 25px; height: 25px; margin-left: 8px; place-items: center; color: #fff; background: #ff4b4f; border-radius: 50%; font-size: 21px; line-height: 1; }
@media (max-width: 1050px) { .learning-home-top { grid-template-columns: minmax(0, 1fr) 270px; gap: 14px; }.learning-home-content { grid-template-columns: repeat(3, minmax(0, 1fr)); }.learning-home-ai-card { grid-column: auto; } }
@media (max-width: 820px) { .learning-home-top { grid-template-columns: 1fr; }.learning-home-top .learning-home-ai-card { min-height: 0; }.learning-home-ai-card { grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: center; }.learning-home-ai-card .learning-home-ai-label, .learning-home-ai-card h2 { grid-column: 1 / -1; }.learning-home-content { grid-template-columns: 1fr 1fr; } }
@media (max-width: 700px) { .learning-home-hero { min-height: 0; padding: 24px; }.learning-home-content { grid-template-columns: 1fr; }.learning-home-ai-card { grid-template-columns: 1fr; }.learning-home-ai-card .learning-home-ai-label, .learning-home-ai-card h2 { grid-column: auto; }.learning-textbook-row { align-items: flex-start; flex-wrap: wrap; }.learning-textbook-action { width: 100%; margin-left: 64px; } }
</style>

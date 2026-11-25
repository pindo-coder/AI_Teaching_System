<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { aiApi, type AiAssistData, type AiSource } from '@/api/ai'
import { agentApi } from '@/api/agents'
import { classroomApi } from '@/api/classroom'
import { courseApi } from '@/api/courses'
import { getErrorMessage } from '@/utils/error'
import {
  newsApi,
  type NewsClassroomActivityType,
  type NewsDebateSourceCitation,
  type NewsItem,
  type TextbookRelationItem,
} from '@/api/news'
import { studyApi } from '@/api/study'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import type { CourseDetail } from '@/types'
import { renderTeachingDocument } from '@/utils/richText'
import { saveClassroomDebateHandoff, saveLessonPrepNewsHandoff } from '@/utils/newsTeachingHandoff'
import { Calendar, MagicStick, Refresh, Search } from '@element-plus/icons-vue'
import PdfCitationViewer from '@/components/PdfCitationViewer.vue'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { formatBeijingDateTime } from '@/utils/time'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const loading = ref(false)
const newsLoading = ref(true)
const news = ref<NewsItem[]>([])
const availableSources = ref<string[]>([])
const searchKeyword = ref('')
const selectedSources = ref<string[]>([])
// 默认只看近 90 天，避免旧 RSS 快照占满“时政要点”；需要历史材料时可手动放宽。
const timeDays = ref<number | null>(90)
const sortBy = ref<'latest' | 'relevance'>('latest')
const currentPage = ref(1)
const pageSize = ref(10)
const totalNews = ref(0)
const textbook = ref<CourseDetail | null>(null)
const textbookOptions = ref<CourseDetail[]>([])
const selectedCourseId = ref<number | null>(null)
const selectedNews = ref<NewsItem | null>(null)
const aiResult = ref<AiAssistData | null>(null)
const aiLoading = ref(false)
const aiMode = ref<'summary' | 'relation'>('summary')
const aiScopeLabel = ref('')
const dialogVisible = ref(false)
const citationVisible = ref(false)
const selectedSource = ref<AiSource | null>(null)
const studyDialogVisible = ref(false)
const refreshing = ref(false)
const relationLoading = ref(false)
const relations = ref<TextbookRelationItem[]>([])
const selectedChapterId = ref<number | null>(null)
const selectedRelation = computed(() => relations.value.find((item) => item.chapter_id === selectedChapterId.value) || null)
const studyDraft = ref('')
const draftLoading = ref(false)
const noteSaving = ref(false)
const noteExists = ref(false)
const savedChapterId = ref<number | null>(null)
const textbookLoading = ref(false)
let textbookPromise: Promise<CourseDetail | null> | null = null
let aiStreamController: AbortController | null = null
let aiRequestSequence = 0
let lastNewsLoadedAt = 0

// 教师端：带入备课素材 & 生成课堂辨析草稿状态
const teachingClasses = ref<TeachingClass[]>([])
let teachingClassesLoaded = false
const prepDialogVisible = ref(false)
const prepCourseId = ref<number | null>(null)
const prepChapterId = ref<number | null>(null)
const prepTeachingClassId = ref<number | null>(null)
const prepRelations = ref<TextbookRelationItem[]>([])
const prepRelationLoading = ref(false)
const prepTeachingGoal = ref('')
const prepCreating = ref(false)

const debateDialogVisible = ref(false)
const debateCourseId = ref<number | null>(null)
const debateChapterId = ref<number | null>(null)
const debateTeachingClassId = ref<number | null>(null)
const debateRelations = ref<TextbookRelationItem[]>([])
const debateRelationLoading = ref(false)
const debateActivityType = ref<NewsClassroomActivityType>('judgment')
const debateQuestion = ref('')
const debateOptionsText = ref('')
const debateMinutes = ref(8)
const debateGuide = ref<string[]>([])
const debateTextbookPosition = ref('')
const debateCitation = ref<NewsDebateSourceCitation | null>(null)
const debateModel = ref('')
const debateGenerating = ref(false)
const debatePublishing = ref(false)
const debatePublished = ref(false)

const availableTextbookCourses = computed(() => textbookOptions.value.filter((item) => item.chapters.length > 0))
const prepCourse = computed(() => availableTextbookCourses.value.find((item) => item.id === prepCourseId.value) || null)
const prepEligibleClasses = computed(() => teachingClasses.value.filter(
  (item) => !prepCourseId.value || !item.material_ids.length || item.material_ids.includes(prepCourseId.value),
))
const prepSelectedRelation = computed(() => prepRelations.value.find((item) => item.chapter_id === prepChapterId.value) || null)

const debateCourse = computed(() => availableTextbookCourses.value.find((item) => item.id === debateCourseId.value) || null)
const debateEligibleClasses = computed(() => teachingClasses.value.filter(
  (item) => !debateCourseId.value || !item.material_ids.length || item.material_ids.includes(debateCourseId.value),
))
const debateSelectedRelation = computed(() => debateRelations.value.find((item) => item.chapter_id === debateChapterId.value) || null)

const renderedAnswer = computed(() => renderTeachingDocument(aiResult.value?.answer || ''))
const sourceNames = computed(() => availableSources.value.length ? availableSources.value : [...new Set(news.value.map((item) => item.source_name))])
const hasFilters = computed(() => Boolean(searchKeyword.value.trim() || selectedSources.value.length || timeDays.value !== 90 || sortBy.value !== 'latest'))
function openCitation(source: AiSource) { if (source.document_id && source.pdf_page_start) { selectedSource.value = source; citationVisible.value = true } else if (source.source_url) window.open(source.source_url, '_blank', 'noopener,noreferrer') }
function sourceTagType(source: AiSource) { return source.material_type === 'central' ? 'danger' : source.material_type === 'textbook' ? 'primary' : 'success' }
function formatPublishedTime(value: string | null) {
  if (!value) return '近期'
  const formatted = formatBeijingDateTime(value)
  return formatted === '--' ? '发布时间待确认' : formatted
}

async function loadNews(resetPage = false) {
  if (resetPage) currentPage.value = 1
  newsLoading.value = true
  try {
    const result = (await newsApi.search({
      q: searchKeyword.value.trim(),
      sources: selectedSources.value,
      days: timeDays.value,
      sort: sortBy.value,
      page: currentPage.value,
      pageSize: pageSize.value,
    })).data.data
    news.value = result.items
    totalNews.value = result.total
    availableSources.value = result.sources
    lastNewsLoadedAt = Date.now()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '时政检索失败，请稍后重试'))
  } finally { newsLoading.value = false }
}
async function refreshNews() {
  refreshing.value = true
  try {
    await newsApi.refresh()
    await loadNews(true)
    lastNewsLoadedAt = Date.now()
    ElMessage.success('已更新时政，并按当前条件重新检索')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '刷新失败，请稍后重试'))
  } finally { refreshing.value = false }
}
function toggleSource(source: string) {
  selectedSources.value = selectedSources.value.includes(source)
    ? selectedSources.value.filter((item) => item !== source)
    : [...selectedSources.value, source]
  void loadNews(true)
}
function clearSources() {
  // “全部”同时代表清除媒体、时间、排序和关键词筛选，避免再占一个重置按钮。
  searchKeyword.value = ''
  selectedSources.value = []
  timeDays.value = 90
  sortBy.value = 'latest'
  void loadNews(true)
}
function changePage(page: number) {
  currentPage.value = page
  void loadNews()
}
async function loadTextbook(): Promise<CourseDetail | null> {
  if (textbookPromise) return textbookPromise
  textbookLoading.value = true
  textbookPromise = (async () => {
    try {
      // 课程中心允许存在尚未拆分章节的空课程。不能再固定取 courses[0]，
      // 否则新建空课程会遮蔽已有教材，导致 AI 功能误报“请先创建专题”。
      const courses = (await courseApi.list()).data.data
      const preferredId = workspace.currentCourse?.id
      const ordered = [...courses].sort((left, right) => {
        if (left.id === preferredId) return -1
        if (right.id === preferredId) return 1
        return right.id - left.id
      })
      const details = await Promise.all(ordered.map(async (course) => {
        try { return (await courseApi.detail(course.id)).data.data }
        catch { return null }
      }))
      const validDetails = details.filter((item): item is CourseDetail => Boolean(item))
      textbookOptions.value = validDetails
      const routeCourseId = Number(route.query.course_id)
      const hasRouteCourse = Number.isFinite(routeCourseId)
      const requestedCourse = hasRouteCourse ? validDetails.find((item) => item.id === routeCourseId) : null
      const preferred = validDetails.find((item) => item.id === preferredId && item.chapters.length)
      const withChapters = validDetails.find((item) => item.chapters.length)
      const selected = requestedCourse || preferred || withChapters || validDetails[0] || null
      textbook.value = selected
      selectedCourseId.value = selected?.id || null
      return selected
    } catch {
      textbook.value = null
      return null
    } finally {
      textbookLoading.value = false
      textbookPromise = null
    }
  })()
  return textbookPromise
}
async function ensureTextbook(): Promise<CourseDetail | null> {
  return textbook.value || await loadTextbook()
}
function changeTextbook(courseId: number) {
  const selected = textbookOptions.value.find((item) => item.id === courseId) || null
  textbook.value = selected
  selectedCourseId.value = selected?.id || null
  aiResult.value = null
  relations.value = []
  void router.replace({ query: { ...route.query, course_id: selected?.id ? String(selected.id) : undefined } })
}
function refreshWhenReturning() {
  if (document.visibilityState === 'visible' && Date.now() - lastNewsLoadedAt > 30 * 60 * 1000) void loadNews()
}
watch(() => route.query.q, (value, previous) => {
  const next = typeof value === 'string' ? value : ''
  const before = typeof previous === 'string' ? previous : ''
  if (next === before) return
  searchKeyword.value = next
  void loadNews(true)
})
onMounted(() => {
  searchKeyword.value = typeof route.query.q === 'string' ? route.query.q : ''
  void loadNews()
  void (async () => {
    // 先尝试使用工作台的当前课程，再回退到课程中心中第一个已有章节的教材。
    await workspace.initialize()
    await loadTextbook()
  })()
  document.addEventListener('visibilitychange', refreshWhenReturning)
})
function cancelAiStream() {
  aiRequestSequence += 1
  aiStreamController?.abort()
  aiStreamController = null
  aiLoading.value = false
}
function closeAiDialog() {
  cancelAiStream()
  dialogVisible.value = false
}
function handleAiDialogVisibility(visible: boolean) {
  if (!visible) cancelAiStream()
}
onUnmounted(() => {
  cancelAiStream()
  document.removeEventListener('visibilitychange', refreshWhenReturning)
})
async function openAi(item: NewsItem, mode: 'summary' | 'relation') {
  cancelAiStream()
  const requestSequence = aiRequestSequence
  const controller = new AbortController()
  aiStreamController = controller
  selectedNews.value = item
  aiMode.value = mode
  aiScopeLabel.value = ''
  aiResult.value = null
  dialogVisible.value = true
  aiLoading.value = true
  try {
    aiResult.value = { answer: '', grounded: true, model: '', sources: [] }
    if (mode === 'summary') {
      aiScopeLabel.value = '信息范围：仅当前时政材料，不检索教材'
      await newsApi.summaryStream(item.id, {
        onMeta: (meta) => { if (aiResult.value) { aiResult.value.grounded = meta.grounded; aiResult.value.model = meta.model } },
        onChunk: (text) => { if (aiResult.value) aiResult.value.answer += text },
        onSources: () => {},
      }, { signal: controller.signal })
      return
    }

    const course = await ensureTextbook()
    let chapter = course?.chapters[0]
    if (!course || !chapter) {
      dialogVisible.value = false
      ElMessage.warning('“关联课本”需要先导入教材并完成章节拆分')
      return
    }
    const recommended = (await newsApi.textbookRelations(item.id, course.id, { signal: controller.signal })).data.data[0]
    if (controller.signal.aborted || requestSequence !== aiRequestSequence) return
    const matched = recommended ? course.chapters.find((candidate) => candidate.id === recommended.chapter_id) : null
    if (matched) chapter = matched
    const relationHint = recommended
      ? `系统初步匹配位置：${recommended.position}；匹配线索：${recommended.reason}。`
      : ''
    aiScopeLabel.value = `教材范围：${course.name} · ${chapter.title}`
    const question = `请分析以下时政信息与当前教材专题的关系，指出对应的教材知识点并说明关联理由。${relationHint}标题：${item.title}；摘要：${item.summary || '无'}`
    if (controller.signal.aborted || requestSequence !== aiRequestSequence) return
    await aiApi.assistStream({
      course_id: course.id,
      chapter_id: chapter.id,
      learning_stage: 'preview',
      task_type: 'question_answer',
      question,
    }, {
      onMeta: (meta) => { if (aiResult.value) { aiResult.value.grounded = meta.grounded; aiResult.value.model = meta.model } },
      onChunk: (text) => { if (aiResult.value) aiResult.value.answer += text },
      onSources: (sources) => { if (aiResult.value) aiResult.value.sources = sources },
    }, { signal: controller.signal })
  } catch (error: unknown) {
    if (!controller.signal.aborted && requestSequence === aiRequestSequence) {
      ElMessage.error(getErrorMessage(error, 'AI 暂时无法生成结果'))
    }
  } finally {
    if (aiStreamController === controller) {
      aiStreamController = null
      aiLoading.value = false
    }
  }
}

async function openStudyNote(item: NewsItem) {
  const course = await ensureTextbook()
  if (!course || !course.chapters.length) return ElMessage.warning('当前还没有可用的教材专题，请先导入教材并完成章节拆分')
  selectedNews.value = item
  studyDialogVisible.value = true
  relations.value = []
  selectedChapterId.value = null
  studyDraft.value = ''
  savedChapterId.value = null
  relationLoading.value = true
  try {
    relations.value = (await newsApi.textbookRelations(item.id, course.id)).data.data
    selectedChapterId.value = relations.value[0]?.chapter_id || course.chapters[0]?.id || null
    await checkNoteStatus()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '暂时无法匹配教材章节'))
  } finally { relationLoading.value = false }
}

async function checkNoteStatus() {
  if (!selectedChapterId.value) return noteExists.value = false
  try { noteExists.value = Boolean((await studyApi.note(selectedChapterId.value)).data.data) }
  catch { noteExists.value = false }
}

async function generateStudyDraft() {
  const course = textbook.value
  const item = selectedNews.value
  const relation = selectedRelation.value
  if (!course || !item || !relation) return ElMessage.warning('请先选择关联的教材章节')
  studyDraft.value = ''
  savedChapterId.value = null
  draftLoading.value = true
  const question = [
    `请把以下时政材料整理为可供学生修改的研学笔记。`,
    `时政标题：${item.title}`,
    `时政摘要：${item.summary || '原始摘要未提供，请勿补写未知事实。'}`,
    `媒体来源：${item.source_name}`,
    `原文链接：${item.article_url}`,
    `教材匹配位置：${relation.position}`,
    `匹配理由：${relation.reason}`,
    `请严格区分时政事实、教材观点和启发性思考，并保留资料来源。`,
  ].join('\n')
  try {
    await aiApi.assistStream({
      course_id: course.id,
      chapter_id: relation.chapter_id,
      learning_stage: 'review',
      task_type: 'news_study_note',
      question,
    }, {
      onMeta: () => {},
      onChunk: (text) => { studyDraft.value += text },
      onSources: () => {},
    })
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '研学笔记生成失败，请稍后重试'))
  } finally { draftLoading.value = false }
}

async function saveStudyNote() {
  const item = selectedNews.value
  const relation = selectedRelation.value
  if (!item || !relation || !studyDraft.value.trim()) return ElMessage.warning('请先生成或填写研学笔记草稿')
  noteSaving.value = true
  try {
    const result = (await newsApi.saveStudyNote(item.id, {
      chapter_id: relation.chapter_id,
      content: studyDraft.value,
      textbook_relation: `${relation.position}；${relation.reason}`,
      mode: noteExists.value ? 'append' : 'create',
    })).data.data
    savedChapterId.value = result.chapter_id
    noteExists.value = true
    ElMessage.success(result.appended ? '已追加到该章节的个人笔记' : '已创建研学笔记')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '研学笔记保存失败'))
  } finally { noteSaving.value = false }
}

function openSavedNote() {
  if (!savedChapterId.value) return
  void router.push({ path: '/notes', query: { chapter_id: String(savedChapterId.value) } })
}

async function ensureTeachingClasses() {
  if (teachingClassesLoaded || !auth.isTeacher) return
  try {
    const list = (await teachingClassApi.list()).data.data
    teachingClasses.value = list.filter((item) => item.status === 'active' || item.status === 'not_started')
    teachingClassesLoaded = true
  } catch {
    teachingClasses.value = []
  }
}

function buildDefaultPrepGoal(newsTitle: string, chapterTitle?: string) {
  return chapterTitle
    ? `围绕“${chapterTitle}”，结合时政热点“${newsTitle}”开展案例剖析与课堂思辨。`
    : `结合时政热点“${newsTitle}”开展案例剖析与课堂思辨。`
}

async function loadPrepRelations(newsId: number, courseId: number) {
  prepRelationLoading.value = true
  prepRelations.value = []
  try {
    prepRelations.value = (await newsApi.textbookRelations(newsId, courseId)).data.data
    const course = availableTextbookCourses.value.find((item) => item.id === courseId)
    const recommended = prepRelations.value[0]?.chapter_id || course?.chapters[0]?.id || null
    prepChapterId.value = recommended
    const chapterTitle = course?.chapters.find((c) => c.id === recommended)?.title
    if (selectedNews.value) {
      prepTeachingGoal.value = buildDefaultPrepGoal(selectedNews.value.title, chapterTitle)
    }
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '暂时无法匹配教材章节'))
  } finally {
    prepRelationLoading.value = false
  }
}

async function openLessonPrepDialog(item: NewsItem) {
  const course = await ensureTextbook()
  const targetCourse = (course && course.chapters.length ? course : availableTextbookCourses.value[0]) || null
  if (!targetCourse) {
    ElMessage.warning('当前还没有可用的教材专题，请先导入教材并完成章节拆分')
    return
  }
  await ensureTeachingClasses()
  selectedNews.value = item
  prepCourseId.value = targetCourse.id
  prepChapterId.value = null
  prepTeachingGoal.value = buildDefaultPrepGoal(item.title)
  prepDialogVisible.value = true
  const matchedClass = teachingClasses.value.find((c) => !c.material_ids.length || c.material_ids.includes(targetCourse.id))
  prepTeachingClassId.value = matchedClass?.id || null
  await loadPrepRelations(item.id, targetCourse.id)
}

async function handlePrepCourseChange(courseId: number) {
  if (!selectedNews.value) return
  if (!prepEligibleClasses.value.some((item) => item.id === prepTeachingClassId.value)) {
    prepTeachingClassId.value = prepEligibleClasses.value[0]?.id || null
  }
  await loadPrepRelations(selectedNews.value.id, courseId)
}

function handlePrepChapterChange(chapterId: number) {
  if (!selectedNews.value) return
  const chapterTitle = prepCourse.value?.chapters.find((item) => item.id === chapterId)?.title
  prepTeachingGoal.value = buildDefaultPrepGoal(selectedNews.value.title, chapterTitle)
}

function sendToLessonPrepWorkspace() {
  const item = selectedNews.value
  if (!item || !prepCourseId.value || !prepChapterId.value) {
    ElMessage.warning('请先选择目标课程与教材专题')
    return
  }
  saveLessonPrepNewsHandoff({
    newsItem: item,
    courseId: prepCourseId.value,
    chapterId: prepChapterId.value,
    teachingClassId: prepTeachingClassId.value,
    teachingGoal: prepTeachingGoal.value.trim(),
    relationReason: prepSelectedRelation.value?.reason || '',
  })
  prepDialogVisible.value = false
  void router.push({ path: '/lesson-prep', query: { news_id: String(item.id) } })
}

async function createLessonPrepWithNews() {
  const item = selectedNews.value
  if (!item || !prepCourseId.value || !prepChapterId.value) {
    ElMessage.warning('请先选择目标课程与教材专题')
    return
  }
  prepCreating.value = true
  try {
    const response = await agentApi.create({
      agent_type: 'teacher_lesson_prep',
      course_id: prepCourseId.value,
      chapter_id: prepChapterId.value,
      teaching_class_id: prepTeachingClassId.value || null,
      input: {
        lesson_hours: 2,
        learning_stage: 'preview',
        student_level: '本科生',
        completion_condition: '教材阅读',
        teaching_goal: prepTeachingGoal.value.trim() || null,
        output_types: ['outline'],
        news_item_ids: [item.id],
      },
    })
    const run = response.data.data
    prepDialogVisible.value = false
    if (run.status === 'failed') {
      ElMessage.error(run.error_message || '备课证据包构建失败')
    } else {
      ElMessage.success('已将时政素材注入备课证据包，请核验后确认生成课纲')
    }
    void router.push({ path: '/lesson-prep', query: { run_id: String(run.id) } })
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '创建备课证据包失败'))
  } finally {
    prepCreating.value = false
  }
}

async function loadDebateRelations(newsId: number, courseId: number) {
  debateRelationLoading.value = true
  debateRelations.value = []
  try {
    debateRelations.value = (await newsApi.textbookRelations(newsId, courseId)).data.data
    const course = availableTextbookCourses.value.find((item) => item.id === courseId)
    debateChapterId.value = debateRelations.value[0]?.chapter_id || course?.chapters[0]?.id || null
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '暂时无法匹配教材章节'))
  } finally {
    debateRelationLoading.value = false
  }
}

async function openDebateDialog(item: NewsItem) {
  const course = await ensureTextbook()
  const targetCourse = (course && course.chapters.length ? course : availableTextbookCourses.value[0]) || null
  if (!targetCourse) {
    ElMessage.warning('当前还没有可用的教材专题，请先导入教材并完成章节拆分')
    return
  }
  await ensureTeachingClasses()
  selectedNews.value = item
  debateCourseId.value = targetCourse.id
  debateChapterId.value = null
  debateActivityType.value = 'judgment'
  debateQuestion.value = ''
  debateOptionsText.value = ''
  debateMinutes.value = 8
  debateGuide.value = []
  debateTextbookPosition.value = ''
  debateCitation.value = null
  debateModel.value = ''
  debatePublished.value = false
  debateDialogVisible.value = true
  const matchedClass = teachingClasses.value.find((c) => !c.material_ids.length || c.material_ids.includes(targetCourse.id))
  debateTeachingClassId.value = matchedClass?.id || null
  await loadDebateRelations(item.id, targetCourse.id)
}

async function handleDebateCourseChange(courseId: number) {
  if (!selectedNews.value) return
  if (!debateEligibleClasses.value.some((item) => item.id === debateTeachingClassId.value)) {
    debateTeachingClassId.value = debateEligibleClasses.value[0]?.id || null
  }
  await loadDebateRelations(selectedNews.value.id, courseId)
}

async function generateDebateDraft() {
  const item = selectedNews.value
  if (!item || !debateCourseId.value || !debateChapterId.value) {
    ElMessage.warning('请先选择关联的教材课程与章节')
    return
  }
  debateGenerating.value = true
  debatePublished.value = false
  try {
    const data = (await newsApi.classroomDebateDraft(item.id, {
      course_id: debateCourseId.value,
      chapter_id: debateChapterId.value,
      activity_type: debateActivityType.value,
    })).data.data
    debateQuestion.value = data.question
    debateOptionsText.value = data.options.join('\n')
    debateMinutes.value = data.suggested_minutes
    debateGuide.value = data.teaching_guide
    debateTextbookPosition.value = data.textbook_position
    debateCitation.value = data.source_citation
    debateModel.value = data.model
    ElMessage.success('课堂互动草稿已生成，请核验修改后再发布')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '生成课堂辨析草稿失败，请稍后重试'))
  } finally {
    debateGenerating.value = false
  }
}

function parsedDebateOptions() {
  return debateOptionsText.value.split('\n').map((line) => line.trim()).filter(Boolean)
}

function sendDebateToInteractionPage() {
  const item = selectedNews.value
  if (!item || !debateCourseId.value || !debateChapterId.value) {
    ElMessage.warning('请先选择教材课程与章节')
    return
  }
  if (!debateQuestion.value.trim()) {
    ElMessage.warning('请先生成或填写课堂互动题干')
    return
  }
  const citation: NewsDebateSourceCitation = debateCitation.value || {
    news_id: item.id,
    title: item.title,
    source_name: item.source_name,
    published_time: formatPublishedTime(item.published_time),
    article_url: item.article_url,
  }
  saveClassroomDebateHandoff({
    teachingClassId: debateTeachingClassId.value,
    courseId: debateCourseId.value,
    chapterId: debateChapterId.value,
    activityType: debateActivityType.value,
    question: debateQuestion.value.trim(),
    options: debateActivityType.value === 'judgment' ? parsedDebateOptions() : [],
    minutes: debateMinutes.value,
    teachingGuide: debateGuide.value,
    textbookPosition: debateTextbookPosition.value,
    sourceCitation: citation,
  })
  debateDialogVisible.value = false
  void router.push('/interaction')
}

async function publishDebateDirectly() {
  const item = selectedNews.value
  if (!item || !debateCourseId.value || !debateChapterId.value) {
    ElMessage.warning('请先选择关联的教材与章节')
    return
  }
  if (!debateTeachingClassId.value) {
    ElMessage.warning('直接发布需要选择目标教学班，也可点击“带入课堂互动页”稍后再选')
    return
  }
  const question = debateQuestion.value.trim()
  if (question.length < 5) {
    ElMessage.warning('课堂题干至少需要 5 个字')
    return
  }
  const options = parsedDebateOptions()
  if (debateActivityType.value === 'judgment' && options.length < 2) {
    ElMessage.warning('观点辨析至少需要 2 个立场选项（每行一个）')
    return
  }
  const citation = debateCitation.value || {
    news_id: item.id,
    title: item.title,
    source_name: item.source_name,
    published_time: formatPublishedTime(item.published_time),
    article_url: item.article_url,
  }
  debatePublishing.value = true
  try {
    await classroomApi.publish({
      teaching_class_id: debateTeachingClassId.value,
      course_id: debateCourseId.value,
      chapter_id: debateChapterId.value,
      question,
      minutes: debateMinutes.value,
      activity_type: debateActivityType.value,
      response_limit: 1,
      grouping_mode: debateActivityType.value === 'group' ? 'manual' : null,
      config: {
        ...(debateActivityType.value === 'judgment' ? { options } : {}),
        source_news_id: citation.news_id,
        source_title: citation.title,
        source_name: citation.source_name,
        source_url: citation.article_url,
        published_time: citation.published_time,
        teaching_guide: debateGuide.value,
      },
    })
    debatePublished.value = true
    ElMessage.success('课堂互动已发布到所选教学班')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '发布课堂互动失败'))
  } finally {
    debatePublishing.value = false
  }
}

function goInteractionPage() {
  debateDialogVisible.value = false
  void router.push('/interaction')
}
</script>

<template>
  <div v-loading="loading" class="current-affairs-page">
    <header class="affairs-page-title">
      <button type="button" class="affairs-back-button" aria-label="返回课程总览" @click="router.push('/courses')">
        <span class="affairs-back-triangle" aria-hidden="true"></span>
      </button>
      <h1>时政要点</h1>
    </header>

    <section class="affairs-layout affairs-layout-single">
      <div>
        <section class="news-search-panel">
          <h2>你好，有什么可以帮助到你的?</h2>
          <div class="news-search-row">
            <el-input v-model="searchKeyword" :prefix-icon="Search" clearable placeholder="搜索政策、主题或关键词，例如：生态文明" @keyup.enter="loadNews(true)" @clear="loadNews(true)" />
            <el-select v-model="timeDays" placeholder="发布时间" clearable @change="loadNews(true)">
              <el-option label="最近 24 小时" :value="1" />
              <el-option label="最近 3 天" :value="3" />
              <el-option label="最近 7 天" :value="7" />
              <el-option label="最近 30 天" :value="30" />
              <el-option label="最近 90 天" :value="90" />
            </el-select>
            <el-select v-model="sortBy" @change="loadNews(true)">
              <el-option label="按时间排序" value="latest" />
              <el-option label="按相关度排序" value="relevance" :disabled="!searchKeyword.trim()" />
            </el-select>
            <el-button type="primary" :icon="Search" :loading="newsLoading" @click="loadNews(true)">搜索</el-button>
          </div>
          <div v-if="sourceNames.length" class="news-source-filter">
            <span class="news-source-label">媒体来源</span>
            <el-check-tag :checked="selectedSources.length === 0" title="清除所有筛选" @change="clearSources">全部</el-check-tag>
            <el-check-tag v-for="source in sourceNames" :key="source" :checked="selectedSources.includes(source)" @change="toggleSource(source)">{{ source }}</el-check-tag>
          </div>
          <div class="news-search-summary">
            <span>共找到 <strong>{{ totalNews }}</strong> 条时政内容</span>
            <span v-if="hasFilters" class="news-filter-note">当前条件仅筛选已采集的权威资讯</span>
          </div>
          <div v-if="textbookOptions.length" class="affairs-textbook-picker">
            <span>关联教材</span>
            <el-select v-model="selectedCourseId" size="small" placeholder="选择教材" @change="changeTextbook">
              <el-option v-for="option in textbookOptions" :key="option.id" :label="option.name" :value="option.id">
                <span>{{ option.name }}</span><small>{{ option.chapters.length }} 个专题</small>
              </el-option>
            </el-select>
            <span v-if="textbook" class="affairs-textbook-status">已关联 {{ textbook.chapters.length }} 个专题</span>
          </div>
        </section>

        <section class="news-summary-section">
          <div class="news-summary-heading">
            <div>
              <h2>时政摘要</h2>
            </div>
            <el-button :icon="Refresh" :loading="refreshing" plain class="news-refresh-button" @click="refreshNews">刷新时政</el-button>
          </div>
          <el-card v-loading="newsLoading" shadow="never" class="news-list">
            <article v-for="item in news" :key="item.id" class="news-item">
              <div class="news-item-body">
                <h3>{{ item.title }}</h3>
                <p>{{ item.summary || '打开原文查看详细内容。' }}</p>
                <div class="news-item-source">{{ item.source_name }}</div>
                <div class="news-actions">
                  <el-button size="small" class="news-action news-action-ai" @click="openAi(item, 'summary')">AI总结</el-button>
                  <el-button size="small" class="news-action news-action-relation" @click="openAi(item, 'relation')">关联课本</el-button>
                  <template v-if="auth.isTeacher">
                    <el-button size="small" class="news-action news-action-prep" @click="openLessonPrepDialog(item)">带入备课素材</el-button>
                    <el-button size="small" class="news-action news-action-debate" @click="openDebateDialog(item)">生成课堂辨析</el-button>
                  </template>
                  <el-button v-else size="small" class="news-action news-action-note" @click="openStudyNote(item)">生成研学笔记</el-button>
                </div>
              </div>
              <div class="news-item-aside">
                <el-link :href="item.article_url" target="_blank" type="primary" underline="never" class="news-original-link">
                  <span>查看原文</span><strong>⟶</strong>
                </el-link>
              </div>
              <div class="news-date"><el-icon><Calendar /></el-icon><span>{{ formatPublishedTime(item.published_time) }}</span></div>
            </article>
            <el-empty v-if="!newsLoading && !news.length" description="暂未获取到时政信息，请稍后再试" />
          </el-card>
          <el-pagination v-if="totalNews > pageSize" class="news-pagination" background layout="prev, pager, next" :current-page="currentPage" :page-size="pageSize" :total="totalNews" @current-change="changePage" />
        </section>
      </div>
    </section>
    <el-dialog v-model="dialogVisible" :title="aiMode === 'summary' ? 'AI 时政总结' : 'AI 课本关联'" width="720px" @update:model-value="handleAiDialogVisibility">
      <div v-if="selectedNews" class="selected-news"><strong>{{ selectedNews.title }}</strong><p>{{ selectedNews.summary || '暂无摘要' }}</p></div>
      <section v-if="aiResult" class="ai-dialog-result ai-result">
        <div class="answer-meta"><el-tag :type="aiResult.grounded ? 'success' : 'warning'" effect="light">{{ aiMode === 'summary' ? 'AI 生成内容 · 依据时政材料' : (aiResult.grounded ? 'AI 生成内容 · 依据教材资料' : 'AI 生成内容 · 教材资料不足') }}</el-tag><span class="answer-scope">{{ aiScopeLabel }}</span><span v-if="aiResult.model" class="answer-model">模型：{{ aiResult.model }}</span></div>
        <article class="answer-content teaching-document" v-html="renderedAnswer"></article><span v-if="aiLoading" class="stream-cursor" aria-label="正在生成"></span>
        <div v-if="aiMode === 'summary' && selectedNews" class="news-summary-source"><span>总结依据：{{ selectedNews.source_name }}提供的标题与摘要</span><el-link :href="selectedNews.article_url" target="_blank" type="primary" underline="never">查看时政原文 →</el-link></div>
        <div v-if="aiResult.sources.length" class="answer-sources"><div class="source-heading"><strong>原文依据与引用位置</strong><span>点击引用核对真实来源</span></div><button v-for="(source, index) in aiResult.sources" :key="`${source.source_title}-${index}`" type="button" class="source-item source-item--button" :class="`source-${source.material_type}`" :disabled="!source.source_url && (!source.document_id || !source.pdf_page_start)" @click="openCitation(source)"><div class="source-title"><span>[{{ index + 1 }}] {{ source.source_title }}</span><el-tag size="small" :type="sourceTagType(source)">{{ source.evidence_type }}</el-tag></div><strong class="source-position">{{ source.section_path || source.position }}</strong><span v-if="source.publisher || source.published_date" class="source-publisher">{{ source.publisher }}<template v-if="source.publisher && source.published_date"> · </template>{{ source.published_date }}</span><p>{{ source.excerpt }}</p><span v-if="source.document_id && source.pdf_page_start" class="source-open">查看 PDF 原页 →</span><span v-else-if="source.source_url" class="source-open">查看权威原文 →</span></button></div>
      </section>
      <el-empty v-else-if="!aiLoading" description="暂无生成结果" />
      <template #footer><el-button @click="closeAiDialog">关闭</el-button></template>
    </el-dialog>
    <PdfCitationViewer v-model:visible="citationVisible" :source="selectedSource" />
    <el-dialog v-if="!auth.isTeacher" v-model="studyDialogVisible" title="生成时政研学笔记" width="880px" class="study-note-dialog">
      <div v-if="selectedNews" class="selected-news"><strong>{{ selectedNews.title }}</strong><p>{{ selectedNews.summary || '暂无摘要，请以原文为准。' }}</p></div>
      <div class="study-note-steps">
        <section v-loading="relationLoading" class="study-note-step">
          <div class="step-title"><span>1</span><div><strong>确认教材章节</strong><small>系统推荐不替代人工判断，可切换后再生成</small></div></div>
          <el-radio-group v-model="selectedChapterId" class="relation-options" @change="checkNoteStatus">
            <el-radio v-for="relation in relations" :key="relation.chapter_id" :value="relation.chapter_id" border>
              <strong>{{ relation.chapter_title }}</strong><span>{{ relation.reason }}</span><small>{{ relation.position }}</small>
            </el-radio>
          </el-radio-group>
          <el-alert v-if="selectedRelation" :closable="false" type="info" show-icon>
            <template #title>教材依据：{{ selectedRelation.excerpt }}</template>
          </el-alert>
        </section>
        <section class="study-note-step">
          <div class="step-title"><span>2</span><div><strong>生成并修改草稿</strong><small>事实来自新闻，理论观点限定在所选章节</small></div><el-button type="primary" :loading="draftLoading" :disabled="!selectedRelation" @click="generateStudyDraft">{{ studyDraft ? '重新生成' : '生成草稿' }}</el-button></div>
          <div class="ai-draft-hint" role="note"><el-icon><MagicStick /></el-icon><span><strong>AI 生成提示</strong>以下内容由 AI 根据所选时政材料和教材章节生成，仅供参考；请核对事实，并结合自己的理解修改后再保存。</span></div>
          <el-input v-model="studyDraft" type="textarea" :autosize="{ minRows: 12, maxRows: 20 }" maxlength="16000" show-word-limit placeholder="生成后可在这里增删、改写；保存后还能在笔记空间继续排版。" />
          <span v-if="draftLoading" class="stream-cursor" aria-label="正在生成"></span>
        </section>
        <section class="study-note-step save-study-note-row">
          <div class="step-title"><span>3</span><div><strong>{{ noteExists ? '追加到已有章节笔记' : '创建章节笔记' }}</strong><small>不会覆盖原笔记，并记录新闻来源与教材关联</small></div></div>
          <div><el-button v-if="savedChapterId" @click="openSavedNote">前往笔记空间修改</el-button><el-button type="success" :loading="noteSaving" :disabled="!studyDraft.trim() || draftLoading" @click="saveStudyNote">{{ noteExists ? '追加到笔记' : '添加到笔记空间' }}</el-button></div>
        </section>
      </div>
      <template #footer><el-button @click="studyDialogVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-if="auth.isTeacher" v-model="prepDialogVisible" title="将时政热点带入备课素材" width="820px" class="study-note-dialog">
      <div v-if="selectedNews" class="selected-news">
        <strong>{{ selectedNews.title }}</strong>
        <p>{{ selectedNews.summary || '暂无摘要，请结合原文链接核对具体事实。' }}</p>
        <div class="teacher-news-meta">
          <span>来源：{{ selectedNews.source_name }} · {{ formatPublishedTime(selectedNews.published_time) }}</span>
          <el-link :href="selectedNews.article_url" target="_blank" type="primary" underline="never">核验原文 →</el-link>
        </div>
      </div>
      <div class="study-note-steps">
        <section v-loading="prepRelationLoading" class="study-note-step">
          <div class="step-title">
            <span>1</span>
            <div><strong>确认目标课程、专题与教学班</strong><small>系统自动推荐关联专题，该时政将作为真实证据卡进入备课证据快照</small></div>
          </div>
          <div class="teacher-scope-grid">
            <el-select v-model="prepCourseId" placeholder="选择教材课程" @change="handlePrepCourseChange">
              <el-option v-for="option in availableTextbookCourses" :key="option.id" :label="option.name" :value="option.id" />
            </el-select>
            <el-select v-model="prepChapterId" placeholder="选择教材专题" @change="handlePrepChapterChange">
              <el-option v-for="chapter in prepCourse?.chapters || []" :key="chapter.id" :label="chapter.title" :value="chapter.id" />
            </el-select>
            <el-select v-model="prepTeachingClassId" clearable placeholder="关联教学班（可选）">
              <el-option v-for="item in prepEligibleClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" />
            </el-select>
          </div>
          <el-radio-group v-if="prepRelations.length" v-model="prepChapterId" class="relation-options" @change="handlePrepChapterChange">
            <el-radio v-for="relation in prepRelations" :key="relation.chapter_id" :value="relation.chapter_id" border>
              <strong>{{ relation.chapter_title }}</strong><span>{{ relation.reason }}</span><small>{{ relation.position }}</small>
            </el-radio>
          </el-radio-group>
        </section>
        <section class="study-note-step">
          <div class="step-title">
            <span>2</span>
            <div><strong>补充教学任务要求（可选）</strong><small>确认证据前仍可在备课工作台调整课时、对象与输出成果</small></div>
          </div>
          <el-input v-model="prepTeachingGoal" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="说明如何将本条时政融入课堂导入、案例剖析或课堂讨论" />
        </section>
      </div>
      <template #footer>
        <el-button @click="prepDialogVisible = false">取消</el-button>
        <el-button :disabled="!prepCourseId || !prepChapterId" @click="sendToLessonPrepWorkspace">带入备课工作台调整</el-button>
        <el-button type="primary" :loading="prepCreating" :disabled="!prepCourseId || !prepChapterId" @click="createLessonPrepWithNews">直接构建备课证据包</el-button>
      </template>
    </el-dialog>

    <el-dialog v-if="auth.isTeacher" v-model="debateDialogVisible" title="从时政热点生成课堂辨析草稿" width="880px" class="study-note-dialog">
      <div v-if="selectedNews" class="selected-news">
        <strong>{{ selectedNews.title }}</strong>
        <p>{{ selectedNews.summary || '暂无摘要，请结合原文链接核对具体事实。' }}</p>
        <div class="teacher-news-meta">
          <span>来源：{{ selectedNews.source_name }} · {{ formatPublishedTime(selectedNews.published_time) }}</span>
          <el-link :href="selectedNews.article_url" target="_blank" type="primary" underline="never">核验原文 →</el-link>
        </div>
      </div>
      <div class="study-note-steps">
        <section v-loading="debateRelationLoading" class="study-note-step">
          <div class="step-title">
            <span>1</span>
            <div><strong>选择教学范围与活动类型</strong><small>支持观点辨析、随堂问答与小组讨论；仅产出草稿，发布前须人工核验</small></div>
            <el-button type="primary" :loading="debateGenerating" :disabled="!debateCourseId || !debateChapterId" @click="generateDebateDraft">{{ debateQuestion ? '重新生成草稿' : 'AI 生成草稿' }}</el-button>
          </div>
          <div class="teacher-scope-grid">
            <el-select v-model="debateTeachingClassId" clearable placeholder="目标教学班（直发必选）">
              <el-option v-for="item in debateEligibleClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" />
            </el-select>
            <el-select v-model="debateCourseId" placeholder="选择教材课程" @change="handleDebateCourseChange">
              <el-option v-for="option in availableTextbookCourses" :key="option.id" :label="option.name" :value="option.id" />
            </el-select>
            <el-select v-model="debateChapterId" placeholder="选择教材专题">
              <el-option v-for="chapter in debateCourse?.chapters || []" :key="chapter.id" :label="chapter.title" :value="chapter.id" />
            </el-select>
          </div>
          <div class="debate-type-row">
            <span class="debate-type-label">互动类型</span>
            <el-radio-group v-model="debateActivityType" size="small">
              <el-radio-button value="judgment">观点辨析</el-radio-button>
              <el-radio-button value="qa">随堂问答</el-radio-button>
              <el-radio-button value="group">小组讨论</el-radio-button>
            </el-radio-group>
            <span v-if="debateSelectedRelation" class="debate-match-hint">推荐依据：{{ debateSelectedRelation.position }}</span>
          </div>
        </section>
        <section class="study-note-step">
          <div class="step-title">
            <span>2</span>
            <div><strong>编辑课堂题干与选项</strong><small>题干与立场选项均可自由修改{{ debateModel ? ` · 模型：${debateModel}` : '' }}</small></div>
          </div>
          <div class="ai-draft-hint" role="note">
            <el-icon><MagicStick /></el-icon>
            <span><strong>AI 教学草稿提示</strong>草稿仅依据当前新闻摘要与所选教材章节片段生成，请结合班级学情核对修改后再发布。</span>
          </div>
          <el-input v-model="debateQuestion" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="点击上方“AI 生成草稿”或直接输入课堂辨析命题……" />
          <div v-if="debateActivityType === 'judgment'" class="debate-options-editor">
            <label class="debate-field-label">辨析立场选项（每行一个，至少 2 项）</label>
            <el-input v-model="debateOptionsText" type="textarea" :rows="3" placeholder="例如：\n赞同核心观点，但需补充前提条件\n以偏概全，忽视了长期战略与制度逻辑" />
          </div>
          <div class="debate-minutes-row">
            <label class="debate-field-label">建议讨论时长</label>
            <el-input-number v-model="debateMinutes" :min="3" :max="60" size="small" />
            <span>分钟</span>
          </div>
          <div v-if="debateGuide.length" class="teacher-guide-box">
            <strong>教师课堂追问与点评参考（仅教师可见）</strong>
            <small v-if="debateTextbookPosition">关联教材位置：{{ debateTextbookPosition }}</small>
            <ul>
              <li v-for="(tip, idx) in debateGuide" :key="idx">{{ tip }}</li>
            </ul>
          </div>
        </section>
      </div>
      <template #footer>
        <el-button @click="debateDialogVisible = false">关闭</el-button>
        <el-button v-if="debatePublished" type="success" @click="goInteractionPage">前往课堂互动查看</el-button>
        <template v-else>
          <el-button :disabled="!debateQuestion.trim() || !debateCourseId || !debateChapterId" @click="sendDebateToInteractionPage">带入课堂互动页继续编辑</el-button>
          <el-button type="primary" :loading="debatePublishing" :disabled="!debateQuestion.trim() || !debateTeachingClassId || !debateCourseId || !debateChapterId" @click="publishDebateDirectly">直接发布到教学班</el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.news-action-prep {
  color: #1f5c99;
  background: #edf5ff;
  border-color: #c5ddfb;
}
.news-action-prep:hover {
  color: #164778;
  background: #dfeeff;
  border-color: #9ec5f8;
}
.news-action-debate {
  color: #9a3412;
  background: #fff3ec;
  border-color: #fed7aa;
}
.news-action-debate:hover {
  color: #7c2d12;
  background: #ffe8d9;
  border-color: #fdba74;
}
.teacher-news-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--ink-500);
}
.teacher-scope-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.teacher-scope-grid :deep(.el-select) {
  width: 100%;
}
.debate-type-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
}
.debate-type-label,
.debate-field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-700);
}
.debate-match-hint {
  font-size: 12px;
  color: var(--ink-500);
}
.debate-options-editor {
  display: grid;
  gap: 6px;
}
.debate-minutes-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ink-600);
}
.teacher-guide-box {
  padding: 12px 14px;
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-left: 3px solid var(--action-blue);
  border-radius: 10px;
}
.teacher-guide-box strong {
  display: block;
  font-size: 13px;
  color: var(--ink-800);
}
.teacher-guide-box small {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-500);
}
.teacher-guide-box ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--ink-700);
  font-size: 13px;
  line-height: 1.65;
}
@media (max-width: 720px) {
  .teacher-scope-grid {
    grid-template-columns: 1fr;
  }
}
</style>

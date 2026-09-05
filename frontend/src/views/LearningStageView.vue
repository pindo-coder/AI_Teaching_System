<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { courseApi } from '@/api/courses'
import { learningApi } from '@/api/learning'
import type { Chapter, CourseDetail, LearningFootprint, LearningStage } from '@/types'
import { formatTextbookParagraphs } from '@/utils/textbookText'
import { studyApi } from '@/api/study'
import type { ReviewAnswerResult, ReviewQuestion, ReviewReferenceItem, StudyNote } from '@/api/study'
import { notePlainText, sanitizeNoteHtml } from '@/utils/noteContent'
import { ElMessage } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import NoteRichEditor from '@/components/NoteRichEditor.vue'
import TextbookAnnotationReader from '@/components/TextbookAnnotationReader.vue'
import logoUrl from '@/assets/logo1.svg'
import learningHeroBackground from '@/assets/learning-hero-reference.png'
import type { AiTaskType } from '@/api/ai'
import { requestWorkspaceAi } from '@/utils/workspaceAiEvents'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const stage = computed(() => route.params.stage as LearningStage)
const course = ref<CourseDetail | null>(null)
const chapter = ref<Chapter | null>(null)
const loading = ref(true)
const savedNote = ref<StudyNote | null>(null)
const noteEditing = ref(false)
const noteDraft = ref('')
const noteSaving = ref(false)
const footprint = ref<LearningFootprint | null>(null)
const practiceDialogVisible = ref(false)
const practiceLoading = ref(false)
const practiceQuestions = ref<ReviewQuestion[]>([])
const practiceIndex = ref(0)
const practiceAnswer = ref('')
const practiceResult = ref<ReviewAnswerResult | null>(null)
const practiceFinished = ref(false)
const practiceSubmissions = ref<Array<{
  question: ReviewQuestion
  answer: string
  result: ReviewAnswerResult
}>>([])
const practiceReferences = ref<ReviewReferenceItem[]>([])
const practiceReferenceLoading = ref(false)
const practiceReferenceError = ref('')
const practiceSavingToNotes = ref(false)
const practiceSavedToNotes = ref(false)
const annotationReader = ref<InstanceType<typeof TextbookAnnotationReader> | null>(null)
let lastReadingPercent = 0
const contentBlocks = computed(() => formatTextbookParagraphs(chapter.value?.content))
const savedNoteText = computed(() => notePlainText(savedNote.value?.content || ''))
const savedNoteHtml = computed(() => sanitizeNoteHtml(savedNote.value?.content || ''))

const configs: Record<LearningStage, {
  title: string
  subtitle: string
  next: LearningStage | null
  goals: string[]
  tasks: string[]
  aiHint: string
}> = {
  preview: {
    title: '预习空间', subtitle: '先建立整体认识，再带着问题进入课堂', next: 'review',
    goals: ['了解本专题研究什么问题', '识别需要重点理解的核心概念', '形成自己的课前疑问'],
    tasks: ['阅读专题导览', '通读教材原文', '使用 AI 生成预习问题'],
    aiHint: '展开页面上方的思政 AI 工作台，生成导读、概念解释和预习问题。',
  },
  review: {
    title: '课后巩固', subtitle: '梳理观点和逻辑，把课堂内容转化为知识结构', next: 'exam',
    goals: ['概括本专题核心观点', '理解概念之间的联系与区别', '形成自己的章节总结'],
    tasks: ['回看教材重点', '完成个人学习总结', '使用 AI 生成复习提纲'],
    aiHint: '展开页面上方的思政 AI 工作台，生成结构化总结、概念辨析和复习提纲。',
  },
  exam: {
    title: '考前冲刺', subtitle: '从理解转向输出，集中训练考点和答题能力', next: null,
    goals: ['提炼必须掌握的核心考点', '熟悉简答和材料分析的答题结构', '通过模拟练习发现薄弱点'],
    tasks: ['快速回顾核心原文', '使用 AI 梳理重点考点', '完成一组模拟练习'],
    aiHint: '展开页面上方的思政 AI 工作台，生成模拟题、参考答案和答题要点。',
  },
}
const config = computed(() => configs[stage.value])
type GuideAiAction = { label: string; description: string; taskType: AiTaskType; prompt: string }
const previewGuideActions: GuideAiAction[] = [
  { label: '梳理本章重点', description: '概括专题主旨与学习线索', taskType: 'chapter_summary', prompt: '请用简洁的层级结构梳理当前专题的核心观点。' },
  { label: '解释核心概念', description: '结合教材原文说明', taskType: 'question_answer', prompt: '请依据当前专题教材解释最重要的核心概念。' },
  { label: '生成预习问题', description: '带着问题进入课堂', taskType: 'preview_questions', prompt: '请严格依据当前专题教材生成 5 个预习问题。' },
]
const reviewGuideActions: GuideAiAction[] = [
  { label: '梳理本章重点', description: '概括专题核心观点与知识结构', taskType: 'chapter_summary', prompt: '请依据当前专题教材，梳理本章核心观点、知识结构和需要重点复习的内容。' },
  { label: '辨析核心概念', description: '理解概念之间的联系与区别', taskType: 'question_answer', prompt: '请依据当前专题教材，辨析本章重要概念之间的联系、区别和适用情境。' },
  { label: '生成复习提纲', description: '形成可直接回顾的章节总结', taskType: 'review_outline', prompt: '请严格依据当前专题教材，生成一份结构清晰的章节复习提纲。' },
]
const examGuideActions: GuideAiAction[] = [
  { label: '提炼考点', description: '识别章节主旨、核心概念和重要论述', taskType: 'chapter_summary', prompt: '请依据当前专题教材，提炼必须掌握的核心考点，并标注每个考点对应的关键论述。' },
  { label: '梳理答题结构', description: '组织概念、观点、依据与意义', taskType: 'question_answer', prompt: '请依据当前专题教材，梳理简答题和材料分析题的答题结构，并给出组织答案的要点。' },
  { label: '生成模拟练习', description: '通过练习定位薄弱知识点', taskType: 'mock_questions', prompt: '请严格依据当前专题教材生成一组考前模拟练习，并附上答题要点。' },
]
const chapterHeading = computed(() => {
  const title = chapter.value?.title?.trim() || ''
  const match = title.match(/^(专题\s*[0-9一二三四五六七八九十百]+)\s*[—\-:：、]?\s*(.*)$/)
  if (match) {
    return {
      label: match[1].replace(/\s+/g, ''),
      title: match[2].trim() || title,
    }
  }
  return {
    label: `专题 ${String(chapter.value?.sort_order || chapter.value?.id || 1).padStart(2, '0')}`,
    title: title || '当前专题',
  }
})
const stageStatus = computed(() => footprint.value?.status_label || '未开始')
const orderedChapters = computed(() => [...(course.value?.chapters || [])].sort((left, right) => (
  left.sort_order - right.sort_order || left.id - right.id
)))
const currentChapterIndex = computed(() => orderedChapters.value.findIndex((item) => item.id === chapterId.value))
const previousChapter = computed(() => currentChapterIndex.value > 0 ? orderedChapters.value[currentChapterIndex.value - 1] : null)
const nextChapter = computed(() => {
  const index = currentChapterIndex.value
  return index >= 0 && index < orderedChapters.value.length - 1 ? orderedChapters.value[index + 1] : null
})
const previousDestination = computed(() => {
  if (stage.value === 'review') return { chapterId: chapterId.value, stage: 'preview' as LearningStage, label: '← 返回上一阶段' }
  if (stage.value === 'exam') return { chapterId: chapterId.value, stage: 'review' as LearningStage, label: '← 返回上一阶段' }
  if (previousChapter.value) return { chapterId: previousChapter.value.id, stage: 'exam' as LearningStage, label: '← 返回上一章节' }
  return null
})
const nextDestination = computed(() => {
  if (stage.value === 'preview') return { chapterId: chapterId.value, stage: 'review' as LearningStage, label: '进入下一阶段 →' }
  if (stage.value === 'review') return { chapterId: chapterId.value, stage: 'exam' as LearningStage, label: '进入下一阶段 →' }
  if (nextChapter.value) return { chapterId: nextChapter.value.id, stage: 'preview' as LearningStage, label: '进入下一章节 →' }
  return null
})
const navigationHint = computed(() => {
  if (stage.value === 'exam') return nextChapter.value ? `下一章节：${nextChapter.value.title}` : '当前已是本课程最后一章'
  return `下一阶段：${configs[config.value.next!].title}`
})

async function recordEvent(event_type: Parameters<typeof learningApi.recordEvent>[0]['event_type'], event_data: Record<string, unknown> = {}) {
  if (!course.value || !chapter.value) return
  try {
    footprint.value = (await learningApi.recordActivity({ course_id: courseId.value, chapter_id: chapterId.value, learning_stage: stage.value, event_type, event_data })).data.data
  } catch { /* 行为统计失败不阻塞学习内容 */ }
  }

async function loadFootprint() {
  footprint.value = (await learningApi.footprint(courseId.value, chapterId.value, stage.value)).data.data
}

function trackReading(event?: Event) {
  const eventTarget = event?.currentTarget
  const element = eventTarget instanceof HTMLElement ? eventTarget : annotationReader.value?.getElement()
  if (!element) return
  const hasInternalScroll = element.scrollHeight > element.clientHeight + 1
  let percent: number
  if (hasInternalScroll) {
    percent = Math.min(100, Math.round(((element.scrollTop + element.clientHeight) / element.scrollHeight) * 100))
  } else {
    const rect = element.getBoundingClientRect()
    const visible = Math.min(window.innerHeight, Math.max(0, window.innerHeight - Math.max(0, rect.top)))
    const total = Math.max(element.offsetHeight, window.innerHeight)
    percent = Math.min(100, Math.round(((Math.max(0, -rect.top) + visible) / total) * 100))
  }
  if (percent >= lastReadingPercent + 10 || (percent >= 80 && lastReadingPercent < 80)) {
    lastReadingPercent = percent
    void recordEvent('reading_progress', { percent })
  }
}

async function load() {
  loading.value = true
  try {
    course.value = (await courseApi.detail(courseId.value)).data.data
    chapter.value = course.value.chapters.find((item) => item.id === chapterId.value) || null
    if (!chapter.value) return router.replace(`/courses/${courseId.value}`)
    savedNote.value = (await studyApi.note(chapterId.value)).data.data
    noteEditing.value = false
    noteDraft.value = sanitizeNoteHtml(savedNote.value?.content || '')
    lastReadingPercent = 0
    await recordEvent('chapter_opened')
    await loadFootprint()
  } finally { loading.value = false }
}
function goToDestination(destination: { chapterId: number; stage: LearningStage }) {
  router.push(`/courses/${courseId.value}/chapters/${destination.chapterId}/${destination.stage}`)
}
function finishPracticeAndContinue() {
  practiceDialogVisible.value = false
  if (nextDestination.value) goToDestination(nextDestination.value)
}
function goToStageDirect(target: LearningStage) {
  router.push(`/courses/${courseId.value}/chapters/${chapterId.value}/${target}`)
}
function askGuideAi(action: GuideAiAction) {
  if (!course.value || !chapter.value) return
  requestWorkspaceAi({
    courseId: courseId.value,
    chapterId: chapterId.value,
    learningStage: stage.value,
    taskType: action.taskType,
    prompt: action.prompt,
  })
  ElMessage.success(`已将“${action.label}”填入 AI 工作台`)
}
function openNoteWorkspace() {
  void router.push({ path: '/notes', query: { chapter_id: String(chapterId.value) } })
}
function startNoteEditing() {
  noteDraft.value = sanitizeNoteHtml(savedNote.value?.content || '<p><br></p>')
  noteEditing.value = true
}
function cancelNoteEditing() {
  noteDraft.value = sanitizeNoteHtml(savedNote.value?.content || '')
  noteEditing.value = false
}
async function saveChapterNote() {
  if (!chapter.value || noteSaving.value) return
  noteSaving.value = true
  try {
    const content = sanitizeNoteHtml(noteDraft.value || '<p><br></p>')
    savedNote.value = (await studyApi.saveNote(chapterId.value, content)).data.data
    noteDraft.value = sanitizeNoteHtml(savedNote.value.content)
    noteEditing.value = false
    ElMessage.success('章节笔记已保存')
    void loadFootprint()
  } catch {
    ElMessage.error('章节笔记保存失败，请稍后重试')
  } finally {
    noteSaving.value = false
  }
}
async function beginPractice() {
  practiceDialogVisible.value = true
  practiceLoading.value = true
  practiceQuestions.value = []
  practiceIndex.value = 0
  practiceAnswer.value = ''
  practiceResult.value = null
  practiceFinished.value = false
  practiceSubmissions.value = []
  practiceReferences.value = []
  practiceReferenceLoading.value = false
  practiceReferenceError.value = ''
  practiceSavingToNotes.value = false
  practiceSavedToNotes.value = false
  try {
    const latest = (await studyApi.latestReviewResult(chapterId.value)).data.data
    if (latest.length) {
      practiceQuestions.value = latest.map((item) => ({ id: item.practice_id, question: item.question, source_position: item.source_position }))
      practiceSubmissions.value = latest.map((item, index) => ({
        question: { id: item.practice_id, question: item.question, source_position: item.source_position },
        answer: item.student_answer || '历史记录未保存学生作答原文',
        result: {
          id: item.practice_id,
          is_correct: item.is_correct,
          feedback: item.feedback,
          reference_answer: item.ai_reference_answer,
          source_position: item.source_position,
          ai_reference_answer: item.ai_reference_answer,
          reference_knowledge_points: item.reference_knowledge_points,
          completed: index === latest.length - 1,
          next_interval_days: null,
        },
      }))
      practiceReferences.value = latest.map((item) => ({ practice_id: item.practice_id, ai_reference_answer: item.ai_reference_answer, reference_knowledge_points: item.reference_knowledge_points }))
      practiceFinished.value = true
      if (latest.some((item) => !item.reference_generated)) void loadPracticeReferences()
    } else {
      practiceQuestions.value = (await studyApi.reviewQuestions(chapterId.value)).data.data
    }
  } finally { practiceLoading.value = false }
}
async function submitPracticeAnswer() {
  const question = practiceQuestions.value[practiceIndex.value]
  if (!question || !practiceAnswer.value.trim()) return ElMessage.warning('请先完成本题作答')
  const submittedAnswer = practiceAnswer.value.trim()
  practiceLoading.value = true
  try {
    const result = (await studyApi.submitReviewAnswer(question.id, submittedAnswer)).data.data
    practiceResult.value = result
    practiceSubmissions.value.push({ question, answer: submittedAnswer, result })
    const isLastQuestion = result.completed || practiceIndex.value >= practiceQuestions.value.length - 1
    if (isLastQuestion) {
      practiceFinished.value = true
      void loadFootprint()
      void loadPracticeReferences()
      ElMessage.success('本轮练习已完成，请查看参考答案和知识点')
    } else {
      practiceIndex.value += 1
      practiceAnswer.value = ''
      practiceResult.value = null
      ElMessage.success(`第 ${practiceIndex.value} 题已提交，已进入下一题`)
    }
  } finally { practiceLoading.value = false }
}
async function loadPracticeReferences(force = false) {
  if (!practiceSubmissions.value.length || practiceReferenceLoading.value) return
  practiceReferenceLoading.value = true
  practiceReferenceError.value = ''
  try {
    practiceReferences.value = (await studyApi.reviewReferences(
      chapterId.value,
      practiceSubmissions.value.map((item) => item.question.id),
      force,
    )).data.data
    if (practiceSavedToNotes.value) await savePracticeToNotes(true)
  } catch {
    practiceReferenceError.value = 'AI 参考答案暂时未能生成，可以重新尝试。'
  } finally { practiceReferenceLoading.value = false }
}
async function savePracticeToNotes(silent = false) {
  if (!practiceSubmissions.value.length || practiceSavingToNotes.value) return
  practiceSavingToNotes.value = true
  try {
    await studyApi.saveReviewToNotes(chapterId.value, practiceSubmissions.value.map((item) => item.question.id))
    practiceSavedToNotes.value = true
    if (!silent) ElMessage.success('答题记录已保存到笔记空间')
  } finally { practiceSavingToNotes.value = false }
}
onMounted(load)
watch(() => [courseId.value, chapterId.value, stage.value], load)
onMounted(() => window.addEventListener('scroll', trackReading, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', trackReading))
</script>

<template>
  <div v-loading="loading" class="learning-stage-page">
    <el-button link @click="router.push(`/courses/${courseId}`)">← 返回课程详情</el-button>
    <header class="learning-hero" :class="`learning-hero-${stage}`" :style="{ backgroundImage: `url(${learningHeroBackground})` }">
      <div class="learning-hero-logo-wrap">
        <img class="learning-hero-logo" :src="logoUrl" alt="思政红芯" />
      </div>
      <div class="learning-hero-copy">
        <p class="learning-hero-textbook">{{ course?.name || '习近平新时代中国特色社会主义思想概论' }}</p>
        <p class="learning-hero-topic"><span>{{ chapterHeading.label }}</span><span aria-hidden="true">—</span>{{ chapterHeading.title }}</p>
        <div class="learning-hero-meta"><span class="learning-hero-stage">{{ config.title }}</span><span>{{ config.subtitle }}</span></div>
      </div>
    </header>
    <nav class="stage-switcher" aria-label="学习阶段">
      <button v-for="item in (['preview', 'review', 'exam'] as LearningStage[])" :key="item" :class="{ active: stage === item }" @click="goToStageDirect(item)">{{ configs[item].title }}</button>
    </nav>
    <section v-if="stage === 'review'" class="review-goal-grid"><div v-for="(goal, index) in config.goals" :key="goal" class="preview-goal-item"><span class="preview-goal-index">0{{ index + 1 }}</span><div class="preview-goal-copy"><strong>{{ goal }}</strong><small>{{ reviewGuideActions[index].description }}</small></div><button type="button" class="preview-goal-ai" :aria-label="`向 AI ${reviewGuideActions[index].label}`" @click="askGuideAi(reviewGuideActions[index])"><el-icon><MagicStick /></el-icon><span>问 AI</span></button></div></section>

    <section v-if="stage === 'preview'" class="stage-workspace preview-workspace">
      <el-card shadow="never" class="workspace-card textbook-card preview-textbook-card"><TextbookAnnotationReader v-if="contentBlocks.length" ref="annotationReader" :course-id="courseId" :chapter-id="chapterId" :learning-stage="stage" :blocks="contentBlocks" reader-title="教材原文" reader-hint="选中文字即可添加标注" reader-label="教材原文预读滚动区" @scroll="trackReading" /><el-empty v-else description="当前专题没有教材正文" /></el-card>
      <aside class="preview-side" aria-label="专题导览与活动记录">
        <el-card shadow="never" class="workspace-card preview-guide-card">
          <template #header><div class="content-heading"><span>专题导览</span><el-tag>课前先读</el-tag></div></template>
          <div class="preview-goal-list"><div v-for="(goal, index) in config.goals" :key="goal" class="preview-goal-item"><span class="preview-goal-index">0{{ index + 1 }}</span><div class="preview-goal-copy"><strong>{{ goal }}</strong><small>{{ previewGuideActions[index].description }}</small></div><button type="button" class="preview-goal-ai" :aria-label="`向 AI ${previewGuideActions[index].label}`" @click="askGuideAi(previewGuideActions[index])"><el-icon><MagicStick /></el-icon><span>问 AI</span></button></div></div>
        </el-card>
        <el-card shadow="never" class="workspace-card preview-activity-card">
          <template #header><div class="content-heading"><span>活动记录</span><span class="muted">自动记录</span></div></template>
          <div class="preview-activity-status"><strong>{{ stageStatus }}</strong><span>本阶段学习状态</span></div>
          <div v-if="footprint?.activities.length" class="preview-activity-list"><div v-for="activity in footprint.activities.slice(0, 4)" :key="`${activity.event_type}-${activity.created_time}`"><span class="preview-activity-dot"></span><span>{{ activity.label }}</span></div></div>
          <p v-else class="preview-activity-empty">开始阅读教材后，最近活动会显示在这里。</p>
          <p class="preview-activity-next">下一步：{{ footprint?.next_action || '先打开专题内容开始学习' }}</p>
        </el-card>
      </aside>
    </section>

    <section v-else-if="stage === 'review'" class="stage-workspace preview-workspace review-workspace">
      <el-card shadow="never" class="workspace-card textbook-card preview-textbook-card review-textbook-card"><TextbookAnnotationReader v-if="contentBlocks.length" ref="annotationReader" :course-id="courseId" :chapter-id="chapterId" :learning-stage="stage" :blocks="contentBlocks" reader-title="教材重点回看" reader-hint="选中文字即可添加标注" reader-label="教材重点回看滚动区" @scroll="trackReading" /><el-empty v-else description="当前专题没有教材正文" /></el-card>
      <aside class="preview-side review-side" aria-label="章节笔记">
        <el-card shadow="never" class="workspace-card note-workspace review-note-card">
        <template #header>
          <div class="content-heading note-card-heading">
            <div><span>我的章节笔记</span><el-tag type="info">仅本人可见</el-tag></div>
            <el-button v-if="!noteEditing" text type="primary" @click="startNoteEditing">编辑本章笔记</el-button>
          </div>
        </template>
        <p class="note-guide">巩固阶段可以直接整理笔记；保存后会同步到笔记空间，并加入间隔复习计划。</p>
        <template v-if="noteEditing">
          <NoteRichEditor v-model="noteDraft" class="learning-note-editor" />
          <div class="learning-note-edit-actions">
            <span>{{ notePlainText(noteDraft).replace(/\s/g, '').length }} 字 · 编辑完成后保存</span>
            <div><el-button @click="cancelNoteEditing">取消</el-button><el-button type="primary" :loading="noteSaving" @click="saveChapterNote">保存笔记</el-button></div>
          </div>
        </template>
        <template v-else>
          <article v-if="savedNoteText" class="learning-note-preview rich-note-content" v-html="savedNoteHtml"></article>
          <el-empty v-else :image-size="64" description="本章还没有保存笔记" />
          <div class="learning-note-actions">
            <el-button plain @click="openNoteWorkspace">进入笔记空间</el-button>
            <el-button type="primary" @click="startNoteEditing">编辑本章笔记</el-button>
          </div>
        </template>
        </el-card>
      </aside>
    </section>

    <section v-else class="stage-workspace preview-workspace exam-workspace">
      <el-card shadow="never" class="workspace-card textbook-card preview-textbook-card"><TextbookAnnotationReader v-if="contentBlocks.length" ref="annotationReader" :course-id="courseId" :chapter-id="chapterId" :learning-stage="stage" :blocks="contentBlocks" reader-title="教材原文" reader-hint="选中文字即可添加标注" reader-label="教材原文冲刺滚动区" @scroll="trackReading" /><el-empty v-else description="当前专题没有教材正文" /></el-card>
      <aside class="preview-side exam-side" aria-label="冲刺训练框架与活动记录">
        <el-card shadow="never" class="workspace-card preview-guide-card exam-framework-card">
          <template #header><div class="content-heading"><span>冲刺训练框架</span><el-tag type="danger">输出与检测</el-tag></div></template>
          <div class="preview-goal-list">
            <div v-for="(action, index) in examGuideActions" :key="action.label" class="preview-goal-item exam-goal-item">
              <span class="preview-goal-index">0{{ index + 1 }}</span>
              <div class="preview-goal-copy"><strong>{{ action.label }}</strong><small>{{ action.description }}</small></div>
              <button type="button" class="preview-goal-ai" :aria-label="`向 AI ${action.label}`" @click="askGuideAi(action)"><el-icon><MagicStick /></el-icon><span>问 AI</span></button>
            </div>
          </div>
          <el-button class="exam-launch-button" type="primary" @click="beginPractice">开始本章练习</el-button>
        </el-card>
        <el-card shadow="never" class="workspace-card preview-activity-card">
          <template #header><div class="content-heading"><span>活动记录</span><span class="muted">自动记录</span></div></template>
          <div class="preview-activity-status"><strong>{{ stageStatus }}</strong><span>本阶段学习状态</span></div>
          <div v-if="footprint?.activities.length" class="preview-activity-list"><div v-for="activity in footprint.activities.slice(0, 4)" :key="`${activity.event_type}-${activity.created_time}`"><span class="preview-activity-dot"></span><span>{{ activity.label }}</span></div></div>
          <p v-else class="preview-activity-empty">开始阅读教材或练习后，最近活动会显示在这里。</p>
          <p class="preview-activity-next">下一步：{{ footprint?.next_action || '先回顾核心原文，再开始本章练习' }}</p>
        </el-card>
      </aside>
    </section>

    <section v-if="stage === 'review'" class="stage-footprint-panel"><div><p class="eyebrow">本阶段学习足迹</p><h2>{{ footprint?.status_label || '未开始' }}</h2><p>{{ config.aiHint }}</p></div><div class="footprint-content"><div v-if="footprint?.outputs.length" class="footprint-outputs"><strong>已有产出</strong><span v-for="output in footprint.outputs" :key="output">{{ output }}</span></div><div v-if="footprint?.activities.length" class="footprint-activities"><strong>最近活动</strong><span v-for="activity in footprint.activities.slice(0, 4)" :key="`${activity.event_type}-${activity.created_time}`">{{ activity.label }}</span></div><p class="footprint-next">下一步：{{ footprint?.next_action || '先打开专题内容开始学习' }}</p></div></section>
    <footer class="learning-footer">
      <div class="learning-footer-copy"><span>系统会记录学习足迹，用于生成更合适的下一步建议。</span><small>{{ navigationHint }}</small></div>
      <div class="learning-footer-actions">
        <el-button v-if="previousDestination" @click="goToDestination(previousDestination)">{{ previousDestination.label }}</el-button>
        <el-button v-if="nextDestination" type="primary" @click="goToDestination(nextDestination)">{{ nextDestination.label }}</el-button>
        <el-button v-else-if="stage === 'exam'" type="primary" plain @click="router.push(`/courses/${courseId}`)">返回课程详情</el-button>
      </div>
    </footer>
    <el-dialog v-model="practiceDialogVisible" width="720px" :close-on-click-modal="false" destroy-on-close title="本章练习">
      <div v-loading="practiceLoading" class="review-quiz">
        <template v-if="practiceFinished">
          <section class="practice-summary">
            <div class="practice-summary-heading"><el-tag type="success">本轮练习已完成</el-tag><h3>练习结果与参考答案</h3><p>以下内容用于对照教材要点，请结合自己的答案检查遗漏之处。</p></div>
            <el-alert v-if="practiceReferenceLoading" title="AI 正在按题目分别生成参考答案和知识点；此时也可以先保存教材依据。" type="info" :closable="false" show-icon />
            <el-alert v-else-if="practiceReferenceError" :title="practiceReferenceError" type="warning" :closable="false" show-icon><el-button size="small" type="warning" plain @click="loadPracticeReferences(true)">重新生成</el-button></el-alert>
            <div v-else class="practice-reference-actions"><el-button size="small" plain @click="loadPracticeReferences(true)">重新生成AI答案</el-button></div>
            <article v-for="(submission, index) in practiceSubmissions" :key="submission.question.id" class="practice-summary-item">
              <span class="quiz-progress">第 {{ index + 1 }} 题</span>
              <h3>{{ submission.question.question }}</h3>
              <div class="practice-answer-block student"><strong>我的作答</strong><p>{{ submission.answer }}</p></div>
              <div class="practice-answer-block reference"><strong>AI 参考答案</strong><p v-if="practiceReferenceLoading" class="practice-reference-pending">正在根据本题生成参考答案，生成完成前不展示临时内容……</p><p v-else>{{ practiceReferences.find((item) => item.practice_id === submission.question.id)?.ai_reference_answer || submission.result.ai_reference_answer || submission.result.reference_answer || '暂未生成参考答案' }}</p></div>
              <div class="practice-answer-block"><strong>参考知识点</strong><p v-if="practiceReferenceLoading" class="practice-reference-pending">将在参考答案生成完成后显示。</p><template v-else><ul class="practice-knowledge-points"><li v-for="point in (practiceReferences.find((item) => item.practice_id === submission.question.id)?.reference_knowledge_points || submission.result.reference_knowledge_points)" :key="point">{{ point }}</li></ul><p v-if="!(practiceReferences.find((item) => item.practice_id === submission.question.id)?.reference_knowledge_points || submission.result.reference_knowledge_points).length">请结合教材依据检查章节主旨、核心概念和观点逻辑。</p></template></div>
            </article>
            <footer><el-button :loading="practiceSavingToNotes" :disabled="practiceSavingToNotes" @click="savePracticeToNotes()">{{ practiceSavedToNotes ? '更新笔记记录' : '保存到笔记空间' }}</el-button><el-button v-if="practiceSavedToNotes" @click="router.push('/notes')">查看笔记</el-button><el-button v-if="nextChapter" type="primary" @click="finishPracticeAndContinue">进入下一章节</el-button><el-button v-else type="primary" @click="practiceDialogVisible = false">完成并关闭</el-button></footer>
          </section>
        </template>
        <template v-else-if="practiceQuestions.length">
          <span class="quiz-progress">第 {{ practiceIndex + 1 }} / {{ practiceQuestions.length }} 题 · {{ practiceQuestions[practiceIndex].source_position }}</span>
          <h3>{{ practiceQuestions[practiceIndex].question }}</h3>
          <el-input v-model="practiceAnswer" type="textarea" :rows="7" maxlength="3000" show-word-limit placeholder="请结合教材中的核心概念、主要观点和逻辑关系作答。" />
          <p class="practice-auto-hint">提交成功后将自动进入下一题，完成最后一题后统一展示参考答案。</p>
          <footer><el-button type="primary" @click="submitPracticeAnswer">提交作答</el-button></footer>
        </template>
        <el-empty v-else-if="!practiceLoading" description="暂时没有生成练习题" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.learning-stage-page {
  display: grid;
  gap: 18px;
}

.learning-stage-page > .el-button {
  justify-self: start;
  height: 20px;
  margin-bottom: -8px;
  color: #7b6f73;
  font-size: 12px;
}

.learning-hero {
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

.learning-hero::before {
  display: none;
}

.learning-hero-logo-wrap,
.learning-hero-copy,
.stage-progress {
  position: relative;
  z-index: 1;
}

.learning-hero-logo-wrap {
  display: grid;
  place-items: center;
  align-self: stretch;
}

.learning-hero-logo {
  display: block;
  width: 86px;
  height: 98px;
  object-fit: contain;
}

.learning-hero-copy {
  min-width: 0;
}

.learning-hero-textbook {
  margin: 0;
  color: #ed2028;
  font-size: clamp(22px, 2.2vw, 36px);
  font-weight: 760;
  letter-spacing: .01em;
  line-height: 1.2;
}

.learning-hero-topic {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  margin: 8px 0 0;
  color: #201b1d;
  font-size: clamp(16px, 1.5vw, 22px);
  font-weight: 600;
  line-height: 1.45;
}

.learning-hero-topic span:first-child {
  font-weight: 760;
}

.learning-hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 9px;
  margin-top: 10px;
  color: #725d61;
  font-size: 13px;
  line-height: 1.5;
}

.learning-hero-stage {
  padding: 4px 10px;
  color: #b52329;
  background: rgba(255, 238, 233, .86);
  border: 1px solid rgba(224, 91, 85, .28);
  border-radius: 999px;
  font-weight: 700;
}

.stage-progress {
  min-width: 146px;
  padding: 14px 17px;
  background: rgba(255, 250, 247, .74);
  border: 1px solid rgba(207, 85, 78, .24);
  border-radius: 13px;
  box-shadow: 0 4px 12px rgba(115, 48, 50, .08);
  text-align: center;
}

.stage-progress strong {
  color: #a6252b;
  font-size: 20px;
  line-height: 1.15;
}

.stage-progress span {
  display: block;
  margin-top: 8px;
  color: #856c70;
  font-size: 13px;
}

.stage-switcher {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 4px;
  background: #fff;
  border: 1px solid #dedede;
  border-radius: 14px;
  box-shadow: 0 4px 10px rgba(39, 39, 39, .14);
}

.stage-switcher button {
  min-height: 42px;
  padding: 6px 12px;
  color: #2f2b2d;
  background: transparent;
  border: 0;
  border-radius: 10px;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
  font-weight: 700;
  transition: background .18s ease, color .18s ease, transform .18s ease;
}

.stage-switcher button:hover {
  color: #e23c3d;
  background: #fff2f2;
}

.stage-switcher button.active {
  color: #fff;
  background: #ff252f;
  box-shadow: 0 7px 14px rgba(255, 37, 47, .2);
  transform: translateY(-1px);
}

.stage-goal-grid {
  margin-top: -2px;
}

.review-goal-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: -2px;
  margin-bottom: 18px;
}

.review-goal-grid .preview-goal-item {
  min-width: 0;
  min-height: 68px;
}

.preview-workspace {
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, .9fr);
  gap: 20px;
}

.preview-textbook-card,
.preview-guide-card,
.preview-activity-card {
  min-width: 0;
}

.preview-textbook-card .textbook-scroll-window {
  max-height: min(68vh, 680px);
}

.review-textbook-card .textbook-scroll-window {
  max-height: min(68vh, 680px);
}

.preview-side {
  display: grid;
  align-content: start;
  gap: 16px;
  min-width: 0;
}

.review-side {
  gap: 16px;
}

.review-note-card :deep(.el-card__header) {
  padding: 14px 16px;
}

.review-note-card :deep(.el-card__body) {
  padding: 16px;
}

.review-note-card .note-guide {
  margin-top: 0;
  padding: 12px 13px;
  color: #806f74;
  background: #fff7f5;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.7;
}

.review-note-card .learning-note-preview {
  margin: 14px 0;
  padding: 15px;
  background: #fffaf8;
  border: 1px solid #f3e5e1;
  border-radius: 10px;
}

.preview-guide-card :deep(.el-card__header),
.preview-activity-card :deep(.el-card__header) {
  padding: 14px 16px;
}

.preview-guide-card :deep(.el-card__body),
.preview-activity-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.preview-goal-list {
  display: grid;
  gap: 10px;
}

.preview-goal-item {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 68px;
  padding: 9px 10px 9px 12px;
  background: #fff0f0;
  border-left: 4px solid #ff2535;
  border-radius: 9px;
}

.preview-goal-index {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: #ff2535;
  background: #fff;
  border-radius: 7px;
  font-size: 17px;
  font-weight: 760;
}

.preview-goal-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.preview-goal-copy strong {
  overflow: hidden;
  color: #61517e;
  font-size: 15px;
  line-height: 1.45;
}

.preview-goal-copy small {
  overflow: hidden;
  color: #a08fa9;
  font-size: 11px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-goal-ai {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 34px;
  padding: 0 12px;
  color: #c84e68;
  background: rgba(255, 247, 247, .72);
  border: 1px solid rgba(216, 111, 132, .3);
  border-radius: 999px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .72);
  transition: color .16s ease, background .16s ease, border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}

.preview-goal-ai:hover {
  color: #fff;
  background: #e56a7d;
  border-color: #e56a7d;
  box-shadow: 0 5px 12px rgba(210, 79, 105, .2);
  transform: translateY(-1px);
}

.preview-goal-ai:focus-visible {
  outline: 2px solid #dc6d83;
  outline-offset: 2px;
}

.preview-goal-ai .el-icon {
  color: #e2788e;
  font-size: 14px;
  transition: color .16s ease, transform .16s ease;
}

.preview-goal-ai:hover .el-icon {
  color: #fff;
  transform: rotate(-8deg);
}

.preview-activity-status {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f0e5e5;
}

.preview-activity-status strong {
  color: #b52329;
  font-size: 17px;
}

.preview-activity-status span,
.preview-activity-empty {
  color: #89777a;
  font-size: 12px;
}

.preview-activity-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.preview-activity-list > div {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #5f5559;
  font-size: 13px;
  line-height: 1.4;
}

.preview-activity-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  background: #ff8589;
  border-radius: 50%;
}

.preview-activity-empty {
  margin: 12px 0;
  line-height: 1.6;
}

.preview-activity-next {
  margin: 12px 0 0;
  padding-top: 10px;
  color: #7b6468;
  border-top: 1px solid #f0e5e5;
  font-size: 12px;
  line-height: 1.6;
}

.exam-framework-card :deep(.el-card__header) {
  padding-bottom: 13px;
}

.exam-goal-item {
  grid-template-columns: 40px minmax(0, 1fr) auto;
}

.exam-launch-button {
  width: 100%;
  min-height: 54px;
  margin-top: 14px;
  border: 0;
  border-radius: 13px;
  box-shadow: 0 9px 17px rgba(224, 64, 75, .18);
  font-size: 14px;
  font-weight: 700;
}

@media (max-width: 767px) {
  .review-goal-grid { grid-template-columns: 1fr; }

  .learning-hero {
    grid-template-columns: 70px minmax(0, 1fr);
    gap: 22px;
    padding: 22px 20px;
  }

  .learning-hero-logo { width: 66px; height: 80px; }
  .learning-hero-textbook { font-size: 24px; white-space: normal; }
  .learning-hero-topic { font-size: 16px; }
  .learning-hero-meta { margin-top: 10px; }
  .stage-switcher button { min-height: 44px; padding: 7px 8px; font-size: 14px; }
}
</style>

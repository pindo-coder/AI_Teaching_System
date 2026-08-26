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

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const stage = computed(() => route.params.stage as LearningStage)
const course = ref<CourseDetail | null>(null)
const chapter = ref<Chapter | null>(null)
const loading = ref(true)
const savedNote = ref<StudyNote | null>(null)
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
const readingContainer = ref<HTMLElement | null>(null)
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

function trackReading() {
  const element = readingContainer.value
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
function openNoteWorkspace() {
  void router.push({ path: '/notes', query: { chapter_id: String(chapterId.value) } })
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
    <nav class="stage-switcher" aria-label="学习阶段">
      <button v-for="item in (['preview', 'review', 'exam'] as LearningStage[])" :key="item" :class="{ active: stage === item }" @click="goToStageDirect(item)">{{ configs[item].title }}</button>
    </nav>
    <header class="learning-hero" :class="`learning-hero-${stage}`">
      <div><p class="eyebrow">{{ course?.name }} · {{ chapter?.title }}</p><h1>{{ config.title }}</h1><p>{{ config.subtitle }}</p></div>
      <div class="stage-progress"><strong>{{ stageStatus }}</strong><span>本阶段学习状态</span></div>
    </header>
    <section class="stage-goal-grid"><div v-for="(goal, index) in config.goals" :key="goal" class="stage-goal-card"><span>0{{ index + 1 }}</span><p>{{ goal }}</p></div></section>

    <section v-if="stage === 'preview'" class="stage-workspace">
      <el-card shadow="never" class="workspace-card"><template #header><div class="content-heading"><span>专题导览</span><el-tag>课前先读</el-tag></div></template><div class="guide-grid"><div><strong>本专题</strong><p>{{ chapter?.title }}</p></div><div><strong>阅读方法</strong><p>先找章节主旨，再标记核心概念和重要论述。</p></div><div><strong>预习产出</strong><p>形成至少 3 个问题，带着问题进入课堂。</p></div></div></el-card>
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>教材原文预读</span><span class="muted">完整正文可滚动查看 · 阅读记录会用于生成学习建议</span></div></template><article ref="readingContainer" v-if="contentBlocks.length" class="chapter-text textbook-document textbook-scroll-window" tabindex="0" aria-label="教材原文预读滚动区" @scroll.passive="trackReading"><p v-for="(block, index) in contentBlocks" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
    </section>

    <section v-else-if="stage === 'review'" class="stage-workspace">
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>教材重点回看</span><span class="muted">阅读记录会用于生成学习建议</span></div></template><article ref="readingContainer" v-if="contentBlocks.length" class="chapter-text textbook-document textbook-scroll-window" tabindex="0" aria-label="教材重点回看滚动区" @scroll.passive="trackReading"><p v-for="(block, index) in contentBlocks" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
      <el-card shadow="never" class="workspace-card note-workspace"><template #header><div class="content-heading"><span>我的章节笔记</span><el-tag type="info">仅本人可见</el-tag></div></template><p class="note-guide">笔记统一在笔记空间编辑，保存后会自动同步到这里并加入间隔复习计划。</p><article v-if="savedNoteText" class="learning-note-preview rich-note-content" v-html="savedNoteHtml"></article><el-empty v-else :image-size="64" description="本章还没有保存笔记" /><div class="learning-note-actions"><el-button type="primary" @click="openNoteWorkspace">进入笔记空间编辑</el-button></div></el-card>
    </section>

    <section v-else class="stage-workspace exam-workspace">
      <el-card shadow="never" class="workspace-card"><template #header><div class="content-heading"><span>冲刺训练框架</span><el-tag type="danger">输出与检测</el-tag></div></template><div class="exam-task-grid"><div><strong>考点提炼</strong><p>识别章节主旨、核心概念和重要论述。</p></div><div><strong>答题训练</strong><p>按照“概念—观点—依据—意义”组织答案。</p></div><div><strong>薄弱点检查</strong><p>通过错题定位未掌握的知识点。</p></div></div><el-button class="practice-launch-button" type="primary" @click="beginPractice">开始本章练习</el-button></el-card>
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>核心原文速览</span><span class="muted">完整正文可滚动查看 · 阅读记录会用于生成学习建议</span></div></template><article ref="readingContainer" v-if="contentBlocks.length" class="chapter-text textbook-document textbook-scroll-window" tabindex="0" aria-label="核心原文速览滚动区" @scroll.passive="trackReading"><p v-for="(block, index) in contentBlocks" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
    </section>

    <section class="stage-footprint-panel"><div><p class="eyebrow">本阶段学习足迹</p><h2>{{ footprint?.status_label || '未开始' }}</h2><p>{{ config.aiHint }}</p></div><div class="footprint-content"><div v-if="footprint?.outputs.length" class="footprint-outputs"><strong>已有产出</strong><span v-for="output in footprint.outputs" :key="output">{{ output }}</span></div><div v-if="footprint?.activities.length" class="footprint-activities"><strong>最近活动</strong><span v-for="activity in footprint.activities.slice(0, 4)" :key="`${activity.event_type}-${activity.created_time}`">{{ activity.label }}</span></div><p class="footprint-next">下一步：{{ footprint?.next_action || '先打开专题内容开始学习' }}</p></div></section>
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

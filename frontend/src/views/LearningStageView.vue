<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { courseApi } from '@/api/courses'
import { learningApi } from '@/api/learning'
import type { Chapter, CourseDetail, LearningStage, TaskProgressSummary } from '@/types'
import { formatTextbookParagraphs } from '@/utils/textbookText'
import { studyApi } from '@/api/study'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const stage = computed(() => route.params.stage as LearningStage)
const course = ref<CourseDetail | null>(null)
const chapter = ref<Chapter | null>(null)
const loading = ref(true)
const selfNote = ref('')
const noteSaving = ref(false)
const taskSummary = ref<TaskProgressSummary | null>(null)
const readingContainer = ref<HTMLElement | null>(null)
let lastReadingPercent = 0
const contentBlocks = computed(() => formatTextbookParagraphs(chapter.value?.content))
const contentPreview = computed(() => contentBlocks.value.slice(0, 3))

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
    aiHint: '使用右下角 AI 预习助手生成导读、概念解释和预习问题。',
  },
  review: {
    title: '课后巩固', subtitle: '梳理观点和逻辑，把课堂内容转化为知识结构', next: 'exam',
    goals: ['概括本专题核心观点', '理解概念之间的联系与区别', '形成自己的章节总结'],
    tasks: ['回看教材重点', '完成个人学习总结', '使用 AI 生成复习提纲'],
    aiHint: '使用右下角 AI 巩固助手生成结构化总结、概念辨析和复习提纲。',
  },
  exam: {
    title: '考前冲刺', subtitle: '从理解转向输出，集中训练考点和答题能力', next: null,
    goals: ['提炼必须掌握的核心考点', '熟悉简答和材料分析的答题结构', '通过模拟练习发现薄弱点'],
    tasks: ['快速回顾核心原文', '使用 AI 梳理重点考点', '完成一组模拟练习'],
    aiHint: '使用右下角 AI 冲刺助手生成模拟题、参考答案和答题要点。',
  },
}
const config = computed(() => configs[stage.value])
const stageProgress = computed(() => taskSummary.value?.progress || 0)

async function recordEvent(event_type: Parameters<typeof learningApi.recordEvent>[0]['event_type'], event_data: Record<string, unknown> = {}) {
  if (!course.value || !chapter.value) return
  try {
    const response = await learningApi.recordEvent({ course_id: courseId.value, chapter_id: chapterId.value, learning_stage: stage.value, event_type, event_data })
    taskSummary.value = response.data.data
  } catch { /* 行为统计失败不阻塞学习内容 */ }
  }

async function loadTaskPoints() {
  taskSummary.value = (await learningApi.taskPoints(courseId.value, chapterId.value, stage.value)).data.data
}

function trackReading() {
  const element = readingContainer.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  const visible = Math.min(window.innerHeight, Math.max(0, window.innerHeight - Math.max(0, rect.top)))
  const total = Math.max(element.offsetHeight, window.innerHeight)
  const percent = Math.min(100, Math.round(((Math.max(0, -rect.top) + visible) / total) * 100))
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
    const savedNote = (await studyApi.note(chapterId.value)).data.data
    if (savedNote) selfNote.value = savedNote.content
    lastReadingPercent = 0
    await recordEvent('chapter_opened')
    await loadTaskPoints()
  } finally { loading.value = false }
}
function goToStage(nextStage: LearningStage) {
  router.push(`/courses/${courseId.value}/chapters/${chapterId.value}/${nextStage}`)
}
function goToStageDirect(target: LearningStage) {
  router.push(`/courses/${courseId.value}/chapters/${chapterId.value}/${target}`)
}
async function saveStudyNote() {
  noteSaving.value = true
  try {
    await studyApi.saveNote(chapterId.value, selfNote.value)
    await recordEvent('note_saved', { content: selfNote.value })
    await studyApi.activateReview(chapterId.value)
    ElMessage.success('学习笔记已保存，并加入间隔复习计划')
  } finally { noteSaving.value = false }
}
onMounted(load)
watch(stage, load)
onMounted(() => window.addEventListener('scroll', trackReading, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', trackReading))
</script>

<template>
  <div v-loading="loading">
    <el-button link @click="router.push(`/courses/${courseId}`)">← 返回课程详情</el-button>
    <nav class="stage-switcher" aria-label="学习阶段">
      <button v-for="item in (['preview', 'review', 'exam'] as LearningStage[])" :key="item" :class="{ active: stage === item }" @click="goToStageDirect(item)">{{ configs[item].title }}</button>
    </nav>
    <header class="learning-hero" :class="`learning-hero-${stage}`">
      <div><p class="eyebrow">{{ course?.name }} · {{ chapter?.title }}</p><h1>{{ config.title }}</h1><p>{{ config.subtitle }}</p></div>
      <div class="stage-progress"><strong>{{ stageProgress }}%</strong><span>任务点进度</span></div>
    </header>
    <section class="stage-goal-grid"><div v-for="(goal, index) in config.goals" :key="goal" class="stage-goal-card"><span>0{{ index + 1 }}</span><p>{{ goal }}</p></div></section>

    <section v-if="stage === 'preview'" class="stage-workspace">
      <el-card shadow="never" class="workspace-card"><template #header><div class="content-heading"><span>专题导览</span><el-tag>课前先读</el-tag></div></template><div class="guide-grid"><div><strong>本专题</strong><p>{{ chapter?.title }}</p></div><div><strong>阅读方法</strong><p>先找章节主旨，再标记核心概念和重要论述。</p></div><div><strong>预习产出</strong><p>形成至少 3 个问题，带着问题进入课堂。</p></div></div></el-card>
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>教材原文预读</span><span class="muted">滚动阅读会自动记录任务点</span></div></template><article ref="readingContainer" v-if="contentPreview.length" class="chapter-text textbook-document preview-text"><p v-for="(block, index) in contentPreview" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
    </section>

    <section v-else-if="stage === 'review'" class="stage-workspace">
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>教材重点回看</span><el-tag type="success">滚动自动记录</el-tag></div></template><article ref="readingContainer" v-if="contentBlocks.length" class="chapter-text textbook-document"><p v-for="(block, index) in contentBlocks" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
      <el-card shadow="never" class="workspace-card note-workspace"><template #header><div class="content-heading"><span>我的章节笔记</span><el-tag type="info">仅本人可见</el-tag></div></template><p class="note-guide">建议按照“章节主旨—核心观点—概念关系—现实意义”四部分整理。保存后会加入间隔复习计划。</p><el-input v-model="selfNote" type="textarea" :rows="8" maxlength="10000" show-word-limit placeholder="请用自己的语言写下本专题笔记……" /><el-button class="note-save-button" type="primary" :loading="noteSaving" @click="saveStudyNote">保存笔记并加入复习</el-button></el-card>
    </section>

    <section v-else class="stage-workspace exam-workspace">
      <el-card shadow="never" class="workspace-card"><template #header><div class="content-heading"><span>冲刺训练框架</span><el-tag type="danger">输出与检测</el-tag></div></template><div class="exam-task-grid"><div><strong>考点提炼</strong><p>识别章节主旨、核心概念和重要论述。</p></div><div><strong>答题训练</strong><p>按照“概念—观点—依据—意义”组织答案。</p></div><div><strong>薄弱点检查</strong><p>通过错题定位未掌握的知识点。</p></div></div></el-card>
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>核心原文速览</span><span class="muted">滚动自动记录</span></div></template><article ref="readingContainer" v-if="contentPreview.length" class="chapter-text textbook-document exam-preview"><p v-for="(block, index) in contentPreview" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
    </section>

    <section class="stage-task-panel"><div><p class="eyebrow">自动任务点 · {{ taskSummary?.completed_count || 0 }}/{{ taskSummary?.total_count || 0 }}</p><h2>学习行为会自动形成进度</h2><p>{{ config.aiHint }}</p></div><div class="auto-task-list"><div v-for="task in taskSummary?.tasks || []" :key="task.id" class="auto-task-item" :class="`task-${task.status}`"><span class="task-dot">{{ task.status === 'completed' ? '✓' : task.status === 'in_progress' ? '◐' : '○' }}</span><div><strong>{{ task.title }}</strong><p>{{ task.evidence_summary || task.description }}</p></div><span class="task-weight">{{ task.weight }}%</span></div></div></section>
    <footer class="learning-footer">
      <span>系统依据阅读、AI 使用、答题和笔记等实际行为自动统计。</span>
      <el-button v-if="config.next" type="primary" @click="goToStage(config.next)">进入下一阶段 →</el-button>
    </footer>
  </div>
</template>

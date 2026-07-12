<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { courseApi } from '@/api/courses'
import { learningApi } from '@/api/learning'
import type { Chapter, CourseDetail, LearningStage } from '@/types'
import { formatTextbookParagraphs } from '@/utils/textbookText'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const stage = computed(() => route.params.stage as LearningStage)
const course = ref<CourseDetail | null>(null)
const chapter = ref<Chapter | null>(null)
const loading = ref(true)
const completedTasks = ref<string[]>([])
const selfNote = ref('')
const contentBlocks = computed(() => formatTextbookParagraphs(chapter.value?.content))
const contentPreview = computed(() => contentBlocks.value.slice(0, 3))

const configs: Record<LearningStage, {
  title: string
  subtitle: string
  progress: number
  next: LearningStage | null
  goals: string[]
  tasks: string[]
  aiHint: string
}> = {
  preview: {
    title: '预习空间', subtitle: '先建立整体认识，再带着问题进入课堂', progress: 30, next: 'review',
    goals: ['了解本专题研究什么问题', '识别需要重点理解的核心概念', '形成自己的课前疑问'],
    tasks: ['阅读专题导览', '通读教材原文', '使用 AI 生成预习问题'],
    aiHint: '使用右下角 AI 预习助手生成导读、概念解释和预习问题。',
  },
  review: {
    title: '课后巩固', subtitle: '梳理观点和逻辑，把课堂内容转化为知识结构', progress: 70, next: 'exam',
    goals: ['概括本专题核心观点', '理解概念之间的联系与区别', '形成自己的章节总结'],
    tasks: ['回看教材重点', '完成个人学习总结', '使用 AI 生成复习提纲'],
    aiHint: '使用右下角 AI 巩固助手生成结构化总结、概念辨析和复习提纲。',
  },
  exam: {
    title: '考前冲刺', subtitle: '从理解转向输出，集中训练考点和答题能力', progress: 100, next: null,
    goals: ['提炼必须掌握的核心考点', '熟悉简答和材料分析的答题结构', '通过模拟练习发现薄弱点'],
    tasks: ['快速回顾核心原文', '使用 AI 梳理重点考点', '完成一组模拟练习'],
    aiHint: '使用右下角 AI 冲刺助手生成模拟题、参考答案和答题要点。',
  },
}
const config = computed(() => configs[stage.value])
const storageKey = computed(() => `learning-workspace:${courseId.value}:${chapterId.value}:${stage.value}`)

function restoreWorkspace() {
  const saved = JSON.parse(localStorage.getItem(storageKey.value) || '{}')
  completedTasks.value = Array.isArray(saved.completedTasks) ? saved.completedTasks : []
  selfNote.value = typeof saved.selfNote === 'string' ? saved.selfNote : ''
}
function saveWorkspace() {
  localStorage.setItem(storageKey.value, JSON.stringify({ completedTasks: completedTasks.value, selfNote: selfNote.value }))
}

async function load() {
  loading.value = true
  try {
    course.value = (await courseApi.detail(courseId.value)).data.data
    chapter.value = course.value.chapters.find((item) => item.id === chapterId.value) || null
    if (!chapter.value) return router.replace(`/courses/${courseId.value}`)
    restoreWorkspace()
    await learningApi.updateProgress({
      course_id: courseId.value,
      chapter_id: chapterId.value,
      learning_stage: stage.value,
      progress: config.value.progress,
    })
  } finally { loading.value = false }
}
function goToStage(nextStage: LearningStage) {
  router.push(`/courses/${courseId.value}/chapters/${chapterId.value}/${nextStage}`)
}
function goToStageDirect(target: LearningStage) {
  router.push(`/courses/${courseId.value}/chapters/${chapterId.value}/${target}`)
}
onMounted(load)
watch(stage, load)
watch([completedTasks, selfNote], saveWorkspace, { deep: true })
</script>

<template>
  <div v-loading="loading">
    <el-button link @click="router.push(`/courses/${courseId}`)">← 返回课程详情</el-button>
    <nav class="stage-switcher" aria-label="学习阶段">
      <button v-for="item in (['preview', 'review', 'exam'] as LearningStage[])" :key="item" :class="{ active: stage === item }" @click="goToStageDirect(item)">{{ configs[item].title }}</button>
    </nav>
    <header class="learning-hero" :class="`learning-hero-${stage}`">
      <div><p class="eyebrow">{{ course?.name }} · {{ chapter?.title }}</p><h1>{{ config.title }}</h1><p>{{ config.subtitle }}</p></div>
      <div class="stage-progress"><strong>{{ config.progress }}%</strong><span>阶段进度</span></div>
    </header>
    <section class="stage-goal-grid"><div v-for="(goal, index) in config.goals" :key="goal" class="stage-goal-card"><span>0{{ index + 1 }}</span><p>{{ goal }}</p></div></section>

    <section v-if="stage === 'preview'" class="stage-workspace">
      <el-card shadow="never" class="workspace-card"><template #header><div class="content-heading"><span>专题导览</span><el-tag>课前先读</el-tag></div></template><div class="guide-grid"><div><strong>本专题</strong><p>{{ chapter?.title }}</p></div><div><strong>阅读方法</strong><p>先找章节主旨，再标记核心概念和重要论述。</p></div><div><strong>预习产出</strong><p>形成至少 3 个问题，带着问题进入课堂。</p></div></div></el-card>
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>教材原文预读</span><span class="muted">先浏览结构，不要求立即记忆</span></div></template><article v-if="contentPreview.length" class="chapter-text textbook-document preview-text"><p v-for="(block, index) in contentPreview" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
    </section>

    <section v-else-if="stage === 'review'" class="stage-workspace">
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>教材重点回看</span><el-tag type="success">理解与梳理</el-tag></div></template><article v-if="contentBlocks.length" class="chapter-text textbook-document"><p v-for="(block, index) in contentBlocks" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
      <el-card shadow="never" class="workspace-card note-workspace"><template #header><div class="content-heading"><span>我的章节总结</span><span class="muted">自动保存在当前浏览器</span></div></template><p class="note-guide">建议按照“章节主旨—核心观点—概念关系—现实意义”四部分整理。</p><el-input v-model="selfNote" type="textarea" :rows="8" maxlength="3000" show-word-limit placeholder="请用自己的语言写下本专题总结……" /></el-card>
    </section>

    <section v-else class="stage-workspace exam-workspace">
      <el-card shadow="never" class="workspace-card"><template #header><div class="content-heading"><span>冲刺训练框架</span><el-tag type="danger">输出与检测</el-tag></div></template><div class="exam-task-grid"><div><strong>考点提炼</strong><p>识别章节主旨、核心概念和重要论述。</p></div><div><strong>答题训练</strong><p>按照“概念—观点—依据—意义”组织答案。</p></div><div><strong>薄弱点检查</strong><p>通过错题定位未掌握的知识点。</p></div></div></el-card>
      <el-card shadow="never" class="workspace-card textbook-card"><template #header><div class="content-heading"><span>核心原文速览</span><span class="muted">答题前快速回忆</span></div></template><article v-if="contentPreview.length" class="chapter-text textbook-document exam-preview"><p v-for="(block, index) in contentPreview" :key="index">{{ block }}</p></article><el-empty v-else description="当前专题没有教材正文" /></el-card>
    </section>

    <section class="stage-task-panel"><div><p class="eyebrow">阶段任务</p><h2>完成本阶段学习闭环</h2><p>{{ config.aiHint }}</p></div><el-checkbox-group v-model="completedTasks" class="stage-task-list"><el-checkbox v-for="task in config.tasks" :key="task" :value="task">{{ task }}</el-checkbox></el-checkbox-group></section>
    <footer class="learning-footer">
      <span>任务勾选和个人总结会自动保存在当前浏览器。</span>
      <el-button v-if="config.next" type="primary" @click="goToStage(config.next)">进入下一阶段 →</el-button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { courseApi } from '@/api/courses'
import { learningApi } from '@/api/learning'
import AiAssistant from '@/components/AiAssistant.vue'
import type { Chapter, CourseDetail, LearningStage } from '@/types'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const stage = computed(() => route.params.stage as LearningStage)
const course = ref<CourseDetail | null>(null)
const chapter = ref<Chapter | null>(null)
const loading = ref(true)

const configs: Record<LearningStage, { title: string; subtitle: string; progress: number; next: LearningStage | null }> = {
  preview: { title: '预习空间', subtitle: '了解章节内容，发现重点问题', progress: 30, next: 'review' },
  review: { title: '课后巩固', subtitle: '回顾章节知识，构建复习框架', progress: 70, next: 'exam' },
  exam: { title: '考前冲刺', subtitle: '聚焦重点考点，开展模拟训练', progress: 100, next: null },
}
const config = computed(() => configs[stage.value])

async function load() {
  loading.value = true
  try {
    course.value = (await courseApi.detail(courseId.value)).data.data
    chapter.value = course.value.chapters.find((item) => item.id === chapterId.value) || null
    if (!chapter.value) return router.replace(`/courses/${courseId.value}`)
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
onMounted(load)
watch(stage, load)
</script>

<template>
  <div v-loading="loading">
    <el-button link @click="router.push(`/courses/${courseId}`)">← 返回课程详情</el-button>
    <header class="learning-hero">
      <div><p class="eyebrow">{{ course?.name }}</p><h1>{{ config.title }}</h1><p>{{ config.subtitle }}</p></div>
      <el-tag effect="dark" round>{{ chapter?.title }}</el-tag>
    </header>
    <div class="learning-layout">
      <section class="chapter-content">
        <el-card shadow="never">
          <template #header><div class="content-heading"><span>章节学习资料</span><el-tag type="info">当前章节</el-tag></div></template>
          <h2>{{ chapter?.title }}</h2>
          <div v-if="chapter?.content" class="chapter-text">{{ chapter.content }}</div>
          <el-empty v-else description="本章内容尚未录入，AI 将不会编造回答" />
        </el-card>
      </section>
      <AiAssistant v-if="chapter" :course-id="courseId" :chapter-id="chapterId" :learning-stage="stage" />
    </div>
    <footer class="learning-footer">
      <span>进入本学习空间后，系统已自动记录阶段进度。</span>
      <el-button v-if="config.next" type="primary" @click="goToStage(config.next)">进入下一阶段 →</el-button>
    </footer>
  </div>
</template>

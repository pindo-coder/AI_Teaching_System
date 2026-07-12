<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { MagicStick, Close } from '@element-plus/icons-vue'
import type { LearningStage } from '@/types'
import AiAssistant from './AiAssistant.vue'

const route = useRoute()
const open = ref(false)
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const learningStage = computed(() => route.params.stage as LearningStage)
const available = computed(() =>
  Number.isFinite(courseId.value)
  && Number.isFinite(chapterId.value)
  && ['preview', 'review', 'exam'].includes(learningStage.value),
)
</script>

<template>
  <div v-if="available" class="floating-ai">
    <el-tooltip v-if="!open" content="打开 AI 助教" placement="left">
      <el-button class="floating-ai-trigger" type="primary" @click="open = true"><el-icon :size="21"><MagicStick /></el-icon><span>AI 助教</span></el-button>
    </el-tooltip>
    <el-card v-else shadow="always" class="floating-ai-panel">
      <button class="floating-ai-close" type="button" aria-label="关闭 AI 助手" @click="open = false"><el-icon><Close /></el-icon></button>
      <AiAssistant :key="`${courseId}-${chapterId}-${learningStage}`" :course-id="courseId" :chapter-id="chapterId" :learning-stage="learningStage" />
    </el-card>
  </div>
</template>

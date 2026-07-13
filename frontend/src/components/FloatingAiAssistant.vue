<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { MagicStick, Close } from '@element-plus/icons-vue'
import type { LearningStage } from '@/types'
import AiAssistant from './AiAssistant.vue'

const route = useRoute()
const open = ref(false)
const floatingRef = ref<HTMLElement | null>(null)
const position = ref<{ x: number; y: number } | null>(null)
let dragging = false
let offsetX = 0
let offsetY = 0
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const learningStage = computed(() => route.params.stage as LearningStage)
const available = computed(() =>
  Number.isFinite(courseId.value)
  && Number.isFinite(chapterId.value)
  && ['preview', 'review', 'exam'].includes(learningStage.value),
)
const floatingStyle = computed(() => position.value ? {
  left: `${position.value.x}px`, top: `${position.value.y}px`, right: 'auto', bottom: 'auto',
} : undefined)

function clampPosition(x: number, y: number) {
  const element = floatingRef.value
  const width = element?.offsetWidth || 440
  const height = element?.offsetHeight || 120
  return {
    x: Math.max(8, Math.min(x, window.innerWidth - width - 8)),
    y: Math.max(8, Math.min(y, window.innerHeight - height - 8)),
  }
}
function startDrag(event: PointerEvent) {
  const rect = floatingRef.value?.getBoundingClientRect()
  if (!rect) return
  dragging = true
  offsetX = event.clientX - rect.left
  offsetY = event.clientY - rect.top
  window.addEventListener('pointermove', moveDrag)
  window.addEventListener('pointerup', stopDrag, { once: true })
}
function moveDrag(event: PointerEvent) {
  if (!dragging) return
  position.value = clampPosition(event.clientX - offsetX, event.clientY - offsetY)
}
function stopDrag() {
  dragging = false
  window.removeEventListener('pointermove', moveDrag)
  if (position.value) localStorage.setItem('floating-ai-position', JSON.stringify(position.value))
}
onMounted(() => {
  try {
    const saved = JSON.parse(localStorage.getItem('floating-ai-position') || 'null')
    if (typeof saved?.x === 'number' && typeof saved?.y === 'number') position.value = clampPosition(saved.x, saved.y)
  } catch { /* 忽略无效的本地位置记录 */ }
})
onUnmounted(() => window.removeEventListener('pointermove', moveDrag))
</script>

<template>
  <div v-if="available" ref="floatingRef" class="floating-ai" :style="floatingStyle">
    <el-tooltip v-if="!open" content="打开 AI 助教" placement="left">
      <el-button class="floating-ai-trigger" type="primary" @click="open = true"><el-icon :size="21"><MagicStick /></el-icon><span>AI 助教</span></el-button>
    </el-tooltip>
    <el-card v-else shadow="always" class="floating-ai-panel">
      <div class="floating-ai-drag-handle" title="按住拖动窗口" @pointerdown="startDrag"><span>AI 助教</span><span>拖动窗口</span></div>
      <button class="floating-ai-close" type="button" aria-label="关闭 AI 助手" @click="open = false"><el-icon><Close /></el-icon></button>
      <AiAssistant :key="`${courseId}-${chapterId}-${learningStage}`" :course-id="courseId" :chapter-id="chapterId" :learning-stage="learningStage" />
    </el-card>
  </div>
</template>

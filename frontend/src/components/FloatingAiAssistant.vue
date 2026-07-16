<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { MagicStick, Close } from '@element-plus/icons-vue'
import type { LearningStage } from '@/types'
import AiAssistant from './AiAssistant.vue'

const route = useRoute()
const open = ref(false)
const floatingRef = ref<HTMLElement | null>(null)
const position = ref<{ x: number; y: number } | null>(null)
let dragging = false
let dragMoved = false
let dragFromTrigger = false
let suppressTriggerClick = false
let offsetX = 0
let offsetY = 0
let startClientX = 0
let startClientY = 0
const courseId = computed(() => Number(route.params.courseId))
const chapterId = computed(() => Number(route.params.chapterId))
const learningStage = computed(() => route.params.stage as LearningStage)
const stageLabel = computed(() => ({ preview: '课前预习', review: '课后巩固', exam: '考前冲刺' })[learningStage.value] || '专题学习')
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
function startDrag(event: PointerEvent, fromTrigger = false) {
  const rect = floatingRef.value?.getBoundingClientRect()
  if (!rect) return
  dragging = true
  dragMoved = false
  dragFromTrigger = fromTrigger
  startClientX = event.clientX
  startClientY = event.clientY
  offsetX = event.clientX - rect.left
  offsetY = event.clientY - rect.top
  window.addEventListener('pointermove', moveDrag)
  window.addEventListener('pointerup', stopDrag, { once: true })
}
function moveDrag(event: PointerEvent) {
  if (!dragging) return
  if (!dragMoved && Math.hypot(event.clientX - startClientX, event.clientY - startClientY) < 4) return
  dragMoved = true
  event.preventDefault()
  position.value = clampPosition(event.clientX - offsetX, event.clientY - offsetY)
}
function stopDrag() {
  if (dragMoved && dragFromTrigger) {
    suppressTriggerClick = true
    window.setTimeout(() => { suppressTriggerClick = false }, 0)
  }
  dragging = false
  window.removeEventListener('pointermove', moveDrag)
  if (position.value) localStorage.setItem('floating-ai-position', JSON.stringify(position.value))
}
async function openAssistant() {
  if (suppressTriggerClick) { suppressTriggerClick = false; return }
  open.value = true
  await nextTick()
  if (position.value) position.value = clampPosition(position.value.x, position.value.y)
}
async function closeAssistant() {
  open.value = false
  await nextTick()
  if (position.value) position.value = clampPosition(position.value.x, position.value.y)
}
function keepInViewport() {
  if (position.value) position.value = clampPosition(position.value.x, position.value.y)
}
onMounted(() => {
  try {
    const saved = JSON.parse(localStorage.getItem('floating-ai-position') || 'null')
    if (typeof saved?.x === 'number' && typeof saved?.y === 'number') position.value = clampPosition(saved.x, saved.y)
  } catch { /* 忽略无效的本地位置记录 */ }
  window.addEventListener('resize', keepInViewport)
})
onUnmounted(() => {
  window.removeEventListener('pointermove', moveDrag)
  window.removeEventListener('resize', keepInViewport)
})
</script>

<template>
  <div v-if="available" ref="floatingRef" class="floating-ai" :style="floatingStyle">
    <el-tooltip v-if="!open" content="可拖动位置，点击打开 AI 助教" placement="left">
      <button class="floating-ai-trigger" type="button" aria-label="AI 助教，可拖动，点击打开" @pointerdown="startDrag($event, true)" @click="openAssistant">
        <span class="floating-ai-trigger-orb"><el-icon><MagicStick /></el-icon><i></i></span>
        <span class="floating-ai-trigger-copy"><small>SMART TUTOR</small><strong>AI 助教</strong></span>
        <span class="floating-ai-trigger-hint">拖动<br>打开</span>
      </button>
    </el-tooltip>
    <section v-else class="floating-ai-panel">
      <header class="floating-ai-drag-handle" title="按住拖动窗口" @pointerdown="startDrag($event)">
        <div class="floating-ai-window-orb"><el-icon><MagicStick /></el-icon><span>AI</span></div>
        <div class="floating-ai-window-title"><small>IDEOLOGY · SMART TUTOR</small><strong>思政 AI 助教</strong><span>{{ stageLabel }} · 当前专题上下文</span></div>
        <div class="floating-ai-window-drag"><i></i><span>按住拖动</span></div>
      </header>
      <button class="floating-ai-close" type="button" aria-label="关闭 AI 助手" @click="closeAssistant"><el-icon><Close /></el-icon></button>
      <div class="floating-ai-context"><span>教材约束</span><span>专题定位</span><span>原文引用</span></div>
      <div class="floating-ai-body"><AiAssistant :key="`${courseId}-${chapterId}-${learningStage}`" :course-id="courseId" :chapter-id="chapterId" :learning-stage="learningStage" /></div>
    </section>
  </div>
</template>

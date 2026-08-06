<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Close, Lock, MagicStick, Unlock } from '@element-plus/icons-vue'
import type { LearningStage } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspaceAiAssistant from './WorkspaceAiAssistant.vue'

const route = useRoute()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const open = ref(false)
const layoutMode = ref<'free' | 'fixed'>('free')
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

const routeCourseId = computed(() => Number(route.params.courseId))
const routeChapterId = computed(() => Number(route.params.chapterId))
const routeLearningStage = computed(() => route.params.stage as LearningStage)
const queryCourseId = computed(() => Number(route.query.course_id))
const courseId = computed(() => {
  if (Number.isFinite(routeCourseId.value) && routeCourseId.value > 0) return routeCourseId.value
  if (Number.isFinite(queryCourseId.value) && queryCourseId.value > 0) return queryCourseId.value
  return workspace.currentCourse?.id || null
})
const chapterId = computed(() => {
  if (Number.isFinite(routeChapterId.value) && routeChapterId.value > 0) return routeChapterId.value
  return workspace.currentCourse?.id === courseId.value ? workspace.currentChapter?.id || null : null
})
const learningStage = computed(() => ['preview', 'review', 'exam'].includes(routeLearningStage.value) ? routeLearningStage.value : 'preview')
const contextTitle = computed(() => workspace.currentCourse?.name || '课程工作台')
const contextDetail = computed(() => workspace.currentChapter?.title || '可随时提问、生成与整理')
const roleLabel = computed(() => ({ student: '学生', teacher: '教师', admin: '管理员' }[auth.user?.role || 'student']))
const floatingStyle = computed(() => layoutMode.value === 'free' && position.value ? {
  left: `${position.value.x}px`, top: `${position.value.y}px`, right: 'auto', bottom: 'auto',
} : undefined)
const layoutTitle = computed(() => layoutMode.value === 'free' ? '自由拖动：点击锁定到右下角' : '固定窗口：点击切换为可拖动')

function clampPosition(x: number, y: number) {
  const element = floatingRef.value
  const width = element?.offsetWidth || 440
  const height = element?.offsetHeight || 120
  return {
    x: Math.max(8, Math.min(x, Math.max(8, window.innerWidth - width - 8))),
    y: Math.max(8, Math.min(y, Math.max(8, window.innerHeight - height - 8))),
  }
}

function startDrag(event: PointerEvent, fromTrigger = false) {
  if (layoutMode.value === 'fixed') return
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
  if (position.value && layoutMode.value === 'free') position.value = clampPosition(position.value.x, position.value.y)
}

async function closeAssistant() {
  open.value = false
  await nextTick()
  if (position.value && layoutMode.value === 'free') position.value = clampPosition(position.value.x, position.value.y)
}

async function toggleLayout() {
  layoutMode.value = layoutMode.value === 'free' ? 'fixed' : 'free'
  localStorage.setItem('floating-ai-layout', layoutMode.value)
  await nextTick()
  if (layoutMode.value === 'free') {
    const rect = floatingRef.value?.getBoundingClientRect()
    if (rect) position.value = clampPosition(rect.left, rect.top)
    else position.value = clampPosition(window.innerWidth - 228, window.innerHeight - 96)
    localStorage.setItem('floating-ai-position', JSON.stringify(position.value))
  }
}

function keepInViewport() {
  if (layoutMode.value === 'free' && position.value) position.value = clampPosition(position.value.x, position.value.y)
}

onMounted(() => {
  try {
    const savedLayout = localStorage.getItem('floating-ai-layout')
    if (savedLayout === 'fixed' || savedLayout === 'free') layoutMode.value = savedLayout
    const savedPosition = JSON.parse(localStorage.getItem('floating-ai-position') || 'null')
    if (typeof savedPosition?.x === 'number' && typeof savedPosition?.y === 'number') position.value = savedPosition
  } catch { /* 忽略无效的本地布局记录 */ }
  window.addEventListener('resize', keepInViewport)
})

onUnmounted(() => {
  window.removeEventListener('pointermove', moveDrag)
  window.removeEventListener('resize', keepInViewport)
})
</script>

<template>
  <div v-if="auth.isAuthenticated" ref="floatingRef" class="floating-ai" :class="{ 'is-open': open, 'is-fixed': layoutMode === 'fixed' }" :style="floatingStyle">
    <el-tooltip v-if="!open" content="可拖动位置，点击打开思政 AI 助教" placement="left">
      <button class="floating-ai-trigger" type="button" aria-label="打开思政 AI 助教；自由模式下可拖动" @pointerdown="startDrag($event, true)" @click="openAssistant">
        <span class="floating-ai-trigger-orb"><el-icon><MagicStick /></el-icon><i></i></span>
        <span class="floating-ai-trigger-copy"><small>IDEOLOGY · SMART TUTOR</small><strong>思政 AI 助教</strong></span>
        <span class="floating-ai-trigger-hint">{{ layoutMode === 'free' ? '拖动 / 打开' : '固定 / 打开' }}</span>
      </button>
    </el-tooltip>
    <section v-else class="floating-ai-panel">
      <header class="floating-ai-drag-handle" :class="{ 'is-locked': layoutMode === 'fixed' }" :title="layoutMode === 'free' ? '按住拖动窗口' : '窗口已固定，点击右上角解锁'" @pointerdown="startDrag($event)">
        <div class="floating-ai-window-orb"><el-icon><MagicStick /></el-icon><span>AI</span></div>
        <div class="floating-ai-window-title"><small>IDEOLOGY · SMART TUTOR</small><strong>思政 AI 助教</strong><span>{{ roleLabel }} · {{ contextTitle }} · {{ contextDetail }}</span></div>
        <div class="floating-ai-window-drag"><i></i><span>{{ layoutMode === 'free' ? '按住拖动' : '窗口已固定' }}</span></div>
      </header>
      <div class="floating-ai-window-actions">
        <button type="button" :title="layoutTitle" :aria-label="layoutTitle" @click="toggleLayout"><el-icon><Unlock v-if="layoutMode === 'free'" /><Lock v-else /></el-icon></button>
        <button type="button" title="关闭 AI 助教" aria-label="关闭 AI 助教" @click="closeAssistant"><el-icon><Close /></el-icon></button>
      </div>
      <div class="floating-ai-context"><span>教材约束</span><span>{{ roleLabel }}模式</span><span>{{ courseId && chapterId ? '专题定位' : '待选择专题' }}</span></div>
      <div class="floating-ai-body"><WorkspaceAiAssistant :key="`${courseId || 0}-${chapterId || 0}-${learningStage}`" :course-id="courseId" :chapter-id="chapterId" :learning-stage="learningStage" /></div>
    </section>
  </div>
</template>

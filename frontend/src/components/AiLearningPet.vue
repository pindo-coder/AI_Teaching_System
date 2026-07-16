<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, RefreshRight } from '@element-plus/icons-vue'
import type { AiPetAction, AiPetContext, AiPetState } from '@/types/aiPet'

const props = withDefaults(defineProps<{
  context: AiPetContext
  loading?: boolean
}>(), { loading: false })

const emit = defineEmits<{
  action: [value: AiPetAction]
}>()

const suggestionIndex = ref(0)
const isTeachingRole = computed(() => props.context.role !== 'student')
const state = computed<AiPetState>(() => {
  if (props.loading) return 'thinking'
  if (props.context.overdueCount > 0) return 'alert'
  if (props.context.pendingCount > 0) return 'reminding'
  if (props.context.chapterTitle) return 'focused'
  return 'idle'
})
const stateLabel = computed(() => ({
  idle: '等待学习',
  focused: '专注陪伴',
  reminding: '任务提醒',
  alert: '优先处理',
  thinking: '正在整理',
})[state.value])

const suggestions = computed(() => {
  const context = props.context
  if (isTeachingRole.value) {
    return [
      context.pendingCount
        ? `当前有 ${context.pendingCount} 项教学任务进行中，可以查看学生完成情况。`
        : '当前没有进行中的教学任务，可以从教材专题发布新任务。',
      context.chapterTitle
        ? `当前教学内容为“${context.chapterTitle}”，我可以辅助生成讨论题与课堂活动。`
        : '选择教材专题后，我会根据章节内容提供教学组织建议。',
      '建议将教材知识点、时政材料和课堂讨论串联成一条教学路径。',
    ]
  }
  if (context.overdueCount > 0) {
    return [
      `有 ${context.overdueCount} 项任务已经逾期，建议先处理时间最紧的学习任务。`,
      context.nextTask ? `可以先完成“${context.nextTask.title}”，完成情况会自动计入学习进度。` : '进入任务中心查看需要优先完成的内容。',
      '完成任务后，可以把易混概念整理到笔记空间，方便后续复习。',
    ]
  }
  if (context.nextTask) {
    return [
      `下一项任务是“${context.nextTask.title}”，我已经为你定位到对应专题。`,
      context.chapterTitle ? `你当前学习到“${context.chapterTitle}”，建议沿着当前阶段继续。` : '先进入任务对应专题，我会结合教材内容继续辅助。',
      '学习过程中保存的笔记和 AI 使用记录会自动形成任务进度。',
    ]
  }
  return context.chapterTitle ? [
    `继续学习“${context.chapterTitle}”，当前综合进度为 ${context.progress}%。`,
    '目前没有待完成任务，可以进入笔记空间整理本章认识。',
    '也可以查看最新时政要点，把现实问题关联回教材知识。',
  ] : [
    '选择一个教材专题后，我会陪你完成预习、巩固和冲刺。',
    '我会根据真实学习行为提供提醒，不需要手动勾选进度。',
    '你可以从专题目录开始建立自己的学习路径。',
  ]
})

const message = computed(() => suggestions.value[suggestionIndex.value % suggestions.value.length])
const primaryAction = computed<AiPetAction & { label: string }>(() => {
  if (isTeachingRole.value) return { type: 'open-teaching-center', path: '/assignments', label: '进入任务管理' }
  if (props.context.nextTask) return { type: 'open-task', path: props.context.nextTask.path, label: '处理下一项任务' }
  return {
    type: 'continue-learning',
    path: props.context.continuePath,
    label: props.context.chapterTitle ? '继续当前专题' : '选择学习专题',
  }
})

function nextSuggestion() {
  suggestionIndex.value = (suggestionIndex.value + 1) % suggestions.value.length
}
function triggerPrimaryAction() {
  const { label: _label, ...action } = primaryAction.value
  emit('action', action)
}

watch(() => [props.context.chapterTitle, props.context.pendingCount, props.context.overdueCount], () => {
  suggestionIndex.value = 0
})
</script>

<template>
  <section class="ai-learning-pet" :class="`is-${state}`" aria-label="AI 学习伙伴">
    <div class="ai-pet-network" aria-hidden="true">
      <span class="ai-pet-orbit orbit-one"></span>
      <span class="ai-pet-orbit orbit-two"></span>
      <span class="ai-pet-node node-book">教材</span>
      <span class="ai-pet-node node-news">时政</span>
      <span class="ai-pet-node node-task">任务</span>
      <span class="ai-pet-node node-note">笔记</span>
      <div class="ai-pet-avatar-shell">
        <!-- 保留 avatar 插槽：后续可直接换成用户提供的图片、SVG、Lottie 或 3D UI。 -->
        <slot name="avatar" :state="state" :context="context">
          <div class="ai-pet-avatar" :class="`face-${state}`">
            <span class="ai-pet-antenna"></span>
            <span class="ai-pet-face"><i></i><i></i><b></b></span>
          </div>
        </slot>
      </div>
    </div>

    <div class="ai-pet-dialogue">
      <div class="ai-pet-heading">
        <div><span>AI 学习伙伴</span><strong>小知</strong></div>
        <em>{{ stateLabel }}</em>
      </div>
      <slot name="message" :message="message" :state="state" :context="context">
        <p aria-live="polite">{{ message }}</p>
      </slot>
      <div class="ai-pet-actions">
        <el-button type="warning" :icon="ArrowRight" @click="triggerPrimaryAction">{{ primaryAction.label }}</el-button>
        <el-button text :icon="RefreshRight" @click="nextSuggestion">换个建议</el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-learning-pet { position: relative; display: grid; width: min(100%, 470px); min-height: 266px; grid-template-columns: minmax(190px, .9fr) minmax(190px, 1.1fr); align-items: center; gap: 8px; }
.ai-pet-network { position: relative; min-height: 250px; }
.ai-pet-orbit { position: absolute; border: 1px solid rgba(214, 241, 255, .5); border-radius: 50%; }
.orbit-one { inset: 26px 4px; }
.orbit-two { inset: 51px 30px; border-style: dashed; opacity: .68; }
.ai-pet-node { position: absolute; display: grid; z-index: 2; width: 42px; height: 42px; place-items: center; color: #e9f7ff; background: rgba(16, 84, 164, .55); border: 1px solid rgba(213, 244, 255, .55); border-radius: 50%; box-shadow: 0 0 20px rgba(95, 211, 255, .25); font-size: 10px; }
.node-book { top: 16px; left: 50%; transform: translateX(-50%); }.node-news { top: 50%; right: -5px; transform: translateY(-50%); }.node-task { bottom: 15px; left: 50%; transform: translateX(-50%); }.node-note { top: 50%; left: -5px; transform: translateY(-50%); }
.ai-pet-avatar-shell { position: absolute; z-index: 3; top: 50%; left: 50%; transform: translate(-50%, -50%); }
.ai-pet-avatar { position: relative; display: grid; width: 102px; height: 92px; place-items: center; background: linear-gradient(145deg, #f9fdff, #bceaff); border: 6px solid rgba(255, 255, 255, .65); border-radius: 34px; box-shadow: 0 14px 36px rgba(8, 55, 124, .35), 0 0 28px rgba(83, 226, 255, .35); }
.ai-pet-antenna { position: absolute; top: -24px; width: 3px; height: 22px; background: #bdeaff; border-radius: 2px; }.ai-pet-antenna::after { position: absolute; top: -5px; left: -4px; width: 11px; height: 11px; content: ''; background: #ffd36d; border-radius: 50%; box-shadow: 0 0 12px #ffd36d; }
.ai-pet-face { position: relative; display: flex; width: 66px; height: 42px; align-items: center; justify-content: space-around; background: #174e9d; border-radius: 17px; }
.ai-pet-face i { width: 7px; height: 11px; background: #8ff4ff; border-radius: 5px; box-shadow: 0 0 9px #8ff4ff; }.ai-pet-face b { position: absolute; bottom: 7px; left: 27px; width: 13px; height: 6px; border-bottom: 2px solid #aef8ff; border-radius: 50%; }
.is-alert .ai-pet-antenna::after { background: #ff8779; box-shadow: 0 0 12px #ff8779; }.is-alert .ai-pet-face b { border: 0; border-top: 2px solid #aef8ff; }.is-focused .ai-pet-face i:first-child { height: 3px; }.is-thinking .ai-pet-face i { animation: ai-pet-blink .9s ease-in-out infinite alternate; }
.ai-pet-dialogue { position: relative; z-index: 4; padding: 18px; color: #f8fbff; background: rgba(10, 49, 113, .58); border: 1px solid rgba(209, 238, 255, .42); border-radius: 18px; box-shadow: 0 14px 32px rgba(9, 44, 102, .2); backdrop-filter: blur(10px); }
.ai-pet-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.ai-pet-heading div { display: grid; gap: 2px; }.ai-pet-heading span { color: #cce9ff; font-size: 10px; letter-spacing: 1px; }.ai-pet-heading strong { font-size: 20px; }.ai-pet-heading em { padding: 4px 8px; color: #ffedba; background: rgba(250, 189, 61, .15); border: 1px solid rgba(255, 221, 142, .4); border-radius: 12px; font-size: 10px; font-style: normal; }
.ai-pet-dialogue p { min-height: 66px; margin: 13px 0; color: #e5f0ff; font-size: 13px; line-height: 1.7; }
.ai-pet-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }.ai-pet-actions .el-button + .el-button { margin-left: 0; }.ai-pet-actions :deep(.el-button.is-text) { color: #e0efff; }
@keyframes ai-pet-blink { to { height: 3px; } }
@media (prefers-reduced-motion: reduce) { .is-thinking .ai-pet-face i { animation: none; } }
@media (max-width: 760px) { .ai-learning-pet { width: 100%; grid-template-columns: 1fr; }.ai-pet-network { min-height: 210px; }.ai-pet-dialogue { margin-top: -18px; } }
</style>

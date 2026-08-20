<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowDown, Check, MagicStick, RefreshRight, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { aiApi, type AiWorkspaceContext } from '@/api/ai'
import { useRoute } from 'vue-router'
import type { LearningStage } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspaceAiAssistant from './WorkspaceAiAssistant.vue'

const auth = useAuthStore()
const workspace = useWorkspaceStore()
const route = useRoute()
const expanded = ref(false)
const loading = ref(false)
const context = ref<AiWorkspaceContext | null>(null)
const manualCourseId = ref<number | null>(null)
const manualChapterIds = ref<number[] | null>(null)
const manualClassId = ref<number | null>(null)

function toPositiveNumber(value: unknown) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

const routeCourseId = computed(() => toPositiveNumber(route.params.courseId) || toPositiveNumber(route.query.course_id))
const routeChapterId = computed(() => toPositiveNumber(route.params.chapterId))
const stage = computed<LearningStage>(() => {
  const value = String(route.params.stage || '')
  return ['preview', 'review', 'exam'].includes(value) ? value as LearningStage : 'preview'
})
const scope = computed(() => ({
  course_id: manualCourseId.value || routeCourseId.value || workspace.currentCourse?.id || null,
  chapter_id: manualChapterIds.value !== null ? manualChapterIds.value[0] || null : routeChapterId.value || (
    !routeCourseId.value || routeCourseId.value === workspace.currentCourse?.id
      ? workspace.currentChapter?.id || null
      : null
  ),
  chapter_ids: manualChapterIds.value !== null ? manualChapterIds.value : undefined,
  teaching_class_id: manualClassId.value || workspace.currentClass?.id || null,
  learning_stage: stage.value,
  page_name: String(route.name || ''),
}))
const sourceLabel = computed(() => ({
  page: '已读取当前页面', manual: '已手动确认', recent_learning: '根据最近学习', default_class: '根据默认教学班', assignment: '根据教学任务', none: '待识别',
}[context.value?.source || 'none']))
const confidenceLabel = computed(() => ({ high: '范围已确认', medium: '建议确认', low: '待确认' }[context.value?.confidence || 'low']))
const contextTitle = computed(() => {
  if (context.value?.course_name && context.value.chapter_ids.length > 1) return `${context.value.course_name} · 已选 ${context.value.chapter_ids.length} 个专题`
  if (context.value?.course_name && context.value?.chapter_title) return `${context.value.course_name} · ${context.value.chapter_title}`
  if (context.value?.course_name) return `${context.value.course_name} · 请选择专题`
  return '自动识别当前教学内容'
})

async function refreshContext() {
  if (!auth.isAuthenticated || loading.value) return
  loading.value = true
  try {
    const response = await aiApi.workspaceContext(scope.value)
    context.value = response.data.data
  } catch {
    context.value = null
  } finally {
    loading.value = false
  }
}

function chooseCandidate(candidate: AiWorkspaceContext['candidates'][number]) {
  manualCourseId.value = candidate.course_id
  manualChapterIds.value = []
  manualClassId.value = candidate.teaching_class_id
  void refreshContext()
}
function chooseChapter(id: number) {
  const selected = manualChapterIds.value === null
    ? [...(context.value?.chapter_ids || (context.value?.chapter_id ? [context.value.chapter_id] : []))]
    : [...manualChapterIds.value]
  const index = selected.indexOf(id)
  if (index >= 0) selected.splice(index, 1)
  else {
    if (selected.length >= 6) return ElMessage.warning('一次最多选择 6 个专题')
    selected.push(id)
  }
  manualChapterIds.value = selected
  void refreshContext()
}
function resetToAutomatic() {
  manualCourseId.value = null
  manualChapterIds.value = null
  manualClassId.value = null
  void refreshContext()
}
function acceptAgentContext(nextContext: AiWorkspaceContext) {
  context.value = nextContext
}

watch(
  () => [route.fullPath, workspace.currentCourse?.id, workspace.currentChapter?.id, workspace.currentClass?.id, auth.isAuthenticated],
  () => { void refreshContext() },
  { deep: false },
)
onMounted(() => void refreshContext())
</script>

<template>
  <section v-if="auth.isAuthenticated" class="agent-dock" :class="{ 'is-expanded': expanded }" aria-label="思政 AI 工作台">
    <header class="agent-dock-bar">
      <button class="agent-dock-brand" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
        <span class="agent-dock-orb"><el-icon><MagicStick /></el-icon><i>AI</i></span>
        <span class="agent-dock-title"><small>SMART TEACHING WORKBENCH</small><strong>思政 AI 工作台</strong></span>
      </button>
      <div class="agent-dock-context">
        <span class="agent-dock-context-status" :class="`is-${context?.confidence || 'low'}`"></span>
        <div><strong>{{ contextTitle }}</strong><small>{{ sourceLabel }} · {{ confidenceLabel }}</small></div>
      </div>
      <div class="agent-dock-actions">
        <el-popover placement="bottom-end" :width="480" trigger="click" popper-class="agent-context-popover">
          <template #reference>
            <el-button :icon="Setting" plain>教学范围</el-button>
          </template>
          <section class="agent-context-picker">
            <div class="agent-context-picker-heading"><div><strong>教学范围</strong><p>优先使用当前页面；不确定时由你一键确认。</p></div><el-button text type="primary" :icon="RefreshRight" :loading="loading" @click="resetToAutomatic">自动识别</el-button></div>
            <div v-if="context?.candidates.length" class="agent-context-candidates">
              <button v-for="candidate in context.candidates" :key="`${candidate.teaching_class_id || 0}-${candidate.course_id}`" type="button" :class="{ active: candidate.course_id === context?.course_id && candidate.teaching_class_id === context?.teaching_class_id }" @click="chooseCandidate(candidate)">
                <strong>{{ candidate.course_name }}</strong><small>{{ candidate.teaching_class_name || '未绑定教学班' }}</small>
              </button>
            </div>
            <p v-else class="agent-context-empty">当前尚未导入教材；导入后可在这里选择教学范围。</p>
            <div v-if="context?.chapters.length" class="agent-context-chapters"><span>专题（可多选，最多 6 个）</span><small>已选 {{ context.chapter_ids.length }} 个；Agent 写入操作以首个专题为主</small><button v-for="chapter in context.chapters" :key="chapter.id" type="button" :class="{ active: context?.chapter_ids.includes(chapter.id) }" @click="chooseChapter(chapter.id)"><el-icon v-if="context?.chapter_ids.includes(chapter.id)"><Check /></el-icon>{{ chapter.title }}</button></div>
          </section>
        </el-popover>
        <button class="agent-dock-toggle" type="button" :aria-label="expanded ? '收起 AI 工作台' : '展开 AI 工作台'" @click="expanded = !expanded"><span>{{ expanded ? '收起' : '展开' }}</span><el-icon :class="{ 'is-rotated': expanded }"><ArrowDown /></el-icon></button>
      </div>
    </header>
    <transition name="agent-dock-reveal">
      <div v-if="expanded" class="agent-dock-body">
        <WorkspaceAiAssistant
          :key="`${context?.course_id || 0}-${context?.chapter_ids.join('-') || 0}-${context?.teaching_class_id || 0}-${stage}`"
          :course-id="context?.course_id"
          :chapter-id="context?.chapter_id"
          :teaching-class-id="context?.teaching_class_id"
          :learning-stage="stage"
          :page-name="String(route.name || '')"
          :context="context"
          @context-updated="acceptAgentContext"
        />
      </div>
    </transition>
  </section>
</template>

<style scoped>
.agent-dock { position: sticky; top: 64px; z-index: 100; margin: 0 28px; color: #21334f; background: rgba(255, 255, 255, .96); border: 1px solid #dfe7f4; border-top: 0; border-radius: 0 0 18px 18px; box-shadow: 0 10px 28px rgba(32, 58, 104, .08); backdrop-filter: blur(16px); }
.agent-dock.is-expanded { display: flex; max-height: calc(100vh - 64px); flex-direction: column; box-shadow: 0 18px 48px rgba(25, 49, 94, .18); }
.agent-dock-bar { display: flex; min-height: 62px; align-items: center; gap: 18px; padding: 8px 16px; }
.agent-dock-brand { display: inline-flex; min-width: 206px; align-items: center; gap: 10px; padding: 0; color: inherit; text-align: left; background: transparent; border: 0; cursor: pointer; }
.agent-dock-orb { position: relative; display: grid; width: 37px; height: 37px; flex: 0 0 auto; place-items: center; color: #fff; background: linear-gradient(140deg, #6d3ab8, #2c6ee2 56%, #18a8c0); border-radius: 13px; box-shadow: 0 7px 17px rgba(54, 90, 202, .22); font-size: 20px; }
.agent-dock-orb i { position: absolute; right: -5px; bottom: -5px; padding: 1px 4px; color: #fff; background: #a92d4d; border: 1px solid #fff; border-radius: 5px; font-size: 7px; font-style: normal; font-weight: 800; }
.agent-dock-title { display: grid; gap: 2px; }.agent-dock-title small { color: #7586a6; font-size: 8px; font-weight: 800; letter-spacing: 1.2px; }.agent-dock-title strong { color: #21385e; font-size: 14px; }
.agent-dock-context { display: flex; min-width: 0; flex: 1; align-items: center; gap: 9px; padding-left: 16px; border-left: 1px solid #e5ebf4; }.agent-dock-context > div { display: grid; min-width: 0; gap: 2px; }.agent-dock-context strong, .agent-dock-context small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.agent-dock-context strong { color: #40516e; font-size: 12px; }.agent-dock-context small { color: #8997ac; font-size: 10px; }.agent-dock-context-status { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; }.agent-dock-context-status.is-high { background: #42ad7d; box-shadow: 0 0 0 4px rgba(66,173,125,.12); }.agent-dock-context-status.is-medium { background: #dc9b2c; box-shadow: 0 0 0 4px rgba(220,155,44,.12); }.agent-dock-context-status.is-low { background: #8a9ab1; box-shadow: 0 0 0 4px rgba(138,154,177,.12); }
.agent-dock-actions { display: flex; align-items: center; gap: 8px; }.agent-dock-actions :deep(.el-button) { border-radius: 9px; }.agent-dock-toggle { display: inline-flex; align-items: center; gap: 4px; padding: 8px; color: #466086; background: #f4f7fd; border: 1px solid #e0e8f5; border-radius: 9px; cursor: pointer; font-size: 11px; }.agent-dock-toggle .el-icon { transition: transform .2s ease; }.agent-dock-toggle .is-rotated { transform: rotate(180deg); }
.agent-dock-body { min-height: 0; overflow-y: auto; overscroll-behavior: contain; background: linear-gradient(180deg, #f7f9fe, #fff 65%); border-top: 1px solid #e7edf7; border-radius: 0 0 18px 18px; scrollbar-gutter: stable; }
.agent-dock-reveal-enter-active, .agent-dock-reveal-leave-active { transition: opacity .2s ease, transform .2s ease; }.agent-dock-reveal-enter-from, .agent-dock-reveal-leave-to { opacity: 0; transform: translateY(-8px); }
:global(.agent-context-popover) { max-width: min(520px, calc(100vw - 20px)); border-radius: 14px; }.agent-context-picker { padding: 4px; }.agent-context-picker-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }.agent-context-picker-heading strong { color: #2d4160; }.agent-context-picker-heading p { margin: 4px 0 0; color: #7f8ca0; font-size: 11px; }.agent-context-candidates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }.agent-context-candidates button { display: grid; gap: 3px; min-width: 0; padding: 9px 10px; color: #465673; text-align: left; background: #f8faff; border: 1px solid #e0e7f3; border-radius: 9px; cursor: pointer; }.agent-context-candidates button.active { color: #295fcb; background: #edf3ff; border-color: #86a9ed; }.agent-context-candidates strong, .agent-context-candidates small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.agent-context-candidates strong { font-size: 12px; }.agent-context-candidates small { color: #8795ab; font-size: 10px; }.agent-context-chapters { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 13px; padding-top: 12px; border-top: 1px dashed #dce4f0; }.agent-context-chapters > span { color: #64748b; font-size: 11px; font-weight: 700; }.agent-context-chapters > small { flex-basis: 100%; color: #8795ab; font-size: 10px; }.agent-context-chapters button { display: inline-flex; align-items: center; gap: 3px; padding: 4px 7px; color: #536782; background: #fff; border: 1px solid #dce5f2; border-radius: 7px; cursor: pointer; font-size: 11px; }.agent-context-chapters button.active { color: #fff; background: #4968cf; border-color: #4968cf; }.agent-context-empty { margin: 0; color: #8190a6; font-size: 12px; }
@media (max-width: 760px) { .agent-dock { top: 58px; margin: 0 10px; border-radius: 0 0 14px 14px; }.agent-dock.is-expanded { max-height: calc(100vh - 58px); }.agent-dock-bar { gap: 8px; padding: 8px 10px; }.agent-dock-brand { min-width: 43px; }.agent-dock-title, .agent-dock-context { display: none; }.agent-dock-actions { flex: 1; justify-content: flex-end; }.agent-dock-actions :deep(.el-button) { padding: 7px 9px; }.agent-context-candidates { grid-template-columns: 1fr; } }
</style>

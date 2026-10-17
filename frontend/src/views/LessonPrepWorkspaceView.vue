<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  agentApi,
  type AgentCapabilities,
  type AgentRun,
  type LessonPublication,
  type PptPreferences,
  type PresentationTemplate,
  type PptVersion,
  type PptVersionPreview,
  type AgentArtifact,
} from '@/api/agents'
import { courseApi } from '@/api/courses'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import EvidenceCard from '@/components/ui/EvidenceCard.vue'
import PptSlidePreview from '@/components/PptSlidePreview.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import type { Course, CourseDetail, LearningStage } from '@/types'
import { formatBeijingDateTime } from '@/utils/time'
import { lessonArtifactProgress } from '@/utils/lessonArtifactProgress'
import { createAgentRunMonitor } from '@/utils/agentRunMonitor'
import { pptPublicationState } from '@/utils/lessonPublication'
import logoUrl from '@/assets/logo1.svg'
import progressBackgroundUrl from '@/assets/lesson-prep-progress-bg.png'
import contextBackgroundUrl from '@/assets/lesson-prep-context-bg.png'
import designBriefBackgroundUrl from '@/assets/challenge-cup-topbar.png'

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const acting = ref(false)
const submittingArtifacts = ref(false)
const progressNow = ref(Date.now())
const progressSyncWarning = ref('')
let progressClock: ReturnType<typeof setInterval> | undefined
const courses = ref<Course[]>([])
const course = ref<CourseDetail | null>(null)
const selectedCourseId = ref<number>()
const selectedChapterId = ref<number>()
const lessonHours = ref(2)
const learningStage = ref<LearningStage>('preview')
const studentLevel = ref('本科生')
const completionCondition = ref('教材阅读')
const teachingGoal = ref('')
const currentRun = ref<AgentRun | null>(null)
const activeStage = ref(1)
const capabilities = ref<AgentCapabilities>({
  ppt_multimodal_available: false,
  ppt_multimodal_model: null,
  ppt_multimodal_max_images: 0,
})
const teachingClasses = ref<TeachingClass[]>([])
const selectedTeachingClassId = ref<number>()
const publishedResult = ref<LessonPublication | null>(null)
const publishTitle = ref('')
const publishDescription = ref('')
const publishPpt = ref(true)
const publishDiscussions = ref(true)
const selectedDiscussionIndices = ref<number[]>([])
const publicationConfirmed = ref(false)
const previousPptConfirmed = ref(false)
const artifactTypes = ref<Array<'lesson_plan' | 'ppt' | 'classroom_activities'>>([
  'ppt',
  'lesson_plan',
  'classroom_activities',
])
const artifactPreview = ref<'ppt' | 'lesson_plan' | 'classroom_activities'>('ppt')
const pptPreferences = ref<PptPreferences>({
  title: '',
  scenario: 'classroom',
  visual_style: 'modern',
  content_density: 'standard',
  min_slides: 10,
  max_slides: 10,
  slide_count: 10,
  include_interaction: true,
  // 已配置百炼多模态时默认生成少量语义插图；教师仍可取消以控制额度。
  include_visuals: true,
  image_frame_shape: 'roundRect',
  template_id: null,
})
const pptTemplates = ref<PresentationTemplate[]>([])
const templateDialogVisible = ref(false)
const templateName = ref('')
const templateDescription = ref('')
const templateFile = ref<File | null>(null)
const slideRevisionVisible = ref(false)
const revisingSlideIndex = ref(0)
const revisionInstruction = ref('')
const revisionMode = ref<'content' | 'design' | 'both'>('both')
const selectedVersionId = ref('')
const versionPreview = ref<PptVersionPreview | null>(null)
const versionLoading = ref(false)
const versionError = ref('')
let versionRequest = 0
let versionController: AbortController | undefined
const versionCache = new Map<string, PptVersionPreview>()
const hydratingRun = ref(false)
const imageDialogVisible = ref(false)
const imageSlideIndex = ref(0)
const imagePrompt = ref('')
const imageRevision = ref('')
const imagePage = computed(() => artifactBundle.value?.ppt?.slides[imageSlideIndex.value])
const imageJob = computed(() => currentRun.value?.output_data.ppt_image_job)

const steps = ['设置任务', '构建证据', '生成课纲', '生成成果', '预览发布']
const learningStageOptions: Array<{ value: LearningStage; label: string }> = [
  { value: 'preview', label: '课前预习' },
  { value: 'review', label: '课后巩固' },
  { value: 'exam', label: '考前冲刺' },
]
const currentStep = computed(() => activeStage.value - 1)
const chapter = computed(() => course.value?.chapters.find((item) => item.id === selectedChapterId.value) || null)
const evidence = computed(() => currentRun.value?.evidence_snapshot || [])
const outline = computed(() => currentRun.value?.output_data.outline)
const artifactBundle = computed(() => currentRun.value?.output_data.artifact_bundle)
const artifacts = computed(() => currentRun.value?.output_data.artifacts || {})
const pptVersions = computed(() => currentRun.value?.output_data.ppt_versions || [])
const historyVersions = computed(() => [...pptVersions.value].reverse().filter(item => !item.is_current))
const isBrowsingHistory = computed(() => Boolean(selectedVersionId.value))
const displayedPpt = computed(() => isBrowsingHistory.value ? versionPreview.value?.ppt : artifactBundle.value?.ppt)
const displayedArtifacts = computed(() => {
  const result: Record<string, AgentArtifact> = { ...artifacts.value }
  if (isBrowsingHistory.value) {
    delete result.ppt
    if (versionPreview.value) result.ppt = {
      kind: 'ppt', title: versionPreview.value.ppt.title, file_name: '', media_type: '',
      ...versionPreview.value.artifact, slide_count: versionPreview.value.ppt.slides.length,
    }
  }
  return result
})
const pptQuality = computed(() => displayedPpt.value?.quality_report)
const canRestoreVersion = computed(() => Boolean(isBrowsingHistory.value && !versionLoading.value
  && versionPreview.value?.version_id === selectedVersionId.value && versionPreview.value.restorable
  && !acting.value && !isExecuting.value))
function versionLabel(item: PptVersion) {
  return `${formatBeijingDateTime(item.generated_time || item.created_time)} · ${item.slide_count} 页 · ${item.title || '教学 PPT'}`
}
function versionReason(item: PptVersion) {
  return /^恢复版本.*前$/.test(item.reason) ? '切换版本前自动保存' : item.reason
}
const artifactAttempt = computed(() => currentRun.value?.output_data.artifact_attempt)
const artifactGenerationProgress = computed(() => lessonArtifactProgress(currentRun.value, {
  submitting: submittingArtifacts.value, now: progressNow.value,
}))
function isHistoricalArtifact(key: string) {
  if (!artifacts.value[key]) return false
  if (typeof artifacts.value[key]?.requires_previous_confirmation === 'boolean') return artifacts.value[key]!.requires_previous_confirmation
  const attempt = artifactAttempt.value
  if (attempt?.requested_types?.includes(key) && ['queued', 'running', 'failed'].includes(attempt.status)) return artifacts.value[key]?.attempt_id !== attempt.id
  return Boolean(currentRun.value?.output_data.artifact_errors?.[key as ArtifactKey])
}
const pptProgress = computed(() => {
  if (isExecuting.value && imageJob.value && ['queued', 'running'].includes(imageJob.value.status)) return `正在更新第 ${imageJob.value.slide_index + 1} 页配图，原课件保留至新图验证完成`
  if (!isExecuting.value && !failedArtifactStep.value) return ''
  const value = currentRun.value?.steps.find(step => step.step_key === 'generate_artifacts')?.output_data.ppt_workflow as
    { stage: string; completed_pages: number; total_pages: number; resume?: { requested?: boolean; resumed?: boolean; reused_pages?: number; reused_images?: number; pending_images?: number; generated_images?: number } } | undefined
  if (!value) return ''
  const labels: Record<string, string> = { waiting_slot: '等待课件生成资源', planning: '编排逐页教学内容', designing: '设计课件页面', illustrating: '准备辅助插图', exporting: '导出与渲染成品', completed: '成品检查完成' }
  const reused = value.resume?.reused_pages || 0
  if (value.stage === 'planning' && value.resume?.requested && !value.resume.resumed) return '没有匹配当前输入和版本的检查点，正在安全重建'
  if (value.stage === 'illustrating' && value.resume?.resumed && reused === value.total_pages) return `页面设计全部复用 · 已有 ${value.resume.reused_images || 0} 张插图 · 已补 ${value.resume.generated_images || 0} 张 · 待补 ${value.resume.pending_images ?? '—'} 张`
  return `${!isExecuting.value ? '本次停在：' : ''}${labels[value.stage] || '正在生成'}${value.total_pages ? ` · ${value.completed_pages}/${value.total_pages} 页` : ''}${reused ? `（已复用 ${reused} 页）` : ''}`
})
const isExecuting = computed(() => ['queued', 'running'].includes(currentRun.value?.status || ''))
const canStart = computed(() => Boolean(selectedCourseId.value && selectedChapterId.value) && !isExecuting.value)
const eligibleTeachingClasses = computed(() => teachingClasses.value.filter(
  (item) => !selectedCourseId.value || item.material_ids.includes(selectedCourseId.value),
))
const classroomActivities = computed(() => artifactBundle.value?.classroom_activities || [])
type ArtifactKey = 'ppt' | 'lesson_plan' | 'classroom_activities'
const artifactLabels: Record<ArtifactKey, string> = {
  ppt: '教学 PPT',
  lesson_plan: '完整教案',
  classroom_activities: '课堂活动',
}
function isArtifactKey(value: unknown): value is ArtifactKey {
  return value === 'ppt' || value === 'lesson_plan' || value === 'classroom_activities'
}
function artifactKeys(value: unknown): ArtifactKey[] {
  return Array.isArray(value) ? value.filter(isArtifactKey) : []
}
const failedArtifactStep = computed(() => currentRun.value?.steps.find(
  (step) => step.step_key === 'generate_artifacts' && step.status === 'failed',
))
const requestedArtifactKeys = computed(() => artifactKeys(currentRun.value?.input_data.artifact_output_types))
const artifactStatusRows = computed(() => {
  const keys = [...new Set([...requestedArtifactKeys.value, ...artifactKeys(Object.keys(artifacts.value))])]
  return keys.map((key) => ({ key, label: artifactLabels[key], ready: Boolean(artifacts.value[key]) && !isHistoricalArtifact(key), historical: isHistoricalArtifact(key) }))
})
const incompleteArtifactKeys = computed(() => [...new Set([
  ...artifactStatusRows.value.filter((item) => !item.ready).map((item) => item.key),
  ...artifactKeys(Object.keys(currentRun.value?.output_data.artifact_errors || {})),
  ...(failedArtifactStep.value ? requestedArtifactKeys.value : []),
])])
const publicationPpt = computed(() => pptPublicationState(currentRun.value))
const canPublish = computed(() => Boolean(
  currentRun.value
  && currentRun.value.status === 'completed' && currentRun.value.current_step >= 3
  && !acting.value
  && !isExecuting.value
  && !isBrowsingHistory.value
  && selectedTeachingClassId.value
  && publicationConfirmed.value
  && publishTitle.value.trim().length >= 2
  && (!publishPpt.value || (publicationPpt.value.valid && (!publicationPpt.value.previous || previousPptConfirmed.value)))
  && (!publishDiscussions.value || (classroomActivities.value.length && selectedDiscussionIndices.value.length))
  && (publishPpt.value || publishDiscussions.value),
))
const maxAvailableStage = computed(() => {
  if (!currentRun.value) return 1
  if (Object.keys(artifacts.value).length) return 5
  if (outline.value) return 4
  if (evidence.value.length) return 2
  return 1
})
const runStatus = computed(() => {
  if (imageJob.value?.status === 'failed') return '配图更新失败，已保留原课件'
  if (failedArtifactStep.value || artifactAttempt.value?.status === 'failed') return '课纲已完成，本次成果生成失败'
  if (artifactAttempt.value?.status === 'partial') return '课件已生成，部分成果或插图未完成'
  if (currentRun.value?.status === 'completed' && currentRun.value.current_step >= 3) {
    return '教学成果已生成'
  }
  const labels: Record<string, string> = {
    queued: '等待执行',
    running: '正在生成',
    waiting_confirmation: '等待教师确认',
    completed: '课纲已生成',
    failed: '生成失败',
    cancelled: '已取消',
  }
  return labels[currentRun.value?.status || ''] || '尚未开始'
})
const runStatusType = computed(() => {
  if (imageJob.value?.status === 'failed') return 'warning'
  if (failedArtifactStep.value || artifactAttempt.value?.status === 'partial' || artifactAttempt.value?.status === 'failed') return 'warning'
  if (currentRun.value?.status === 'failed') return 'danger'
  if (currentRun.value?.status === 'completed') return 'success'
  if (currentRun.value?.status === 'waiting_confirmation') return 'warning'
  return 'info'
})

async function loadCourse(courseId: number, preferredChapterId?: number | null) {
  const response = await courseApi.detail(courseId)
  course.value = response.data.data
  selectedChapterId.value = preferredChapterId && course.value.chapters.some((item) => item.id === preferredChapterId)
    ? preferredChapterId
    : course.value.chapters[0]?.id
}

function resetRun() {
  if (isExecuting.value) return
  currentRun.value = null
  pptPreferences.value.title = ''
  activeStage.value = 1
  publishedResult.value = null
}

async function applyRun(run: AgentRun) {
  hydratingRun.value = true
  try {
    currentRun.value = run
    selectedCourseId.value = run.course_id || courses.value[0]?.id
    if (selectedCourseId.value) await loadCourse(selectedCourseId.value, run.chapter_id)
    selectedTeachingClassId.value = run.teaching_class_id || eligibleTeachingClasses.value[0]?.id
    lessonHours.value = Number(run.input_data.lesson_hours || 2)
    learningStage.value = learningStageOptions.some((item) => item.value === run.input_data.learning_stage)
      ? run.input_data.learning_stage as LearningStage
      : 'preview'
    studentLevel.value = String(run.input_data.student_level || '本科生')
    completionCondition.value = String(run.input_data.completion_condition || '教材阅读')
    teachingGoal.value = String(run.input_data.teaching_goal || '')
    if (run.input_data.ppt_preferences) {
      const savedPreferences = run.input_data.ppt_preferences as Partial<PptPreferences>
      pptPreferences.value = { ...pptPreferences.value, ...savedPreferences, title: savedPreferences.title || '' }
      setSlideCount(pptPreferences.value.slide_count || pptPreferences.value.min_slides || 10)
    } else pptPreferences.value.title = ''
    syncArtifactInput(run)
    syncRunStage(run)
    if (['queued', 'running'].includes(run.status)) void listenToRun(run.id)
  } finally {
    hydratingRun.value = false
  }
}

async function openRunFromRoute() {
  const runId = Number(route.query.run_id)
  if (!Number.isFinite(runId) || runId < 1 || currentRun.value?.id === runId) return
  try {
    const response = await agentApi.detail(runId)
    await applyRun(response.data.data)
    ElMessage.success(`已打开 Agent 创建的备课草稿 #${runId}`)
  } catch {
    ElMessage.warning('无法打开指定备课草稿，已保留当前任务')
  }
}

function goStage(stage: number) {
  if (stage > maxAvailableStage.value) {
    ElMessage.info(`请先完成“${steps[stage - 2]}”`)
    return
  }
  activeStage.value = stage
}

function setSlideCount(value: number) {
  const count = Math.max(6, Math.min(30, Math.round(value || 10)))
  pptPreferences.value.slide_count = count
  pptPreferences.value.min_slides = count
  pptPreferences.value.max_slides = count
}

function changeSlideCount(delta: number) {
  setSlideCount((pptPreferences.value.slide_count || 10) + delta)
}

function handleSlideCountChange(event: Event) {
  setSlideCount(Number((event.target as HTMLInputElement).value))
}

function changeLessonHours(delta: number) {
  lessonHours.value = Math.max(1, Math.min(8, lessonHours.value + delta))
}

function syncArtifactInput(run: AgentRun) {
  if (run.current_step < 3) return
  const actual = run.input_data.ppt_preferences as Partial<PptPreferences> | undefined
  if (actual) {
    pptPreferences.value = { ...pptPreferences.value, ...actual, title: actual.title || '' }
    setSlideCount(actual.slide_count || actual.min_slides || 10)
  }
  const requested = artifactKeys(run.input_data.artifact_output_types)
  if (requested.length) artifactTypes.value = requested
}

const progressMonitor = createAgentRunMonitor<AgentRun>({
  fetchRun: async (id, signal) => (await agentApi.detail(id, signal)).data.data,
  stream: (id, handlers, signal) => agentApi.stream(id, handlers, signal),
  onSnapshot: (run) => {
    if (currentRun.value?.id !== run.id) return
    const previous = currentRun.value
    const phaseChanged = previous.status !== run.status || previous.current_step !== run.current_step
      || previous.output_data.ppt_image_job?.status !== run.output_data.ppt_image_job?.status
    progressSyncWarning.value = ''
    currentRun.value = run
    syncArtifactInput(run)
    // Polling identical state must not pull a teacher out of a page they are
    // reviewing. Only a task phase/terminal transition changes the active tab.
    if (phaseChanged) syncRunStage(run)
  },
  onError: (_error, fatal) => {
    progressSyncWarning.value = fatal ? '无法同步当前任务，请检查登录状态或重新打开任务。'
      : '进度同步暂时中断，正在自动恢复；后台任务不受影响。'
  },
})
function syncRunStage(run: AgentRun) {
  const executing = ['queued', 'running'].includes(run.status)
  if (run.output_data.ppt_image_job && ['queued', 'running'].includes(run.output_data.ppt_image_job.status)) activeStage.value = 5
  else if (!executing && Object.keys(run.output_data.artifacts || {}).length) activeStage.value = 5
  else if (run.current_step >= 3) activeStage.value = 4
  else if (run.output_data.outline) activeStage.value = 3
  else if (run.evidence_snapshot.length) activeStage.value = 2
  else activeStage.value = 1
}
function listenToRun(id: number) {
  progressMonitor.start(id)
}
function refreshVisibleProgress() {
  if (!document.hidden) progressMonitor.refresh()
}

async function startAgent() {
  if (!selectedCourseId.value || !selectedChapterId.value) {
    ElMessage.warning('请先选择课程与教材专题')
    return
  }
  acting.value = true
  try {
    const response = await agentApi.create({
      agent_type: 'teacher_lesson_prep',
      course_id: selectedCourseId.value,
      chapter_id: selectedChapterId.value,
      teaching_class_id: selectedTeachingClassId.value || null,
      input: {
        lesson_hours: lessonHours.value,
        learning_stage: learningStage.value,
        student_level: studentLevel.value,
        completion_condition: completionCondition.value.trim() || null,
        teaching_goal: teachingGoal.value.trim() || null,
        output_types: ['outline'],
      },
    })
    currentRun.value = response.data.data
    if (currentRun.value.status === 'failed') {
      ElMessage.error(currentRun.value.error_message || '证据包构建失败')
    } else {
      ElMessage.success('证据包已构建，请核验后确认')
      activeStage.value = 2
    }
  } finally {
    acting.value = false
  }
}

async function confirmEvidence() {
  if (!currentRun.value) return
  await ElMessageBox.confirm(
    `确认将当前 ${evidence.value.length} 条资料冻结为本次课纲的证据快照吗？确认后开始后台生成。`,
    '确认备课证据',
    { confirmButtonText: '确认并生成课纲', cancelButtonText: '继续核验', type: 'warning' },
  )
  acting.value = true
  try {
    const response = await agentApi.confirmEvidence(currentRun.value.id)
    currentRun.value = response.data.data
    activeStage.value = 3
    ElMessage.success('已进入后台生成，可以离开本页面')
    void listenToRun(currentRun.value.id)
  } finally {
    acting.value = false
  }
}

async function generateArtifacts() {
  if (!currentRun.value || !artifactTypes.value.length) {
    ElMessage.warning('请至少选择一种教学成果')
    return
  }
  setSlideCount(pptPreferences.value.slide_count)
  const selectedTypes = [...artifactTypes.value]
  const selectedPreferences = { ...pptPreferences.value, title: pptPreferences.value.title?.trim() || null }
  const requestSummary = selectedTypes.map(key => key === 'ppt'
    ? `教学 PPT${selectedPreferences.title ? `《${selectedPreferences.title}》` : ''}（${selectedPreferences.slide_count} 页）` : artifactLabels[key]).join('、')
  await ElMessageBox.confirm(
    `将根据当前已确认课纲生成：${requestSummary}。生成后仍需教师预览核验，不会自动发布。`,
    '生成教学成果',
    { confirmButtonText: '开始后台生成', cancelButtonText: '取消', type: 'warning' },
  )
  acting.value = true
  submittingArtifacts.value = true
  try {
    const response = await agentApi.generateArtifacts(
      currentRun.value.id,
      selectedTypes,
      selectedPreferences,
    )
    currentRun.value = response.data.data
    activeStage.value = 4
    ElMessage.success('教学成果已进入后台生成，可以离开本页面')
    void listenToRun(currentRun.value.id)
  } finally {
    submittingArtifacts.value = false
    acting.value = false
  }
}

async function retryArtifact(key: ArtifactKey) {
  if (!currentRun.value || isExecuting.value) return
  acting.value = true
  submittingArtifacts.value = true
  try {
    const response = await agentApi.generateArtifacts(
      currentRun.value.id,
      [key],
      key === 'ppt' ? pptPreferences.value : undefined,
      key === 'ppt',
    )
    currentRun.value = response.data.data
    activeStage.value = 4
    ElMessage.success(key === 'ppt' ? '已继续生成未完成部分；输入变化时会安全重建' : `${artifactLabels[key]}已重新进入后台生成`)
    void listenToRun(currentRun.value.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : `${artifactLabels[key]}重试失败，请稍后重试`)
  } finally {
    submittingArtifacts.value = false
    acting.value = false
  }
}

function preparePublication() {
  if (!currentRun.value || !Object.keys(artifacts.value).length) return
  publishTitle.value = publishTitle.value || `${chapter.value?.title || outline.value?.title || '专题'}教学成果`
  publishDescription.value = publishDescription.value || '本次课程的教学课件与课堂讨论任务。'
  selectedDiscussionIndices.value = classroomActivities.value.map((_, index) => index)
  publishPpt.value = Boolean(artifacts.value.ppt)
  publishDiscussions.value = Boolean(classroomActivities.value.length)
  publicationConfirmed.value = false
  previousPptConfirmed.value = false
  activeStage.value = 5
}

async function publishLesson() {
  if (!currentRun.value || !selectedTeachingClassId.value) {
    ElMessage.warning('请选择要发布到的教学班')
    return
  }
  if (!canPublish.value) {
    ElMessage.warning('请选择发布内容并完成最终确认')
    return
  }
  // Bind the confirmation dialog to a snapshot, not reactive state that can
  // change while the teacher is deciding in another tab or during polling.
  const runId = currentRun.value.id
  const payload = {
    teaching_class_id: selectedTeachingClassId.value,
    title: publishTitle.value.trim(),
    description: publishDescription.value.trim(),
    publish_ppt: publishPpt.value,
    publish_discussions: publishDiscussions.value,
    discussion_indices: publishDiscussions.value ? [...selectedDiscussionIndices.value] : [],
    confirmed: true,
    expected_ppt_revision: publishPpt.value ? publicationPpt.value.revision : undefined,
    allow_previous_ppt: publishPpt.value && publicationPpt.value.previous && previousPptConfirmed.value,
  }
  const confirmed = await ElMessageBox.confirm(
    `${payload.allow_previous_ppt ? '本次将发布保留的上一版 PPT。' : ''}发布后，学生可下载课件，所选讨论会直接出现在课堂互动中。是否继续？`,
    '确认发布教学成果',
    { confirmButtonText: '确认发布', cancelButtonText: '返回核验', type: 'warning' },
  ).then(() => true, () => false)
  if (!confirmed) return
  if (!canPublish.value || currentRun.value?.id !== runId) {
    ElMessage.warning('待发布内容已变化，请重新核验并确认')
    return
  }
  acting.value = true
  try {
    const response = await agentApi.publish(runId, payload)
    publishedResult.value = response.data.data
    ElMessage.success('教学成果已发布，学生端可以访问')
  } catch (error) {
    publicationConfirmed.value = false
    previousPptConfirmed.value = false
    ElMessage.error(versionFailure(error, '发布失败，课件已保留，请重新核验后重试'))
  } finally {
    acting.value = false
  }
}

function chooseTemplateFile(event: Event) {
  const input = event.target as HTMLInputElement
  templateFile.value = input.files?.[0] || null
  if (templateFile.value && !templateName.value) {
    templateName.value = templateFile.value.name.replace(/\.pptx$/i, '')
  }
}

async function uploadPptTemplate() {
  if (!templateFile.value || !templateName.value.trim()) {
    ElMessage.warning('请选择 PPTX 文件并填写模板名称')
    return
  }
  acting.value = true
  try {
    const form = new FormData()
    form.append('name', templateName.value.trim())
    form.append('description', templateDescription.value.trim())
    form.append('is_shared', 'false')
    form.append('file', templateFile.value)
    const response = await agentApi.uploadPptTemplate(form)
    pptTemplates.value.unshift(response.data.data)
    pptPreferences.value.template_id = response.data.data.id
    templateDialogVisible.value = false
    templateName.value = ''
    templateDescription.value = ''
    templateFile.value = null
    ElMessage.success('模板解析完成，已选为本次 PPT 风格参考')
  } finally {
    acting.value = false
  }
}

function openSlideRevision(index: number) {
  if (isBrowsingHistory.value) return
  revisingSlideIndex.value = index
  revisionInstruction.value = ''
  revisionMode.value = 'both'
  slideRevisionVisible.value = true
}

function openImageRevision(index: number) {
  if (isBrowsingHistory.value) return
  imageSlideIndex.value = index
  imagePrompt.value = artifactBundle.value?.ppt?.slides[index]?.visual_prompt || ''
  imageRevision.value = artifactBundle.value?.ppt?.revision_id || ''
  imageDialogVisible.value = true
}

async function replaceImage() {
  if (isBrowsingHistory.value) return
  if (!currentRun.value || imagePrompt.value.trim().length < 10) {
    ElMessage.warning('请用至少 10 个字描述需要的画面')
    return
  }
  acting.value = true
  try {
    const response = await agentApi.replacePptImage(currentRun.value.id, imageSlideIndex.value,
      imagePrompt.value.trim(), imageRevision.value)
    currentRun.value = response.data.data
    imageDialogVisible.value = false
    ElMessage.success('仅更新这一张配图，文字、版式和其他图片保持不变')
    void listenToRun(currentRun.value.id)
  } finally { acting.value = false }
}

async function reviseSlide() {
  if (isBrowsingHistory.value) return
  if (!currentRun.value || !revisionInstruction.value.trim()) {
    ElMessage.warning('请说明希望如何修改本页')
    return
  }
  acting.value = true
  try {
    const response = await agentApi.revisePptSlide(
      currentRun.value.id,
      revisingSlideIndex.value,
      revisionInstruction.value.trim(),
      revisionMode.value,
    )
    currentRun.value = response.data.data
    slideRevisionVisible.value = false
    ElMessage.success('本页已更新，上一版本已保存')
  } finally {
    acting.value = false
  }
}

function versionFailure(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

async function loadVersionPreview() {
  const request = ++versionRequest
  versionController?.abort()
  versionPreview.value = null
  versionError.value = ''
  versionLoading.value = false
  if (!currentRun.value || !selectedVersionId.value) return
  const runId = currentRun.value.id
  const versionId = selectedVersionId.value
  artifactPreview.value = 'ppt'
  const cacheKey = `${runId}:${versionId}`
  if (versionCache.has(cacheKey)) {
    versionPreview.value = versionCache.get(cacheKey)!
    return
  }
  versionController = new AbortController()
  versionLoading.value = true
  try {
    const response = await agentApi.previewPptVersion(runId, versionId, versionController.signal)
    if (request !== versionRequest) return
    versionPreview.value = response.data.data
    versionCache.set(cacheKey, response.data.data)
    if (versionCache.size > 10) versionCache.delete(versionCache.keys().next().value!)
  } catch (error) {
    if (request === versionRequest) versionError.value = versionFailure(error, '历史版本读取失败，请重试；当前版本未被修改')
  } finally {
    if (request === versionRequest) versionLoading.value = false
  }
}

async function restorePptVersion() {
  if (!currentRun.value || !canRestoreVersion.value || !versionPreview.value) return
  const runId = currentRun.value.id
  const versionId = selectedVersionId.value
  const revision = artifactBundle.value?.ppt?.revision_id || ''
  const label = versionLabel(versionPreview.value)
  try {
    await ElMessageBox.confirm(`将“${label}”设为当前课件，后续修改、下载和发布均使用此版本。原课件会自动保留在历史版本中。`, '设为当前版本', {
      confirmButtonText: '确认切换', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  if (currentRun.value?.id !== runId || selectedVersionId.value !== versionId || !canRestoreVersion.value) return
  acting.value = true
  try {
    const response = await agentApi.restorePptVersion(runId, versionId, revision)
    if (currentRun.value?.id !== runId) return
    currentRun.value = response.data.data
    selectedVersionId.value = ''
    publicationConfirmed.value = false
    publishedResult.value = null
    versionCache.clear()
    ElMessage.success('已设为当前版本，原课件已保留，可随时切回')
  } catch (error) {
    ElMessage.error(versionFailure(error, '版本切换失败，当前课件保持不变，请重试'))
    // Refresh metadata after a concurrent edit or a missing-file error. Do not
    // silently retry a write against the newly fetched version.
    try {
      const refreshed = (await agentApi.detail(runId)).data.data
      if (currentRun.value?.id !== runId) return
      currentRun.value = refreshed
    } catch { /* keep the known state */ }
    versionCache.clear()
    void loadVersionPreview()
  } finally {
    acting.value = false
  }
}

async function downloadArtifact(key: string) {
  if (!currentRun.value) return
  const artifact = displayedArtifacts.value[key]
  if (!artifact) return
  if (key === 'ppt' && isBrowsingHistory.value && !versionPreview.value?.restorable) return
  try {
    const response = await agentApi.downloadArtifact(currentRun.value.id, key,
      key === 'ppt' && isBrowsingHistory.value ? selectedVersionId.value : undefined,
      key === 'ppt' && !isBrowsingHistory.value ? artifactBundle.value?.ppt?.revision_id || '' : undefined)
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = artifact.file_name
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch { ElMessage.error('下载失败，文件可能已变化，请刷新后重试') }
}

async function cancelRun() {
  if (!currentRun.value) return
  const response = await agentApi.cancel(currentRun.value.id)
  currentRun.value = response.data.data
  ElMessage.info('任务已请求取消')
}

async function retryRun() {
  if (!currentRun.value) return
  acting.value = true
  try {
    const response = await agentApi.retry(currentRun.value.id)
    currentRun.value = response.data.data
    ElMessage.success('已重新构建证据包')
  } finally {
    acting.value = false
  }
}

onMounted(async () => {
  try {
    const [courseResponse, runResponse, templateResponse, classResponse, capabilityResponse] = await Promise.all([
      courseApi.list(),
      agentApi.list(10),
      agentApi.listPptTemplates(),
      teachingClassApi.list(),
      agentApi.capabilities(),
    ])
    courses.value = courseResponse.data.data
    pptTemplates.value = templateResponse.data.data
    teachingClasses.value = classResponse.data.data.filter((item) => ['active', 'not_started'].includes(item.status))
    capabilities.value = capabilityResponse.data.data
    if (!capabilities.value.ppt_multimodal_available) pptPreferences.value.include_visuals = false
    const requestedRunId = Number(route.query.run_id)
    const latest = runResponse.data.data.find((item) => item.id === requestedRunId)
      || runResponse.data.data.find((item) => item.agent_type === 'teacher_lesson_prep')
      || null
    if (latest) await applyRun(latest)
    else if (courses.value[0]?.id) {
      selectedCourseId.value = courses.value[0].id
      await loadCourse(courses.value[0].id)
    }
    if (Number.isFinite(requestedRunId) && requestedRunId > 0 && latest?.id !== requestedRunId) {
      await openRunFromRoute()
    }
  } finally {
    loading.value = false
  }
})

watch(selectedCourseId, async (value, previous) => {
  if (value && previous && value !== previous && !hydratingRun.value) {
    resetRun()
    await loadCourse(value)
    if (!eligibleTeachingClasses.value.some((item) => item.id === selectedTeachingClassId.value)) {
      selectedTeachingClassId.value = eligibleTeachingClasses.value[0]?.id
    }
  }
})
watch(selectedChapterId, (value, previous) => {
  if (value && previous && value !== previous && value !== currentRun.value?.chapter_id) resetRun()
})
watch(artifacts, (value) => {
  const keys = Object.keys(value) as Array<'ppt' | 'lesson_plan' | 'classroom_activities'>
  if (keys.length && !keys.includes(artifactPreview.value)) artifactPreview.value = keys[0]
})
watch([
  () => currentRun.value?.id, () => publicationPpt.value.revision,
  () => publicationPpt.value.previous, () => currentRun.value?.output_data.artifact_attempt?.id,
  selectedTeachingClassId, publishPpt, publishDiscussions,
  () => selectedDiscussionIndices.value.join(','), publishTitle, publishDescription,
], () => {
  publicationConfirmed.value = false
  previousPptConfirmed.value = false
}, { flush: 'sync' })
watch(() => pptPreferences.value.slide_count, (value) => setSlideCount(value || 10))
watch(() => route.query.run_id, () => { void openRunFromRoute() })
watch(selectedVersionId, () => { void loadVersionPreview() })
watch(() => currentRun.value?.id, () => {
  selectedVersionId.value = ''
  versionCache.clear()
  void loadVersionPreview()
})
watch(() => [currentRun.value?.id, currentRun.value?.status] as const, ([id, status]) => {
  if (id && status && ['queued', 'running'].includes(status)) listenToRun(id)
  else progressMonitor.stop()
  progressSyncWarning.value = ''
}, { flush: 'sync' })
onMounted(() => {
  document.addEventListener('visibilitychange', refreshVisibleProgress)
  window.addEventListener('online', refreshVisibleProgress)
  progressClock = setInterval(() => {
    if (isExecuting.value || submittingArtifacts.value) progressNow.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => {
  progressMonitor.stop()
  document.removeEventListener('visibilitychange', refreshVisibleProgress)
  window.removeEventListener('online', refreshVisibleProgress)
  versionRequest++; versionController?.abort(); versionCache.clear()
  if (progressClock) clearInterval(progressClock)
})
</script>

<template>
  <div v-loading="loading" class="lesson-prep-workspace">
    <header class="prep-page-header">
      <div class="prep-page-brand">
        <img :src="logoUrl" alt="思政红芯" class="prep-page-logo">
        <div>
          <p class="prep-page-eyebrow">LESSON PREPARATION</p>
          <h1>课程备课</h1>
          <p class="prep-page-description">先确定教学专题，再冻结证据快照并生成课纲草稿；任何发布操作仍由教师确认。</p>
        </div>
      </div>
      <div class="prep-page-actions">
        <StatusChip :label="runStatus" :status="runStatusType" />
        <span v-if="pptProgress" role="status">{{ pptProgress }}</span>
        <el-button @click="router.push('/courses')">查看教材专题</el-button>
        <el-button @click="router.push('/knowledge')">管理资料</el-button>
      </div>
    </header>

    <UiCard class="prep-progress-card" :style="{ backgroundImage: `url(${progressBackgroundUrl})` }">
      <ol class="prep-step-progress" aria-label="任务步骤">
        <li
          v-for="(step, index) in steps"
          :key="step"
          :class="{ active: index === currentStep, completed: index < currentStep, locked: index + 1 > maxAvailableStage }"
          :aria-current="index === currentStep ? 'step' : undefined"
        >
          <span class="prep-step-node">{{ index + 1 }}</span>
          <strong>{{ step }}</strong>
        </li>
      </ol>
      <nav class="stage-navigation" aria-label="备课步骤导航">
        <button
          v-for="(step, index) in steps"
          :key="step"
          type="button"
          :class="{ active: activeStage === index + 1, available: index + 1 <= maxAvailableStage }"
          :disabled="index + 1 > maxAvailableStage"
          @click="goStage(index + 1)"
        >
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          {{ step }}
        </button>
      </nav>
      <div v-if="currentRun" class="run-toolbar">
        <span>任务 #{{ currentRun.id }} · {{ currentRun.model_name }} · {{ currentRun.prompt_version }}</span>
        <el-button v-if="isExecuting" text type="danger" @click="cancelRun">中止任务</el-button>
        <el-button v-if="['failed', 'cancelled'].includes(currentRun.status) && !outline" text type="primary" @click="retryRun">重新执行</el-button>
      </div>
    </UiCard>

    <el-alert
      v-if="currentRun?.error_message"
      :title="currentRun.error_message"
      type="error"
      show-icon
      :closable="false"
    />

    <section class="prep-grid">
      <UiCard v-show="activeStage === 1" class="prep-settings stage-card" :style="{ '--prep-context-bg': `url(${contextBackgroundUrl})` }">
        <template #title>
          <div><p class="eyebrow">01 · CONTEXT</p><h2>教学任务</h2></div>
        </template>
        <div class="prep-settings-body">
          <el-form label-position="top">
            <el-form-item>
              <template #label><span class="prep-field-label">目标教学班 <i>*</i></span></template>
              <el-select v-model="selectedTeachingClassId" :disabled="isExecuting" placeholder="任务将发布到具体教学班">
                <el-option
                  v-for="item in eligibleTeachingClasses"
                  :key="item.id"
                  :label="`${item.name} · ${item.term_name}`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <div class="compact-form-row prep-context-row">
              <el-form-item>
                <template #label><span class="prep-field-label">课程 <i>*</i></span></template>
                <el-select v-model="selectedCourseId" :disabled="isExecuting" placeholder="选择课程">
                  <el-option v-for="item in courses" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <template #label><span class="prep-field-label">专题章节 <i>*</i></span></template>
                <el-select v-model="selectedChapterId" :disabled="isExecuting" placeholder="选择专题">
                  <el-option v-for="item in course?.chapters || []" :key="item.id" :label="item.title" :value="item.id" />
                </el-select>
              </el-form-item>
            </div>
            <div class="compact-form-row prep-context-row">
              <el-form-item>
                <template #label><span class="prep-field-label">学习阶段 <i>*</i></span></template>
                <el-select v-model="learningStage" :disabled="isExecuting" placeholder="选择学习阶段">
                  <el-option
                    v-for="item in learningStageOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
              </el-form-item>
              <el-form-item>
                <template #label><span class="prep-field-label">课时安排 <i>*</i></span></template>
                <div class="prep-number-control" :class="{ 'is-disabled': isExecuting }">
                  <button type="button" aria-label="减少课时" :disabled="isExecuting || lessonHours <= 1" @click="changeLessonHours(-1)">−</button>
                  <input v-model.number="lessonHours" type="number" min="1" max="8" :disabled="isExecuting" aria-label="课时数">
                  <button type="button" aria-label="增加课时" :disabled="isExecuting || lessonHours >= 8" @click="changeLessonHours(1)">＋</button>
                </div>
              </el-form-item>
            </div>
            <div class="compact-form-row prep-context-row">
              <el-form-item>
                <template #label><span class="prep-field-label">学生层次 <i>*</i></span></template>
                <el-select v-model="studentLevel" :disabled="isExecuting">
                  <el-option label="本科生" value="本科生" />
                  <el-option label="高职学生" value="高职学生" />
                  <el-option label="研究生" value="研究生" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <template #label><span class="prep-field-label">完成条件 <small>（选修）</small></span></template>
                <el-input
                  v-model="completionCondition"
                  :disabled="isExecuting"
                  maxlength="200"
                  placeholder="例如：完成教材阅读并提交学习卡片"
                />
              </el-form-item>
            </div>
            <el-form-item>
              <template #label><span class="prep-field-label">任务要求 <i>*</i></span></template>
              <el-input v-model="teachingGoal" type="textarea" :rows="4" :disabled="isExecuting" placeholder="说明学习重点和具体要求，例如：围绕本专题梳理核心概念并准备课堂讨论。" />
            </el-form-item>
          </el-form>
          <div class="prep-settings-footer">
            <span>带 * 的项目用于生成更准确的课纲，提交后仍可在证据阶段核验资料。</span>
            <el-button type="primary" :loading="acting" :disabled="!canStart" @click="startAgent">
              构建备课证据包
            </el-button>
          </div>
        </div>
      </UiCard>

      <UiCard v-show="activeStage === 2" class="prep-evidence stage-card">
        <template #title>
          <div><p class="eyebrow">02 · EVIDENCE</p><h2>证据快照</h2></div>
        </template>
        <template #actions>
          <StatusChip :label="`${evidence.length} 条资料`" :status="evidence.length ? 'success' : 'warning'" />
        </template>
        <div v-if="evidence.length" class="evidence-list">
          <EvidenceCard
            v-for="(item, index) in evidence"
            :key="`${item.document_id}-${item.vector_id}-${index}`"
            :title="`[资料${index + 1}] ${item.source_title}`"
            :source="item.publisher || item.evidence_type"
            :published-date="item.published_date"
            :authority="item.material_type === 'central'"
            :status-label="item.material_type === 'textbook' ? '教材' : undefined"
            :source-url="item.source_url"
            :excerpt="`${item.position} · ${item.excerpt}`"
          />
          <el-button
            v-if="currentRun?.status === 'waiting_confirmation'"
            type="primary"
            :loading="acting"
            @click="confirmEvidence"
          >
            确认证据并生成课纲
          </el-button>
        </div>
        <UiEmptyState
          v-else
          title="尚未构建证据快照"
          description="设置课程、专题、课时和学生层次后启动任务。Agent 只会使用当前可检索的教材与已发布权威资料。"
        />
      </UiCard>

      <UiCard v-show="activeStage === 3 || activeStage === 4" class="prep-output stage-card">
        <template #title>
          <div>
            <p class="eyebrow">{{ activeStage === 3 ? '03 · OUTLINE' : '04 · DELIVERABLES' }}</p>
            <h2>{{ activeStage === 3 ? '课纲草稿' : '生成教学成果' }}</h2>
            <el-tag size="small" type="info">AI 生成内容 · 发布前须由教师核验</el-tag>
          </div>
        </template>
        <div v-if="outline" class="outline-document">
          <div v-if="activeStage === 3" class="outline-content">
            <h3>{{ outline.title }}</h3>
            <section><h4>课程定位</h4><p>{{ outline.positioning }}</p></section>
            <section>
              <h4>教学目标</h4>
              <dl class="objective-list">
                <div><dt>知识</dt><dd>{{ outline.objectives.knowledge.join('；') }}</dd></div>
                <div><dt>能力</dt><dd>{{ outline.objectives.ability.join('；') }}</dd></div>
                <div><dt>价值</dt><dd>{{ outline.objectives.values.join('；') }}</dd></div>
              </dl>
            </section>
            <section><h4>教学重点</h4><ul><li v-for="item in outline.key_points" :key="item">{{ item }}</li></ul></section>
            <section><h4>教学难点</h4><ul><li v-for="item in outline.difficult_points" :key="item">{{ item }}</li></ul></section>
            <section>
              <h4>教学流程</h4>
              <article v-for="item in outline.teaching_flow" :key="`${item.stage}-${item.duration_minutes}`" class="flow-item">
                <strong>{{ item.stage }} · {{ item.duration_minutes }} 分钟</strong>
                <p>教师：{{ item.teacher_activity }}</p>
                <p>学生：{{ item.student_activity }}</p>
                <small>依据：{{ item.evidence_refs.join('、') }}</small>
              </article>
            </section>
            <section><h4>讨论问题</h4><ol><li v-for="item in outline.discussion_questions" :key="item">{{ item }}</li></ol></section>
            <section><h4>课后任务建议</h4><p>{{ outline.after_class_task }}</p></section>
            <el-alert title="当前为教师草稿，尚未发布到教学班" type="warning" :closable="false" show-icon />
            <el-button type="primary" @click="goStage(4)">课纲确认，进入成果生成</el-button>
          </div>
          <section v-else class="artifact-builder">
            <h4>生成教学成果</h4>
            <el-checkbox-group v-model="artifactTypes" :disabled="isExecuting">
              <el-checkbox-button value="ppt">教学 PPT</el-checkbox-button>
              <el-checkbox-button value="lesson_plan">完整教案</el-checkbox-button>
              <el-checkbox-button value="classroom_activities">课堂活动</el-checkbox-button>
            </el-checkbox-group>
            <section v-if="failedArtifactStep && incompleteArtifactKeys.length" class="artifact-retry-banner">
              <div>
                <strong>有成果未完成</strong>
                <p>{{ failedArtifactStep.error_message || '上次生成没有返回可用结果。已完成的成果会保留，无需全部重做。' }}</p>
              </div>
              <div class="artifact-retry-actions">
                <el-button
                  v-for="key in incompleteArtifactKeys"
                  :key="key"
                  size="small"
                  type="warning"
                  plain
                  :loading="acting"
                  @click="retryArtifact(key)"
                >
                  {{ key === 'ppt' ? '继续生成未完成部分' : `重试${artifactLabels[key]}` }}
                </el-button>
              </div>
            </section>
            <div v-if="artifactTypes.includes('ppt')" class="ppt-preferences">
              <div class="preference-heading">
                <div>
                  <strong>PPT 生成偏好</strong>
                </div>
                <el-button plain @click="templateDialogVisible = true">上传模板</el-button>
              </div>
              <div class="preference-grid">
                <el-form-item label="PPT 名称" class="ppt-title-field">
                  <el-input :model-value="pptPreferences.title || ''" @update:model-value="pptPreferences.title = String($event)"
                    :disabled="acting || isExecuting" maxlength="60" show-word-limit clearable
                    placeholder="自定义课件名称，留空则自动命名" />
                </el-form-item>
                <el-form-item label="使用场景">
                  <el-select v-model="pptPreferences.scenario">
                    <el-option label="日常课堂" value="classroom" />
                    <el-option label="公开课" value="open_lesson" />
                    <el-option label="汇报展示" value="presentation" />
                  </el-select>
                </el-form-item>
                <el-form-item label="视觉风格">
                  <el-select v-model="pptPreferences.visual_style">
                    <el-option label="庄重典雅" value="serious" />
                    <el-option label="现代简洁" value="modern" />
                    <el-option label="青年化表达" value="youthful" />
                  </el-select>
                </el-form-item>
                <el-form-item label="内容密度">
                  <el-select v-model="pptPreferences.content_density">
                    <el-option label="精简" value="concise" />
                    <el-option label="标准" value="standard" />
                    <el-option label="详细" value="detailed" />
                  </el-select>
                </el-form-item>
                <el-form-item label="图片形状">
                  <el-select v-model="pptPreferences.image_frame_shape" :disabled="isExecuting">
                    <el-option label="圆角矩形（推荐多人场景）" value="roundRect" />
                    <el-option label="圆形（主体居中裁切）" value="circle" />
                  </el-select>
                </el-form-item>
                <el-form-item label="风格模板">
                  <el-select v-model="pptPreferences.template_id" clearable placeholder="由 Agent 自主设计">
                    <el-option
                      v-for="item in pptTemplates"
                      :key="item.id"
                      :label="`${item.name} · ${item.slide_count}页`"
                      :value="item.id"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="PPT 页数">
                  <div class="slide-count-control" aria-label="设置 PPT 页数">
                    <button type="button" :disabled="isExecuting || pptPreferences.slide_count <= 6" @click="changeSlideCount(-1)">−</button>
                    <label>
                      <input
                        v-model.number="pptPreferences.slide_count"
                        :disabled="isExecuting"
                        type="number"
                        min="6"
                        max="30"
                        inputmode="numeric"
                        @change="handleSlideCountChange"
                      >
                      <span>页</span>
                    </label>
                    <button type="button" :disabled="isExecuting || pptPreferences.slide_count >= 30" @click="changeSlideCount(1)">＋</button>
                  </div>
                </el-form-item>
                <el-form-item label="教学增强">
                  <div class="preference-switches">
                    <el-checkbox v-model="pptPreferences.include_interaction">加入课堂互动</el-checkbox>
                    <el-tooltip
                      :content="capabilities.ppt_multimodal_available
                        ? `由 ${capabilities.ppt_multimodal_model} 生成，最多 ${capabilities.ppt_multimodal_max_images} 张`
                        : '配置阿里云百炼多模态 API Key 后开放'"
                    >
                      <el-checkbox
                        v-model="pptPreferences.include_visuals"
                        :disabled="!capabilities.ppt_multimodal_available"
                      >
                        生成辅助插图
                      </el-checkbox>
                    </el-tooltip>
                  </div>
                </el-form-item>
              </div>
            </div>
            <section v-if="artifactGenerationProgress" class="artifact-generation-progress" role="status" aria-label="教学成果生成进度">
              <div class="generation-progress-heading">
                <strong>{{ artifactGenerationProgress.label }}</strong>
                <span>阶段进度 <b>{{ artifactGenerationProgress.percentage }}%</b></span>
              </div>
              <el-progress :percentage="artifactGenerationProgress.percentage" :show-text="false" :stroke-width="10"
                :status="artifactGenerationProgress.status"
                :color="artifactGenerationProgress.status === 'success' ? '#2aa361' : artifactGenerationProgress.status === 'exception' ? '#d65360' : artifactGenerationProgress.status === 'warning' ? '#d29636' : '#ff6878'" />
              <div class="generation-progress-footnote">
                <p class="generation-progress-detail">{{ artifactGenerationProgress.detail }}</p>
                <span v-if="artifactGenerationProgress.elapsed">{{ artifactGenerationProgress.elapsed }}</span>
              </div>
              <p v-if="progressSyncWarning" class="generation-progress-detail">{{ progressSyncWarning }}</p>
            </section>
            <el-button
              type="primary"
              :loading="acting || (isExecuting && currentRun?.current_step === 3)"
              :disabled="!artifactTypes.length || isExecuting"
              @click="generateArtifacts"
            >
              {{ Object.keys(artifacts).length ? '重新生成所选成果' : '生成所选成果' }}
            </el-button>
            <el-button
              v-if="Object.keys(artifacts).length && !isExecuting"
              plain
              @click="preparePublication"
            >
              进入预览发布
            </el-button>
          </section>
        </div>
        <div v-else-if="isExecuting" class="generating-state">
          <el-progress :percentage="currentRun?.status === 'running' ? 65 : 35" :indeterminate="currentRun?.status === 'running'" />
          <strong>正在依据已确认资料生成课纲</strong>
          <p>任务会在后台继续运行，可以离开本页面后再回来查看。</p>
        </div>
        <UiEmptyState
          v-else
          title="等待课纲生成"
          description="确认当前证据快照后，Agent 才会生成结构化课纲。生成、修改草稿无需再次确认，发布任务和发送通知仍需教师确认。"
        />
      </UiCard>

      <UiCard
        v-if="Object.keys(artifacts).length"
        v-show="activeStage === 5"
        class="artifact-results stage-card"
      >
        <template #title>
          <div class="artifact-results-heading"><h2>预览与发布</h2><p class="eyebrow">05 · REVIEW & PUBLISH</p></div>
        </template>
        <template #actions>
          <div class="artifact-actions">
            <StatusChip label="待教师核验" status="warning" />
          </div>
        </template>

        <section class="artifact-overview" aria-label="成果与课件版本"
          :style="{ '--artifact-overview-bg': `url(${designBriefBackgroundUrl})` }">
          <div class="artifact-overview-header">
            <div class="artifact-overview-heading">
              <strong>成果总览</strong>
              <span>草稿可下载、补生成；发布前请核验并确认。</span>
            </div>
            <div class="artifact-status-list">
              <span
                v-for="item in artifactStatusRows"
                :key="item.key"
                :class="['artifact-status-item', { 'is-ready': item.ready }]"
              >
                <span class="artifact-status-dot"></span>
                {{ item.label }} · {{ item.historical ? '保留上一版，非本次成果' : item.ready ? '已就绪' : '待补生成' }}
              </span>
            </div>
          </div>

          <div v-if="artifacts.ppt || pptVersions.length" class="ppt-version-panel" aria-label="PPT 版本管理">
            <div class="version-switcher">
              <strong class="version-caption">{{ isBrowsingHistory ? '历史版本 · 只读预览' : '当前使用的课件' }}</strong>
              <el-select :model-value="selectedVersionId || 'current'" @update:model-value="selectedVersionId = $event === 'current' ? '' : $event"
                aria-label="选择 PPT 版本" popper-class="ppt-version-options" :disabled="acting || isExecuting" :loading="versionLoading">
                <el-option :label="`当前版本 · ${artifactBundle?.ppt?.slides.length || 0} 页 · ${artifactBundle?.ppt?.title || '教学 PPT'}`" value="current" />
                <el-option v-for="item in historyVersions" :key="item.version_id"
                  :label="versionLabel(item)" :value="item.version_id">
                  <div class="version-option">
                    <span :title="versionLabel(item)">{{ versionLabel(item) }}</span>
                    <small>{{ versionReason(item) }}{{ item.design_name ? ` · 风格：${item.design_name}` : '' }}{{ item.restorable === false ? ` · ${item.unavailable_reason || '仅内容快照'}` : '' }}</small>
                  </div>
                </el-option>
              </el-select>
              <small class="version-switch-hint">选择即预览，设为当前才切换；原课件保留。</small>
            </div>
            <div v-if="isBrowsingHistory" class="version-preview-state" role="status" aria-live="polite">
              <span v-if="versionLoading">正在读取历史版本…</span>
              <span v-else-if="versionError" class="version-error">{{ versionError }}</span>
              <span v-else-if="versionPreview">
                正在预览 {{ displayedPpt?.slides.length || 0 }} 页 · {{ displayedPpt?.design?.name || displayedPpt?.title }}，当前课件未改变。
                <small v-if="!versionPreview.restorable">{{ versionPreview.unavailable_reason }}，可查看内容，不能恢复或下载。</small>
              </span>
              <div class="version-preview-actions">
                <el-button v-if="versionError" size="small" @click="loadVersionPreview">重试</el-button>
                <el-button size="small" :disabled="acting" @click="selectedVersionId = ''">返回当前版本</el-button>
                <el-button size="small" type="primary" :disabled="!canRestoreVersion" :loading="acting" @click="restorePptVersion">设为当前版本</el-button>
              </div>
            </div>
          </div>
          <div v-if="failedArtifactStep && incompleteArtifactKeys.length" class="artifact-overview-retry">
            <span>本次生成未完成：{{ failedArtifactStep.error_message }}。上一版文件仍可查看，不代表本次生成成功。</span>
            <el-button
              v-for="key in incompleteArtifactKeys"
              :key="`overview-${key}`"
              size="small"
              type="warning"
              plain
              :loading="acting"
              @click="retryArtifact(key)"
            >
              {{ key === 'ppt' ? '继续生成未完成部分' : `重试${artifactLabels[key]}` }}
            </el-button>
          </div>
        </section>

        <div class="artifact-file-grid">
          <article v-for="(item, key) in displayedArtifacts" :key="key" class="artifact-file">
            <span class="artifact-file-type">
              {{ key === 'ppt' ? 'PPTX' : 'DOCX' }}
            </span>
            <div class="artifact-file-info">
              <strong :title="item.title">{{ item.title }}</strong>
              <p v-if="item.slide_count">{{ item.slide_count }} 页课件</p>
              <p v-else-if="item.activity_count">{{ item.activity_count }} 个课堂活动</p>
              <p v-else>可编辑教学文档</p>
              <p v-if="key === 'ppt' && isBrowsingHistory">所选历史版本 · 尚未设为当前</p>
              <p v-else-if="isHistoricalArtifact(String(key))">上一成功版本 · 非本次生成成果</p>
            </div>
            <div class="artifact-file-footer">
              <small v-if="item.generated_time" :title="`生成时间：${new Date(item.generated_time).toLocaleString()}`">
                {{ new Date(item.generated_time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }}
              </small>
              <el-button size="small" type="primary" plain :aria-label="`下载${item.title}`" :disabled="key === 'ppt' && isBrowsingHistory && !versionPreview?.restorable" @click="downloadArtifact(String(key))">{{ key === 'ppt' && isBrowsingHistory ? '下载此版本' : isHistoricalArtifact(String(key)) ? '下载上一版' : '下载' }}</el-button>
            </div>
          </article>
        </div>

        <el-tabs v-model="artifactPreview" class="artifact-preview-tabs">
          <el-tab-pane v-if="artifactBundle?.ppt || isBrowsingHistory" :label="isBrowsingHistory ? '历史 PPT 预览（只读）' : isHistoricalArtifact('ppt') ? '上一版 PPT 预览（非本次）' : 'PPT 逐页预览'" name="ppt">
            <div v-if="versionLoading" class="version-loading" v-loading="true" aria-busy="true">正在切换课件预览…</div>
            <UiEmptyState v-else-if="versionError" title="历史版本读取失败" description="可重试，或返回当前版本继续使用。当前课件未被修改。" />
            <template v-else-if="displayedPpt">
            <section v-if="pptQuality && (!pptQuality.passed || pptQuality.issues.length)" class="ppt-quality" role="status">
              <div class="quality-heading">
                <strong>课件有待核验项</strong>
                <span>{{ pptQuality.summary }}</span>
              </div>
              <details v-if="pptQuality.issues.length" class="quality-details">
                <summary>查看 {{ pptQuality.issues.length }} 项检查建议</summary>
                <div class="quality-issues">
                  <button
                    v-for="(issue, issueIndex) in pptQuality.issues"
                    :key="`${issue.slide_index}-${issueIndex}`"
                    type="button"
                    :disabled="isBrowsingHistory"
                    @click="issue.slide_index !== null && openSlideRevision(issue.slide_index)"
                  >
                    <b>{{ issue.slide_index === null ? '整套' : `第 ${issue.slide_index + 1} 页` }}</b>
                    <span>{{ issue.message }}</span>
                    <small>{{ issue.suggestion }}</small>
                  </button>
                </div>
              </details>
            </section>
            <div v-if="displayedPpt.design" class="ppt-design-brief"
              :style="{ backgroundImage: `url(${designBriefBackgroundUrl})` }">
              <div>
                <small>VISUAL DIRECTION</small>
                <strong>{{ displayedPpt.design.name }}</strong>
                <p>{{ displayedPpt.design.concept }}</p>
                <p v-if="displayedPpt.design.topic_keywords?.length">课题关键词：{{ displayedPpt.design.topic_keywords.join('、') }}</p>
                <p v-if="displayedPpt.design.visual_motif">视觉意象：{{ displayedPpt.design.visual_motif }}</p>
              </div>
              <StatusChip
                :type="displayedPpt.pipeline_version === 'ppt-master-svg-v2' ? 'success' : 'info'"
                :label="displayedPpt.pipeline_version === 'ppt-master-svg-v2' ? 'PPT Master · 成品预览' : '历史课件'"
              />
            </div>
            <el-alert
              v-if="displayedPpt.multimodal"
              :title="displayedPpt.multimodal.message"
              :description="displayedPpt.multimodal.errors?.length
                ? displayedPpt.multimodal.errors.join('；')
                : displayedPpt.multimodal.generated_count && displayedPpt.multimodal.selected_slides?.length
                  ? `已生成第 ${displayedPpt.multimodal.selected_slides.join('、')} 页辅助插图`
                  : undefined"
              :type="displayedPpt.multimodal.status === 'completed' ? 'success' : 'warning'"
              :closable="false"
              show-icon
              class="multimodal-status"
            />
            <el-button v-if="!isBrowsingHistory && displayedPpt.multimodal?.requested_count && displayedPpt.multimodal.generated_count < displayedPpt.multimodal.requested_count"
              :disabled="isExecuting" :loading="acting" plain @click="retryArtifact('ppt')">仅补生成未完成插图</el-button>
            <div class="slide-preview-list">
              <el-alert v-if="!isBrowsingHistory && imageJob?.status === 'failed'" title="换图未完成，原课件未被覆盖"
                :description="imageJob.error" type="warning" :closable="false" show-icon />
              <article v-for="(slide, index) in displayedPpt.slides"
                :key="`${selectedVersionId}-${displayedPpt.revision_id}-${index}`" class="ppt-native-page">
                <div class="ppt-native-heading">
                  <strong>第 {{ index + 1 }} 页 · {{ slide.title }}</strong>
                  <div v-if="!isBrowsingHistory" class="ppt-page-actions">
                    <el-button v-if="slide.visual_prompt || slide.visual_asset" size="small" :disabled="acting || isExecuting" @click="openImageRevision(index)">配图设置</el-button>
                    <el-button size="small" :disabled="displayedPpt.pipeline_version !== 'ppt-master-svg-v2' || acting || isExecuting"
                      @click="openSlideRevision(index)">修改本页</el-button>
                  </div>
                </div>
                <PptSlidePreview v-if="slide.preview_available && currentRun"
                  :run-id="currentRun.id" :slide-index="index"
                  :revision="displayedPpt.revision_id || ''" :version-id="selectedVersionId || undefined" :title="slide.title" />
                <div v-else class="legacy-ppt-content">
                  <p>历史课件暂无成品预览，请下载查看。重新生成后可预览和修改单页。</p>
                  <strong>{{ slide.takeaway }}</strong>
                  <ul><li v-for="item in slide.bullets" :key="item">{{ item }}</li></ul>
                </div>
                <details v-if="slide.visual_brief" class="ppt-page-notes"><summary>视觉教学意图 · {{ { illustration: '情境插图', diagram: '关系图解', none: '文字表达' }[slide.visual_brief.kind] }}</summary>
                  <p>{{ slide.visual_brief.purpose }}</p>
                  <p>正文依据：{{ slide.visual_brief.content_anchors.join('、') }}</p>
                  <p v-if="slide.visual_brief.key_elements?.length">需要表现：{{ slide.visual_brief.key_elements.join('、') }}</p>
                  <p v-if="slide.visual_brief.difference">本图区别：{{ slide.visual_brief.difference }}</p>
                </details>
                <p v-if="slide.visual_asset" class="image-review-status" :class="{ reviewed: slide.visual_asset.review?.status === 'passed' }">
                  {{ slide.visual_asset.review?.status === 'passed' ? '语义复核通过，仍需教师确认' : '语义复核未完成，待教师核验' }}
                  <span v-if="slide.visual_asset.review?.reason"> · {{ slide.visual_asset.review.reason }}</span>
                </p>
                <details class="ppt-page-notes"><summary>讲稿与教材依据</summary>
                  <p>{{ slide.speaker_notes }}</p>
                  <p>{{ slide.evidence_refs.join('、') || '未关联资料，请教师核验' }}</p>
                </details>
              </article>
            </div>
            </template>
          </el-tab-pane>

          <el-tab-pane v-if="artifactBundle?.lesson_plan" label="教案预览" name="lesson_plan">
            <article class="document-preview">
              <h3>{{ artifactBundle.lesson_plan.title }}</h3>
              <h4>课程定位</h4>
              <p>{{ artifactBundle.lesson_plan.overview }}</p>
              <h4>教学目标</h4>
              <ul><li v-for="item in artifactBundle.lesson_plan.objectives" :key="item">{{ item }}</li></ul>
              <h4>教学过程</h4>
              <div
                v-for="item in artifactBundle.lesson_plan.procedures"
                :key="`${item.stage}-${item.duration_minutes}`"
                class="procedure-preview"
              >
                <strong>{{ item.stage }} · {{ item.duration_minutes }} 分钟</strong>
                <p>教师：{{ item.teacher_activity }}</p>
                <p>学生：{{ item.student_activity }}</p>
              </div>
            </article>
          </el-tab-pane>

          <el-tab-pane
            v-if="artifactBundle?.classroom_activities"
            label="课堂活动预览"
            name="classroom_activities"
          >
            <div class="activity-preview-list">
              <article
                v-for="item in artifactBundle.classroom_activities"
                :key="item.title"
                class="activity-preview"
              >
                <small>{{ item.format }} · {{ item.duration_minutes }} 分钟</small>
                <h3>{{ item.title }}</h3>
                <p>{{ item.purpose }}</p>
                <ol><li v-for="step in item.instructions" :key="step">{{ step }}</li></ol>
                <strong>评价：{{ item.evaluation }}</strong>
              </article>
            </div>
          </el-tab-pane>
        </el-tabs>
        <el-alert
          title="以上成果均为可编辑草稿。下载、修改不等于发布，后续发布仍需教师再次确认。"
          type="warning"
          :closable="false"
          show-icon
        />
        <section class="publish-panel">
          <div class="publish-heading">
            <div>
              <p class="eyebrow">FINAL CONFIRMATION</p>
              <h3>快捷发布到教学班</h3>
              <p>课件将进入学生资源区；所选讨论将同步生成课堂互动。</p>
            </div>
            <StatusChip
              :label="publishedResult ? '已发布' : '等待教师确认'"
              :status="publishedResult ? 'success' : 'warning'"
            />
          </div>
          <el-result
            v-if="publishedResult"
            icon="success"
            title="教学成果发布成功"
            :sub-title="`已发布到 ${publishedResult.teaching_class_name}`"
          >
            <template #extra>
              <el-button type="primary" @click="router.push('/interaction')">查看课堂互动</el-button>
            </template>
          </el-result>
          <el-alert v-else-if="isBrowsingHistory" title="正在浏览历史课件，暂不能发布。请先设为当前版本，或返回当前版本。" type="info" :closable="false" show-icon />
          <el-form v-else label-position="top" class="publish-form">
            <div class="publish-form-grid">
              <el-form-item label="发布到教学班">
                <el-select v-model="selectedTeachingClassId" placeholder="请选择教学班">
                  <el-option
                    v-for="item in eligibleTeachingClasses"
                    :key="item.id"
                    :label="`${item.name} · ${item.term_name}`"
                    :value="item.id"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="成果标题">
                <el-input v-model="publishTitle" maxlength="200" />
              </el-form-item>
            </div>
            <el-form-item label="发布说明">
              <el-input v-model="publishDescription" type="textarea" :rows="3" maxlength="1000" show-word-limit />
            </el-form-item>
            <div class="publication-options">
              <el-checkbox v-model="publishPpt" :disabled="!artifacts.ppt">发布教学 PPT</el-checkbox>
              <el-checkbox v-model="publishDiscussions" :disabled="!classroomActivities.length">
                发布课堂讨论
              </el-checkbox>
            </div>
            <el-alert v-if="publishPpt && publicationPpt.previous" title="本次 PPT 尚未成功生成，当前保留的是上一版课件。"
              type="warning" :closable="false" show-icon />
            <el-checkbox v-if="publishPpt && publicationPpt.previous" v-model="previousPptConfirmed">
              我已下载核验上一版 PPT，明确选择发布上一版
            </el-checkbox>
            <el-checkbox-group
              v-if="publishDiscussions && classroomActivities.length"
              v-model="selectedDiscussionIndices"
              class="discussion-selector"
            >
              <el-checkbox
                v-for="(item, index) in classroomActivities"
                :key="`${item.title}-${index}`"
                :value="index"
              >
                {{ item.title }} · {{ item.duration_minutes }} 分钟
              </el-checkbox>
            </el-checkbox-group>
            <el-checkbox v-model="publicationConfirmed" class="publication-confirmation">
              我已核验课纲、PPT 和讨论内容，确认发布给学生
            </el-checkbox>
            <el-button
              type="primary"
              size="large"
              :loading="acting"
              :disabled="!canPublish"
              @click="publishLesson"
            >
              确认并快捷发布
            </el-button>
          </el-form>
        </section>
      </UiCard>
    </section>

    <el-dialog v-model="templateDialogVisible" title="上传 PPTX 风格模板" width="min(560px, 92vw)">
      <el-alert
        title="系统会提取主题色、字体、页面比例和版式清单，复杂动画与母版对象暂不直接复制。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="dialog-form">
        <el-form-item label="模板名称">
          <el-input v-model="templateName" maxlength="120" />
        </el-form-item>
        <el-form-item label="使用说明">
          <el-input v-model="templateDescription" type="textarea" :rows="3" placeholder="例如：学院公开课统一视觉规范" />
        </el-form-item>
        <el-form-item label="PPTX 文件">
          <input type="file" accept=".pptx" @change="chooseTemplateFile" />
          <small v-if="templateFile">{{ templateFile.name }} · {{ (templateFile.size / 1024 / 1024).toFixed(2) }}MB</small>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="templateDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="acting" @click="uploadPptTemplate">上传并解析</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="imageDialogVisible" :title="`第 ${imageSlideIndex + 1} 页配图设置`" width="min(680px, 94vw)" :close-on-click-modal="false">
      <p>{{ imagePage?.title }}</p>
      <p v-if="imagePage?.visual_brief">教学意图：{{ imagePage.visual_brief.purpose }}</p>
      <p v-if="imagePage?.visual_brief?.key_elements?.length">需保留的关键元素：{{ imagePage.visual_brief.key_elements.join('、') }}</p>
      <p class="image-dialog-hint">仅替换这一张插图，保留文字、版式和其他图片；完成验证后生成新版本。生成图仅作教学意象，不代表真实史料。</p>
      <el-form label-position="top">
        <el-form-item label="场景提示词（可修改）">
          <el-input v-model="imagePrompt" type="textarea" :rows="6" maxlength="1200" show-word-limit
            placeholder="描述具体主体、动作和关键物体，说明需要表现的概念，避免仅写围桌讨论。" />
        </el-form-item>
      </el-form>
      <details v-if="imagePage?.visual_asset?.prompt" class="ppt-page-notes"><summary>上次实际发送给图像模型的完整提示词</summary>
        <p>{{ imagePage.visual_asset.prompt }}</p>
      </details>
      <p v-if="imagePage?.visual_asset?.review">语义复核：{{ imagePage.visual_asset.review.reason }}</p>
      <template #footer>
        <el-button @click="imageDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="acting" :disabled="isExecuting" @click="replaceImage">仅重新生成这张图</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="slideRevisionVisible" :title="`修改第 ${revisingSlideIndex + 1} 页`" width="min(600px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="修改范围">
          <el-radio-group v-model="revisionMode">
            <el-radio-button value="both">内容与设计</el-radio-button>
            <el-radio-button value="content">内容表达</el-radio-button>
            <el-radio-button value="design">只改设计</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="告诉 Agent 你希望如何修改">
          <el-input
            v-model="revisionInstruction"
            type="textarea"
            :rows="5"
            maxlength="500"
            show-word-limit
            placeholder="例如：这一页太单调，把核心结论放大，保留两个要点并增加明显的逻辑层次。"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="slideRevisionVisible = false">取消</el-button>
        <el-button type="primary" :loading="acting" @click="reviseSlide">重新生成本页</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ppt-native-page { padding: 16px; border: 1px solid #e8e9ed; border-radius: 12px; min-width: 0; }
.ppt-native-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.ppt-page-notes { margin-top: 12px; color: #637084; font-size: 13px; }
.ppt-page-notes p { white-space: pre-wrap; }
.ppt-page-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.image-review-status, .image-dialog-hint { font-size: 13px; color: #9a6b28; line-height: 1.6; }
.image-review-status.reviewed { color: #367d62; }
.legacy-ppt-content { padding: 16px; background: #f6f7f9; }
.lesson-prep-workspace { display: grid; gap: clamp(14px, 1.6vw, 20px); }
.prep-page-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.prep-page-brand { display: flex; min-width: 0; align-items: center; gap: 16px; }
.prep-page-logo { flex: none; width: 66px; height: 66px; object-fit: contain; border-radius: 50%; box-shadow: 0 6px 14px rgb(193 55 73 / 12%); }
.prep-page-brand > div { min-width: 0; }
.prep-page-eyebrow { margin: 0 0 4px; color: #ff7b82; font-size: clamp(10px, .9vw, 13px); font-weight: 800; letter-spacing: .11em; }
.prep-page-header h1 { margin: 0 0 4px; color: #2e1c2a; font-size: clamp(26px, 2.7vw, 36px); font-weight: 800; letter-spacing: .02em; line-height: 1.12; }
.prep-page-description { max-width: 680px; margin: 0; color: #71757e; font-size: clamp(12px, 1.05vw, 15px); line-height: 1.45; }
.prep-page-actions { display: flex; flex: none; align-items: center; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.prep-page-actions :deep(.el-button) { min-height: 36px; padding: 0 13px; color: #684d78; background: #fff; border: 1px solid #f2b8bd; border-radius: 9px; box-shadow: 0 4px 8px rgb(71 44 73 / 12%); font-size: 12px; font-weight: 650; }
.prep-page-actions :deep(.el-button:hover), .prep-page-actions :deep(.el-button:focus) { color: #c52c45; border-color: #ff7e87; background: #fff8f8; }
/* The source artwork has baked-in white bands above and below the pink panel.
   Crop those bands in CSS without changing the shared background asset. */
.prep-progress-card { overflow: hidden; padding: 18px clamp(20px, 2.7vw, 36px) 12px; background-color: #fff5f7; background-position: center; background-repeat: no-repeat; background-size: 100% 174%; border-color: #f4dfe3; border-radius: 15px; box-shadow: 0 7px 13px rgb(68 42 65 / 13%); }
.prep-step-progress { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 0; padding: 0; list-style: none; }
.prep-step-progress li { position: relative; z-index: 0; display: grid; justify-items: center; gap: 7px; color: #7f828a; font-size: clamp(12px, 1vw, 15px); font-weight: 650; text-align: center; }
.prep-step-progress li::after { position: absolute; z-index: -1; top: 21px; left: 50%; width: 100%; height: 2px; content: ''; background: #d9d9dc; }
.prep-step-progress li:last-child::after { display: none; }
.prep-step-progress li.completed::after, .prep-step-progress li.active::after { background: #ff5966; }
.prep-step-progress li.locked { color: #8d9097; }
.prep-step-node { display: grid; width: 44px; height: 44px; place-items: center; color: #6e7076; background: #fff; border: 2px solid #c5c6c9; border-radius: 50%; box-shadow: 0 4px 7px rgb(45 45 55 / 12%); font-family: Georgia, serif; font-size: 20px; font-weight: 700; }
.prep-step-progress li.active { color: #ff4656; }
.prep-step-progress li.active .prep-step-node { color: #fff; background: #ff3e4e; border-color: #ff2338; box-shadow: 0 0 0 9px rgb(255 101 111 / 22%), 0 5px 10px rgb(211 53 64 / 30%); }
.prep-step-progress li.completed .prep-step-node { color: #fff; background: #ff6570; border-color: #ff5663; }
.stage-navigation { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: clamp(8px, 1vw, 15px); margin-top: 14px; padding-bottom: 1px; }
.stage-navigation button { display: flex; min-width: 0; height: 45px; align-items: center; justify-content: center; gap: 7px; padding: 0 9px; color: #686b72; background: rgb(255 255 255 / 90%); border: 1px solid #d8d8dc; border-radius: 14px; box-shadow: 0 4px 6px rgb(43 43 50 / 14%); font: inherit; font-size: clamp(12px, 1vw, 15px); font-weight: 650; cursor: pointer; transition: border-color .18s ease, background .18s ease, color .18s ease, transform .18s ease; }
.stage-navigation button span { color: #6c6b72; font-family: Georgia, serif; font-weight: 700; }
.stage-navigation button.available { cursor: pointer; }
.stage-navigation button.available:hover { color: #e03349; border-color: #ff8b91; transform: translateY(-2px); }
.stage-navigation button.active { color: #f33648; background: #ffe1e4; border: 2px solid #ff5060; box-shadow: 0 6px 10px rgb(198 49 63 / 20%); }
.stage-navigation button.active span { color: #ee3a4c; }
.stage-navigation button:disabled { cursor: not-allowed; opacity: .55; }
.run-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-top: 12px; padding-top: 10px; color: #747780; border-top: 1px solid #e8dfe4; font-size: 11px; }
.prep-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.prep-grid h2 { margin: var(--space-1) 0 0; font-size: var(--fs-section); }
.prep-settings, .prep-evidence, .prep-output, .artifact-results { min-width: 0; }
.stage-card { width: 100%; }
.prep-settings { overflow: hidden; padding: 0; border-color: #ecdce1; border-radius: 18px; box-shadow: 0 8px 16px rgb(72 40 62 / 9%); }
.prep-settings :deep(.ui-card__header) { min-height: 140px; align-items: flex-start; margin: 0; padding: 24px 30px 20px; background: #fff9fa var(--prep-context-bg) center / cover no-repeat; border-bottom: 1px solid #eadfe3; }
.prep-settings :deep(.ui-card__header) .eyebrow { margin: 0 0 13px; color: #ff6975 !important; font-size: 13px; letter-spacing: .1em; }
.prep-settings :deep(.ui-card__header) h2 { margin: 0; color: #2d1b2a; font-size: clamp(23px, 2vw, 30px); letter-spacing: .02em; }
.prep-settings-body { padding: 18px 26px 20px; }
.prep-settings :deep(.el-form) { display: grid; gap: 3px; }
.prep-settings :deep(.el-form-item) { margin-bottom: 8px; }
.prep-settings :deep(.el-form-item__label) { height: auto; margin-bottom: 5px; padding: 0; color: #5f4578; font-size: 14px; font-weight: 650; line-height: 1.3; }
.prep-field-label i { color: #ff5270; font-style: normal; }
.prep-field-label small { color: #7f7485; font-size: .8em; font-weight: 500; }
.prep-settings :deep(.el-input__wrapper), .prep-settings :deep(.el-select .el-input__wrapper), .prep-settings :deep(.el-textarea__inner) { min-height: 40px; padding: 0 12px; background: #fff; border: 1px solid #e5e1e8; border-radius: 9px; box-shadow: 0 3px 6px rgb(47 35 55 / 8%); }
.prep-settings :deep(.el-input__wrapper:hover), .prep-settings :deep(.el-select .el-input__wrapper:hover), .prep-settings :deep(.el-textarea__inner:hover) { border-color: #d3b9dc; }
.prep-settings :deep(.el-input__wrapper.is-focus), .prep-settings :deep(.el-select .el-input__wrapper.is-focus), .prep-settings :deep(.el-textarea__inner:focus) { border-color: #c4a9d2; box-shadow: 0 0 0 3px rgb(175 126 197 / 13%); }
.prep-settings :deep(.el-input__inner), .prep-settings :deep(.el-select .el-input__inner), .prep-settings :deep(.el-textarea__inner) { color: #684d78; font-size: 14px; }
.prep-settings :deep(.el-input.is-disabled .el-input__wrapper), .prep-settings :deep(.el-select .el-input.is-disabled .el-input__wrapper) { background: #fff; }
.prep-number-control { display: grid; grid-template-columns: 34px minmax(0, 1fr) 34px; width: 100%; min-height: 40px; overflow: hidden; background: #fff; border: 1px solid #e5e1e8; border-radius: 9px; box-shadow: 0 3px 6px rgb(47 35 55 / 8%); }
.prep-number-control:focus-within { border-color: #c4a9d2; box-shadow: 0 0 0 3px rgb(175 126 197 / 13%); }
.prep-number-control button { color: #745080; background: #f9f4fb; border: 0; font-size: 17px; cursor: pointer; }
.prep-number-control button:first-child { border-right: 1px solid #eee6f1; }
.prep-number-control button:last-child { border-left: 1px solid #eee6f1; }
.prep-number-control button:hover:not(:disabled) { color: #c52c45; background: #fff1f2; }
.prep-number-control button:disabled { color: #bdb3c2; cursor: not-allowed; }
.prep-number-control input { min-width: 0; width: 100%; color: #684d78; background: transparent; border: 0; outline: 0; font: inherit; font-size: 14px; text-align: center; appearance: textfield; }
.prep-number-control input::-webkit-inner-spin-button, .prep-number-control input::-webkit-outer-spin-button { margin: 0; appearance: none; }
.prep-number-control.is-disabled { background: #fff; opacity: .72; }
.prep-context-row { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(18px, 2vw, 28px); }
.prep-settings :deep(.el-textarea__inner) { min-height: 96px; padding: 10px 12px; line-height: 1.5; resize: vertical; }
.prep-settings-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 2px; padding-top: 11px; border-top: 1px solid #eee5eb; }
.prep-settings-footer > span { color: #867c89; font-size: 11px; line-height: 1.45; }
.prep-settings-footer :deep(.el-button) { min-width: 158px; height: 40px; border: 0; border-radius: 9px; box-shadow: 0 6px 11px rgb(205 53 70 / 20%); font-size: 13px; font-weight: 700; }
.compact-form-row { display: grid; grid-template-columns: 1fr 1.25fr; gap: var(--space-2); }
.full-button { width: 100%; }
.evidence-list { display: grid; max-height: 680px; gap: var(--space-3); overflow: auto; }
.outline-document, .outline-content { display: grid; gap: var(--space-4); }
.outline-document { max-height: none; padding-right: 0; overflow: visible; }
.outline-document h3 { margin: 0; color: var(--ink-900); font-size: 22px; }
.outline-document section { display: grid; gap: var(--space-2); }
.outline-document h4, .outline-document p, .outline-document ul, .outline-document ol, .objective-list { margin: 0; }
.outline-document h4 { padding-bottom: var(--space-2); border-bottom: 1px solid var(--line); font-size: var(--fs-card-title); }
.outline-document p, .outline-document li, .objective-list { color: var(--ink-600); line-height: 1.75; }
.objective-list { display: grid; gap: var(--space-2); }
.objective-list div { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: var(--space-2); }
.objective-list dt { color: var(--action-blue); font-weight: var(--fw-bold); }
.objective-list dd { margin: 0; }
.flow-item { display: grid; gap: var(--space-1); padding: var(--space-3); background: var(--surface-muted); border-left: 3px solid var(--action-blue); border-radius: var(--radius-input); }
.flow-item p { font-size: var(--fs-aux); }
.flow-item small { color: var(--authority-red); }
.artifact-builder { padding: clamp(18px, 2.2vw, 28px); background: var(--surface-muted); border-radius: var(--radius-card); }
.artifact-builder > h4 { margin-bottom: 12px; }
.artifact-generation-progress { display: grid; gap: 8px; margin: 14px 0 12px; }
.generation-progress-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px 16px; }
.generation-progress-heading strong { color: #63333f; font-size: 14px; }
.generation-progress-heading > span { color: #806e76; font-size: 12px; }
.generation-progress-heading b { margin-left: 5px; color: #d64b65; font-size: 22px; font-variant-numeric: tabular-nums; }
.artifact-generation-progress .generation-progress-detail { min-height: 0; margin: 0; color: #6c6470; font-size: 13px; line-height: 1.5; }
.generation-progress-footnote { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; color: #8b7f87; font-size: 11px; line-height: 1.5; font-variant-numeric: tabular-nums; }
.artifact-builder :deep(.el-checkbox-group) { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.artifact-builder :deep(.el-checkbox-button__inner) { border: 1px solid var(--line); border-radius: var(--radius-input); box-shadow: none; }
.artifact-retry-banner { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-top: var(--space-4); padding: var(--space-3); color: #7a4a00; background: #fff8e8; border: 1px solid #efd48a; border-radius: var(--radius-input); }
.artifact-retry-banner p { margin: 4px 0 0; color: #876b35; font-size: var(--fs-meta); }
.artifact-retry-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
.ppt-preferences { display: grid; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
.preference-heading, .quality-heading, .artifact-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.preference-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 var(--space-3); }
.ppt-title-field { grid-column: 1 / -1; }
.preference-grid :deep(.el-select), .preference-grid :deep(.el-input-number) { width: 100%; }
.slide-count-control { display: grid; grid-template-columns: 44px minmax(92px, 1fr) 44px; width: min(230px, 100%); overflow: hidden; border: 1px solid var(--action-blue); border-radius: var(--radius-input); }
.slide-count-control button { min-height: 42px; color: var(--action-blue); background: #eef5ff; border: 0; font-size: 22px; cursor: pointer; }
.slide-count-control button:disabled { color: var(--ink-300); cursor: not-allowed; }
.slide-count-control label { display: grid; grid-template-columns: 1fr auto; align-items: center; padding: 0 10px; background: white; border-right: 1px solid var(--line); border-left: 1px solid var(--line); }
.slide-count-control input { min-width: 0; width: 100%; color: var(--ink-900); background: transparent; border: 0; outline: 0; font: inherit; font-weight: var(--fw-bold); text-align: center; appearance: textfield; }
.slide-count-control input::-webkit-inner-spin-button { appearance: none; }
.slide-count-control label span { color: var(--ink-400); font-size: var(--fs-meta); }
.preference-switches { display: flex; min-height: 32px; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.artifact-results { grid-column: 1 / -1; }
.artifact-results :deep(.ui-card__header) { align-items: center; gap: 12px; margin-bottom: 12px; min-height: 0; }
.artifact-results-heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; }
.artifact-results-heading h2 { margin: 0; font-size: 20px; line-height: 1.3; }
.artifact-results-heading .eyebrow { min-height: 0; margin: 0; font-size: 10px; line-height: 1.4; letter-spacing: .1em; }
.artifact-actions { flex-wrap: wrap; }
.ppt-version-panel { min-width: 0; }
.version-switcher { display: grid; grid-template-columns: auto minmax(180px, 1fr) minmax(140px, 220px); align-items: center; gap: 12px; }
.version-caption { margin: 0; color: #63434a; font-size: 13px; font-weight: 650; }
.version-switch-hint { color: #765d65; font-size: 12px; line-height: 1.5; }
.version-switcher :deep(.el-select) { width: 100%; min-width: 0; }
.version-switcher :deep(.el-select__wrapper) { background: rgb(255 255 255 / 88%); }
.version-option { display: grid; gap: 3px; line-height: 1.5; padding: 6px 0; }
.version-option small { font-size: 12px; color: #8c7c80; }
:global(.ppt-version-options .el-select-dropdown__item) { height: auto; min-height: 40px; display: flex; align-items: center; }
.version-option span { overflow: hidden; text-overflow: ellipsis; }
.version-preview-state { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgb(191 126 140 / 18%); color: var(--ink-600); font-size: var(--fs-meta); }
.version-preview-state > span { flex: 1 1 240px; }
.version-preview-state small { display: block; margin-top: 4px; color: #a46d27; }
.version-preview-actions { display: flex; gap: 8px; }
.version-preview-actions :deep(.el-button + .el-button) { margin-left: 0; }
.version-error { color: #b33d45; }
.version-loading { display: grid; min-height: 240px; place-items: center; color: var(--ink-500); }
.artifact-overview { display: grid; gap: 10px; margin-bottom: 14px; padding: 14px 18px; background-color: #fff9f8; background-image: linear-gradient(90deg, rgb(255 251 250 / 94%), rgb(255 251 250 / 65%) 60%, rgb(255 251 250 / 38%)), var(--artifact-overview-bg); background-position: center; background-repeat: no-repeat; background-size: cover; border: 1px solid #efdcdf; border-radius: var(--radius-card); }
.artifact-overview-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 16px; min-width: 0; }
.artifact-overview-heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; min-width: 0; }
.artifact-overview-heading strong { margin: 0; color: #66333e; font-size: 15px; line-height: 1.5; }
.artifact-overview-heading > span { color: #765d65; font-size: 12px; line-height: 1.5; }
.artifact-status-list { display: flex; flex-wrap: wrap; gap: 6px; }
.artifact-status-item { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; color: var(--ink-500); background: rgb(255 255 255 / 86%); border: 1px solid var(--line); border-radius: 999px; font-size: 12px; line-height: 1.4; }
.artifact-status-item.is-ready { color: #167a42; border-color: #b9dfc7; background: #f0faf4; }
.artifact-status-dot { width: 7px; height: 7px; background: var(--ink-300); border-radius: 50%; }
.artifact-status-item.is-ready .artifact-status-dot { background: #2aa361; }
.artifact-overview-retry { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); padding-top: 8px; border-top: 1px solid rgb(191 126 140 / 18%); color: #876b35; font-size: var(--fs-meta); }
.artifact-file-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 10px; }
.artifact-file { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-content: start; align-items: start; gap: 8px 10px; min-width: 0; padding: 12px; background: var(--surface-muted); border: 1px solid var(--line); border-radius: 12px; }
.artifact-file-type { display: grid; width: 32px; height: 32px; place-items: center; color: white; background: var(--authority-red); border-radius: 50%; font-size: 9px; font-weight: var(--fw-bold); }
.artifact-file-info { min-width: 0; }
.artifact-file-info strong { display: -webkit-box; height: 2.9em; margin: 0; overflow: hidden; color: var(--ink-900); font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.artifact-file-info p { min-height: 0; margin: 3px 0 0; color: var(--ink-400); font-size: 12px; line-height: 1.4; }
.artifact-file-footer { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
.artifact-file-footer small { min-width: 0; overflow: hidden; color: #897b83; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.artifact-file-footer :deep(.el-button) { flex: none; margin-left: auto; }
.artifact-preview-tabs { margin-top: var(--space-5); }
.multimodal-status { margin-bottom: var(--space-4); }
.ppt-quality { display: grid; gap: 6px; margin-bottom: 12px; padding: 10px 12px; background: #fff8ee; border: 1px solid #edd3a7; border-radius: var(--radius-input); }
.quality-heading { justify-content: flex-start; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; }
.quality-heading strong { color: #855514; font-size: 13px; line-height: 1.5; }
.quality-heading > span { color: #816c51; font-size: 12px; line-height: 1.5; }
.quality-details summary { color: #855514; font-size: 12px; cursor: pointer; }
.quality-issues { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); margin-top: var(--space-3); }
.quality-issues button { display: grid; gap: 4px; padding: var(--space-3); color: inherit; background: rgb(255 255 255 / 72%); border: 1px solid var(--line); border-radius: var(--radius-input); text-align: left; cursor: pointer; }
.quality-issues button:hover { border-color: var(--action-blue); }
.quality-issues b { color: var(--authority-red); font-size: var(--fs-meta); }
.quality-issues span { font-weight: var(--fw-semibold); }
.quality-issues small { color: var(--ink-500); line-height: 1.5; }
.slide-preview-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.ppt-design-brief { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-4); padding: var(--space-4); color: #642a33; background-color: #fff9f8; background-position: center; background-repeat: no-repeat; background-size: cover; border: 1px solid #f0dfe0; border-radius: var(--radius-card); }
.ppt-design-brief small { display: block; margin-bottom: var(--space-1); color: #ad4757; letter-spacing: .14em; }
.ppt-design-brief strong { display: block; font-size: var(--fs-h3); }
.ppt-design-brief p { max-width: 720px; margin: var(--space-2) 0 0; color: #694d58; line-height: 1.65; }
.slide-preview { position: relative; display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: var(--space-3); min-height: 220px; padding: var(--space-4); background: linear-gradient(145deg, #fff, var(--surface-muted)); border-left: 5px solid var(--authority-red); border-radius: var(--radius-card); }
.slide-actions { position: absolute; z-index: 3; top: var(--space-2); right: var(--space-2); opacity: 0; transition: opacity .18s ease; }
.slide-preview:hover .slide-actions, .slide-preview:focus-within .slide-actions { opacity: 1; }
.slide-preview > span { color: var(--authority-red); font-family: Georgia, serif; font-size: 24px; }
.slide-preview h3, .slide-preview p, .slide-preview ul { margin: 0; }
.slide-preview small { color: var(--ink-400); letter-spacing: .08em; }
.slide-preview strong { display: block; margin: var(--space-2) 0; color: var(--authority-red); }
.slide-preview li, .slide-preview p, .document-preview p, .document-preview li, .activity-preview p, .activity-preview li { color: var(--ink-600); line-height: 1.65; }
.slide-preview p { margin-top: var(--space-3); font-size: var(--fs-meta); }
.slide-preview.is-title, .slide-preview.is-question, .slide-preview.is-discussion { color: white; background: linear-gradient(135deg, #6f1828, #173b72); border-left-color: var(--warning-gold); }
.slide-preview.is-title > span, .slide-preview.is-question > span, .slide-preview.is-discussion > span,
.slide-preview.is-title small, .slide-preview.is-question small, .slide-preview.is-discussion small { color: #f0d691; }
.slide-preview.is-title strong, .slide-preview.is-question strong, .slide-preview.is-discussion strong,
.slide-preview.is-title li, .slide-preview.is-question li, .slide-preview.is-discussion li { color: #edf2fa; }
.preview-keyword { display: inline-grid; min-width: 132px; min-height: 72px; margin-top: var(--space-3); padding: var(--space-3); place-items: center; color: white; background: var(--authority-red); border-radius: 50%; font-size: 20px; font-weight: var(--fw-bold); }
.preview-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); margin-top: var(--space-3); }
.preview-comparison section { padding: var(--space-3); background: #f9edef; }
.preview-comparison section:last-child { background: #edf3fc; }
.preview-comparison ul { margin-top: var(--space-2); padding-left: 18px; }
.preview-steps, .preview-timeline { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: var(--space-2); margin-top: var(--space-3); }
.preview-steps section, .preview-timeline section { position: relative; padding-top: var(--space-3); border-top: 2px solid var(--brand-blue); }
.preview-steps i { display: inline-grid; width: 24px; height: 24px; margin-right: 6px; place-items: center; color: white; background: var(--authority-red); border-radius: 50%; font-style: normal; font-size: 12px; }
.preview-steps p, .preview-timeline p { margin-top: var(--space-1); }
.document-preview, .activity-preview-list { display: grid; gap: var(--space-4); }
.document-preview h3, .document-preview h4, .document-preview p, .document-preview ul { margin: 0; }
.procedure-preview, .activity-preview { padding: var(--space-4); background: var(--surface-muted); border-radius: var(--radius-card); }
.procedure-preview p { margin: var(--space-1) 0 0; }
.activity-preview h3 { margin: var(--space-1) 0; }
.publish-panel { display: grid; gap: var(--space-4); margin-top: var(--space-5); padding: clamp(18px, 3vw, 36px); background: linear-gradient(145deg, #f9fbff, #f6f2ea); border: 1px solid var(--line); border-radius: var(--radius-card); }
.publish-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.publish-heading h3, .publish-heading p { margin: 0; }
.publish-heading h3 { margin: var(--space-1) 0; font-size: var(--fs-h3); }
.publish-heading > div > p:last-child { color: var(--ink-500); }
.publish-form { display: grid; gap: var(--space-3); }
.publish-form-grid { display: grid; grid-template-columns: minmax(220px, .8fr) minmax(280px, 1.2fr); gap: var(--space-3); }
.publish-form-grid :deep(.el-select) { width: 100%; }
.publication-options, .discussion-selector { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.discussion-selector { padding: var(--space-3); background: white; border: 1px solid var(--line); border-radius: var(--radius-input); }
.publication-confirmation { padding-top: var(--space-3); border-top: 1px solid var(--line); }
.generating-state { display: grid; min-height: 280px; align-content: center; gap: var(--space-3); text-align: center; }
.generating-state p { margin: 0; color: var(--ink-600); }
.dialog-form { margin-top: var(--space-4); }
.dialog-form input[type="file"] { display: block; width: 100%; padding: var(--space-3); background: var(--surface-muted); border: 1px dashed var(--line); border-radius: var(--radius-input); }
.dialog-form small { display: block; margin-top: var(--space-2); color: var(--ink-400); }
@media (max-width: 767px) {
  .artifact-overview { padding: 12px 14px; }
  .version-switcher { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .version-switch-hint { font-size: 11px; }
  .version-preview-state > span { flex-basis: 100%; }
}
@media (max-width: 767px) { .stage-navigation { display: flex; overflow-x: auto; padding-bottom: var(--space-1); } .stage-navigation button { min-width: 132px; } .prep-grid, .compact-form-row, .slide-preview-list, .preference-grid, .quality-issues, .publish-form-grid { grid-template-columns: 1fr; } .prep-output, .artifact-results { grid-column: auto; } .run-toolbar, .preference-heading, .quality-heading, .publish-heading, .artifact-retry-banner { align-items: flex-start; flex-direction: column; } .ppt-quality { grid-template-columns: 1fr; } .quality-score { padding-bottom: var(--space-3); border-right: 0; border-bottom: 1px solid var(--line); } .quality-heading > span { max-width: none; text-align: left; } .slide-actions { opacity: 1; } }
</style>

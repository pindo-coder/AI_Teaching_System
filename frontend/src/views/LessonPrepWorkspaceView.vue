<script setup lang="ts">
import { computed, onMounted, ref, watch, type CSSProperties } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  agentApi,
  type AgentCapabilities,
  type AgentRun,
  type LessonPublication,
  type PptPreferences,
  type PresentationTemplate,
} from '@/api/agents'
import { courseApi } from '@/api/courses'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import EvidenceCard from '@/components/ui/EvidenceCard.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import StepProgress from '@/components/ui/StepProgress.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import type { Course, CourseDetail } from '@/types'

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const acting = ref(false)
const courses = ref<Course[]>([])
const course = ref<CourseDetail | null>(null)
const selectedCourseId = ref<number>()
const selectedChapterId = ref<number>()
const lessonHours = ref(2)
const studentLevel = ref('本科生')
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
const artifactTypes = ref<Array<'lesson_plan' | 'ppt' | 'classroom_activities'>>([
  'ppt',
  'lesson_plan',
  'classroom_activities',
])
const artifactPreview = ref<'ppt' | 'lesson_plan' | 'classroom_activities'>('ppt')
const pptPreferences = ref<PptPreferences>({
  scenario: 'classroom',
  visual_style: 'modern',
  content_density: 'standard',
  min_slides: 10,
  max_slides: 10,
  slide_count: 10,
  include_interaction: true,
  // 已配置百炼多模态时默认生成少量语义插图；教师仍可取消以控制额度。
  include_visuals: true,
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
const hydratingRun = ref(false)

const steps = ['设置任务', '构建证据', '生成课纲', '生成成果', '预览发布']
const currentStep = computed(() => activeStage.value - 1)
const chapter = computed(() => course.value?.chapters.find((item) => item.id === selectedChapterId.value) || null)
const evidence = computed(() => currentRun.value?.evidence_snapshot || [])
const outline = computed(() => currentRun.value?.output_data.outline)
const artifactBundle = computed(() => currentRun.value?.output_data.artifact_bundle)
const artifacts = computed(() => currentRun.value?.output_data.artifacts || {})
const pptVersions = computed(() => currentRun.value?.output_data.ppt_versions || [])
const pptQuality = computed(() => artifactBundle.value?.ppt?.quality_report)
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
  return keys.map((key) => ({ key, label: artifactLabels[key], ready: Boolean(artifacts.value[key]) }))
})
const incompleteArtifactKeys = computed(() => artifactStatusRows.value.filter((item) => !item.ready).map((item) => item.key))
const canPublish = computed(() => Boolean(
  currentRun.value
  && selectedTeachingClassId.value
  && publicationConfirmed.value
  && ((publishPpt.value && artifacts.value.ppt) || (publishDiscussions.value && classroomActivities.value.length)),
))
const maxAvailableStage = computed(() => {
  if (!currentRun.value) return 1
  if (Object.keys(artifacts.value).length) return 5
  if (outline.value) return 4
  if (evidence.value.length) return 2
  return 1
})
const runStatus = computed(() => {
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
  if (currentRun.value?.status === 'failed') return 'danger'
  if (currentRun.value?.status === 'completed') return 'success'
  if (currentRun.value?.status === 'waiting_confirmation') return 'warning'
  return 'info'
})

type ArtifactPpt = NonNullable<NonNullable<AgentRun['output_data']['artifact_bundle']>['ppt']>
type PptSlide = ArtifactPpt['slides'][number]
type CanvasElement = NonNullable<PptSlide['canvas']>[number]

function canvasSource(slide: PptSlide, source: string, index: number) {
  if (source === 'title') return slide.title
  if (source === 'takeaway') return slide.takeaway
  if (source === 'keyword') return slide.keyword || ''
  if (source === 'page_number') return String(index + 1).padStart(2, '0')
  let match = source.match(/^bullet:(\d+)$/)
  if (match) return slide.bullets[Number(match[1])] || ''
  match = source.match(/^(left|right)\.title$/)
  if (match) return slide[match[1] as 'left' | 'right']?.title || ''
  match = source.match(/^(left|right)\.point:(\d+)$/)
  if (match) return slide[match[1] as 'left' | 'right']?.points[Number(match[2])] || ''
  match = source.match(/^step:(\d+)\.(title|description)$/)
  if (match) return slide.steps?.[Number(match[1])]?.[match[2] as 'title' | 'description'] || ''
  match = source.match(/^timeline:(\d+)\.(label|title)$/)
  if (match) return slide.timeline?.[Number(match[1])]?.[match[2] as 'label' | 'title'] || ''
  return ''
}

function canvasElementStyle(element: CanvasElement, ppt: ArtifactPpt): CSSProperties {
  const palette = ppt.design?.palette || {}
  const fontSizes: Record<string, string> = {
    hero: 'clamp(15px, 2.35vw, 30px)',
    title: 'clamp(13px, 1.65vw, 23px)',
    subtitle: 'clamp(11px, 1.2vw, 18px)',
    body: 'clamp(9px, .92vw, 14px)',
    label: 'clamp(8px, .72vw, 11px)',
    number: 'clamp(17px, 2.25vw, 31px)',
    quote: 'clamp(13px, 1.45vw, 21px)',
  }
  return {
    left: `${element.x}%`,
    top: `${element.y}%`,
    width: `${element.w}%`,
    height: `${element.h}%`,
    color: `#${palette[element.color] || '172033'}`,
    backgroundColor: element.fill ? `#${palette[element.fill] || 'FFFFFF'}` : undefined,
    borderColor: element.type !== 'text' ? `#${palette[element.color] || '172033'}` : undefined,
    borderRadius: element.shape === 'ellipse' ? '50%' : element.shape === 'roundRect' ? '12px' : undefined,
    fontSize: fontSizes[element.style],
    fontWeight: element.bold ? '700' : undefined,
    textAlign: element.align,
  }
}

function canvasBackground(slide: PptSlide, ppt: ArtifactPpt) {
  const role = slide.canvas_background || 'background'
  return `#${ppt.design?.palette?.[role] || 'F7F4EE'}`
}

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
    studentLevel.value = String(run.input_data.student_level || '本科生')
    teachingGoal.value = String(run.input_data.teaching_goal || '')
    if (run.input_data.ppt_preferences) {
      pptPreferences.value = { ...pptPreferences.value, ...(run.input_data.ppt_preferences as Partial<PptPreferences>) }
      setSlideCount(pptPreferences.value.slide_count || pptPreferences.value.min_slides || 10)
    }
    if (Object.keys(run.output_data.artifacts || {}).length) activeStage.value = 4
    else if (run.output_data.outline) activeStage.value = 3
    else if (run.evidence_snapshot.length) activeStage.value = 2
    else activeStage.value = 1
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

async function listenToRun(id: number) {
  try {
    await agentApi.stream(id, {
      onSnapshot: (run) => {
        currentRun.value = run
        if (run.output_data.artifacts && Object.keys(run.output_data.artifacts).length) activeStage.value = 4
        else if (run.output_data.outline) activeStage.value = 3
      },
      onDone: async () => {
        const response = await agentApi.detail(id)
        currentRun.value = response.data.data
        if (Object.keys(response.data.data.output_data.artifacts || {}).length) activeStage.value = 4
        else if (response.data.data.output_data.outline) activeStage.value = 3
      },
    })
  } catch {
    const response = await agentApi.detail(id)
    currentRun.value = response.data.data
  }
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
        student_level: studentLevel.value,
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
  await ElMessageBox.confirm(
    '将根据当前已确认课纲生成教学成果草稿。生成后仍需教师预览核验，不会自动发布。',
    '生成教学成果',
    { confirmButtonText: '开始后台生成', cancelButtonText: '取消', type: 'warning' },
  )
  acting.value = true
  try {
    setSlideCount(pptPreferences.value.slide_count)
    const response = await agentApi.generateArtifacts(
      currentRun.value.id,
      artifactTypes.value,
      pptPreferences.value,
    )
    currentRun.value = response.data.data
    activeStage.value = 4
    ElMessage.success('教学成果已进入后台生成，可以离开本页面')
    void listenToRun(currentRun.value.id)
  } finally {
    acting.value = false
  }
}

async function retryArtifact(key: ArtifactKey) {
  if (!currentRun.value || isExecuting.value) return
  acting.value = true
  try {
    const response = await agentApi.generateArtifacts(
      currentRun.value.id,
      [key],
      key === 'ppt' ? pptPreferences.value : undefined,
    )
    currentRun.value = response.data.data
    activeStage.value = 4
    ElMessage.success(`${artifactLabels[key]}已重新进入后台生成`)
    void listenToRun(currentRun.value.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : `${artifactLabels[key]}重试失败，请稍后重试`)
  } finally {
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
  await ElMessageBox.confirm(
    '发布后，学生可下载课件，所选讨论会直接出现在课堂互动中。是否继续？',
    '确认发布教学成果',
    { confirmButtonText: '确认发布', cancelButtonText: '返回核验', type: 'warning' },
  )
  acting.value = true
  try {
    const response = await agentApi.publish(currentRun.value.id, {
      teaching_class_id: selectedTeachingClassId.value,
      title: publishTitle.value.trim(),
      description: publishDescription.value.trim(),
      publish_ppt: publishPpt.value,
      publish_discussions: publishDiscussions.value,
      discussion_indices: publishDiscussions.value ? selectedDiscussionIndices.value : [],
      confirmed: true,
    })
    publishedResult.value = response.data.data
    ElMessage.success('教学成果已发布，学生端可以访问')
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
  revisingSlideIndex.value = index
  revisionInstruction.value = ''
  revisionMode.value = 'both'
  slideRevisionVisible.value = true
}

async function reviseSlide() {
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

async function restorePptVersion() {
  if (!currentRun.value || !selectedVersionId.value) return
  await ElMessageBox.confirm('恢复后当前版本也会自动保存，可以再次切换回来。', '恢复 PPT 版本', {
    confirmButtonText: '确认恢复',
    cancelButtonText: '取消',
    type: 'warning',
  })
  acting.value = true
  try {
    const response = await agentApi.restorePptVersion(currentRun.value.id, selectedVersionId.value)
    currentRun.value = response.data.data
    selectedVersionId.value = ''
    ElMessage.success('PPT 版本已恢复')
  } finally {
    acting.value = false
  }
}

async function downloadArtifact(key: string) {
  if (!currentRun.value) return
  const artifact = artifacts.value[key]
  if (!artifact) return
  const response = await agentApi.downloadArtifact(currentRun.value.id, key)
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = artifact.file_name
  link.click()
  URL.revokeObjectURL(url)
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
watch(() => pptPreferences.value.slide_count, (value) => setSlideCount(value || 10))
watch(() => route.query.run_id, () => { void openRunFromRoute() })
</script>

<template>
  <div v-loading="loading" class="lesson-prep-workspace">
    <UiPageHeader
      eyebrow="LESSON PREPARATION"
      title="课程备课"
      description="先确定教学专题，再冻结证据快照并生成课纲草稿；任何发布操作仍由教师确认。"
    >
      <template #actions>
        <StatusChip :label="runStatus" :status="runStatusType" />
        <el-button @click="router.push('/courses')">查看教材专题</el-button>
        <el-button @click="router.push('/knowledge')">管理资料</el-button>
      </template>
    </UiPageHeader>

    <UiCard class="prep-progress-card">
      <StepProgress :steps="steps" :current="currentStep" />
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
      <UiCard v-show="activeStage === 1" class="prep-settings stage-card">
        <template #title>
          <div><p class="eyebrow">01 · CONTEXT</p><h2>教学任务</h2></div>
        </template>
        <el-form label-position="top">
          <el-form-item label="课程">
            <el-select v-model="selectedCourseId" :disabled="isExecuting" placeholder="选择课程">
              <el-option v-for="item in courses" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="教材专题">
            <el-select v-model="selectedChapterId" :disabled="isExecuting" placeholder="选择专题">
              <el-option v-for="item in course?.chapters || []" :key="item.id" :label="item.title" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标教学班">
            <el-select v-model="selectedTeachingClassId" :disabled="isExecuting" placeholder="选择教学班">
              <el-option
                v-for="item in eligibleTeachingClasses"
                :key="item.id"
                :label="`${item.name} · ${item.term_name}`"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <div class="compact-form-row">
            <el-form-item label="课时">
              <el-input-number v-model="lessonHours" :min="1" :max="8" :disabled="isExecuting" />
            </el-form-item>
            <el-form-item label="学生层次">
              <el-select v-model="studentLevel" :disabled="isExecuting">
                <el-option label="本科生" value="本科生" />
                <el-option label="高职学生" value="高职学生" />
                <el-option label="研究生" value="研究生" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="教师补充目标">
            <el-input v-model="teachingGoal" type="textarea" :rows="4" :disabled="isExecuting" placeholder="可选：说明本次课希望重点解决的问题" />
          </el-form-item>
        </el-form>
        <el-button type="primary" class="full-button" :loading="acting" :disabled="!canStart" @click="startAgent">
          构建备课证据包
        </el-button>
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
            <p>选择需要的成果类型。系统会继续使用当前证据快照，不会重新引入未确认资料。</p>
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
                  重试{{ artifactLabels[key] }}
                </el-button>
              </div>
            </section>
            <div v-if="artifactTypes.includes('ppt')" class="ppt-preferences">
              <div class="preference-heading">
                <div>
                  <strong>PPT 生成偏好</strong>
                  <p>这些条件交给内容策划与视觉设计 Agent，不是切换固定模板。</p>
                </div>
                <el-button plain @click="templateDialogVisible = true">上传模板</el-button>
              </div>
              <div class="preference-grid">
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
                    <button type="button" :disabled="pptPreferences.slide_count <= 6" @click="changeSlideCount(-1)">−</button>
                    <label>
                      <input
                        :value="pptPreferences.slide_count"
                        type="number"
                        min="6"
                        max="30"
                        inputmode="numeric"
                        @change="handleSlideCountChange"
                      >
                      <span>页</span>
                    </label>
                    <button type="button" :disabled="pptPreferences.slide_count >= 30" @click="changeSlideCount(1)">＋</button>
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
            <el-progress
              v-if="isExecuting && currentRun?.current_step === 3"
              :percentage="58"
              indeterminate
              status="success"
            />
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
          <div><p class="eyebrow">05 · REVIEW & PUBLISH</p><h2>预览与发布</h2></div>
        </template>
        <template #actions>
          <div class="artifact-actions">
            <div v-if="pptVersions.length" class="version-switcher">
              <el-select v-model="selectedVersionId" placeholder="历史版本" size="small">
                <el-option
                  v-for="item in pptVersions"
                  :key="item.version_id"
                  :label="`${item.reason} · ${new Date(item.created_time).toLocaleString()}`"
                  :value="item.version_id"
                />
              </el-select>
              <el-button size="small" :disabled="!selectedVersionId" @click="restorePptVersion">恢复</el-button>
            </div>
            <StatusChip label="待教师核验" status="warning" />
          </div>
        </template>

        <section class="artifact-overview">
          <div>
            <p class="eyebrow">成果总览</p>
            <strong>先看齐全度，再决定发布什么</strong>
            <span>成果可以单独下载、补生成；发布前仍由教师选择教学班并确认。</span>
          </div>
          <div class="artifact-status-list">
            <span
              v-for="item in artifactStatusRows"
              :key="item.key"
              :class="['artifact-status-item', { 'is-ready': item.ready }]"
            >
              <span class="artifact-status-dot"></span>
              {{ item.label }} · {{ item.ready ? '已就绪' : '待补生成' }}
            </span>
          </div>
          <div v-if="failedArtifactStep && incompleteArtifactKeys.length" class="artifact-overview-retry">
            <span>生成步骤有异常，已完成内容不会被覆盖：</span>
            <el-button
              v-for="key in incompleteArtifactKeys"
              :key="`overview-${key}`"
              size="small"
              type="warning"
              plain
              :loading="acting"
              @click="retryArtifact(key)"
            >
              重试{{ artifactLabels[key] }}
            </el-button>
          </div>
        </section>

        <div class="artifact-file-grid">
          <article v-for="(item, key) in artifacts" :key="key" class="artifact-file">
            <span class="artifact-file-type">
              {{ key === 'ppt' ? 'PPTX' : 'DOCX' }}
            </span>
            <div>
              <strong>{{ item.title }}</strong>
              <p v-if="item.slide_count">{{ item.slide_count }} 页课件</p>
              <p v-else-if="item.activity_count">{{ item.activity_count }} 个课堂活动</p>
              <p v-else>可编辑教学文档</p>
            </div>
            <el-button type="primary" plain @click="downloadArtifact(String(key))">下载</el-button>
          </article>
        </div>

        <el-tabs v-model="artifactPreview" class="artifact-preview-tabs">
          <el-tab-pane v-if="artifactBundle?.ppt" label="PPT 逐页预览" name="ppt">
            <section v-if="pptQuality" class="ppt-quality" :class="{ 'is-passed': pptQuality.passed }">
              <div class="quality-score">
                <strong>{{ pptQuality.score }}</strong>
                <span>质量评分</span>
              </div>
              <div class="quality-content">
                <div class="quality-heading">
                  <div>
                    <small>AUTOMATED REVIEW</small>
                    <strong>{{ pptQuality.passed ? '已通过自动质检' : '建议修改后再使用' }}</strong>
                  </div>
                  <span>{{ pptQuality.summary }}</span>
                </div>
                <div v-if="pptQuality.issues.length" class="quality-issues">
                  <button
                    v-for="(issue, issueIndex) in pptQuality.issues"
                    :key="`${issue.slide_index}-${issueIndex}`"
                    type="button"
                    @click="issue.slide_index !== null && openSlideRevision(issue.slide_index)"
                  >
                    <b>{{ issue.slide_index === null ? '整套' : `第 ${issue.slide_index + 1} 页` }}</b>
                    <span>{{ issue.message }}</span>
                    <small>{{ issue.suggestion }}</small>
                  </button>
                </div>
              </div>
            </section>
            <div v-if="artifactBundle.ppt.design" class="ppt-design-brief">
              <div>
                <small>VISUAL DIRECTION</small>
                <strong>{{ artifactBundle.ppt.design.name }}</strong>
                <p>{{ artifactBundle.ppt.design.concept }}</p>
              </div>
              <StatusChip
                :type="artifactBundle.ppt.design.status === 'personalized' ? 'success' : 'warning'"
                :label="artifactBundle.ppt.design.status === 'personalized' ? '个性化视觉已生成' : '安全版式回退'"
              />
            </div>
            <el-alert
              v-if="artifactBundle.ppt.multimodal"
              :title="artifactBundle.ppt.multimodal.message"
              :description="artifactBundle.ppt.multimodal.generated_count && artifactBundle.ppt.multimodal.selected_slides?.length
                ? `已生成第 ${artifactBundle.ppt.multimodal.selected_slides.join('、')} 页辅助插图`
                : undefined"
              :type="artifactBundle.ppt.multimodal.status === 'completed' ? 'success' : 'warning'"
              :closable="false"
              show-icon
              class="multimodal-status"
            />
            <div class="slide-preview-list">
              <article
                v-for="(slide, index) in artifactBundle.ppt.slides"
                :key="`${slide.title}-${index}`"
                class="slide-preview"
                :class="{ [`is-${slide.layout}`]: !slide.canvas?.length, 'has-canvas': slide.canvas?.length }"
              >
                <div class="slide-actions">
                  <el-button size="small" @click="openSlideRevision(index)">修改本页</el-button>
                </div>
                <div
                  v-if="slide.canvas?.length"
                  class="canvas-preview"
                  :style="{ backgroundColor: canvasBackground(slide, artifactBundle.ppt) }"
                >
                  <template v-for="(element, elementIndex) in slide.canvas" :key="`${element.source}-${elementIndex}`">
                    <div
                      v-if="element.type === 'text'"
                      class="canvas-element is-text"
                      :style="canvasElementStyle(element, artifactBundle.ppt)"
                    >
                      {{ canvasSource(slide, element.source, index) }}
                    </div>
                    <div
                      v-else
                      class="canvas-element"
                      :class="`is-${element.type}`"
                      :style="canvasElementStyle(element, artifactBundle.ppt)"
                    />
                  </template>
                </div>
                <template v-else>
                  <span>{{ String(index + 1).padStart(2, '0') }}</span>
                  <div>
                  <small>{{ slide.layout.toUpperCase() }}</small>
                  <h3>{{ slide.title }}</h3>
                  <strong>{{ slide.takeaway }}</strong>
                  <div v-if="slide.layout === 'concept' && slide.keyword" class="preview-keyword">
                    {{ slide.keyword }}
                  </div>
                  <div
                    v-if="slide.layout === 'comparison' && (slide.left || slide.right)"
                    class="preview-comparison"
                  >
                    <section>
                      <b>{{ slide.left?.title }}</b>
                      <ul><li v-for="item in slide.left?.points" :key="item">{{ item }}</li></ul>
                    </section>
                    <section>
                      <b>{{ slide.right?.title }}</b>
                      <ul><li v-for="item in slide.right?.points" :key="item">{{ item }}</li></ul>
                    </section>
                  </div>
                  <div v-else-if="slide.steps?.length" class="preview-steps">
                    <section v-for="(step, stepIndex) in slide.steps" :key="`${step.title}-${stepIndex}`">
                      <i>{{ stepIndex + 1 }}</i>
                      <b>{{ step.title }}</b>
                      <p>{{ step.description }}</p>
                    </section>
                  </div>
                  <div v-else-if="slide.timeline?.length" class="preview-timeline">
                    <section
                      v-for="(item, timelineIndex) in slide.timeline"
                      :key="`${item.label}-${timelineIndex}`"
                    >
                      <b>{{ item.label }}</b>
                      <p>{{ item.title }}</p>
                    </section>
                  </div>
                  <ul v-else><li v-for="item in slide.bullets" :key="item">{{ item }}</li></ul>
                  </div>
                </template>
              </article>
            </div>
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
.lesson-prep-workspace { display: grid; gap: var(--space-5); }
.prep-progress-card { overflow: auto; }
.stage-navigation { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-2); margin-top: var(--space-5); }
.stage-navigation button { display: flex; min-width: 0; align-items: center; justify-content: center; gap: var(--space-2); padding: 10px 12px; color: var(--ink-400); background: var(--surface-muted); border: 1px solid var(--line); border-radius: 999px; font: inherit; font-size: var(--fs-meta); cursor: pointer; }
.stage-navigation button span { color: var(--ink-300); font-family: Georgia, serif; }
.stage-navigation button.available { color: var(--ink-700); cursor: pointer; }
.stage-navigation button.active { color: white; background: linear-gradient(110deg, var(--authority-red), var(--action-blue)); border-color: transparent; box-shadow: var(--shadow-card); }
.stage-navigation button.active span { color: #f8db9a; }
.stage-navigation button:disabled { cursor: not-allowed; opacity: .55; }
.run-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-top: var(--space-5); padding-top: var(--space-3); color: var(--ink-400); border-top: 1px solid var(--line); font-size: var(--fs-meta); }
.prep-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.prep-grid h2 { margin: var(--space-1) 0 0; font-size: var(--fs-section); }
.prep-settings, .prep-evidence, .prep-output, .artifact-results { min-width: 0; }
.stage-card { width: 100%; }
.prep-settings :deep(.el-select), .prep-settings :deep(.el-input-number) { width: 100%; }
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
.artifact-builder { padding: clamp(18px, 3vw, 36px); background: var(--surface-muted); border-radius: var(--radius-card); }
.artifact-builder :deep(.el-checkbox-group) { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.artifact-builder :deep(.el-checkbox-button__inner) { border: 1px solid var(--line); border-radius: var(--radius-input); box-shadow: none; }
.artifact-retry-banner { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-top: var(--space-4); padding: var(--space-3); color: #7a4a00; background: #fff8e8; border: 1px solid #efd48a; border-radius: var(--radius-input); }
.artifact-retry-banner p { margin: 4px 0 0; color: #876b35; font-size: var(--fs-meta); }
.artifact-retry-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
.ppt-preferences { display: grid; gap: var(--space-3); margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--line); }
.preference-heading, .quality-heading, .artifact-actions, .version-switcher { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.preference-heading p { margin: 4px 0 0; color: var(--ink-400); font-size: var(--fs-meta); }
.preference-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 var(--space-3); }
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
.artifact-actions { flex-wrap: wrap; }
.version-switcher :deep(.el-select) { width: min(300px, 38vw); }
.artifact-overview { display: grid; gap: var(--space-3); margin-bottom: var(--space-4); padding: var(--space-4); background: linear-gradient(135deg, #f3f7ff, #fffaf0); border: 1px solid #d8e2f6; border-radius: var(--radius-card); }
.artifact-overview > div:first-child { display: grid; gap: 4px; }
.artifact-overview strong { color: var(--ink-900); font-size: var(--fs-card-title); }
.artifact-overview > div:first-child > span { color: var(--ink-500); font-size: var(--fs-meta); }
.artifact-status-list { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.artifact-status-item { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; color: var(--ink-500); background: white; border: 1px solid var(--line); border-radius: 999px; font-size: var(--fs-meta); }
.artifact-status-item.is-ready { color: #167a42; border-color: #b9dfc7; background: #f0faf4; }
.artifact-status-dot { width: 7px; height: 7px; background: var(--ink-300); border-radius: 50%; }
.artifact-status-item.is-ready .artifact-status-dot { background: #2aa361; }
.artifact-overview-retry { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); color: #876b35; font-size: var(--fs-meta); }
.artifact-file-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.artifact-file { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: var(--space-3); padding: var(--space-4); background: var(--surface-muted); border: 1px solid var(--line); border-radius: var(--radius-card); }
.artifact-file-type { display: grid; width: 48px; height: 48px; place-items: center; color: white; background: var(--authority-red); border-radius: 50%; font-size: 11px; font-weight: var(--fw-bold); }
.artifact-file strong, .artifact-file p { margin: 0; }
.artifact-file p { margin-top: 4px; color: var(--ink-400); font-size: var(--fs-meta); }
.artifact-preview-tabs { margin-top: var(--space-5); }
.multimodal-status { margin-bottom: var(--space-4); }
.ppt-quality { display: grid; grid-template-columns: 116px minmax(0, 1fr); gap: var(--space-4); margin-bottom: var(--space-4); padding: var(--space-4); background: #fff5f3; border: 1px solid #f2c7c0; border-radius: var(--radius-card); }
.ppt-quality.is-passed { background: #f0faf4; border-color: #b9dfc7; }
.quality-score { display: grid; align-content: center; justify-items: center; border-right: 1px solid var(--line); }
.quality-score strong { color: var(--authority-red); font-family: Georgia, serif; font-size: 42px; line-height: 1; }
.ppt-quality.is-passed .quality-score strong { color: #167a42; }
.quality-score span { margin-top: 6px; color: var(--ink-400); font-size: var(--fs-meta); }
.quality-content { min-width: 0; }
.quality-heading { align-items: flex-start; }
.quality-heading small { display: block; color: var(--action-blue); letter-spacing: .12em; }
.quality-heading strong { display: block; margin-top: 4px; }
.quality-heading > span { max-width: 48%; color: var(--ink-500); font-size: var(--fs-meta); text-align: right; }
.quality-issues { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); margin-top: var(--space-3); }
.quality-issues button { display: grid; gap: 4px; padding: var(--space-3); color: inherit; background: rgb(255 255 255 / 72%); border: 1px solid var(--line); border-radius: var(--radius-input); text-align: left; cursor: pointer; }
.quality-issues button:hover { border-color: var(--action-blue); }
.quality-issues b { color: var(--authority-red); font-size: var(--fs-meta); }
.quality-issues span { font-weight: var(--fw-semibold); }
.quality-issues small { color: var(--ink-500); line-height: 1.5; }
.slide-preview-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.ppt-design-brief { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-4); padding: var(--space-4); color: white; background: linear-gradient(125deg, #721b2b, #244f9d); border-radius: var(--radius-card); }
.ppt-design-brief small { display: block; margin-bottom: var(--space-1); color: #f0d691; letter-spacing: .14em; }
.ppt-design-brief strong { display: block; font-size: var(--fs-h3); }
.ppt-design-brief p { max-width: 720px; margin: var(--space-2) 0 0; color: #e7edf8; line-height: 1.65; }
.slide-preview { position: relative; display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: var(--space-3); min-height: 220px; padding: var(--space-4); background: linear-gradient(145deg, #fff, var(--surface-muted)); border-left: 5px solid var(--authority-red); border-radius: var(--radius-card); }
.slide-actions { position: absolute; z-index: 3; top: var(--space-2); right: var(--space-2); opacity: 0; transition: opacity .18s ease; }
.slide-preview:hover .slide-actions, .slide-preview:focus-within .slide-actions { opacity: 1; }
.slide-preview.has-canvas { display: block; min-height: 0; padding: 0; overflow: hidden; background: #111827; border: 1px solid var(--border-default); border-left-width: 1px; aspect-ratio: 16 / 9; box-shadow: var(--shadow-card); }
.canvas-preview { position: relative; width: 100%; height: 100%; overflow: hidden; }
.canvas-element { position: absolute; box-sizing: border-box; }
.canvas-element.is-text { display: flex; align-items: center; overflow: hidden; padding: 2px; line-height: 1.28; white-space: normal; }
.canvas-element.is-shape { border: 1px solid; }
.canvas-element.is-line { height: 0 !important; border-top: 2px solid; background: transparent !important; }
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
@media (max-width: 1199px) { .artifact-file-grid { grid-template-columns: 1fr; } }
@media (max-width: 767px) { .stage-navigation { display: flex; overflow-x: auto; padding-bottom: var(--space-1); } .stage-navigation button { min-width: 132px; } .prep-grid, .compact-form-row, .slide-preview-list, .preference-grid, .quality-issues, .publish-form-grid { grid-template-columns: 1fr; } .prep-output, .artifact-results { grid-column: auto; } .run-toolbar, .preference-heading, .quality-heading, .publish-heading, .artifact-retry-banner { align-items: flex-start; flex-direction: column; } .artifact-file { grid-template-columns: auto minmax(0, 1fr); } .artifact-file .el-button { grid-column: 1 / -1; } .ppt-quality { grid-template-columns: 1fr; } .quality-score { padding-bottom: var(--space-3); border-right: 0; border-bottom: 1px solid var(--line); } .quality-heading > span { max-width: none; text-align: left; } .slide-actions { opacity: 1; } }
</style>

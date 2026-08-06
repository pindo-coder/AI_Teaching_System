<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, CircleCheck, Delete, Loading, MagicStick, Promotion, Plus, RefreshRight, Setting, Tickets } from '@element-plus/icons-vue'
import {
  aiApi,
  type AiAgentAction,
  type AiAgentExecution,
  type AiAgentPlan,
  type AiAgentTemplate,
  type AiSource,
  type AiWorkspaceContext,
  type AiWorkspaceMode,
  type AiWorkspaceRole,
} from '@/api/ai'
import { agentApi, type AgentRun } from '@/api/agents'
import { useAuthStore } from '@/stores/auth'
import type { LearningStage } from '@/types'
import { renderTeachingDocument } from '@/utils/richText'

interface AssistantMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  grounded?: boolean
  model?: string
  sources?: AiSource[]
  plan?: AiAgentPlan
  progress?: Array<{ title: string; status: string }>
  actions?: AiAgentAction[]
  toolCalls?: Array<{ name: string; title: string; status: string; error?: string; requires_confirmation?: boolean }>
  execution?: AiAgentExecution
  run?: AgentRun
  createdAt: string
}

interface QuickAction {
  title: string
  description: string
  prompt: string
  icon: typeof Setting
  requiresContext?: boolean
}

const props = defineProps<{
  courseId?: number | null
  chapterId?: number | null
  teachingClassId?: number | null
  learningStage?: LearningStage
  pageName?: string
  context?: AiWorkspaceContext | null
}>()

const emit = defineEmits<{ (event: 'context-updated', context: AiWorkspaceContext): void }>()

const auth = useAuthStore()
const router = useRouter()
const mode = ref<AiWorkspaceMode>(auth.user?.role === 'student' ? 'chat' : 'agent')
const messages = ref<AssistantMessage[]>([])
const question = ref('')
const loading = ref(false)
const historyVisible = ref(false)
const taskCenterVisible = ref(false)
const executions = ref<AiAgentExecution[]>([])
const serverTemplates = ref<AiAgentTemplate[]>([])
const executionLoading = ref(false)
const messageList = ref<HTMLElement | null>(null)
const role = computed<AiWorkspaceRole>(() => auth.user?.role || 'student')
const roleLabel = computed(() => ({ student: '学生学习助手', teacher: '教师备课助手', admin: '教学管理助手' }[role.value]))
const contextLabel = computed(() => {
  if (props.context?.course_name && props.context.chapter_title) return `${props.context.course_name} · ${props.context.chapter_title}`
  if (props.context?.course_name) return `${props.context.course_name} · 待选专题`
  if (props.courseId && props.chapterId) return props.learningStage === 'review' ? '当前专题 · 课后巩固' : props.learningStage === 'exam' ? '当前专题 · 考前冲刺' : '当前专题 · 课前预习'
  return '正在自动识别教学范围'
})
const storageKey = computed(() => `workspace-ai-history:${auth.user?.id || 'guest'}:${props.context?.course_id || props.courseId || 0}:${props.context?.chapter_id || props.chapterId || 0}`)
function templateIcon(category: string) {
  if (category === 'interaction') return ChatDotRound
  if (category === 'monitor' || category === 'review') return RefreshRight
  if (category === 'task') return CircleCheck
  if (category === 'plan') return Setting
  return MagicStick
}
const quickActions = computed<QuickAction[]>(() => {
  if (serverTemplates.value.length) return serverTemplates.value.map((item) => ({
    title: item.title,
    description: item.description,
    prompt: item.prompt,
    icon: templateIcon(item.category),
    requiresContext: item.requires_context,
  }))
  if (role.value === 'teacher') return [
    { title: '生成本专题课纲', description: '梳理目标、重点和课堂流程', prompt: '请根据当前教材专题给出一份可编辑的课程备课方案。', icon: Setting },
    { title: '生成 PPT 工作流', description: '创建草稿后按需生成课件', prompt: '请为当前教材专题创建一份包含 PPT 的备课草稿。', icon: MagicStick },
    { title: '设计课堂互动', description: '生成讨论题与学生参与方式', prompt: '请围绕当前教材专题设计一组课堂互动活动，并说明教师引导语。', icon: ChatDotRound },
    { title: '布置学习任务', description: '先形成草案，再由教师发布', prompt: '请为当前教材专题设计一项课后学习任务。', icon: Setting },
    { title: '查看任务学情', description: '汇总待完成与完成进度', prompt: '请帮我分析当前教学任务的完成情况和需跟进事项。', icon: CircleCheck },
    { title: '准备批改量规', description: '不伪造批改，先建立标准', prompt: '请为当前专题准备一份作业批改量规和反馈模板。', icon: RefreshRight },
  ]
  if (role.value === 'admin') return [
    { title: '检查资料索引', description: '查看当前教材知识库状态', prompt: '请帮我检查当前教材资料是否具备可检索的索引和引用依据。', icon: CircleCheck },
    { title: '规划资料更新', description: '整理版本与权威材料更新事项', prompt: '请给出当前教材和中央材料的更新检查清单。', icon: RefreshRight },
    { title: '审核资料范围', description: '检查教材与中央材料优先级', prompt: '请检查当前资料范围和中央材料优先级。', icon: MagicStick },
    { title: '查看任务学情', description: '汇总班级任务完成情况', prompt: '请帮我分析当前教学任务的完成情况。', icon: ChatDotRound },
    { title: '准备教师备课', description: '创建可审阅的备课草稿', prompt: '请为当前专题创建可审阅的备课草稿。', icon: Setting },
    { title: '查看操作边界', description: '确认需要人工审核的操作', prompt: '请说明管理员当前可用的资料、索引和审核操作。', icon: CircleCheck },
  ]
  return [
    { title: '制定学习计划', description: '结合学习阶段安排下一步', prompt: '请根据当前专题和我的学习状态制定学习计划。', icon: MagicStick },
    { title: '查看待完成任务', description: '优先处理教师布置内容', prompt: '请帮我查看当前待完成的学习任务。', icon: CircleCheck },
    { title: '梳理本章重点', description: '生成结构化复习线索', prompt: '请用简洁的层级结构梳理当前专题的学习重点。', icon: CircleCheck },
    { title: '生成预习问题', description: '带着问题进入课堂', prompt: '请严格依据当前专题教材生成 5 个预习问题。', icon: ChatDotRound },
    { title: '解释核心概念', description: '结合教材原文说明', prompt: '请用教材化表达解释当前专题中最重要的核心概念。', icon: MagicStick },
    { title: '考前冲刺建议', description: '定位重点与易混概念', prompt: '请根据当前专题给出考前冲刺的复习顺序。', icon: RefreshRight },
  ]
})

const renderedMessages = computed(() => messages.value.map((message) => ({
  ...message,
  rendered: message.role === 'assistant' ? renderTeachingDocument(message.content) : '',
})))

function loadHistory() {
  try {
    const raw = localStorage.getItem(storageKey.value)
    messages.value = raw ? JSON.parse(raw) as AssistantMessage[] : []
  } catch { messages.value = [] }
}
function persistHistory() {
  localStorage.setItem(storageKey.value, JSON.stringify(messages.value.slice(-40)))
}
function scrollToBottom() {
  void nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}
function selectQuickAction(prompt: string, selectedMode: AiWorkspaceMode = mode.value) {
  mode.value = selectedMode
  question.value = prompt
}
function newConversation() {
  messages.value = []
  historyVisible.value = false
  localStorage.removeItem(storageKey.value)
}
function clearHistory() {
  newConversation()
  ElMessage.success('本次 AI 会话已清空')
}
async function loadExecutions() {
  executionLoading.value = true
  try {
    const response = await aiApi.workspaceAgentExecutions()
    executions.value = response.data.data
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '任务中心暂时无法加载')
  } finally {
    executionLoading.value = false
  }
}
async function loadTemplates() {
  try {
    const response = await aiApi.workspaceAgentTemplates()
    serverTemplates.value = response.data.data
  } catch {
    // 保留本地模板回退，不让模板接口异常影响基础问答。
    serverTemplates.value = []
  }
}
function openTaskCenter() {
  taskCenterVisible.value = !taskCenterVisible.value
  historyVisible.value = false
  if (taskCenterVisible.value) void loadExecutions()
}
function executionStatusLabel(status: AiAgentExecution['status']) {
  return ({ planning: '正在规划', running: '正在执行', waiting_confirmation: '等待确认', completed: '已完成', failed: '执行异常', cancelled: '已取消' } as Record<AiAgentExecution['status'], string>)[status]
}
async function retryExecution(execution: AiAgentExecution) {
  if (loading.value) return
  try {
    const response = await aiApi.retryWorkspaceAgentExecution(execution.id)
    taskCenterVisible.value = false
    question.value = execution.question
    await send(response.data.data.id)
    void loadExecutions()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建重试任务失败')
  }
}
async function confirmPendingExecution(execution: AiAgentExecution) {
  const action = execution.result?.blocking_actions?.[0]
  if (!action || action.kind !== 'approve_evidence' || !action.run_id) {
    ElMessage.warning('该任务需要先进入对应业务页面完成确认')
    if (action?.href) void router.push(action.href)
    return
  }
  try {
    await agentApi.confirmEvidence(action.run_id)
    await aiApi.resolveWorkspaceAgentExecution(execution.id, 'confirmed', '已在 Agent 任务中心确认教材证据')
    ElMessage.success('资料已确认，课纲正在后台生成')
    void router.push({ path: '/lesson-prep', query: { run_id: String(action.run_id) } })
    await loadExecutions()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '确认失败，请稍后重试')
  }
}
async function cancelPendingExecution(execution: AiAgentExecution) {
  try {
    await aiApi.resolveWorkspaceAgentExecution(execution.id, 'cancelled', '用户取消待确认操作')
    ElMessage.success('已取消本次 Agent 后续操作')
    await loadExecutions()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '取消失败，请稍后重试')
  }
}
function updateAssistantMessage(id: number, updater: (message: AssistantMessage) => void) {
  const message = messages.value.find((item) => item.id === id)
  if (message) updater(message)
}
function generationLabel(message: AssistantMessage) {
  return message.progress?.at(-1)?.title || '正在连接 Agent 并准备执行任务'
}
function navigateAction(action: AiAgentAction) {
  if (!action.href) return
  void router.push(action.href)
}
function openLessonPrep(runId: number) {
  void router.push({ path: '/lesson-prep', query: { run_id: String(runId) } })
}
function runStatusLabel(status: AgentRun['status']) {
  return ({
    queued: '任务已排队',
    running: '正在生成',
    waiting_confirmation: '等待确认',
    completed: '已完成',
    failed: '生成失败',
    cancelled: '已取消',
  } as Record<AgentRun['status'], string>)[status]
}
function planStatus(status: string): AiAgentPlan['steps'][number]['status'] {
  if (status === 'completed') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed' || status === 'cancelled') return 'blocked'
  if (status === 'waiting_confirmation') return 'needs_input'
  if (status === 'queued') return 'pending'
  return 'pending'
}
function runFailure(run: AgentRun) {
  const failedStep = run.steps.find((step) => step.status === 'failed')
  return failedStep?.error_message || (run.status === 'failed' ? run.error_message : null)
}
function updateRunSnapshot(messageId: number, run: AgentRun) {
  updateAssistantMessage(messageId, (message) => {
    message.run = run
    message.plan = {
      intent: 'lesson_prep',
      title: '备课任务实时进度',
      steps: run.steps.map((step) => ({ key: step.step_key, title: step.title, status: planStatus(step.status) })),
    }
    const latest = run.steps.find((step) => step.status === 'running' || step.status === 'queued')
    const failedStep = run.steps.find((step) => step.status === 'failed')
    const progressText = failedStep
      ? `${failedStep.title}失败：${failedStep.error_message || '可重新执行该步骤'}`
      : run.status === 'completed'
      ? '课纲已生成，可继续选择教学成果'
      : run.status === 'failed'
        ? `生成失败：${run.error_message || '请重试'}`
        : latest
          ? `${latest.title}：${runStatusLabel(run.status)}`
          : runStatusLabel(run.status)
    const previous = message.progress?.at(-1)
    if (previous?.title !== progressText) {
      message.progress = [...(message.progress || []), {
        title: progressText,
        status: run.status === 'completed' ? 'completed' : run.status === 'failed' ? 'failed' : 'running',
      }]
    }
  })
  persistHistory()
  scrollToBottom()
}
async function retryRun(messageId: number, run: AgentRun) {
  try {
    const response = await agentApi.retry(run.id)
    const retried = response.data.data
    updateRunSnapshot(messageId, retried)
    updateAssistantMessage(messageId, (message) => {
      message.actions = [{
        kind: 'approve_evidence',
        label: '确认资料并重新生成课纲',
        href: '',
        run_id: retried.id,
        requires_confirmation: true,
      }]
      message.content += '\n\n已重新构建证据快照。请确认资料范围后重新生成课纲。'
    })
    persistHistory()
    ElMessage.success('已创建重试任务，请重新确认资料范围')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重试任务创建失败，请稍后重试')
  }
}
async function watchRun(messageId: number, runId: number) {
  try {
    await agentApi.stream(runId, {
      onSnapshot: (run) => updateRunSnapshot(messageId, run),
    })
  } catch (error) {
    updateAssistantMessage(messageId, (message) => {
      message.progress = [...(message.progress || []), {
        title: error instanceof Error ? error.message : '任务进度连接中断，可稍后刷新查看。',
        status: 'failed',
      }]
    })
    persistHistory()
  }
}
async function executeAction(messageId: number, action: AiAgentAction) {
  if (action.kind !== 'approve_evidence' || !action.run_id) {
    navigateAction(action)
    return
  }
  if (action.status === 'running' || action.status === 'completed') return

  action.status = 'running'
  try {
    const response = await agentApi.confirmEvidence(action.run_id)
    action.status = 'completed'
    action.label = '已确认，课纲正在后台生成'
    updateRunSnapshot(messageId, response.data.data)
    const currentExecution = messages.value.find((item) => item.id === messageId)?.execution
    if (currentExecution?.status === 'waiting_confirmation') {
      try {
        const resolved = await aiApi.resolveWorkspaceAgentExecution(currentExecution.id, 'confirmed', '已在 Agent 对话中确认教材证据')
        updateAssistantMessage(messageId, (message) => { message.execution = resolved.data.data })
      } catch {
        // 备课工作流已经成功启动，执行记录可在任务中心继续同步，不反向报错。
      }
    }
    void watchRun(messageId, action.run_id)
    ElMessage.success('资料已确认，课纲正在后台生成')
  } catch (error) {
    action.status = 'failed'
    action.label = '重新确认并生成课纲'
    persistHistory()
    ElMessage.error(error instanceof Error ? error.message : '确认失败，请稍后重试')
  }
}
async function generateArtifacts(messageId: number, run: AgentRun, outputTypes: Array<'ppt' | 'lesson_plan' | 'classroom_activities'>) {
  if (run.status === 'queued' || run.status === 'running') return
  try {
    const response = await agentApi.generateArtifacts(run.id, outputTypes)
    updateRunSnapshot(messageId, response.data.data)
    void watchRun(messageId, run.id)
    ElMessage.success('教学成果正在后台生成，进度会持续显示在当前对话中')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '教学成果生成失败，请稍后重试')
  }
}
async function downloadArtifact(run: AgentRun, artifactKey: string, fileName: string) {
  try {
    const response = await agentApi.downloadArtifact(run.id, artifactKey)
    const link = document.createElement('a')
    link.href = URL.createObjectURL(response.data)
    link.download = fileName
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(link.href)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '成果下载失败，请稍后重试')
  }
}
async function send(executionId?: number | Event) {
  // Vue 会把 click/keydown 的原生事件作为无参处理器的第一个参数传入。
  // 只有任务中心显式传入的数字才是 execution_id，原生事件必须忽略。
  const safeExecutionId = typeof executionId === 'number' && Number.isInteger(executionId) && executionId > 0
    ? executionId
    : undefined
  const content = (safeExecutionId
    ? executions.value.find((item) => item.id === safeExecutionId)?.question || question.value
    : question.value).trim()
  if (!content || loading.value) return
  question.value = ''
  const userMessage: AssistantMessage = { id: Date.now(), role: 'user', content, createdAt: new Date().toISOString() }
  const assistantMessage: AssistantMessage = { id: Date.now() + 1, role: 'assistant', content: '', grounded: false, sources: [], progress: [], actions: [], createdAt: new Date().toISOString() }
  messages.value.push(userMessage, assistantMessage)
  historyVisible.value = false
  taskCenterVisible.value = false
  loading.value = true
  scrollToBottom()
  try {
    const currentScope = {
      course_id: props.context?.course_id || props.courseId || null,
      chapter_id: props.context?.chapter_id || props.chapterId || null,
      teaching_class_id: props.context?.teaching_class_id || props.teachingClassId || null,
      learning_stage: props.context?.learning_stage || props.learningStage || 'preview',
      page_name: props.pageName || null,
    }
    // 从任务中心重试时必须锁定原任务的上下文快照，不能被当前页面的课程覆盖。
    const scope = safeExecutionId
      ? { course_id: null, chapter_id: null, teaching_class_id: null, learning_stage: 'preview' as LearningStage, page_name: null }
      : currentScope
    if (mode.value === 'agent') {
      await aiApi.workspaceAgentStream({ role: role.value, question: content, execution_id: safeExecutionId, ...scope }, {
        onContext: (context) => {
          emit('context-updated', context)
          updateAssistantMessage(assistantMessage.id, (message) => { message.grounded = Boolean(context.course_id && context.chapter_id) })
        },
        onMeta: (meta) => updateAssistantMessage(assistantMessage.id, (message) => { message.grounded = meta.grounded; message.model = meta.model }),
        onExecution: (execution) => updateAssistantMessage(assistantMessage.id, (message) => { message.execution = execution }),
        onPlan: (plan) => updateAssistantMessage(assistantMessage.id, (message) => { message.plan = plan }),
        onProgress: (progress) => updateAssistantMessage(assistantMessage.id, (message) => { message.progress = [...(message.progress || []), progress] }),
        onTool: (tool) => updateAssistantMessage(assistantMessage.id, (message) => {
          const existing = message.toolCalls || []
          const index = existing.findIndex((item) => item.name === tool.name)
          if (index >= 0) existing[index] = tool
          else existing.push(tool)
          message.toolCalls = [...existing]
        }),
        onAction: (action) => {
          updateAssistantMessage(assistantMessage.id, (message) => { message.actions = [...(message.actions || []), action] })
          // 生成类工具沿用已有备课成果接口，规划器不直接写文件；生成完成后
          // 仍只展示可下载结果，发布权留给教师。
          if (action.kind === 'generate_artifacts' && action.run_id && action.output_types?.length) {
            action.status = 'running'
            void (async () => {
              try {
                const detail = await agentApi.detail(action.run_id!)
                updateRunSnapshot(assistantMessage.id, detail.data.data)
                await generateArtifacts(assistantMessage.id, detail.data.data, action.output_types!)
                action.status = 'completed'
                action.label = '成果生成已提交'
                persistHistory()
              } catch (error) {
                action.status = 'failed'
                ElMessage.error(error instanceof Error ? error.message : '成果生成失败，请稍后重试')
              }
            })()
          }
        },
        onChunk: (text) => { updateAssistantMessage(assistantMessage.id, (message) => { message.content += text }); scrollToBottom() },
        onSources: (sources) => updateAssistantMessage(assistantMessage.id, (message) => { message.sources = sources }),
      })
    } else {
      await aiApi.workspaceStream({ mode: mode.value, role: role.value, question: content, ...scope }, {
        onMeta: (meta) => updateAssistantMessage(assistantMessage.id, (message) => { message.grounded = meta.grounded; message.model = meta.model }),
        onChunk: (text) => { updateAssistantMessage(assistantMessage.id, (message) => { message.content += text }); scrollToBottom() },
        onSources: (sources) => updateAssistantMessage(assistantMessage.id, (message) => { message.sources = sources }),
      })
    }
    persistHistory()
    if (mode.value === 'agent') void loadExecutions()
  } catch (error: unknown) {
    updateAssistantMessage(assistantMessage.id, (message) => {
      message.content = error instanceof Error ? error.message : 'AI 暂时无法连接，请稍后重试。'
      message.grounded = false
    })
    persistHistory()
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

watch(storageKey, loadHistory, { immediate: true })
onMounted(() => { void loadTemplates() })
</script>

<template>
  <section class="workspace-ai-assistant">
    <div class="workspace-ai-toolbar">
      <div class="workspace-ai-context"><span class="workspace-ai-context-dot"></span><div><strong>{{ roleLabel }}</strong><small>{{ contextLabel }}</small></div></div>
      <div class="workspace-ai-toolbar-actions">
        <el-tooltip content="新建会话"><el-button text :icon="Plus" aria-label="新建会话" @click="newConversation" /></el-tooltip>
        <el-tooltip content="任务中心"><el-button text :icon="Tickets" aria-label="打开任务中心" @click="openTaskCenter" /></el-tooltip>
        <el-tooltip content="历史记录"><el-button text :icon="RefreshRight" aria-label="查看历史记录" @click="historyVisible = !historyVisible; taskCenterVisible = false" /></el-tooltip>
        <el-tooltip content="清空会话"><el-button text :icon="Delete" aria-label="清空会话" @click="clearHistory" /></el-tooltip>
      </div>
    </div>

    <div v-if="taskCenterVisible" class="workspace-ai-history workspace-ai-task-center">
      <div class="workspace-ai-history-heading"><strong>Agent 任务中心</strong><el-button text size="small" :loading="executionLoading" @click="loadExecutions">刷新</el-button></div>
      <article v-for="execution in executions" :key="execution.id" class="workspace-ai-task-item">
        <div><el-tag size="small" :type="execution.status === 'completed' ? 'success' : execution.status === 'failed' ? 'danger' : 'warning'">{{ executionStatusLabel(execution.status) }}</el-tag><span>#{{ execution.id }} · {{ execution.intent }}</span></div>
        <strong>{{ execution.question }}</strong>
        <small>{{ execution.result?.summary || execution.error_message || '任务正在建立执行记录' }}</small>
        <div class="workspace-ai-task-actions">
          <template v-if="execution.status === 'waiting_confirmation'">
            <el-button size="small" type="primary" @click="confirmPendingExecution(execution)">确认并继续</el-button>
            <el-button size="small" @click="cancelPendingExecution(execution)">取消</el-button>
          </template>
          <el-button v-else-if="execution.status === 'failed' || execution.status === 'completed'" size="small" type="primary" plain @click="retryExecution(execution)">基于此任务重试</el-button>
        </div>
      </article>
      <el-empty v-if="!executions.length && !executionLoading" description="还没有可追踪的 Agent 任务" :image-size="68" />
    </div>
    <div v-else-if="historyVisible" class="workspace-ai-history">
      <div class="workspace-ai-history-heading"><strong>本章会话</strong><span>{{ messages.length }} 条消息</span></div>
      <button v-for="message in messages" :key="message.id" type="button" class="workspace-ai-history-item" @click="historyVisible = false; scrollToBottom()">
        <span :class="`history-role-${message.role}`">{{ message.role === 'user' ? '我' : 'AI' }}</span><p>{{ message.content || '正在生成……' }}</p>
      </button>
      <el-empty v-if="!messages.length" description="还没有历史会话" :image-size="68" />
    </div>

    <div v-else ref="messageList" class="workspace-ai-scroll">
      <section v-if="!messages.length" class="workspace-ai-welcome">
        <div class="workspace-ai-welcome-icon"><el-icon><MagicStick /></el-icon><span>AI</span></div>
        <div><p class="workspace-ai-eyebrow">IDEOLOGY · SMART TUTOR</p><h2>你好，我是思政 AI 助教</h2><p>围绕教材、专题和学习阶段，帮你把问题变成可执行的学习任务。</p></div>
      </section>
      <section v-if="!messages.length" class="workspace-ai-capabilities">
        <p>我可以帮你</p>
        <button v-for="action in quickActions" :key="action.title" type="button" @click="selectQuickAction(action.prompt, 'agent')"><el-icon><component :is="action.icon" /></el-icon><span><strong>{{ action.title }}</strong><small>{{ action.description }}</small><em v-if="action.requiresContext && !(props.context?.chapter_id || props.chapterId)">执行前需选择教材专题</em></span></button>
      </section>
      <div v-for="message in renderedMessages" :key="message.id" class="workspace-ai-message" :class="`is-${message.role}`">
        <div v-if="message.role === 'assistant'" class="workspace-ai-avatar"><el-icon><MagicStick /></el-icon><span>AI</span></div>
        <div class="workspace-ai-bubble">
          <p v-if="message.role === 'user'">{{ message.content }}</p>
          <article v-else class="teaching-document">
            <div v-if="!message.content && loading && message.id === messages[messages.length - 1]?.id" class="workspace-ai-generating" role="status" aria-live="polite">
              <span class="workspace-ai-generating-spinner"><el-icon class="is-loading"><Loading /></el-icon></span>
              <span><strong>{{ generationLabel(message) }}</strong><small>Agent 正在执行，请保持当前页面打开。</small></span>
            </div>
            <div v-else v-html="message.rendered"></div>
          </article>
          <section v-if="message.role === 'assistant' && message.plan" class="workspace-ai-plan">
            <strong>{{ message.plan.title }}</strong>
            <ol>
              <li v-for="step in message.plan.steps" :key="step.key" :class="`is-${step.status}`"><span></span>{{ step.title }}</li>
            </ol>
          </section>
          <section v-if="message.role === 'assistant' && message.toolCalls?.length" class="workspace-ai-tools">
            <strong>工具调用记录</strong>
            <span v-for="tool in message.toolCalls" :key="tool.name" :class="`is-${tool.status}`">
              {{ tool.status === 'completed' ? '✓' : tool.status === 'failed' ? '!' : '·' }} {{ tool.title }}
            </span>
          </section>
          <section v-if="message.role === 'assistant' && message.execution" class="workspace-ai-execution-status">
            <span>任务 #{{ message.execution.id }}</span>
            <strong>{{ executionStatusLabel(message.execution.status) }}</strong>
            <small v-if="message.execution.result?.verified === false">存在可重试工具，已保留其余可用结果</small>
            <small v-else-if="message.execution.status === 'waiting_confirmation'">Agent 已暂停，等待你确认后才会继续生成</small>
          </section>
          <section v-if="message.role === 'assistant' && message.execution?.result?.verification?.checks?.length" class="workspace-ai-verification">
            <strong>执行校验</strong>
            <span v-for="check in message.execution.result.verification.checks" :key="check.key" :class="{ failed: !check.passed }">{{ check.passed ? '✓' : '!' }} {{ check.label }}<small v-if="check.detail">{{ check.detail }}</small></span>
          </section>
          <section v-if="message.role === 'assistant' && message.execution?.result?.warnings?.length" class="workspace-ai-warning-list">
            <strong>需要留意</strong><span v-for="warning in message.execution.result.warnings" :key="warning">{{ warning }}</span>
          </section>
          <section v-if="message.role === 'assistant' && message.progress?.length" class="workspace-ai-progress">
            <span v-for="progress in message.progress.slice(-2)" :key="`${progress.title}-${progress.status}`">{{ progress.status === 'completed' ? '✓' : '·' }} {{ progress.title }}</span>
          </section>
          <div v-if="message.role === 'assistant' && message.actions?.length" class="workspace-ai-actions">
            <el-button v-for="action in message.actions" :key="`${action.kind}-${action.href || action.run_id || ''}`" size="small" type="primary" plain :loading="action.status === 'running'" :disabled="action.status === 'completed'" @click="executeAction(message.id, action)">{{ action.label }}</el-button>
          </div>
          <section v-if="message.role === 'assistant' && message.run" class="workspace-ai-run" :class="`is-${message.run.status}`">
            <header class="workspace-ai-run-header">
              <div><span>任务 #{{ message.run.id }}</span><strong>备课执行状态</strong></div>
              <el-tag size="small" :type="message.run.status === 'completed' ? 'success' : message.run.status === 'failed' ? 'danger' : 'warning'">{{ runStatusLabel(message.run.status) }}</el-tag>
            </header>
            <section v-if="message.run.evidence_snapshot.length" class="workspace-ai-evidence">
              <strong>本次证据快照 · {{ message.run.evidence_snapshot.length }} 条</strong>
              <span v-for="source in message.run.evidence_snapshot.slice(0, 3)" :key="`${source.source_title}-${source.position}`">{{ source.source_title }} · {{ source.position }}</span>
            </section>
            <p v-if="runFailure(message.run)" class="workspace-ai-run-error">{{ runFailure(message.run) }}</p>
            <section v-if="message.run.output_data.outline" class="workspace-ai-outline">
              <p class="workspace-ai-run-eyebrow">已生成课纲</p>
              <h4>{{ message.run.output_data.outline.title }}</h4>
              <p>{{ message.run.output_data.outline.positioning }}</p>
              <div class="workspace-ai-outline-grid">
                <div><strong>教学目标</strong><ul><li v-for="item in [...message.run.output_data.outline.objectives.knowledge, ...message.run.output_data.outline.objectives.ability, ...message.run.output_data.outline.objectives.values].slice(0, 4)" :key="item">{{ item }}</li></ul></div>
                <div><strong>重点与难点</strong><ul><li v-for="item in [...message.run.output_data.outline.key_points, ...message.run.output_data.outline.difficult_points].slice(0, 4)" :key="item">{{ item }}</li></ul></div>
              </div>
              <div class="workspace-ai-flow"><strong>课堂流程</strong><span v-for="item in message.run.output_data.outline.teaching_flow.slice(0, 3)" :key="item.stage">{{ item.stage }} · {{ item.duration_minutes }} 分钟</span></div>
            </section>
            <section v-if="message.run.status === 'completed' && message.run.output_data.outline" class="workspace-ai-artifact-actions">
              <p>课纲已就绪，继续生成所需教学成果：</p>
              <div>
                <el-button size="small" type="primary" @click="generateArtifacts(message.id, message.run!, ['ppt'])">{{ message.run.output_data.artifacts?.ppt ? '重新生成 PPT' : '生成 PPT' }}</el-button>
                <el-button size="small" @click="generateArtifacts(message.id, message.run!, ['lesson_plan'])">{{ message.run.output_data.artifacts?.lesson_plan ? '重新生成教案' : '生成教案' }}</el-button>
                <el-button size="small" @click="generateArtifacts(message.id, message.run!, ['classroom_activities'])">{{ message.run.output_data.artifacts?.classroom_activities ? '重新生成互动' : '生成课堂互动' }}</el-button>
                <el-button size="small" plain @click="generateArtifacts(message.id, message.run!, ['ppt', 'lesson_plan', 'classroom_activities'])">一键生成全部</el-button>
              </div>
            </section>
            <div v-if="message.run.status === 'failed'" class="workspace-ai-actions">
              <el-button size="small" type="primary" plain @click="retryRun(message.id, message.run)">重新生成课纲</el-button>
            </div>
            <section v-if="message.run.output_data.artifacts && Object.keys(message.run.output_data.artifacts).length" class="workspace-ai-artifacts">
              <div class="workspace-ai-artifacts-heading"><strong>已生成成果</strong><el-button size="small" type="primary" plain @click="openLessonPrep(message.run.id)">进入预览与发布</el-button></div>
              <article v-for="(artifact, key) in message.run.output_data.artifacts" :key="key"><span>{{ artifact.title }}</span><el-button text type="primary" size="small" @click="downloadArtifact(message.run!, key, artifact.file_name)">下载</el-button></article>
            </section>
          </section>
          <div v-if="message.role === 'assistant' && message.content" class="workspace-ai-meta"><el-tag size="small" :type="message.grounded ? 'success' : 'warning'">{{ message.grounded ? '教材依据' : '待绑定教材' }}</el-tag><span v-if="message.model">{{ message.model }}</span></div>
          <div v-if="message.role === 'assistant' && message.sources?.length" class="workspace-ai-sources"><span v-for="source in message.sources.slice(0, 3)" :key="`${source.source_title}-${source.position}`">{{ source.source_title }} · {{ source.position }}</span></div>
        </div>
      </div>
    </div>

    <div class="workspace-ai-composer">
      <el-input v-model="question" type="textarea" :rows="2" resize="none" maxlength="2000" placeholder="你可以这样问：本章的核心观点是什么？" @keydown.ctrl.enter.prevent="send()" @keydown.meta.enter.prevent="send()" />
      <div class="workspace-ai-composer-footer"><div class="workspace-ai-mode-switch" role="tablist" aria-label="AI 工作模式"><button type="button" :class="{ active: mode === 'agent' }" @click="mode = 'agent'"><el-icon><MagicStick /></el-icon>Agent</button><button type="button" :class="{ active: mode === 'chat' }" @click="mode = 'chat'"><el-icon><ChatDotRound /></el-icon>Chat</button></div><span class="workspace-ai-hint">{{ mode === 'agent' ? '任务规划 · 操作前确认' : '教材问答 · 只回答' }}</span><el-button type="primary" :loading="loading" :icon="Promotion" aria-label="发送" @click="send()">发送</el-button></div>
    </div>
    <p class="workspace-ai-disclaimer">内容依据当前教材资料生成，仅供教学参考；发布、删除、导入和通知等操作需人工确认。</p>
  </section>
</template>

<style scoped>
.workspace-ai-assistant {
  display: flex;
  min-height: 0;
  flex-direction: column;
  color: #1d2b46;
  background: linear-gradient(180deg, #fbfcff 0%, #f5f8ff 100%);
}

.workspace-ai-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 68px;
  padding: 12px 18px;
  background: rgba(255, 255, 255, .92);
  border-bottom: 1px solid #e5ebf5;
}
.workspace-ai-context { display: flex; align-items: center; min-width: 0; gap: 10px; }
.workspace-ai-context > div { display: grid; min-width: 0; gap: 2px; }
.workspace-ai-context strong { overflow: hidden; color: #223454; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.workspace-ai-context small { overflow: hidden; color: #8291a9; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.workspace-ai-context-dot { width: 10px; height: 10px; flex: 0 0 auto; background: #4f68e8; border-radius: 50%; box-shadow: 0 0 0 5px rgba(79, 104, 232, .12); }
.workspace-ai-toolbar-actions { display: flex; align-items: center; gap: 2px; }
.workspace-ai-toolbar-actions :deep(.el-button) { color: #71809a; }
.workspace-ai-toolbar-actions :deep(.el-button:hover) { color: #315ed5; background: #eef3ff; }

.workspace-ai-scroll { min-height: 230px; max-height: min(540px, 52vh); overflow-y: auto; padding: 20px 18px 12px; scrollbar-color: #b7c6e2 transparent; }
.workspace-ai-welcome { display: flex; align-items: center; gap: 15px; margin: 2px 0 18px; }
.workspace-ai-welcome-icon { position: relative; display: grid; width: 58px; height: 58px; flex: 0 0 auto; place-items: center; color: #fff; background: linear-gradient(145deg, #4b58db, #8449c3); border-radius: 17px; box-shadow: 0 10px 23px rgba(75, 88, 219, .25); }
.workspace-ai-welcome-icon .el-icon { font-size: 28px; }
.workspace-ai-welcome-icon span { position: absolute; right: -6px; bottom: -5px; padding: 2px 5px; color: #fff; background: #a82e4c; border: 2px solid #fff; border-radius: 7px; font-size: 8px; font-weight: 800; }
.workspace-ai-welcome h2 { margin: 3px 0 6px; color: #1f2f4b; font-size: 22px; line-height: 1.25; }
.workspace-ai-welcome p:not(.workspace-ai-eyebrow) { margin: 0; color: #75839a; font-size: 12px; line-height: 1.6; }
.workspace-ai-eyebrow { margin: 0; color: #5370d9; font-size: 9px; font-weight: 800; letter-spacing: 1.6px; }
.workspace-ai-capabilities > p { margin: 0 0 9px; color: #6d7a90; font-size: 12px; }
.workspace-ai-capabilities { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.workspace-ai-capabilities button { display: flex; min-height: 72px; align-items: flex-start; gap: 9px; padding: 12px; color: #34435d; text-align: left; background: #fff; border: 1px solid #e4eaf5; border-radius: 12px; cursor: pointer; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.workspace-ai-capabilities button:hover { border-color: #90a8ee; box-shadow: 0 8px 18px rgba(59, 91, 172, .1); transform: translateY(-1px); }
.workspace-ai-capabilities .el-icon { margin-top: 1px; color: #4d68df; font-size: 19px; }
.workspace-ai-capabilities button span { display: grid; gap: 4px; }
.workspace-ai-capabilities strong { font-size: 12px; }
.workspace-ai-capabilities small { color: #8b98ad; font-size: 10px; line-height: 1.35; }
.workspace-ai-capabilities em { color: #a46b14; font-size: 9px; font-style: normal; }

.workspace-ai-message { display: flex; align-items: flex-start; gap: 9px; margin-top: 16px; }
.workspace-ai-message.is-user { justify-content: flex-end; }
.workspace-ai-avatar { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; color: #fff; background: #6675db; border-radius: 10px; font-size: 14px; }
.workspace-ai-avatar span { position: absolute; margin-top: 24px; padding: 1px 3px; color: #fff; background: #a82e4c; border: 1px solid #fff; border-radius: 4px; font-size: 6px; }
.workspace-ai-bubble { max-width: 89%; padding: 12px 14px; background: #fff; border: 1px solid #e0e8f5; border-radius: 15px; box-shadow: 0 4px 12px rgba(40, 63, 105, .05); }
.is-user .workspace-ai-bubble { color: #fff; background: linear-gradient(135deg, #3164d8, #4a55d5); border-color: transparent; border-bottom-right-radius: 5px; }
.is-assistant .workspace-ai-bubble { border-bottom-left-radius: 5px; }
.workspace-ai-bubble > p { margin: 0; font-size: 13px; line-height: 1.75; white-space: pre-wrap; }
.workspace-ai-bubble :deep(.teaching-document) { color: #33415b; font-size: 13px; line-height: 1.75; }
.workspace-ai-bubble :deep(.teaching-document h3), .workspace-ai-bubble :deep(.teaching-document h4) { margin: 0 0 8px; color: #213b69; font-size: 15px; }
.workspace-ai-bubble :deep(.teaching-document p) { margin: 0 0 8px; }
.workspace-ai-bubble :deep(.teaching-document strong) { color: #2e54c4; font-weight: 750; }
.workspace-ai-meta, .workspace-ai-sources { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; color: #8693a9; font-size: 10px; }
.workspace-ai-sources span { padding: 3px 6px; color: #5572a7; background: #f1f5fc; border-radius: 5px; }
.workspace-ai-plan { margin-top: 10px; padding: 10px; background: #f6f8ff; border: 1px solid #dde5fb; border-radius: 10px; }
.workspace-ai-plan > strong { display: block; color: #3853b4; font-size: 12px; }
.workspace-ai-plan ol { display: grid; gap: 6px; margin: 8px 0 0; padding: 0; list-style: none; }
.workspace-ai-plan li { display: flex; align-items: center; gap: 6px; color: #6b7890; font-size: 11px; }
.workspace-ai-plan li span { width: 7px; height: 7px; background: #b6c0d2; border-radius: 50%; }
.workspace-ai-plan li.is-completed { color: #276949; }.workspace-ai-plan li.is-completed span { background: #40a777; }.workspace-ai-plan li.is-needs_input, .workspace-ai-plan li.is-blocked { color: #a46b14; }.workspace-ai-plan li.is-needs_input span, .workspace-ai-plan li.is-blocked span { background: #e8ad45; }
.workspace-ai-plan li.is-running { color: #2859ce; }.workspace-ai-plan li.is-running span { background: #3d7cff; box-shadow: 0 0 0 4px rgba(61, 124, 255, .14); animation: workspace-ai-pulse 1s ease-in-out infinite; }
.workspace-ai-generating { display: flex; align-items: center; gap: 12px; min-height: 72px; padding: 14px 16px; color: #31518a; background: linear-gradient(120deg, #f3f7ff, #ffffff); border: 1px solid #d8e4fb; border-radius: 12px; }
.workspace-ai-generating-spinner { display: inline-grid; flex: 0 0 auto; width: 32px; height: 32px; place-items: center; color: #3d70e8; background: #e8f0ff; border-radius: 50%; font-size: 18px; }
.workspace-ai-generating strong, .workspace-ai-generating small { display: block; }.workspace-ai-generating strong { font-size: 13px; }.workspace-ai-generating small { margin-top: 3px; color: #8290a9; font-size: 11px; }
.workspace-ai-progress { display: grid; gap: 3px; margin-top: 9px; color: #75839a; font-size: 10px; }.workspace-ai-progress span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@keyframes workspace-ai-pulse { 50% { opacity: .55; transform: scale(.82); } }
.workspace-ai-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.workspace-ai-run { display: grid; gap: 10px; margin-top: 12px; padding: 12px; background: linear-gradient(145deg, #f5f8ff, #fff); border: 1px solid #dce6fa; border-radius: 12px; }.workspace-ai-run.is-running, .workspace-ai-run.is-queued { border-color: #aebffc; }.workspace-ai-run.is-completed { border-color: #b8e6ce; }.workspace-ai-run.is-failed { border-color: #f2c3c7; }.workspace-ai-run-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.workspace-ai-run-header div { display: grid; gap: 2px; }.workspace-ai-run-header span, .workspace-ai-run-eyebrow { color: #8191aa; font-size: 10px; }.workspace-ai-run-header strong { color: #29466e; font-size: 12px; }.workspace-ai-evidence { display: flex; flex-wrap: wrap; gap: 5px; padding: 8px; background: #fbfcff; border: 1px dashed #d7e2f5; border-radius: 8px; }.workspace-ai-evidence strong { width: 100%; color: #52709e; font-size: 10px; }.workspace-ai-evidence span { max-width: 100%; overflow: hidden; padding: 3px 5px; color: #687995; text-overflow: ellipsis; white-space: nowrap; background: #eef4ff; border-radius: 5px; font-size: 10px; }.workspace-ai-run-error { margin: 0; color: #b33c49; font-size: 11px; line-height: 1.55; }.workspace-ai-outline { padding: 11px; background: #fff; border: 1px solid #e5ebf4; border-radius: 10px; }.workspace-ai-outline h4 { margin: 3px 0 5px; color: #263f67; font-size: 14px; }.workspace-ai-outline > p:not(.workspace-ai-run-eyebrow) { margin: 0; color: #65748b; font-size: 11px; line-height: 1.55; }.workspace-ai-outline-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 9px; }.workspace-ai-outline-grid > div, .workspace-ai-flow { padding: 8px; background: #f8faff; border-radius: 8px; }.workspace-ai-outline-grid strong, .workspace-ai-flow strong, .workspace-ai-artifacts > strong { display: block; color: #4564a4; font-size: 11px; }.workspace-ai-outline-grid ul { display: grid; gap: 3px; margin: 5px 0 0; padding-left: 16px; color: #66758d; font-size: 10px; line-height: 1.45; }.workspace-ai-flow { display: flex; flex-wrap: wrap; gap: 5px 7px; margin-top: 8px; }.workspace-ai-flow strong { width: 100%; }.workspace-ai-flow span { padding: 3px 5px; color: #677790; background: #fff; border: 1px solid #e4eaf4; border-radius: 5px; font-size: 10px; }.workspace-ai-artifact-actions { display: grid; gap: 7px; }.workspace-ai-artifact-actions p { margin: 0; color: #55677f; font-size: 11px; }.workspace-ai-artifact-actions > div { display: flex; flex-wrap: wrap; gap: 6px; }.workspace-ai-artifacts { display: grid; gap: 6px; padding-top: 2px; }.workspace-ai-artifacts article { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 9px; color: #50627b; background: #fff; border: 1px solid #e3eaf5; border-radius: 8px; font-size: 11px; }
.workspace-ai-artifacts-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.workspace-ai-tools { display: grid; gap: 4px; margin-top: 8px; padding: 8px 10px; background: #f8faff; border: 1px solid #e5ebf7; border-radius: 8px; }.workspace-ai-tools strong { color: #4564a4; font-size: 11px; }.workspace-ai-tools span { color: #75839a; font-size: 10px; }.workspace-ai-tools span.is-completed { color: #2e8b62; }.workspace-ai-tools span.is-failed { color: #b33c49; }

.workspace-ai-history { min-height: 230px; max-height: min(540px, 52vh); overflow-y: auto; padding: 16px 18px; }
.workspace-ai-history-heading { display: flex; justify-content: space-between; margin-bottom: 10px; color: #425573; font-size: 12px; }
.workspace-ai-history-heading span { color: #9aa6b9; }
.workspace-ai-history-item { display: flex; width: 100%; align-items: center; gap: 8px; padding: 10px 0; color: #52627c; text-align: left; background: transparent; border: 0; border-bottom: 1px solid #eef2f8; cursor: pointer; }
.workspace-ai-history-item:hover p { color: #315ed5; }
.workspace-ai-history-item span { display: grid; width: 23px; height: 23px; flex: 0 0 auto; place-items: center; color: #fff; background: #7a88a4; border-radius: 7px; font-size: 10px; }
.workspace-ai-history-item .history-role-user { background: #3e6bd8; }
.workspace-ai-history-item p { overflow: hidden; margin: 0; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.workspace-ai-task-center { display: grid; align-content: start; gap: 9px; }
.workspace-ai-task-item { display: grid; gap: 6px; padding: 11px; background: #fff; border: 1px solid #e2e9f5; border-radius: 10px; }
.workspace-ai-task-item > div:first-child { display: flex; align-items: center; gap: 6px; color: #8090a9; font-size: 10px; }.workspace-ai-task-item strong { overflow: hidden; color: #30425f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.workspace-ai-task-item small { display: -webkit-box; overflow: hidden; color: #78879c; font-size: 10px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.workspace-ai-task-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.workspace-ai-execution-status { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 9px; padding: 7px 9px; color: #6e7d95; background: #f4f7ff; border: 1px solid #dce6fb; border-radius: 8px; font-size: 10px; }.workspace-ai-execution-status strong { color: #3860c2; }.workspace-ai-execution-status small { width: 100%; color: #a06d21; }
.workspace-ai-verification, .workspace-ai-warning-list { display: grid; gap: 4px; margin-top: 8px; padding: 8px 10px; border-radius: 8px; font-size: 10px; }.workspace-ai-verification { color: #397758; background: #f2fbf6; border: 1px solid #d6efdf; }.workspace-ai-verification > strong, .workspace-ai-warning-list > strong { font-size: 11px; }.workspace-ai-verification span { display: flex; flex-wrap: wrap; gap: 4px; }.workspace-ai-verification span.failed { color: #a46b14; }.workspace-ai-verification small { color: #7e8ca2; }.workspace-ai-warning-list { color: #94631d; background: #fff9ed; border: 1px solid #f2dfb9; }

.workspace-ai-composer { padding: 12px 18px 9px; background: rgba(255,255,255,.95); border-top: 1px solid #e5ebf5; }
.workspace-ai-composer :deep(.el-textarea__inner) { padding: 10px 12px; color: #2b3a56; background: #fbfcff; border-color: #dfe7f4; border-radius: 11px; box-shadow: none; }
.workspace-ai-composer :deep(.el-textarea__inner:focus) { border-color: #637ce5; box-shadow: 0 0 0 2px rgba(99,124,229,.12); }
.workspace-ai-composer-footer { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.workspace-ai-mode-switch { display: inline-flex; overflow: hidden; border: 1px solid #d8e1ef; border-radius: 8px; }
.workspace-ai-mode-switch button { display: inline-flex; align-items: center; gap: 4px; padding: 5px 9px; color: #687890; background: #fff; border: 0; cursor: pointer; font-size: 11px; }
.workspace-ai-mode-switch button + button { border-left: 1px solid #d8e1ef; }
.workspace-ai-mode-switch button.active { color: #2e5dce; background: #edf2ff; font-weight: 700; }
.workspace-ai-hint { flex: 1; color: #8a98ad; font-size: 10px; }
.workspace-ai-composer-footer :deep(.el-button) { min-width: 64px; border-radius: 8px; }
.workspace-ai-disclaimer { margin: 0; padding: 0 18px 10px; color: #a3acbb; font-size: 10px; line-height: 1.5; text-align: center; }

@media (max-width: 680px) {
  .workspace-ai-toolbar { padding: 10px 12px; }
  .workspace-ai-scroll, .workspace-ai-history { padding-right: 12px; padding-left: 12px; }
  .workspace-ai-capabilities, .workspace-ai-outline-grid { grid-template-columns: 1fr; }
  .workspace-ai-welcome h2 { font-size: 19px; }
  .workspace-ai-composer { padding-right: 12px; padding-left: 12px; }
  .workspace-ai-composer-footer { flex-wrap: wrap; }
  .workspace-ai-hint { order: 3; width: 100%; flex-basis: 100%; }
}
</style>

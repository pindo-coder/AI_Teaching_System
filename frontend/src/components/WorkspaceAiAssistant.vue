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
  type AiTaskType,
  type AiWorkspaceContext,
  type AiWorkspaceMode,
  type AiWorkspaceRole,
} from '@/api/ai'
import { agentApi, type AgentRun } from '@/api/agents'
import { aiMediaApi, type AiMediaAsset } from '@/api/aiMedia'
import { learningApi } from '@/api/learning'
import AiMediaComposer from '@/components/AiMediaComposer.vue'
import { useAuthStore } from '@/stores/auth'
import type { LearningStage } from '@/types'
import { renderTeachingDocument } from '@/utils/richText'

interface AssistantMessage {
  id: number
  mode: AiWorkspaceMode
  role: 'user' | 'assistant'
  content: string
  failed?: boolean
  grounded?: boolean
  model?: string
  sources?: AiSource[]
  plan?: AiAgentPlan
  progress?: Array<{ title: string; status: string; iteration?: number }>
  actions?: AiAgentAction[]
  toolCalls?: Array<{ name: string; title: string; status: string; error?: string; requires_confirmation?: boolean }>
  execution?: AiAgentExecution
  run?: AgentRun
  attachments?: Array<{ id: number; name: string }>
  createdAt: string
}

interface QuickAction {
  title: string
  description: string
  prompt: string
  icon: typeof Setting
  requiresContext?: boolean
  taskType?: AiTaskType
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
const chatMessages = ref<AssistantMessage[]>([])
const agentMessages = ref<AssistantMessage[]>([])
const chatQuestion = ref('')
const agentQuestion = ref('')
const chatTaskType = ref<AiTaskType>('question_answer')
const chatQuestionIsUserAuthored = ref(false)
const loadingByMode = ref<Record<AiWorkspaceMode, boolean>>({ chat: false, agent: false })
const messages = computed<AssistantMessage[]>({
  get: () => mode.value === 'chat' ? chatMessages.value : agentMessages.value,
  set: (value) => { if (mode.value === 'chat') chatMessages.value = value; else agentMessages.value = value },
})
const question = computed<string>({
  get: () => mode.value === 'chat' ? chatQuestion.value : agentQuestion.value,
  set: (value) => { if (mode.value === 'chat') chatQuestion.value = value; else agentQuestion.value = value },
})
const loading = computed(() => loadingByMode.value[mode.value])
const historyVisible = ref(false)
const taskCenterVisible = ref(false)
const executions = ref<AiAgentExecution[]>([])
const serverTemplates = ref<AiAgentTemplate[]>([])
const executionLoading = ref(false)
const deletingExecutionId = ref<number | null>(null)
const expandedActivityIds = ref<Set<number>>(new Set())
const mediaAssets = ref<AiMediaAsset[]>([])
const mediaBusy = ref(false)
const messageList = ref<HTMLElement | null>(null)
const role = computed<AiWorkspaceRole>(() => auth.user?.role || 'student')
const roleLabel = computed(() => ({ student: '学生学习助手', teacher: '教师备课助手', admin: '平台治理助手' }[role.value]))
const contextLabel = computed(() => {
  if (props.context?.course_name && props.context.chapter_ids.length > 1) return `${props.context.course_name} · 已选 ${props.context.chapter_ids.length} 个专题`
  if (props.context?.course_name && props.context.chapter_title) return `${props.context.course_name} · ${props.context.chapter_title}`
  if (props.context?.course_name) return `${props.context.course_name} · 待选专题`
  if (props.courseId && props.chapterId) return props.learningStage === 'review' ? '当前专题 · 课后巩固' : props.learningStage === 'exam' ? '当前专题 · 考前冲刺' : '当前专题 · 课前预习'
  return role.value === 'admin' ? '正在读取平台运行状态' : '正在自动识别教学范围'
})
const agentWelcome = computed(() => role.value === 'admin'
  ? '检查资料、知识库、AI 服务和教学组织状态，只提供治理建议与管理入口。'
  : '把教学目标拆成可追踪步骤，涉及写入和发布时由你确认。')
const composerPlaceholder = computed(() => mode.value === 'chat'
  ? '向 Chat 提问：本章的核心观点是什么？'
  : role.value === 'admin'
    ? '交给 Admin Agent：检查平台当前运行风险'
    : '交给 Agent：为当前专题制定一份学习计划')
const modeHint = computed(() => mode.value === 'chat'
  ? '教材问答 · 只回答'
  : role.value === 'admin'
    ? '治理检查 · 只读建议'
    : '任务规划 · 操作前确认')
const disclaimer = computed(() => role.value === 'admin'
  ? 'AI 生成内容仅汇总平台状态并提供管理入口，不会自动审核、发布、删除或修改服务配置。'
  : 'AI 生成内容依据当前教材资料，仅供教学参考；发布、删除、导入和通知等操作需人工确认。')
const storageScopeKey = computed(() => `workspace-ai-history:${auth.user?.id || 'guest'}:${props.context?.course_id || props.courseId || 0}:${props.context?.chapter_ids.join('-') || props.context?.chapter_id || props.chapterId || 0}`)
function storageKey(targetMode: AiWorkspaceMode) {
  return `${storageScopeKey.value}:${targetMode}`
}
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
    { title: '梳理资料审核队列', description: '汇总待审核、高优先级与来源异常', prompt: '请检查资料发现和候选审核队列，告诉我最需要先处理的事项。', icon: RefreshRight },
    { title: '检查知识库健康', description: '检查发布、索引、校准与失败资料', prompt: '请检查知识库、教材版本和索引状态，列出需要管理员处理的异常。', icon: CircleCheck },
    { title: '诊断 AI 运行状态', description: '汇总模型调用、失败率与当前配置', prompt: '请检查近 24 小时 AI 调用和服务配置状态，指出运行风险。', icon: RefreshRight },
    { title: '监督教学组织运行', description: '检查教师、教学班与任务发布状态', prompt: '请汇总教师审核、教学班和已发布教学任务的运行状态。', icon: Setting },
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
const chatQuickActions = computed<QuickAction[]>(() => {
  const learningStage = props.context?.learning_stage || props.learningStage || 'preview'
  if (learningStage === 'review') return [
    { title: '生成复习提纲', description: '梳理观点、概念和逻辑关系', prompt: '请依据当前专题教材生成一份结构清晰的复习提纲。', icon: CircleCheck, taskType: 'review_outline' },
    { title: '梳理本章重点', description: '提炼教材核心观点', prompt: '请用简洁的层级结构梳理当前专题的核心观点。', icon: ChatDotRound, taskType: 'chapter_summary' },
    { title: '辨析易混观点', description: '比较概念并给出教材依据', prompt: '请列出当前专题中容易混淆的概念并逐一辨析。', icon: RefreshRight, taskType: 'question_answer' },
  ]
  if (learningStage === 'exam') return [
    { title: '生成模拟练习', description: '依据教材生成考前自测题', prompt: '请依据当前专题教材生成一组模拟练习题，并在题目后给出参考要点。', icon: CircleCheck, taskType: 'mock_questions' },
    { title: '梳理重点考点', description: '形成考前冲刺提纲', prompt: '请依据当前专题教材梳理重点考点和答题线索。', icon: ChatDotRound, taskType: 'review_outline' },
    { title: '检查知识盲点', description: '定位易错概念和薄弱点', prompt: '请列出当前专题容易遗漏或混淆的知识点，并说明检查方法。', icon: RefreshRight, taskType: 'question_answer' },
  ]
  return [
    { title: '生成预习问题', description: '带着问题进入课堂', prompt: '请严格依据当前专题教材生成 5 个预习问题。', icon: CircleCheck, taskType: 'preview_questions' },
    { title: '梳理本章重点', description: '提炼教材核心观点', prompt: '请用简洁的层级结构梳理当前专题的核心观点。', icon: ChatDotRound, taskType: 'chapter_summary' },
    { title: '解释核心概念', description: '依据当前教材直接回答', prompt: '请依据当前专题教材解释最重要的核心概念。', icon: RefreshRight, taskType: 'question_answer' },
  ]
})

const renderedMessages = computed(() => messages.value.map((message) => ({
  ...message,
  rendered: message.role === 'assistant' ? renderTeachingDocument(localizeAgentTerms(message.content)) : '',
})))

function localizeAgentTerms(content: string) {
  return content
    .replace(/invalid arguments for [\w-]+:[^\n]*/g, '工具参数校验未通过，请重试。')
    .replace(/extra_forbidden/g, '字段不支持')
    .replace(/classroom_activities/g, '课堂活动')
    .replace(/lesson_plan/g, '完整教案')
    .replace(/generate_classroom_activity/g, '生成课堂活动')
    .replace(/generate_lesson_plan/g, '生成教案')
    .replace(/generate_ppt/g, '生成教学 PPT')
}

function loadHistory() {
  try {
    const chatRaw = localStorage.getItem(storageKey('chat'))
    const agentRaw = localStorage.getItem(storageKey('agent'))
    if (chatRaw !== null || agentRaw !== null) {
      chatMessages.value = chatRaw ? (JSON.parse(chatRaw) as AssistantMessage[]).map((item) => ({ ...item, mode: 'chat' })) : []
      agentMessages.value = agentRaw ? (JSON.parse(agentRaw) as AssistantMessage[]).map((item) => ({ ...item, mode: 'agent' })) : []
      return
    }
    // 兼容旧版共用历史：依据助手结果识别频道，并让用户提问跟随其后的回答迁移。
    const legacyRaw = localStorage.getItem(storageScopeKey.value)
    const legacy = legacyRaw ? JSON.parse(legacyRaw) as Array<Omit<AssistantMessage, 'mode'> & { mode?: AiWorkspaceMode }> : []
    const migrated: Record<AiWorkspaceMode, AssistantMessage[]> = { chat: [], agent: [] }
    for (let index = 0; index < legacy.length; index += 1) {
      const item = legacy[index]
      const pairedAssistant = item.role === 'user' ? legacy[index + 1] : item
      const inferredMode: AiWorkspaceMode = item.mode || (pairedAssistant?.plan || pairedAssistant?.execution || pairedAssistant?.run || pairedAssistant?.toolCalls?.length || pairedAssistant?.actions?.length ? 'agent' : 'chat')
      migrated[inferredMode].push({ ...item, mode: inferredMode } as AssistantMessage)
    }
    chatMessages.value = migrated.chat
    agentMessages.value = migrated.agent
    if (legacy.length) persistHistory()
  } catch {
    chatMessages.value = []
    agentMessages.value = []
  }
}
function persistHistory() {
  localStorage.setItem(storageKey('chat'), JSON.stringify(chatMessages.value.slice(-40)))
  localStorage.setItem(storageKey('agent'), JSON.stringify(agentMessages.value.slice(-40)))
}
function scrollToBottom(targetMode: AiWorkspaceMode = mode.value) {
  if (targetMode !== mode.value) return
  void nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}
function selectQuickAction(prompt: string, selectedMode: AiWorkspaceMode = mode.value, taskType?: AiTaskType) {
  switchMode(selectedMode)
  if (selectedMode === 'chat') {
    chatQuestion.value = prompt
    chatTaskType.value = taskType || 'question_answer'
    chatQuestionIsUserAuthored.value = false
  }
  else agentQuestion.value = prompt
}
function resetChatTaskType() {
  if (mode.value === 'chat') {
    chatTaskType.value = 'question_answer'
    chatQuestionIsUserAuthored.value = true
  }
}
function completedChatHistory() {
  const history: Array<{ role: 'user' | 'assistant'; content: string }> = []
  for (let index = 0; index < chatMessages.value.length - 1; index += 1) {
    const userMessage = chatMessages.value[index]
    const assistantMessage = chatMessages.value[index + 1]
    if (userMessage.role !== 'user' || assistantMessage.role !== 'assistant' || assistantMessage.failed || !assistantMessage.content.trim()) continue
    history.push(
      { role: 'user', content: userMessage.content.trim().slice(0, 600) },
      { role: 'assistant', content: assistantMessage.content.trim().slice(0, 600) },
    )
    index += 1
  }
  return history.slice(-6)
}
function discardComposerMedia() {
  const discarded = [...mediaAssets.value]
  mediaAssets.value = []
  void Promise.allSettled(discarded.map((asset) => aiMediaApi.deleteAsset(asset.id)))
}
function switchMode(nextMode: AiWorkspaceMode) {
  if (nextMode === 'agent' && mediaBusy.value) {
    ElMessage.warning('请先等待图片上传或语音转写完成')
    return
  }
  if (nextMode === 'agent' && mediaAssets.value.length && !loadingByMode.value.chat) {
    discardComposerMedia()
    ElMessage.info('Agent 暂不接收图片或语音，已清理本轮临时附件')
  }
  mode.value = nextMode
  historyVisible.value = false
  taskCenterVisible.value = false
  scrollToBottom(nextMode)
}
function appendTranscription(text: string) {
  const normalized = text.trim()
  if (!normalized) return
  chatTaskType.value = 'question_answer'
  chatQuestionIsUserAuthored.value = true
  chatQuestion.value = chatQuestion.value.trim()
    ? `${chatQuestion.value.trim()}\n${normalized}`
    : normalized
}
function newConversation() {
  if (mediaAssets.value.length && loadingByMode.value.chat) {
    ElMessage.warning('请等待当前图片回答完成后再新建会话')
    return false
  }
  if (mediaBusy.value) {
    ElMessage.warning('请先等待图片上传或语音转写完成')
    return false
  }
  if (mediaAssets.value.length) discardComposerMedia()
  messages.value = []
  if (mode.value === 'chat') {
    chatTaskType.value = 'question_answer'
    chatQuestionIsUserAuthored.value = false
  }
  historyVisible.value = false
  localStorage.removeItem(storageKey(mode.value))
  return true
}
async function clearHistory() {
  if (!newConversation()) return
  try {
    const response = await aiApi.clearWorkspaceAgentExecutions()
    executions.value = []
    const deletedCount = response.data.data.deleted_count
    ElMessage.success(deletedCount ? `本次 AI 会话已清空，已删除 ${deletedCount} 条 Agent 记录` : '本次 AI 会话已清空')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'Agent 会话清空失败，请稍后重试')
  }
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
  switchMode('agent')
  if (mode.value !== 'agent') return
  taskCenterVisible.value = !taskCenterVisible.value
  historyVisible.value = false
  if (taskCenterVisible.value) void loadExecutions()
}
function executionStatusLabel(status: AiAgentExecution['status']) {
  return ({ planning: '正在规划', running: '正在执行', waiting_input: '等待补充信息', waiting_confirmation: '等待确认', waiting_user_action: '等待你处理', advice_ready: '建议已生成', completed: '已完成', failed: '执行异常', cancelled: '已取消' } as Record<AiAgentExecution['status'], string>)[status]
}
async function retryExecution(execution: AiAgentExecution) {
  if (loadingByMode.value.agent) return
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
async function cancelRunningExecution(execution: AiAgentExecution) {
  try {
    await aiApi.cancelWorkspaceAgentExecution(execution.id)
    ElMessage.success('已请求停止本次 Agent 任务')
    await loadExecutions()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '停止失败，请稍后重试')
  }
}
async function deleteExecution(execution: AiAgentExecution) {
  if (deletingExecutionId.value !== null) return
  try {
    deletingExecutionId.value = execution.id
    await aiApi.deleteWorkspaceAgentExecution(execution.id)
    executions.value = executions.value.filter((item) => item.id !== execution.id)
    ElMessage.success('Agent 任务已删除')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'Agent 任务删除失败，请稍后重试')
  } finally {
    deletingExecutionId.value = null
  }
}
function updateAssistantMessage(id: number, updater: (message: AssistantMessage) => void) {
  const message = [...chatMessages.value, ...agentMessages.value].find((item) => item.id === id)
  if (message) updater(message)
}
async function submitStudentLearningQuestion(
  scope: { course_id: number | null; chapter_id: number | null; learning_stage: LearningStage },
  content: string,
) {
  if (role.value !== 'student' || !scope.course_id || !scope.chapter_id) return
  try {
    await learningApi.submitQuestion({
      course_id: scope.course_id,
      chapter_id: scope.chapter_id,
      learning_stage: scope.learning_stage,
      content,
    })
  } catch {
    // 问题留痕失败不应把已经成功生成的 Chat 回答改成错误消息。
  }
}
function generationLabel(message: AssistantMessage) {
  return message.mode === 'agent'
    ? message.progress?.at(-1)?.title || '正在连接 Agent 并准备执行任务'
    : '正在检索教材并生成回答'
}
function progressMarker(status: string) {
  return status === 'completed' ? '✓' : status === 'replanning' ? '↻' : status === 'failed' || status === 'needs_input' ? '!' : '·'
}
function progressLabel(progress: { title: string; status: string; iteration?: number }) {
  return progress.status === 'replanning' && progress.iteration
    ? `${progress.title}（第 ${progress.iteration} 轮）`
    : progress.title
}
function completedPlanStepCount(plan: AiAgentPlan) {
  return plan.steps.filter((step) => step.status === 'completed').length
}
function toggleActivitySteps(messageId: number) {
  const next = new Set(expandedActivityIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  expandedActivityIds.value = next
}
function activityExpanded(messageId: number) {
  return expandedActivityIds.value.has(messageId)
}
function stepStatusLabel(status: AiAgentPlan['steps'][number]['status']) {
  return ({ completed: '已完成', pending: '待执行', running: '执行中', ready: '待开始', needs_input: '待补充', blocked: '已阻塞', advice_ready: '建议已生成', waiting_user_action: '等待你处理' } as Record<AiAgentPlan['steps'][number]['status'], string>)[status]
}
function hasFailedVerification(message: AssistantMessage) {
  return Boolean(message.execution?.result?.verification?.checks?.some((check) => !check.passed))
}
function verificationChecks(message: AssistantMessage) {
  return message.execution?.result?.verification?.checks || []
}
function activityCount(message: AssistantMessage) {
  if (message.plan?.steps?.length) return completedPlanStepCount(message.plan)
  if (message.execution?.tool_results?.length) return message.execution.tool_results.length
  if (message.run?.steps?.length) return message.run.steps.filter((step) => step.status === 'completed').length
  return message.toolCalls?.filter((tool) => tool.status === 'completed').length || 0
}
function agentActivityStatus(message: AssistantMessage) {
  if (message.execution?.status === 'waiting_user_action' || message.execution?.status === 'advice_ready') return 'needs_input'
  if (message.execution?.status === 'failed' || message.run?.status === 'failed' || message.failed) return 'failed'
  if (message.execution?.status === 'waiting_input' || message.execution?.status === 'waiting_confirmation' || message.run?.status === 'waiting_confirmation') return 'needs_input'
  if (message.execution?.status === 'completed' || message.run?.status === 'completed') return 'completed'
  if (message.progress?.at(-1)?.status) return message.progress.at(-1)!.status
  if (loading.value) return 'running'
  return message.plan ? (message.plan.steps.some((step) => step.status === 'pending' || step.status === 'running') ? 'running' : 'completed') : ''
}
function agentActivityLabel(message: AssistantMessage) {
  const status = agentActivityStatus(message)
  const count = activityCount(message)
  if (status === 'failed') return message.execution?.error_message || message.run?.error_message || '执行异常，请查看提示'
  if (status === 'needs_input') {
    if (message.execution?.status === 'waiting_user_action' || message.execution?.status === 'advice_ready') return '建议已生成 · 等待你编辑保存'
    return message.execution?.status === 'waiting_confirmation' || message.run?.status === 'waiting_confirmation' ? '等待确认后继续' : '等待补充信息'
  }
  if (status === 'completed') return `已完成 · 共执行 ${count} 步`
  const latest = message.progress?.at(-1)
  if (latest) return progressLabel(latest)
  const activeTool = message.toolCalls?.find((tool) => tool.status === 'running')
  return activeTool ? `正在${activeTool.title}` : generationLabel(message)
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
  scrollToBottom('agent')
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
    if (action.kind === 'open_assignments' && (action.draft || action.rubric)) {
      const payload = encodeURIComponent(JSON.stringify({ draft: action.draft || null, rubric: action.rubric || null }))
      void router.push({ path: '/assignments', query: { agent_draft: payload } })
      return
    }
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
  const requestMode: AiWorkspaceMode = safeExecutionId ? 'agent' : mode.value
  const requestTaskType: AiTaskType = requestMode === 'chat' ? chatTaskType.value : 'question_answer'
  const shouldSubmitLearningQuestion = requestMode === 'chat'
    && requestTaskType === 'question_answer'
    && chatQuestionIsUserAuthored.value
  const rawContent = (safeExecutionId
    ? executions.value.find((item) => item.id === safeExecutionId)?.question || question.value
    : requestMode === 'chat' ? chatQuestion.value : agentQuestion.value).trim()
  const selectedImages = requestMode === 'chat'
    ? mediaAssets.value.filter((asset) => asset.media_kind === 'image' && asset.status === 'ready')
    : []
  const content = rawContent || (selectedImages.length ? '请结合当前教材分析这些图片。' : '')
  if (!content || loadingByMode.value[requestMode]) return
  if (requestMode === 'chat' && mediaBusy.value) {
    ElMessage.warning('图片或语音仍在处理中，请稍候再发送')
    return
  }
  const conversationHistory = requestMode === 'chat' ? completedChatHistory() : []
  if (requestMode === 'chat') {
    chatQuestion.value = ''
    chatTaskType.value = 'question_answer'
    chatQuestionIsUserAuthored.value = false
  }
  else agentQuestion.value = ''
  const messageId = Date.now()
  const userMessage: AssistantMessage = {
    id: messageId,
    mode: requestMode,
    role: 'user',
    content,
    attachments: selectedImages.map((asset) => ({ id: asset.id, name: asset.original_filename })),
    createdAt: new Date().toISOString(),
  }
  const assistantMessage: AssistantMessage = { id: messageId + 1, mode: requestMode, role: 'assistant', content: '', grounded: false, sources: [], progress: [], actions: [], createdAt: new Date().toISOString() }
  const targetMessages = requestMode === 'chat' ? chatMessages.value : agentMessages.value
  targetMessages.push(userMessage, assistantMessage)
  historyVisible.value = false
  taskCenterVisible.value = false
  loadingByMode.value[requestMode] = true
  scrollToBottom(requestMode)
  try {
    const currentScope = {
      course_id: props.context?.course_id || props.courseId || null,
      chapter_id: props.context?.chapter_id || props.chapterId || null,
      chapter_ids: props.context?.chapter_ids || (props.chapterId ? [props.chapterId] : []),
      teaching_class_id: props.context?.teaching_class_id || props.teachingClassId || null,
      learning_stage: props.context?.learning_stage || props.learningStage || 'preview',
      page_name: props.pageName || null,
    }
    // 从任务中心重试时必须锁定原任务的上下文快照，不能被当前页面的课程覆盖。
    const scope = safeExecutionId
      ? { course_id: null, chapter_id: null, chapter_ids: [], teaching_class_id: null, learning_stage: 'preview' as LearningStage, page_name: null }
      : currentScope
    if (requestMode === 'agent') {
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
        onChunk: (text) => { updateAssistantMessage(assistantMessage.id, (message) => { message.content += text }); scrollToBottom(requestMode) },
        onSources: (sources) => updateAssistantMessage(assistantMessage.id, (message) => { message.sources = sources }),
      })
    } else {
      await aiApi.workspaceStream({
        mode: requestMode,
        role: role.value,
        question: content,
        task_type: requestTaskType,
        attachment_ids: selectedImages.map((asset) => asset.id),
        conversation_history: conversationHistory,
        ...scope,
      }, {
        onMeta: (meta) => updateAssistantMessage(assistantMessage.id, (message) => { message.grounded = meta.grounded; message.model = meta.model }),
        onChunk: (text) => { updateAssistantMessage(assistantMessage.id, (message) => { message.content += text }); scrollToBottom(requestMode) },
        onSources: (sources) => updateAssistantMessage(assistantMessage.id, (message) => { message.sources = sources }),
      })
      if (assistantMessage.content.trim() && shouldSubmitLearningQuestion) {
        await submitStudentLearningQuestion(scope, content)
      }
    }
    persistHistory()
    if (requestMode === 'agent') void loadExecutions()
  } catch (error: unknown) {
    updateAssistantMessage(assistantMessage.id, (message) => {
      message.content = error instanceof Error ? error.message : 'AI 暂时无法连接，请稍后重试。'
      message.failed = true
      message.grounded = false
    })
    persistHistory()
  } finally {
    if (selectedImages.length) {
      const sentIds = new Set(selectedImages.map((asset) => asset.id))
      await Promise.allSettled(selectedImages.map((asset) => aiMediaApi.deleteAsset(asset.id)))
      mediaAssets.value = mediaAssets.value.filter((asset) => !sentIds.has(asset.id))
    }
    loadingByMode.value[requestMode] = false
    scrollToBottom(requestMode)
  }
}

watch(storageScopeKey, loadHistory, { immediate: true })
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
          <template v-else-if="execution.status === 'planning' || execution.status === 'running'">
            <el-button size="small" type="danger" plain @click="cancelRunningExecution(execution)">停止</el-button>
          </template>
          <el-button v-else-if="execution.status === 'failed' || execution.status === 'completed' || execution.status === 'waiting_user_action' || execution.status === 'advice_ready'" size="small" type="primary" plain @click="retryExecution(execution)">基于此任务重试</el-button>
          <el-button
            size="small"
            text
            type="danger"
            :icon="Delete"
            :loading="deletingExecutionId === execution.id"
            aria-label="删除 Agent 任务"
            @click="deleteExecution(execution)"
          >删除</el-button>
        </div>
      </article>
      <el-empty v-if="!executions.length && !executionLoading" description="还没有可追踪的 Agent 任务" :image-size="68" />
    </div>
    <div v-else-if="historyVisible" class="workspace-ai-history">
      <div class="workspace-ai-history-heading"><strong>{{ mode === 'chat' ? 'Chat 问答记录' : 'Agent 执行记录' }}</strong><span>{{ messages.length }} 条消息</span></div>
      <button v-for="message in messages" :key="message.id" type="button" class="workspace-ai-history-item" @click="historyVisible = false; scrollToBottom()">
        <span :class="`history-role-${message.role}`">{{ message.role === 'user' ? '我' : 'AI' }}</span><p>{{ message.content || '正在生成……' }}</p>
      </button>
      <el-empty v-if="!messages.length" description="还没有历史会话" :image-size="68" />
    </div>

    <div v-else ref="messageList" class="workspace-ai-scroll">
      <section v-if="!messages.length" class="workspace-ai-welcome">
        <div class="workspace-ai-welcome-icon"><el-icon><MagicStick /></el-icon><span>AI</span></div>
        <div><p class="workspace-ai-eyebrow">{{ mode === 'chat' ? 'TEXTBOOK · CHAT' : role === 'admin' ? 'PLATFORM · GOVERNANCE' : 'TEACHING · AGENT' }}</p><h2>{{ mode === 'chat' ? 'Chat 教材问答' : role === 'admin' ? 'Admin 治理 Agent' : 'Agent 任务执行' }}</h2><p>{{ mode === 'chat' ? '围绕当前教材直接回答、解释和辨析，不触发任务操作。' : agentWelcome }}</p></div>
      </section>
      <section v-if="!messages.length" class="workspace-ai-capabilities">
        <p>我可以帮你</p>
        <button v-for="action in mode === 'chat' ? chatQuickActions : quickActions" :key="action.title" type="button" @click="selectQuickAction(action.prompt, mode, action.taskType)"><el-icon><component :is="action.icon" /></el-icon><span><strong>{{ action.title }}</strong><small>{{ action.description }}</small><em v-if="action.requiresContext && !(props.context?.chapter_id || props.chapterId)">执行前需选择教材专题</em></span></button>
      </section>
      <div v-for="message in renderedMessages" :key="message.id" class="workspace-ai-message" :class="`is-${message.role}`">
        <div v-if="message.role === 'assistant'" class="workspace-ai-avatar"><el-icon><MagicStick /></el-icon><span>AI</span></div>
        <div class="workspace-ai-bubble">
          <p v-if="message.role === 'user'">{{ message.content }}</p>
          <article v-else class="teaching-document">
            <div v-if="!message.content && loading && message.id === messages[messages.length - 1]?.id" class="workspace-ai-generating" role="status" aria-live="polite">
              <span class="workspace-ai-generating-spinner"><el-icon class="is-loading"><Loading /></el-icon></span>
              <span><strong>{{ generationLabel(message) }}</strong><small>{{ message.mode === 'agent' ? 'Agent 正在执行，可切换到 Chat 继续问答。' : 'Chat 正在组织教材依据，不会接入 Agent。' }}</small></span>
            </div>
            <div v-else v-html="message.rendered"></div>
          </article>
          <section v-if="message.role === 'assistant' && (message.plan || message.execution || message.run || message.progress?.length || (loading && message.id === messages[messages.length - 1]?.id))" class="workspace-ai-activity" :class="`is-${agentActivityStatus(message) || 'running'}`" role="status" aria-live="polite">
            <button v-if="message.plan?.steps?.length" type="button" class="workspace-ai-activity-toggle" :aria-expanded="activityExpanded(message.id)" @click="toggleActivitySteps(message.id)">
              <span class="workspace-ai-activity-marker">{{ progressMarker(agentActivityStatus(message)) }}</span>
              <span class="workspace-ai-activity-label">{{ agentActivityLabel(message) }}</span>
              <span class="workspace-ai-activity-chevron" aria-hidden="true">{{ activityExpanded(message.id) ? '⌃' : '⌄' }}</span>
            </button>
            <template v-else>
              <span class="workspace-ai-activity-marker">{{ progressMarker(agentActivityStatus(message)) }}</span>
              <span class="workspace-ai-activity-label">{{ agentActivityLabel(message) }}</span>
            </template>
            <ol v-if="message.plan?.steps?.length && activityExpanded(message.id)" class="workspace-ai-activity-details">
              <li v-for="step in message.plan.steps" :key="step.key" :class="`is-${step.status}`">
                <span class="workspace-ai-step-dot"></span><span>{{ step.title }}</span><small>{{ stepStatusLabel(step.status) }}</small>
              </li>
            </ol>
          </section>
          <section v-if="message.role === 'assistant' && hasFailedVerification(message)" class="workspace-ai-verification">
            <strong>执行校验</strong>
            <span v-for="check in verificationChecks(message)" :key="check.key" :class="{ failed: !check.passed }">{{ check.passed ? '✓' : '!' }} {{ check.label }}<small v-if="check.detail">{{ check.detail }}</small></span>
          </section>
          <section v-if="message.role === 'assistant' && message.execution?.result?.warnings?.length" class="workspace-ai-warning-list">
            <strong>需要留意</strong><span v-for="warning in message.execution.result.warnings" :key="warning">{{ warning }}</span>
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
          <div v-if="message.role === 'user' && message.attachments?.length" class="workspace-ai-attachments"><span v-for="attachment in message.attachments" :key="attachment.id">图片 · {{ attachment.name }}</span></div>
          <div v-if="message.role === 'assistant' && message.content" class="workspace-ai-meta"><el-tag size="small" :type="role === 'admin' && message.mode === 'agent' ? 'success' : message.grounded ? 'success' : 'warning'">{{ role === 'admin' && message.mode === 'agent' ? 'AI 生成内容 · 平台数据' : message.grounded ? 'AI 生成内容 · 教材依据' : 'AI 生成内容 · 待绑定教材' }}</el-tag><span v-if="message.model">{{ message.model }}</span></div>
          <div v-if="message.role === 'assistant' && message.sources?.length" class="workspace-ai-sources"><span v-for="source in message.sources.slice(0, 3)" :key="`${source.source_title}-${source.position}`">{{ source.source_title }} · {{ source.position }}</span></div>
        </div>
      </div>
    </div>

    <div class="workspace-ai-composer">
      <el-input v-model="question" type="textarea" :rows="2" resize="none" maxlength="2000" :placeholder="composerPlaceholder" @input="resetChatTaskType" @keydown.ctrl.enter.prevent="send()" @keydown.meta.enter.prevent="send()" />
      <AiMediaComposer v-if="mode === 'chat'" v-model="mediaAssets" :course-id="props.context?.course_id || props.courseId || null" :chapter-id="props.context?.chapter_id || props.chapterId || null" :disabled="loading" @transcribed="appendTranscription" @busy-changed="mediaBusy = $event" />
      <div class="workspace-ai-composer-footer"><div class="workspace-ai-mode-switch" role="tablist" aria-label="AI 工作模式"><button type="button" role="tab" :aria-selected="mode === 'chat'" :class="{ active: mode === 'chat' }" @click="switchMode('chat')"><el-icon><ChatDotRound /></el-icon>Chat<i v-if="loadingByMode.chat"></i></button><button type="button" role="tab" :aria-selected="mode === 'agent'" :class="{ active: mode === 'agent' }" @click="switchMode('agent')"><el-icon><MagicStick /></el-icon>Agent<i v-if="loadingByMode.agent"></i></button></div><span class="workspace-ai-hint">{{ modeHint }}</span><el-button type="primary" :loading="loading" :disabled="mode === 'chat' && mediaBusy" :icon="Promotion" aria-label="发送" @click="send()">发送</el-button></div>
    </div>
    <p class="workspace-ai-disclaimer">{{ disclaimer }}</p>
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
.workspace-ai-bubble :deep(.teaching-document) { color: #33415b; font-size: 13px; line-height: 1.7; }
.workspace-ai-bubble :deep(.teaching-document h3), .workspace-ai-bubble :deep(.teaching-document h4) { margin: 0 0 10px; color: #213b69; font-size: 17px; }
.workspace-ai-bubble :deep(.teaching-document p) { margin: 0 0 10px; }
.workspace-ai-bubble :deep(.teaching-document strong) { color: #2e54c4; font-weight: 750; }
.workspace-ai-meta, .workspace-ai-sources { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; color: #8693a9; font-size: 10px; }
.workspace-ai-sources span { padding: 3px 6px; color: #5572a7; background: #f1f5fc; border-radius: 5px; }
.workspace-ai-attachments { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 7px; }
.workspace-ai-attachments span { max-width: 220px; overflow: hidden; padding: 3px 7px; color: #315ed5; background: rgba(255,255,255,.9); border-radius: 6px; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.workspace-ai-generating { display: flex; align-items: center; gap: 10px; min-height: 42px; padding: 7px 0; color: #31518a; }
.workspace-ai-generating-spinner { display: inline-grid; flex: 0 0 auto; width: 32px; height: 32px; place-items: center; color: #3d70e8; background: #e8f0ff; border-radius: 50%; font-size: 18px; }
.workspace-ai-generating strong, .workspace-ai-generating small { display: block; }.workspace-ai-generating strong { font-size: 13px; }.workspace-ai-generating small { margin-top: 3px; color: #8290a9; font-size: 11px; }
.workspace-ai-activity { display: flex; min-width: 0; align-items: center; gap: 7px; margin-top: 10px; color: #71809a; font-size: 11px; line-height: 1.4; }
.workspace-ai-activity-toggle { display: flex; width: 100%; min-width: 0; align-items: center; gap: 7px; padding: 0; color: inherit; text-align: left; background: transparent; border: 0; cursor: pointer; }
.workspace-ai-activity-marker { display: inline-grid; width: 17px; height: 17px; flex: 0 0 auto; place-items: center; color: #fff; background: #6c82dd; border-radius: 50%; font-size: 10px; font-weight: 700; }
.workspace-ai-activity-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-ai-activity-chevron { flex: 0 0 auto; margin-left: auto; color: #8b99ad; font-size: 13px; }
.workspace-ai-activity-details { display: grid; width: 100%; gap: 6px; margin: 5px 0 0 24px; padding: 7px 0 1px; border-top: 1px solid #edf1f7; list-style: none; }
.workspace-ai-activity-details li { display: flex; min-width: 0; align-items: center; gap: 6px; color: #728098; font-size: 10px; }
.workspace-ai-activity-details li > span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-ai-activity-details small { margin-left: auto; color: #9aa6b8; font-size: 9px; }
.workspace-ai-step-dot { width: 6px; height: 6px; flex: 0 0 auto; background: #b9c3d2; border-radius: 50%; }
.workspace-ai-activity-details li.is-completed { color: #438263; }.workspace-ai-activity-details li.is-completed .workspace-ai-step-dot { background: #4eaf80; }
.workspace-ai-activity-details li.is-running { color: #3968c9; }.workspace-ai-activity-details li.is-running .workspace-ai-step-dot { background: #4f73df; box-shadow: 0 0 0 3px rgba(79, 115, 223, .13); }
.workspace-ai-activity-details li.is-blocked, .workspace-ai-activity-details li.is-needs_input { color: #a4661c; }.workspace-ai-activity-details li.is-blocked .workspace-ai-step-dot, .workspace-ai-activity-details li.is-needs_input .workspace-ai-step-dot { background: #d29132; }
.workspace-ai-activity.is-running .workspace-ai-activity-marker, .workspace-ai-activity.is-replanning .workspace-ai-activity-marker { background: #4f73df; animation: workspace-ai-pulse 1.2s ease-in-out infinite; }
.workspace-ai-activity.is-completed { color: #2f7a5c; }.workspace-ai-activity.is-completed .workspace-ai-activity-marker { background: #43a878; }
.workspace-ai-activity.is-failed, .workspace-ai-activity.is-needs_input { color: #a4661c; }.workspace-ai-activity.is-failed .workspace-ai-activity-marker { background: #c45656; }.workspace-ai-activity.is-needs_input .workspace-ai-activity-marker { background: #d29132; }
@keyframes workspace-ai-pulse { 50% { opacity: .55; transform: scale(.82); } }
.workspace-ai-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.workspace-ai-run { display: grid; gap: 10px; margin-top: 12px; padding: 12px; background: linear-gradient(145deg, #f5f8ff, #fff); border: 1px solid #dce6fa; border-radius: 12px; }.workspace-ai-run.is-running, .workspace-ai-run.is-queued { border-color: #aebffc; }.workspace-ai-run.is-completed { border-color: #b8e6ce; }.workspace-ai-run.is-failed { border-color: #f2c3c7; }.workspace-ai-run-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.workspace-ai-run-header div { display: grid; gap: 2px; }.workspace-ai-run-header span, .workspace-ai-run-eyebrow { color: #8191aa; font-size: 10px; }.workspace-ai-run-header strong { color: #29466e; font-size: 12px; }.workspace-ai-evidence { display: flex; flex-wrap: wrap; gap: 5px; padding: 8px; background: #fbfcff; border: 1px dashed #d7e2f5; border-radius: 8px; }.workspace-ai-evidence strong { width: 100%; color: #52709e; font-size: 10px; }.workspace-ai-evidence span { max-width: 100%; overflow: hidden; padding: 3px 5px; color: #687995; text-overflow: ellipsis; white-space: nowrap; background: #eef4ff; border-radius: 5px; font-size: 10px; }.workspace-ai-run-error { margin: 0; color: #b33c49; font-size: 11px; line-height: 1.55; }.workspace-ai-outline { padding: 11px; background: #fff; border: 1px solid #e5ebf4; border-radius: 10px; }.workspace-ai-outline h4 { margin: 3px 0 5px; color: #263f67; font-size: 14px; }.workspace-ai-outline > p:not(.workspace-ai-run-eyebrow) { margin: 0; color: #65748b; font-size: 11px; line-height: 1.55; }.workspace-ai-outline-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 9px; }.workspace-ai-outline-grid > div, .workspace-ai-flow { padding: 8px; background: #f8faff; border-radius: 8px; }.workspace-ai-outline-grid strong, .workspace-ai-flow strong, .workspace-ai-artifacts > strong { display: block; color: #4564a4; font-size: 11px; }.workspace-ai-outline-grid ul { display: grid; gap: 3px; margin: 5px 0 0; padding-left: 16px; color: #66758d; font-size: 10px; line-height: 1.45; }.workspace-ai-flow { display: flex; flex-wrap: wrap; gap: 5px 7px; margin-top: 8px; }.workspace-ai-flow strong { width: 100%; }.workspace-ai-flow span { padding: 3px 5px; color: #677790; background: #fff; border: 1px solid #e4eaf4; border-radius: 5px; font-size: 10px; }.workspace-ai-artifact-actions { display: grid; gap: 7px; }.workspace-ai-artifact-actions p { margin: 0; color: #55677f; font-size: 11px; }.workspace-ai-artifact-actions > div { display: flex; flex-wrap: wrap; gap: 6px; }.workspace-ai-artifacts { display: grid; gap: 6px; padding-top: 2px; }.workspace-ai-artifacts article { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 9px; color: #50627b; background: #fff; border: 1px solid #e3eaf5; border-radius: 8px; font-size: 11px; }
.workspace-ai-artifacts-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }

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
.workspace-ai-verification, .workspace-ai-warning-list { display: grid; gap: 4px; margin-top: 8px; padding: 8px 10px; border-radius: 8px; font-size: 10px; }.workspace-ai-verification { color: #397758; background: #f2fbf6; border: 1px solid #d6efdf; }.workspace-ai-verification > strong, .workspace-ai-warning-list > strong { font-size: 11px; }.workspace-ai-verification span { display: flex; flex-wrap: wrap; gap: 4px; }.workspace-ai-verification span.failed { color: #a46b14; }.workspace-ai-verification small { color: #7e8ca2; }.workspace-ai-warning-list { color: #94631d; background: #fff9ed; border: 1px solid #f2dfb9; }

.workspace-ai-composer { padding: 12px 18px 9px; background: rgba(255,255,255,.95); border-top: 1px solid #e5ebf5; }
.workspace-ai-composer :deep(.el-textarea__inner) { padding: 10px 12px; color: #2b3a56; background: #fbfcff; border-color: #dfe7f4; border-radius: 11px; box-shadow: none; }
.workspace-ai-composer :deep(.el-textarea__inner:focus) { border-color: #637ce5; box-shadow: 0 0 0 2px rgba(99,124,229,.12); }
.workspace-ai-composer-footer { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.workspace-ai-mode-switch { display: inline-flex; overflow: hidden; border: 1px solid #d8e1ef; border-radius: 8px; }
.workspace-ai-mode-switch button { position: relative; display: inline-flex; align-items: center; gap: 4px; padding: 5px 9px; color: #687890; background: #fff; border: 0; cursor: pointer; font-size: 11px; }
.workspace-ai-mode-switch button + button { border-left: 1px solid #d8e1ef; }
.workspace-ai-mode-switch button.active { color: #2e5dce; background: #edf2ff; font-weight: 700; }
.workspace-ai-mode-switch button i { width: 6px; height: 6px; background: #3975dc; border-radius: 50%; box-shadow: 0 0 0 3px rgba(57,117,220,.12); }
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

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, Setting, View, Warning } from '@element-plus/icons-vue'
import {
  knowledgeApi,
  type AuthoritySource,
  type AuthoritySourcePreview,
  type CandidateDecisionSummary,
  type CandidateTopicGroup,
  type DiscoveryJob,
  type DiscoveryRuntimeStatus,
  type MaterialCandidate,
  type MaterialSnapshot,
  type PolicyChange,
} from '@/api/knowledge'
import { courseApi } from '@/api/courses'
import type { CourseDetail } from '@/types'
import UiCard from '@/components/ui/UiCard.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import { getErrorMessage } from '@/utils/error'
import { formatBeijingDateTime } from '@/utils/time'

const loading = ref(true)
const route = useRoute()
const running = ref(false)
const publishing = ref(false)
const sources = ref<AuthoritySource[]>([])
const jobs = ref<DiscoveryJob[]>([])
const candidates = ref<MaterialCandidate[]>([])
const candidateSummary = ref<CandidateDecisionSummary>({ pending_review: 0, high_priority: 0, observed: 0, filtered: 0 })
const runtimeStatus = ref<DiscoveryRuntimeStatus | null>(null)
const topicGroups = ref<CandidateTopicGroup[]>([])
const selectedCandidateIds = ref<number[]>([])
const policyChanges = ref<PolicyChange[]>([])
const courseDetails = ref<CourseDetail[]>([])
const keyword = ref('')
const candidateQuery = ref('')
const candidateSourceFilter = ref<number | undefined>()
const selectedSources = ref<number[]>([])
const selectedCandidateId = ref<number | null>(null)

// 完整发布元数据与教材/专题范围表单（自动回填系统推荐，管理员可随时补充修改）
const publishForm = reactive({
  source_title: '',
  publisher: '',
  published_date: '',
  course_ids: [] as number[],
  chapter_ids: [] as number[],
  knowledge_tags: [] as string[],
})

// 完整正文快照按需加载
const fullSnapshot = ref<MaterialSnapshot | null>(null)
const fullTextExpanded = ref(false)
const fullTextLoading = ref(false)

// 来源试抓预览
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('')
const previewResult = ref<AuthoritySourcePreview | null>(null)

const runVisible = ref(false)
const sourceVisible = ref(false)
const editingSourceId = ref<number | null>(null)
const sourceForm = ref({
  name: '',
  domain: '',
  source_level: 'A' as AuthoritySource['source_level'],
  adapter_type: 'html_list' as AuthoritySource['adapter_type'],
  entry_url: '',
  fetch_interval_minutes: 1440,
  request_interval_seconds: 3,
  allow_full_text: true,
  allow_alert: true,
  is_enabled: true,
})
const candidateFilters = new Set(['pending_review', 'observed', 'filtered', 'published', 'rejected'])
const requestedFilter = String(route.query.filter || '')
const activeFilter = ref(candidateFilters.has(requestedFilter) ? requestedFilter : 'pending_review')
const selectedCandidate = computed(() => candidates.value.find((item) => item.id === selectedCandidateId.value) || candidates.value[0] || null)
const availableChapterGroups = computed(() => {
  const chosenCourses = publishForm.course_ids.length
    ? courseDetails.value.filter((course) => publishForm.course_ids.includes(course.id))
    : courseDetails.value
  return chosenCourses.filter((course) => course.chapters.length > 0)
})
const candidateAnalysisState = computed(() => {
  const candidate = selectedCandidate.value
  if (!candidate) return { label: '等待分析', status: 'neutral' as const, retry: true }
  if (candidate.analysis_reason?.includes('自动关联/差异分析失败')) {
    return { label: '自动分析失败', status: 'danger' as const, retry: true }
  }
  if (candidate.suggested_course_ids !== null && candidate.suggested_chapter_ids !== null) {
    return { label: '自动分析完成', status: 'success' as const, retry: false }
  }
  return { label: '等待分析', status: 'warning' as const, retry: true }
})
const runningJob = computed(() => jobs.value.find((item) => ['queued', 'running'].includes(item.status)))
let jobPollTimer: ReturnType<typeof setTimeout> | undefined

function syncPublishForm(candidate: MaterialCandidate | null) {
  fullSnapshot.value = null
  fullTextExpanded.value = false
  if (!candidate) {
    publishForm.source_title = ''
    publishForm.publisher = ''
    publishForm.published_date = ''
    publishForm.course_ids = []
    publishForm.chapter_ids = []
    publishForm.knowledge_tags = []
    return
  }
  const source = sources.value.find((item) => item.id === candidate.source_registry_id)
  publishForm.source_title = candidate.title || ''
  publishForm.publisher = candidate.publisher || source?.name || ''
  publishForm.published_date = candidate.published_date || ''
  const validCourseIds = new Set(courseDetails.value.map((course) => course.id))
  const validChapterIds = new Set(courseDetails.value.flatMap((course) => course.chapters.map((ch) => ch.id)))
  const baseCourses = candidate.course_ids.length ? candidate.course_ids : (candidate.suggested_course_ids || [])
  const baseChapters = candidate.chapter_ids.length ? candidate.chapter_ids : (candidate.suggested_chapter_ids || [])
  publishForm.course_ids = baseCourses.filter((id) => validCourseIds.has(id))
  publishForm.chapter_ids = baseChapters.filter((id) => validChapterIds.has(id))
  publishForm.knowledge_tags = [...(candidate.knowledge_tags.length ? candidate.knowledge_tags : (candidate.suggested_knowledge_tags || []))]
}

function handlePublishCoursesChange(courseIds: number[]) {
  if (!courseIds.length) return
  const allowedChapterIds = new Set(
    courseDetails.value
      .filter((course) => courseIds.includes(course.id))
      .flatMap((course) => course.chapters.map((chapter) => chapter.id)),
  )
  publishForm.chapter_ids = publishForm.chapter_ids.filter((id) => allowedChapterIds.has(id))
}

async function loadCourseDetails() {
  const courseList = (await courseApi.list()).data.data
  const details = await Promise.all(
    courseList.map((course) => courseApi.detail(course.id).then((res) => res.data.data).catch(() => null)),
  )
  courseDetails.value = details.filter((item): item is CourseDetail => Boolean(item))
}

async function loadPolicyChanges(candidateId: number | null) {
  policyChanges.value = []
  if (!candidateId) return
  try {
    policyChanges.value = (await knowledgeApi.candidatePolicyChanges(candidateId)).data.data
  } catch { /* 旧数据库尚未迁移时不阻断候选材料审核 */ }
}

async function toggleFullText() {
  const candidate = selectedCandidate.value
  if (!candidate) return
  if (fullTextExpanded.value) {
    fullTextExpanded.value = false
    return
  }
  if (fullSnapshot.value && fullSnapshot.value.candidate_id === candidate.id) {
    fullTextExpanded.value = true
    return
  }
  fullTextLoading.value = true
  try {
    const snapshots = (await knowledgeApi.candidateSnapshots(candidate.id)).data.data
    if (!snapshots.length) {
      ElMessage.warning('该候选材料暂无完整正文快照')
      return
    }
    fullSnapshot.value = snapshots[0]
    fullTextExpanded.value = true
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '读取完整正文快照失败'))
  } finally {
    fullTextLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [sourceResult, jobResult, candidateResult, summaryResult, groupResult, runtimeResult] = await Promise.all([
      knowledgeApi.authoritySources(),
      knowledgeApi.discoveryJobs(30),
      knowledgeApi.discoveryCandidates({
        status: activeFilter.value,
        source_registry_id: candidateSourceFilter.value,
        q: candidateQuery.value.trim() || undefined,
        limit: 200,
      }),
      knowledgeApi.candidateDecisionSummary(),
      knowledgeApi.candidateTopicGroups(),
      knowledgeApi.discoveryRuntimeStatus().catch(() => null),
      courseDetails.value.length ? Promise.resolve() : loadCourseDetails(),
    ])
    sources.value = sourceResult.data.data
    jobs.value = jobResult.data.data
    candidates.value = candidateResult.data.data
    candidateSummary.value = summaryResult.data.data
    topicGroups.value = groupResult.data.data
    if (runtimeResult) runtimeStatus.value = runtimeResult.data.data
    selectedCandidateIds.value = selectedCandidateIds.value.filter((id) => candidates.value.some((item) => item.id === id))
    if (!selectedSources.value.length) selectedSources.value = sources.value.filter((item) => item.is_enabled).map((item) => item.id)
    const requested = Number(route.query.candidate)
    if (!candidates.value.some((item) => item.id === selectedCandidateId.value)) {
      selectedCandidateId.value = candidates.value.some((item) => item.id === requested)
        ? requested
        : (candidates.value[0]?.id || null)
    }
    syncPublishForm(selectedCandidate.value)
    await loadPolicyChanges(selectedCandidateId.value)
    window.dispatchEvent(new Event('notifications-changed'))
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '资料动态加载失败'))
  } finally { loading.value = false }
}

async function runDiscovery() {
  running.value = true
  try {
    await knowledgeApi.createDiscoveryJob({
      query_text: keyword.value.trim() || undefined,
      keywords: keyword.value.split(/[，,、\s]+/).map((item) => item.trim()).filter(Boolean),
      source_ids: selectedSources.value,
    })
    ElMessage.success('发现任务已转入后台')
    runVisible.value = false
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '发现任务启动失败')) }
  finally { running.value = false }
}

async function refresh() { await load() }

let disposed = false

function scheduleJobPoll() {
  if (jobPollTimer) clearTimeout(jobPollTimer)
  jobPollTimer = undefined
  if (disposed || !runningJob.value) return
  jobPollTimer = setTimeout(async () => {
    if (disposed) return
    const previousId = runningJob.value?.id
    try {
      if (document.visibilityState === 'visible') {
        jobs.value = (await knowledgeApi.discoveryJobs(30)).data.data
        if (disposed) return
        if (previousId && !jobs.value.some((item) => item.id === previousId && ['queued', 'running'].includes(item.status))) {
          await load()
        }
      }
    } catch {
      // 临时网络失败留给下一轮或用户手动刷新，不反复弹出错误提示。
    } finally {
      if (!disposed) scheduleJobPoll()
    }
  }, 10_000)
}

function editSource(source?: AuthoritySource) {
  editingSourceId.value = source?.id || null
  sourceForm.value = source ? {
    name: source.name, domain: source.domain, source_level: source.source_level,
    adapter_type: source.adapter_type, entry_url: source.entry_url,
    fetch_interval_minutes: source.fetch_interval_minutes, request_interval_seconds: source.request_interval_seconds,
    allow_full_text: source.allow_full_text, allow_alert: source.allow_alert, is_enabled: source.is_enabled,
  } : { name: '', domain: '', source_level: 'A', adapter_type: 'html_list', entry_url: '', fetch_interval_minutes: 1440, request_interval_seconds: 3, allow_full_text: true, allow_alert: true, is_enabled: true }
  sourceVisible.value = true
}

async function saveSource() {
  if (!sourceForm.value.name.trim() || !sourceForm.value.domain.trim() || !sourceForm.value.entry_url.trim()) return ElMessage.warning('请完整填写来源名称、域名和栏目入口')
  running.value = true
  try {
    if (editingSourceId.value) await knowledgeApi.updateAuthoritySource(editingSourceId.value, sourceForm.value)
    else await knowledgeApi.createAuthoritySource(sourceForm.value)
    ElMessage.success(editingSourceId.value ? '来源设置已更新' : '权威来源已添加')
    sourceVisible.value = false
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '来源保存失败')) }
  finally { running.value = false }
}

async function previewSourceConfig(source?: AuthoritySource) {
  previewTitle.value = source ? `${source.name}（${source.domain}）` : `${sourceForm.value.name || '未保存来源'}（${sourceForm.value.domain}）`
  previewResult.value = null
  previewVisible.value = true
  previewLoading.value = true
  try {
    if (source) {
      previewResult.value = (await knowledgeApi.previewAuthoritySource(source.id)).data.data
    } else {
      if (!sourceForm.value.domain.trim() || !sourceForm.value.entry_url.trim()) {
        previewVisible.value = false
        ElMessage.warning('请先填写白名单域名和栏目入口网址')
        return
      }
      previewResult.value = (await knowledgeApi.previewDraftAuthoritySource({
        domain: sourceForm.value.domain.trim(),
        adapter_type: sourceForm.value.adapter_type,
        entry_url: sourceForm.value.entry_url.trim(),
        allow_full_text: sourceForm.value.allow_full_text,
        fetch_sample_article: true,
      })).data.data
    }
  } catch (error: unknown) {
    previewResult.value = {
      ok: false,
      adapter: 'unknown',
      discovered_count: 0,
      sample_links: [],
      sample_article: null,
      error: getErrorMessage(error, '试抓请求失败'),
    }
  } finally {
    previewLoading.value = false
  }
}

async function toggleSource(source: AuthoritySource) {
  try {
    await knowledgeApi.updateAuthoritySource(source.id, { is_enabled: !source.is_enabled })
    ElMessage.success(source.is_enabled ? '来源已停用' : '来源已启用')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '来源状态更新失败')) }
}

async function deleteSource(source: AuthoritySource) {
  await ElMessageBox.confirm(`确定删除权威来源“${source.name}”吗？若该来源下已有历史候选材料将禁止删除（可改为停用）。`, '删除权威来源', { type: 'warning' })
  try {
    await knowledgeApi.deleteAuthoritySource(source.id)
    selectedSources.value = selectedSources.value.filter((id) => id !== source.id)
    ElMessage.success('权威来源已删除')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '删除权威来源失败')) }
}

async function retryJob(job: DiscoveryJob) {
  try {
    await knowledgeApi.retryDiscoveryJob(job.id)
    ElMessage.success('失败任务已重新进入后台队列')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '任务重试失败')) }
}

async function cancelJob(job: DiscoveryJob) {
  try {
    await knowledgeApi.cancelDiscoveryJob(job.id)
    ElMessage.success('后台发现任务已停止')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '任务停止失败')) }
}

async function deleteJob(job: DiscoveryJob) {
  await ElMessageBox.confirm(`确定删除任务 #${job.id} 的执行记录吗？候选材料会保留。`, '删除发现任务', { type: 'warning' })
  try {
    await knowledgeApi.deleteDiscoveryJob(job.id)
    ElMessage.success('任务记录已删除')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '删除任务失败')) }
}

async function analyze() {
  if (!selectedCandidate.value) return
  running.value = true
  try {
    const updated = (await knowledgeApi.analyzeDiscoveryCandidate(selectedCandidate.value.id)).data.data
    const statusText = candidateStatusLabel(updated.status)
    ElMessage.success(`分析完成（当前状态：${statusText}）`)
    if (candidateFilters.has(updated.status) && updated.status !== activeFilter.value) {
      activeFilter.value = updated.status
    }
    selectedCandidateId.value = updated.id
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '自动分析失败')) }
  finally { running.value = false }
}

async function reviewChange(change: PolicyChange, action: 'confirm' | 'dismiss' | 'observe') {
  try {
    const response = await knowledgeApi.reviewPolicyChange(change.id, { action })
    const reviewedChange = response.data.data
    const syncStatus = reviewedChange.kb_sync_status
    ElMessage.success(action === 'confirm'
      ? (syncStatus === 'synced'
          ? (reviewedChange.alert_recommended ? '已确认、重建索引并提醒相关教师' : '已确认并同步；该证据不会作为重要提醒')
          : '已确认，候选材料发布后将自动同步')
      : action === 'observe' ? '已加入观察' : '已标记为误判')
    await loadPolicyChanges(selectedCandidate.value?.id || null)
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '政策变化审核失败')) }
}

async function syncChange(change: PolicyChange) {
  try {
    await knowledgeApi.syncPolicyChange(change.id)
    ElMessage.success('已重试政策变化同步')
    await loadPolicyChanges(selectedCandidate.value?.id || null)
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '知识库同步失败')) }
}

async function review(action: 'reject' | 'duplicate' | 'restore' | 'observe') {
  if (!selectedCandidate.value) return
  const labels: Record<typeof action, string> = {
    reject: '驳回候选材料',
    duplicate: '标记为重复材料',
    restore: '移回待审核队列',
    observe: '转入观察中',
  }
  if (action === 'reject' || action === 'duplicate') {
    await ElMessageBox.confirm(`确定要${labels[action]}“${selectedCandidate.value.title}”吗？`, labels[action], { type: 'warning' })
  }
  try {
    const res = await knowledgeApi.reviewDiscoveryCandidate(selectedCandidate.value.id, { action })
    window.dispatchEvent(new Event('notifications-changed'))
    ElMessage.success(res.data.message || '审核状态已更新')
    if (action === 'restore') {
      activeFilter.value = 'pending_review'
      selectedCandidateId.value = res.data.data.id
    }
    await load()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '状态更新失败'))
  }
}

async function deleteCandidate() {
  if (!selectedCandidate.value) return
  await ElMessageBox.confirm(`确定永久删除候选材料“${selectedCandidate.value.title}”吗？相关正文快照和差异证据也会删除。`, '删除候选材料', { type: 'warning' })
  try {
    await knowledgeApi.deleteDiscoveryCandidate(selectedCandidate.value.id)
    window.dispatchEvent(new Event('notifications-changed'))
    selectedCandidateId.value = null
    ElMessage.success('候选材料已删除')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '删除候选材料失败')) }
}

function toggleCandidate(candidateId: number, selected: boolean | string | number) {
  selectedCandidateIds.value = Boolean(selected)
    ? [...new Set([...selectedCandidateIds.value, candidateId])]
    : selectedCandidateIds.value.filter((id) => id !== candidateId)
}

function selectAllCandidates(selected: boolean | string | number) {
  selectedCandidateIds.value = Boolean(selected) ? candidates.value.map((item) => item.id) : []
}

async function batchCandidates(action: 'reject' | 'observe' | 'delete' | 'restore') {
  if (!selectedCandidateIds.value.length) return ElMessage.warning('请先选择候选材料')
  const label = {
    reject: '批量忽略',
    observe: '批量加入观察',
    delete: '批量删除',
    restore: '批量移回待审核',
  }[action]
  const detail = action === 'delete'
    ? '正文快照和差异证据也会永久删除。'
    : action === 'restore'
      ? '这些材料将回到待审核队列且不再被自动过滤。'
      : '这些材料将退出当前列表。'
  await ElMessageBox.confirm(`确定${label}所选 ${selectedCandidateIds.value.length} 条材料吗？${detail}`, label, { type: 'warning' })
  try {
    await knowledgeApi.batchDiscoveryCandidates({ candidate_ids: selectedCandidateIds.value, action })
    selectedCandidateIds.value = []
    selectedCandidateId.value = null
    window.dispatchEvent(new Event('notifications-changed'))
    ElMessage.success(`${label}完成`)
    if (action === 'restore') activeFilter.value = 'pending_review'
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, `${label}失败`)) }
}

async function retainTopicPrimary(group: CandidateTopicGroup) {
  const secondaryIds = group.candidate_ids.filter((id) => id !== group.primary_candidate_id)
  if (!secondaryIds.length) return
  await ElMessageBox.confirm(
    `保留“${group.title}”作为主材料，并将其余 ${secondaryIds.length} 条标记为同议题旁证吗？主材料仍需单独确认发布。`,
    '归并同类材料',
    { type: 'warning' },
  )
  try {
    await knowledgeApi.batchDiscoveryCandidates({
      candidate_ids: secondaryIds,
      action: 'duplicate',
      note: `同议题旁证已归并到候选 #${group.primary_candidate_id}`,
    })
    selectedCandidateId.value = group.primary_candidate_id
    selectedCandidateIds.value = []
    window.dispatchEvent(new Event('notifications-changed'))
    ElMessage.success(`已保留主材料，并归并 ${secondaryIds.length} 条旁证`)
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '同类材料归并失败')) }
}

function openTopicPrimary(group: CandidateTopicGroup) {
  selectedCandidateId.value = group.primary_candidate_id
  document.querySelector('.candidate-layout')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function publish() {
  if (!selectedCandidate.value) return
  const title = publishForm.source_title.trim()
  const publisher = publishForm.publisher.trim()
  const publishedDate = publishForm.published_date.trim()
  if (!title) return ElMessage.warning('请填写发布标题')
  if (!publisher) return ElMessage.warning('发布前请补全发布机构')
  if (!publishedDate) return ElMessage.warning('发布前请补全发布日期')
  if (!publishForm.course_ids.length && !publishForm.chapter_ids.length) {
    return ElMessage.warning('发布前请至少选择一本关联教材或一个专题章节')
  }
  const courseNames = courseDetails.value
    .filter((item) => publishForm.course_ids.includes(item.id))
    .map((item) => item.name)
    .join('、')
  await ElMessageBox.confirm(
    `确认将《${title}》发布到“${courseNames || '所选专题对应教材'}”（${publishForm.chapter_ids.length} 个专题章节）的中央材料层吗？`,
    '确认发布',
    { type: 'warning' },
  )
  publishing.value = true
  try {
    await knowledgeApi.reviewDiscoveryCandidate(selectedCandidate.value.id, {
      action: 'publish',
      course_ids: publishForm.course_ids,
      chapter_ids: publishForm.chapter_ids,
      knowledge_tags: publishForm.knowledge_tags,
      source_title: title,
      publisher,
      published_date: publishedDate,
    })
    window.dispatchEvent(new Event('notifications-changed'))
    ElMessage.success('候选材料已发布并进入中央知识库')
    await load()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '材料发布失败')) }
  finally { publishing.value = false }
}

function sourceLevelLabel(level: string) { return ({ A: 'A级·中央机关', B: 'B级·权威媒体', C: 'C级·地方来源', D: 'D级·线索来源' } as Record<string, string>)[level] || level }
function candidateStatusLabel(status: string) {
  return ({
    pending_review: '待审核',
    observed: '观察中',
    filtered: '已过滤',
    published: '已发布',
    rejected: '已驳回',
    duplicate: '重复',
  } as Record<string, string>)[status] || status
}
function jobStatusLabel(status: string) { return ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '执行失败', cancelled: '已停止' } as Record<string, string>)[status] || status }
function jobTitle(job: DiscoveryJob) { return job.query_text || (job.trigger_type === 'scheduled' ? '每日权威资料巡检' : '全量来源巡检') }
function jobSources(job: DiscoveryJob) { return job.source_ids.map((id) => sources.value.find((source) => source.id === id)?.name).filter(Boolean).join('、') || '已配置来源' }
function jobChipStatus(job: DiscoveryJob) {
  if (job.status === 'failed') return 'danger'
  if (job.status === 'completed') return job.failed_count ? 'warning' : 'success'
  return 'info'
}
function importanceLabel(level: string) { return ({ high: '重要', medium: '重点', observe: '观察' } as Record<string, string>)[level] || '待评估' }
function changeSuggestion(change: PolicyChange) {
  if (!change.alert_recommended && change.importance === 'low') return '建议人工核对'
  if (change.change_type.includes('新增') || change.similarity_score < 0.35) return '建议补充知识点'
  if (change.old_document_id || change.old_chapter_id) return '建议修订既有表述'
  return '建议加入教学案例'
}
function formatDateTime(value: string | null | undefined) {
  return value ? formatBeijingDateTime(value) : '—'
}

async function focusCandidatePool() {
  if (route.hash !== '#candidate-pool') return
  await nextTick()
  document.getElementById('candidate-pool')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(async () => {
  await load()
  await focusCandidatePool()
  scheduleJobPoll()
})
onBeforeUnmount(() => {
  disposed = true
  if (jobPollTimer) clearTimeout(jobPollTimer)
})
watch(runningJob, scheduleJobPoll)
watch(selectedCandidateId, (value) => {
  syncPublishForm(selectedCandidate.value)
  void loadPolicyChanges(value)
})
watch(() => route.query.filter, async (value) => {
  const nextFilter = String(value || '')
  if (candidateFilters.has(nextFilter) && nextFilter !== activeFilter.value) {
    activeFilter.value = nextFilter
    await load()
  }
  await focusCandidatePool()
})
watch(() => route.hash, () => { void focusCandidatePool() })
</script>

<template>
  <div v-loading="loading" class="discovery-page">
    <UiPageHeader
      eyebrow="AUTHORITY DISCOVERY"
      title="资料动态"
      description="从白名单权威来源发现线索、试抓验证、抓取全文快照并交由管理员核验发布；未确认材料不会进入正式知识库。"
    >
      <template #actions>
        <el-button :icon="Refresh" @click="refresh">刷新状态</el-button>
        <el-button
          type="primary"
          :icon="Search"
          :disabled="Boolean(runningJob)"
          :title="runningJob ? `任务 #${runningJob.id} 正在执行，请稍后再试` : '启动后台发现任务'"
          @click="runVisible = true"
        >{{ runningJob ? '发现进行中' : '启动发现' }}</el-button>
      </template>
    </UiPageHeader>

    <section class="discovery-metrics">
      <UiCard><span>启用来源</span><strong>{{ sources.filter(item => item.is_enabled).length }}</strong><small>共 {{ sources.length }} 个白名单栏目</small></UiCard>
      <UiCard><span>待人工决策</span><strong>{{ candidateSummary.pending_review }}</strong><small>高优 {{ candidateSummary.high_priority }} · 观察 {{ candidateSummary.observed }}</small></UiCard>
      <UiCard><span>后台任务</span><strong>{{ runningJob ? '运行中' : '空闲' }}</strong><small>{{ runningJob?.progress_stage || '可启动新的发现任务' }}</small></UiCard>
      <UiCard>
        <span>自动定时巡检</span>
        <strong>{{ runtimeStatus?.scheduler_enabled ? '已开启' : '未开启' }}</strong>
        <small>{{ runtimeStatus?.scheduler_enabled ? `每 ${Math.round((runtimeStatus.scheduler_poll_seconds || 300) / 60)} 分钟检查到期来源` : '当前仅支持手动启动（.env 可开启）' }}</small>
      </UiCard>
    </section>

    <section class="discovery-grid">
      <UiCard>
        <template #title><div><p class="eyebrow">SOURCE REGISTRY</p><h2>权威来源白名单</h2></div></template>
        <template #actions><el-button size="small" :icon="Setting" @click="editSource()">新增栏目来源</el-button></template>
        <div class="source-list">
          <div v-for="source in sources" :key="source.id" class="source-item">
            <el-checkbox v-model="selectedSources" :value="source.id" :disabled="!source.is_enabled" />
            <span>
              <strong>{{ source.name }}</strong>
              <small>{{ sourceLevelLabel(source.source_level) }} · {{ source.domain }} · {{ source.adapter_type }}</small>
              <small :title="source.entry_url">{{ source.entry_url }}</small>
              <small>最近抓取：{{ source.last_success_time ? formatBeijingDateTime(source.last_success_time) : '尚未抓取' }}</small>
            </span>
            <StatusChip :label="source.is_enabled ? '启用' : '停用'" :status="source.is_enabled ? 'success' : 'neutral'" />
            <el-dropdown trigger="click">
              <el-button text :icon="Setting" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="previewSourceConfig(source)">试抓预览</el-dropdown-item>
                  <el-dropdown-item @click="editSource(source)">编辑设置</el-dropdown-item>
                  <el-dropdown-item @click="toggleSource(source)">{{ source.is_enabled ? '停用来源' : '启用来源' }}</el-dropdown-item>
                  <el-dropdown-item divided @click="deleteSource(source)">删除来源</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </UiCard>

      <UiCard>
        <template #title><div><p class="eyebrow">DISCOVERY JOBS</p><h2>发现任务</h2></div></template>
        <div class="job-list">
          <div v-for="job in jobs.slice(0, 8)" :key="job.id" class="job-item">
            <div class="job-main"><strong>任务 #{{ job.id }} · {{ jobTitle(job) }}</strong><small>{{ job.trigger_type === 'scheduled' ? '自动巡检' : job.trigger_type === 'retry' ? '失败重试' : '管理员手动' }} · {{ jobSources(job) }}</small><small>{{ job.progress_stage }} · 创建于 {{ formatDateTime(job.created_time) }}</small><small v-if="job.started_time || job.finished_time">开始于 {{ formatDateTime(job.started_time) }} · {{ job.finished_time ? `完成于 ${formatDateTime(job.finished_time)}` : '尚未完成' }}</small><div class="job-steps"><span :class="{ active: job.discovered_count > 0 }">读取来源</span><span :class="{ active: job.extraction_failed_count + job.fetched_count > 0 }">提取正文</span><span :class="{ active: job.filtered_count > 0 || job.pending_review_count > 0 }">相关性过滤</span><span :class="{ active: job.pending_review_count > 0 }">待审核</span></div></div>
            <div class="job-side"><StatusChip :label="jobStatusLabel(job.status)" :status="jobChipStatus(job)" /><small>{{ job.fetched_count }} 条正文 · {{ job.pending_review_count }} 条待审</small><small>过滤 {{ job.filtered_count }} · 去重 {{ job.deduped_count }} · 失败 {{ job.failed_count }}</small><small v-if="job.error_message" class="job-error" :title="job.error_message">{{ job.error_message }}</small><el-button v-if="job.status === 'failed'" text type="primary" size="small" @click="retryJob(job)">重试</el-button><el-button v-if="['queued', 'running'].includes(job.status)" text type="danger" size="small" @click="cancelJob(job)">停止</el-button><el-button v-if="!['queued', 'running'].includes(job.status)" text type="danger" size="small" @click="deleteJob(job)">删除</el-button></div>
          </div>
          <div v-if="!jobs.length" class="empty-line">尚未执行发现任务</div>
        </div>
      </UiCard>
    </section>

    <UiCard id="candidate-pool" class="candidate-card">
      <template #title><div><p class="eyebrow">CANDIDATE MATERIALS</p><h2>候选材料池</h2></div></template>
      <template #actions>
        <el-radio-group v-model="activeFilter" size="small" @change="load">
          <el-radio-button value="pending_review">待审核 ({{ candidateSummary.pending_review }})</el-radio-button>
          <el-radio-button value="observed">观察中 ({{ candidateSummary.observed }})</el-radio-button>
          <el-radio-button value="filtered">已过滤 ({{ candidateSummary.filtered }})</el-radio-button>
          <el-radio-button value="published">已发布</el-radio-button>
          <el-radio-button value="rejected">已驳回</el-radio-button>
        </el-radio-group>
      </template>

      <div class="candidate-filter-bar">
        <el-input
          v-model="candidateQuery"
          :prefix-icon="Search"
          clearable
          size="small"
          placeholder="按标题或发布机构检索当前候选池"
          @keyup.enter="load"
          @clear="load"
        />
        <el-select v-model="candidateSourceFilter" clearable size="small" placeholder="全部来源" @change="load">
          <el-option v-for="source in sources" :key="source.id" :label="source.name" :value="source.id" />
        </el-select>
        <el-button size="small" @click="load">筛选</el-button>
      </div>

      <section v-if="activeFilter === 'pending_review' && topicGroups.length" class="topic-groups" aria-label="同类材料议题包">
        <div class="topic-groups-heading"><div><p class="eyebrow">TOPIC GROUPS</p><h3>同类材料议题包</h3></div><span>{{ topicGroups.length }} 组可合并审核</span></div>
        <div class="topic-group-list">
          <article v-for="group in topicGroups" :key="group.group_key" class="topic-group-item">
            <div class="topic-group-copy">
              <div><StatusChip label="推荐主材料" status="authority" /><strong>{{ group.title }}</strong></div>
              <span>{{ group.member_count }} 条材料 · {{ group.members.map(member => member.publisher || `${member.source_level}级来源`).join('、') }}</span>
              <small>{{ group.reason }}</small>
            </div>
            <div class="topic-group-actions"><el-button size="small" @click="openTopicPrimary(group)">查看主材料</el-button><el-button size="small" type="primary" plain @click="retainTopicPrimary(group)">保留主材料</el-button></div>
          </article>
        </div>
      </section>

      <div v-if="activeFilter !== 'published'" class="batch-toolbar">
        <el-checkbox
          :model-value="Boolean(candidates.length) && selectedCandidateIds.length === candidates.length"
          :indeterminate="selectedCandidateIds.length > 0 && selectedCandidateIds.length < candidates.length"
          @change="selectAllCandidates"
        >全选当前列表</el-checkbox>
        <span>已选择 {{ selectedCandidateIds.length }} 条</span>
        <el-button v-if="activeFilter !== 'pending_review'" size="small" type="success" plain :disabled="!selectedCandidateIds.length" @click="batchCandidates('restore')">移回待审核</el-button>
        <el-button v-if="activeFilter === 'pending_review'" size="small" :disabled="!selectedCandidateIds.length" @click="batchCandidates('observe')">加入观察</el-button>
        <el-button v-if="activeFilter !== 'rejected'" size="small" :disabled="!selectedCandidateIds.length" @click="batchCandidates('reject')">批量忽略</el-button>
        <el-button size="small" type="danger" plain :disabled="!selectedCandidateIds.length" @click="batchCandidates('delete')">批量删除</el-button>
      </div>

      <div v-if="candidates.length" class="candidate-layout">
        <div class="candidate-list">
          <div v-for="item in candidates" :key="item.id" :class="['candidate-item', { active: selectedCandidate?.id === item.id }]" @click="selectedCandidateId = item.id">
            <el-checkbox v-if="activeFilter !== 'published'" :model-value="selectedCandidateIds.includes(item.id)" @click.stop @change="toggleCandidate(item.id, $event)" />
            <div class="candidate-copy">
              <div class="candidate-badges">
                <StatusChip :label="sourceLevelLabel(item.source_level)" :status="item.source_level === 'A' ? 'authority' : 'info'" />
                <StatusChip :label="`${importanceLabel(item.importance_level)} ${Math.round(item.importance_score * 100)}%`" :status="item.importance_level === 'high' ? 'danger' : item.importance_level === 'medium' ? 'warning' : 'neutral'" />
              </div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.publisher || '机构待补全' }} · {{ item.published_date || '日期待补全' }}</span>
              <span>抓取于 {{ formatDateTime(item.created_time) }}</span>
            </div>
          </div>
        </div>
        <div v-if="selectedCandidate" class="candidate-detail">
          <div class="candidate-heading">
            <div>
              <div class="candidate-badges">
                <StatusChip :label="candidateStatusLabel(selectedCandidate.status)" :status="selectedCandidate.status === 'published' ? 'success' : selectedCandidate.status === 'pending_review' ? 'warning' : 'neutral'" />
                <StatusChip label="正文快照" status="info" />
              </div>
              <h3>{{ selectedCandidate.title }}</h3>
            </div>
            <div class="candidate-heading-actions">
              <el-button text size="small" :icon="View" :loading="fullTextLoading" @click="toggleFullText">
                {{ fullTextExpanded ? '收起为摘要预览' : '查看完整正文' }}
              </el-button>
              <a :href="selectedCandidate.source_url" target="_blank" rel="noreferrer">查看原文 ↗</a>
              <el-button v-if="selectedCandidate.status !== 'published'" text type="danger" size="small" @click="deleteCandidate">删除候选</el-button>
            </div>
          </div>
          <div class="candidate-preview-wrap">
            <p class="candidate-preview" :class="{ expanded: fullTextExpanded }">
              {{ fullTextExpanded && fullSnapshot ? fullSnapshot.content : (selectedCandidate.content_preview || '暂无正文预览') }}
            </p>
            <small v-if="fullTextExpanded && fullSnapshot" class="snapshot-meta">
              完整快照共 {{ fullSnapshot.content.length }} 字符 · 解析器 {{ fullSnapshot.parser_version }} · 抓取于 {{ formatDateTime(fullSnapshot.fetched_time) }}
            </small>
          </div>
          <dl class="candidate-meta"><div><dt>抓取时间</dt><dd>{{ formatDateTime(selectedCandidate.created_time) }}</dd></div><div><dt>来源等级</dt><dd>{{ sourceLevelLabel(selectedCandidate.source_level) }}</dd></div><div><dt>主题相关度</dt><dd>{{ selectedCandidate.relevance_score ? `${Math.round(selectedCandidate.relevance_score * 100)}%` : '全量巡检，未设单一主题' }}</dd></div><div><dt>教材关联度</dt><dd>{{ Math.round((selectedCandidate.association_confidence || 0) * 100) }}%</dd></div><div><dt>正文质量</dt><dd>{{ Math.round((selectedCandidate.extraction_quality_score || 0) * 100) }}%</dd></div><div><dt>教学重要度</dt><dd>{{ importanceLabel(selectedCandidate.importance_level) }} · {{ Math.round((selectedCandidate.importance_score || 0) * 100) }}%</dd></div><div><dt>分析说明</dt><dd>{{ selectedCandidate.analysis_reason || selectedCandidate.importance_reason || '待补充' }}</dd></div></dl>

          <section v-if="selectedCandidate.status !== 'published'" class="publish-panel">
            <div class="panel-heading">
              <div>
                <p class="eyebrow">PUBLISH &amp; REVIEW</p>
                <h4>核验元数据并发布到中央材料</h4>
              </div>
              <StatusChip
                v-if="selectedCandidate.suggested_chapter_ids?.length"
                :label="`已自动带入 ${selectedCandidate.suggested_chapter_ids.length} 个推荐专题`"
                status="info"
              />
            </div>
            <el-form label-position="top" size="small" class="publish-form">
              <el-form-item label="发布标题（可修订）">
                <el-input v-model="publishForm.source_title" maxlength="500" placeholder="填写正式入库的资料标题" />
              </el-form-item>
              <div class="publish-meta-grid">
                <el-form-item label="发布机构（必填）">
                  <el-input v-model="publishForm.publisher" maxlength="255" placeholder="例如：国务院 / 教育部 / 中国政府网" />
                </el-form-item>
                <el-form-item label="发布日期（必填）">
                  <el-date-picker
                    v-model="publishForm.published_date"
                    type="date"
                    value-format="YYYY-MM-DD"
                    placeholder="补全原文发布日期"
                    style="width: 100%"
                  />
                </el-form-item>
              </div>
              <div class="publish-meta-grid">
                <el-form-item label="关联教材（支持多选）">
                  <el-select
                    v-model="publishForm.course_ids"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="选择关联教材"
                    style="width: 100%"
                    @change="handlePublishCoursesChange"
                  >
                    <el-option v-for="course in courseDetails" :key="course.id" :label="course.name" :value="course.id" />
                  </el-select>
                </el-form-item>
                <el-form-item label="关联专题章节（建议勾选以支持后续政策对比）">
                  <el-select
                    v-model="publishForm.chapter_ids"
                    multiple
                    filterable
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="选择具体专题章节"
                    style="width: 100%"
                  >
                    <el-option-group v-for="course in availableChapterGroups" :key="course.id" :label="course.name">
                      <el-option v-for="chapter in course.chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" />
                    </el-option-group>
                  </el-select>
                </el-form-item>
              </div>
              <el-form-item label="知识点标签（可选）">
                <el-select
                  v-model="publishForm.knowledge_tags"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="输入关键词回车添加标签"
                  style="width: 100%"
                />
              </el-form-item>
            </el-form>
            <div class="decision-area">
              <el-button type="primary" :loading="publishing" @click="publish">确认发布到中央材料</el-button>
              <el-button v-if="selectedCandidate.status !== 'pending_review'" type="success" plain @click="review('restore')">移回待审核</el-button>
              <el-button v-if="selectedCandidate.status === 'pending_review'" @click="review('observe')">加入观察</el-button>
              <el-button v-if="selectedCandidate.status !== 'rejected'" @click="review('reject')">驳回</el-button>
              <el-button text type="warning" @click="review('duplicate')">标记重复</el-button>
            </div>
          </section>

          <section class="association-panel">
            <div class="panel-heading"><div><p class="eyebrow">SCOPE &amp; EVIDENCE</p><h4>教材关联与政策变化</h4></div><div class="analysis-actions"><StatusChip :label="candidateAnalysisState.label" :status="candidateAnalysisState.status" /><el-button size="small" :loading="running" @click="analyze">{{ candidateAnalysisState.retry ? '重试分析' : '重新分析' }}</el-button></div></div>
            <div class="association-summary">
              <span>章节匹配置信度 {{ Math.round((selectedCandidate.association_confidence || 0) * 100) }}%</span>
              <span>{{ selectedCandidate.suggested_chapter_ids?.length || 0 }} 个专题</span>
              <span>{{ policyChanges.length }} 条原文差异</span>
            </div>
            <p class="association-reason">{{ selectedCandidate.association_reason || '尚未完成自动关联，请点击重新分析。' }}</p>
            <div v-if="policyChanges.length" class="change-list">
              <article v-for="change in policyChanges" :key="change.id" class="change-item">
                <div class="change-title"><div><strong>{{ change.change_type }}</strong><small>{{ changeSuggestion(change) }}</small></div><StatusChip :label="change.alert_recommended ? '建议提醒' : change.importance === 'high' || change.importance === 'medium' ? '重点关注' : '观察'" :status="change.alert_recommended ? 'danger' : 'info'" /></div>
                <p class="change-source">旧依据：{{ change.old_source_title || '教材原文' }} · 证据置信度 {{ Math.round(change.evidence_confidence * 100) }}% · 字面相似度 {{ Math.round(change.similarity_score * 100) }}%</p>
                <div class="evidence-grid"><div><small>既有原文</small><blockquote>{{ change.old_excerpt || '该专题既有材料中未找到可比表述' }}</blockquote></div><div><small>新材料原文</small><blockquote>{{ change.new_excerpt }}</blockquote></div></div>
                <p class="change-explanation">{{ change.ai_explanation }}</p>
                <div v-if="change.review_status === 'pending'" class="change-actions"><el-button size="small" type="success" @click="reviewChange(change, 'confirm')">{{ change.alert_recommended ? '确认并提醒教师' : '确认变化' }}</el-button><el-button size="small" @click="reviewChange(change, 'observe')">加入观察</el-button><el-button size="small" text type="danger" @click="reviewChange(change, 'dismiss')">误判</el-button></div>
                <div v-else class="reviewed-label">
                  <span>{{ change.review_status === 'confirmed' ? '已确认' : change.review_status === 'observed' ? '观察中' : '已忽略' }}</span>
                  <span v-if="change.review_status === 'confirmed'" class="sync-state">知识库：{{ change.kb_sync_status === 'synced' ? '已同步' : change.kb_sync_status === 'waiting_publish' ? '待发布材料' : change.kb_sync_status === 'failed' ? '同步失败' : '处理中' }}</span>
                  <el-button v-if="change.review_status === 'confirmed' && change.kb_sync_status === 'failed'" text type="primary" size="small" @click="syncChange(change)">重试同步</el-button>
                </div>
              </article>
            </div>
            <div v-else class="empty-evidence">暂无可对照的变化证据；这不代表材料无效，请结合上方发布面板核对范围后发布。</div>
          </section>
        </div>
      </div>
      <div v-else class="empty-line"><el-icon><Warning /></el-icon>当前筛选下没有候选材料</div>
    </UiCard>

    <el-dialog v-model="runVisible" title="启动权威资料发现" width="min(92vw, 620px)">
      <el-form label-position="top">
        <el-alert title="系统会读取来源文章详情页，提取正文后进行相关度和教材关联筛选；低相关材料可在观察中/已过滤查看并随时手动发布。" type="info" :closable="false" show-icon />
        <el-form-item label="检索主题"><el-input v-model="keyword" placeholder="例如：全过程人民民主 思政课 建设；留空表示全量权威巡检" /></el-form-item>
        <el-form-item label="参与来源"><el-checkbox-group v-model="selectedSources"><el-checkbox v-for="source in sources.filter(item => item.is_enabled)" :key="source.id" :value="source.id">{{ source.name }}</el-checkbox></el-checkbox-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="runVisible = false">取消</el-button><el-button type="primary" :loading="running" @click="runDiscovery">开始后台发现</el-button></template>
    </el-dialog>

    <el-dialog v-model="sourceVisible" :title="editingSourceId ? '编辑权威来源' : '新增权威栏目来源'" width="min(92vw, 680px)">
      <el-form label-position="top">
        <el-alert title="同一白名单域名允许配置多个不同栏目入口（如中国政府网政策库与要闻、教育部社科司与新闻发布）或单篇权威原文，按入口网址判重。" type="info" :closable="false" show-icon style="margin-bottom: 12px" />
        <div class="source-form-grid"><el-form-item label="来源名称"><el-input v-model="sourceForm.name" placeholder="例如：教育部·社科司" /></el-form-item><el-form-item label="白名单域名"><el-input v-model="sourceForm.domain" :disabled="Boolean(editingSourceId)" placeholder="例如 moe.gov.cn" /></el-form-item></div>
        <el-form-item label="栏目入口（必须为 HTTPS 且属于白名单域名）"><el-input v-model="sourceForm.entry_url" placeholder="https://www.moe.gov.cn/s78/A13/" /></el-form-item>
        <div class="source-form-grid"><el-form-item label="来源级别"><el-select v-model="sourceForm.source_level"><el-option v-for="level in ['A','B','C','D']" :key="level" :label="sourceLevelLabel(level)" :value="level" /></el-select></el-form-item><el-form-item label="适配器"><el-select v-model="sourceForm.adapter_type"><el-option label="HTML 列表页" value="html_list" /><el-option label="单篇权威原文" value="single_article" /><el-option label="RSS" value="rss" /><el-option label="Sitemap" value="sitemap" /></el-select></el-form-item></div>
        <div class="source-form-grid"><el-form-item label="检查周期（分钟）"><el-input-number v-model="sourceForm.fetch_interval_minutes" :min="5" :max="10080" /></el-form-item><el-form-item label="请求间隔（秒）"><el-input-number v-model="sourceForm.request_interval_seconds" :min="1" :max="60" /></el-form-item></div>
        <el-space wrap><el-checkbox v-model="sourceForm.allow_full_text">允许抓取全文</el-checkbox><el-checkbox v-model="sourceForm.allow_alert">允许生成提醒</el-checkbox><el-checkbox v-model="sourceForm.is_enabled">立即启用</el-checkbox></el-space>
      </el-form>
      <template #footer>
        <el-button @click="sourceVisible = false">取消</el-button>
        <el-button :loading="previewLoading" @click="previewSourceConfig()">试抓预览</el-button>
        <el-button type="primary" :loading="running" @click="saveSource">保存来源</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="`试抓预览 · ${previewTitle}`" width="min(92vw, 760px)">
      <div v-loading="previewLoading" class="preview-dialog-body">
        <template v-if="previewResult">
          <el-alert
            :type="previewResult.ok ? 'success' : 'warning'"
            :title="previewResult.ok ? `连接与正文解析正常（适配器：${previewResult.adapter}，发现 ${previewResult.discovered_count} 条链接）` : (previewResult.error || '试抓未通过')"
            :closable="false"
            show-icon
          />
          <div v-if="previewResult.sample_article" class="preview-article-card">
            <strong>首篇正文试抓结果：{{ previewResult.sample_article.title }}</strong>
            <div class="preview-article-meta">
              <span>机构：{{ previewResult.sample_article.publisher || '未识别（发布时可手填）' }}</span>
              <span>日期：{{ previewResult.sample_article.published_date || '未识别（发布时可手填）' }}</span>
              <span>字数：{{ previewResult.sample_article.content_length }}</span>
              <span>质量分：{{ Math.round(previewResult.sample_article.extraction_quality_score * 100) }}%</span>
            </div>
            <p>{{ previewResult.sample_article.content_preview }}</p>
          </div>
          <div v-if="previewResult.sample_links.length" class="preview-link-list">
            <strong>前 {{ previewResult.sample_links.length }} 条解析链接</strong>
            <ul>
              <li v-for="link in previewResult.sample_links" :key="link.url">
                <a :href="link.url" target="_blank" rel="noreferrer">{{ link.title }}</a>
              </li>
            </ul>
          </div>
        </template>
      </div>
      <template #footer><el-button @click="previewVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.discovery-page { display: grid; gap: var(--space-5); }
.discovery-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); }
.discovery-metrics > * { display: grid; gap: var(--space-2); }
.discovery-metrics span { color: var(--ink-600); }
.discovery-metrics strong { color: var(--ink-900); font-size: 28px; }
.discovery-metrics small { color: var(--ink-400); }
.discovery-grid { display: grid; grid-template-columns: minmax(280px, .85fr) minmax(360px, 1.15fr); gap: var(--space-4); align-items: start; }
.discovery-grid h2, .candidate-card h2 { margin: var(--space-1) 0 0; font-size: var(--fs-section); }
.source-list, .job-list { display: grid; gap: var(--space-2); }
.source-item, .job-item { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-input); }
.source-item > span, .job-main { display: grid; min-width: 0; gap: 3px; flex: 1; }
.source-item small, .job-item small { color: var(--ink-400); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job-side { display: grid; justify-items: end; gap: 3px; }
.job-side small { max-width: 150px; }
.job-side .job-error { max-width: 220px; color: var(--danger); }
.job-steps { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.job-steps span { padding: 2px 7px; color: var(--ink-400); background: var(--surface-page); border-radius: 999px; font-size: 11px; }
.job-steps span.active { color: var(--action-blue); background: var(--action-soft); }
.source-form-grid, .publish-meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.empty-line { display: flex; justify-content: center; align-items: center; gap: var(--space-2); min-height: 100px; color: var(--ink-400); }
.candidate-filter-bar { display: grid; grid-template-columns: minmax(220px, 1fr) 210px auto; gap: var(--space-2); margin-bottom: var(--space-3); }
.topic-groups { display: grid; gap: var(--space-3); margin-bottom: var(--space-4); padding-bottom: var(--space-4); border-bottom: 1px solid var(--line); }
.topic-groups-heading, .topic-group-item, .topic-group-actions { display: flex; align-items: center; gap: var(--space-3); }
.topic-groups-heading { justify-content: space-between; }
.topic-groups-heading h3 { margin: 2px 0 0; font-size: var(--fs-body); }
.topic-groups-heading > span { color: var(--ink-400); font-size: var(--fs-meta); }
.topic-group-list { display: grid; gap: 0; border-top: 1px solid var(--line); }
.topic-group-item { justify-content: space-between; padding: var(--space-3) 0; border-bottom: 1px solid var(--line); }
.topic-group-copy { display: grid; min-width: 0; gap: 5px; }
.topic-group-copy > div { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.topic-group-copy > span, .topic-group-copy > small { color: var(--ink-500); }
.topic-group-copy > small { line-height: 1.5; }
.topic-group-actions { flex: 0 0 auto; }
.batch-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-3); padding: var(--space-3); color: var(--ink-500); background: var(--surface-page); border: 1px solid var(--line); border-radius: var(--radius-input); }
.batch-toolbar > span { margin-right: auto; font-size: var(--fs-meta); }
.candidate-layout { display: grid; grid-template-columns: minmax(250px, .7fr) minmax(0, 1.3fr); gap: var(--space-4); }
.candidate-list { display: grid; gap: var(--space-2); max-height: 760px; overflow: auto; }
.candidate-item { display: flex; align-items: start; gap: var(--space-2); width: 100%; padding: var(--space-3); color: var(--ink-900); background: transparent; border: 1px solid var(--line); border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.candidate-copy { display: grid; justify-items: start; min-width: 0; gap: var(--space-2); flex: 1; }
.candidate-item:hover, .candidate-item.active { background: var(--action-soft); border-color: var(--action-line); }
.candidate-item span:last-child { color: var(--ink-400); font-size: var(--fs-meta); }
.candidate-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.candidate-detail { display: grid; gap: var(--space-3); min-width: 0; }
.candidate-heading { display: flex; align-items: start; justify-content: space-between; gap: var(--space-3); }
.candidate-heading > div { display: grid; gap: var(--space-2); }
.candidate-heading > .candidate-heading-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.candidate-heading h3 { margin: 0; font-size: 21px; line-height: 1.5; }
.candidate-heading a { color: var(--action-blue); white-space: nowrap; }
.candidate-preview-wrap { display: grid; gap: 6px; }
.candidate-preview { max-height: 260px; margin: 0; padding: var(--space-4); overflow: auto; color: var(--ink-700); background: var(--surface-page); border-radius: var(--radius-input); line-height: 1.8; white-space: pre-wrap; }
.candidate-preview.expanded { max-height: 540px; }
.snapshot-meta { color: var(--ink-400); font-size: 12px; }
.candidate-meta { display: grid; gap: 0; margin: 0; }
.candidate-meta div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: var(--space-2); padding: var(--space-2) 0; border-bottom: 1px solid var(--line); }
.candidate-meta dt { color: var(--ink-400); }
.candidate-meta dd { margin: 0; color: var(--ink-700); }
.publish-panel { display: grid; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--line); border-left: 3px solid var(--authority-red); border-radius: var(--radius-card); background: var(--surface-card); }
.publish-form :deep(.el-form-item) { margin-bottom: 10px; }
.decision-area { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); padding-top: var(--space-1); }
.association-panel { display: grid; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--action-line); border-radius: var(--radius-card); background: color-mix(in srgb, var(--action-soft) 45%, white); }
.panel-heading, .change-title { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.analysis-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.panel-heading h4 { margin: 0; font-size: 18px; }
.association-summary { display: flex; flex-wrap: wrap; gap: var(--space-2); color: var(--action-blue); font-size: var(--fs-meta); }
.association-summary span { padding: 5px 9px; background: white; border: 1px solid var(--line); border-radius: 999px; }
.association-reason, .change-source, .change-explanation { margin: 0; color: var(--ink-600); line-height: 1.65; }
.change-list { display: grid; gap: var(--space-3); }
.change-item { display: grid; gap: var(--space-2); padding: var(--space-3); background: white; border: 1px solid var(--line); border-radius: var(--radius-input); }
.change-title > div { display: grid; gap: 3px; }
.change-title strong { color: var(--ink-900); }
.change-title small { color: var(--action-blue); }
.change-source { font-size: var(--fs-meta); }
.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
.evidence-grid > div { min-width: 0; padding: var(--space-2); background: var(--surface-page); border-radius: var(--radius-input); }
.evidence-grid small { color: var(--ink-400); }
.evidence-grid blockquote { margin: var(--space-1) 0 0; color: var(--ink-700); line-height: 1.7; white-space: pre-wrap; }
.change-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.reviewed-label { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); color: var(--ink-400); font-size: var(--fs-meta); }
.sync-state { color: var(--action-blue); }
.empty-evidence { padding: var(--space-3); color: var(--ink-400); background: white; border-radius: var(--radius-input); }
.preview-dialog-body { display: grid; gap: 14px; min-height: 120px; }
.preview-article-card { display: grid; gap: 8px; padding: 12px 14px; background: var(--surface-page); border: 1px solid var(--line); border-radius: var(--radius-input); }
.preview-article-meta { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 12px; color: var(--ink-500); }
.preview-article-card p { margin: 0; font-size: 13px; line-height: 1.7; color: var(--ink-700); white-space: pre-wrap; max-height: 220px; overflow: auto; }
.preview-link-list ul { margin: 8px 0 0; padding-left: 18px; display: grid; gap: 5px; font-size: 13px; }
.preview-link-list a { color: var(--action-blue); }
@media (max-width: 1100px) { .discovery-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { .discovery-grid, .candidate-layout { grid-template-columns: 1fr; } }
@media (max-width: 767px) { .discovery-metrics, .source-form-grid, .publish-meta-grid, .candidate-filter-bar { grid-template-columns: 1fr; } .candidate-heading, .topic-group-item { display: grid; } .topic-group-actions { justify-content: start; } .evidence-grid { grid-template-columns: 1fr; } }
</style>

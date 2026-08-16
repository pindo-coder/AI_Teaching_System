<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  AI_CAPABILITY_NAMES,
  aiOperationsApi,
  type AiCallLog,
  type AiCapabilityConfig,
  type AiCapabilityInput,
  type AiCapabilityInputMap,
  type AiCapabilityName,
  type AiCapabilityOperationResult,
  type AiOperationSummary,
  type AiProviderConfig,
  type AiProviderPreset,
  type AiUnifiedConfig,
  type AiUnifiedConfigInput,
  type AiUnifiedProviderName,
} from '@/api/aiOperations'
import StatusChip from '@/components/ui/StatusChip.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import type { SemanticStatus } from '@/types/workspace'
import { getErrorMessage } from '@/utils/error'
import { formatBeijingDateTime } from '@/utils/time'

interface UnifiedConfigForm {
  provider_name: AiUnifiedProviderName
  api_key: string
  capabilities: AiCapabilityInputMap
}

interface CapabilityMeta {
  label: string
  shortLabel: string
  description: string
  modelPlaceholder: string
}

const capabilityMeta: Record<AiCapabilityName, CapabilityMeta> = {
  text: {
    label: '文本生成',
    shortLabel: 'TEXT',
    description: '教材问答、Agent 规划、课纲和教学内容生成',
    modelPlaceholder: '例如：qwen-plus',
  },
  embedding: {
    label: '向量嵌入',
    shortLabel: 'VECTOR',
    description: '知识库索引、语义检索和教材证据召回',
    modelPlaceholder: '例如：text-embedding-v4',
  },
  vision: {
    label: '图片理解',
    shortLabel: 'VISION',
    description: '识别课堂图片、教材截图和多模态提问',
    modelPlaceholder: '例如：qwen3-vl-plus',
  },
  asr: {
    label: '语音识别',
    shortLabel: 'ASR',
    description: '将师生语音输入安全转写为可编辑文本',
    modelPlaceholder: '例如：qwen3-asr-flash',
  },
  image_generation: {
    label: '图片生成',
    shortLabel: 'IMAGE',
    description: '当前仅支持阿里云百炼 Wan 原生接口，为课件生成教学配图',
    modelPlaceholder: '例如：wan2.7-image-pro',
  },
}

function defaultCapability(capability: AiCapabilityName): AiCapabilityInput {
  const base: AiCapabilityInput = {
    enabled: capability === 'text',
    base_url: '',
    model_name: '',
    api_key: '',
    timeout_seconds: capability === 'asr' || capability === 'image_generation' ? 120 : capability === 'vision' ? 90 : 60,
  }
  if (capability === 'embedding') base.dimensions = 1024
  if (capability === 'text') {
    base.temperature = 0.2
    base.streaming_enabled = true
  }
  return base
}

function defaultCapabilities(): AiCapabilityInputMap {
  return {
    text: defaultCapability('text'),
    embedding: defaultCapability('embedding'),
    vision: defaultCapability('vision'),
    asr: defaultCapability('asr'),
    image_generation: defaultCapability('image_generation'),
  }
}

function normalizedCapability(
  capability: AiCapabilityName,
  value?: Partial<AiCapabilityInput | AiCapabilityConfig> | null,
): AiCapabilityInput {
  const fallback = defaultCapability(capability)
  const normalized: AiCapabilityInput = {
    enabled: value?.enabled ?? fallback.enabled,
    base_url: value?.base_url ?? fallback.base_url,
    model_name: value?.model_name ?? fallback.model_name,
    api_key: '',
    timeout_seconds: Number(value?.timeout_seconds ?? fallback.timeout_seconds),
  }
  if (capability === 'embedding') {
    normalized.dimensions = Number(value?.dimensions ?? fallback.dimensions ?? 1024)
  }
  if (capability === 'text') {
    normalized.temperature = Number(value?.temperature ?? fallback.temperature ?? 0.2)
    normalized.streaming_enabled = value?.streaming_enabled ?? fallback.streaming_enabled ?? true
  }
  return normalized
}

function legacyUnifiedConfig(legacy: AiProviderConfig): AiUnifiedConfig {
  return {
    provider_name: 'custom',
    api_key_masked: legacy.api_key_masked,
    capabilities: {
      text: {
        id: legacy.id,
        capability: 'text',
        provider_name: 'custom',
        source: legacy.source,
        enabled: true,
        base_url: legacy.base_url || '',
        model_name: legacy.model_name,
        api_key_masked: legacy.api_key_masked,
        dimensions: null,
        temperature: legacy.temperature,
        timeout_seconds: legacy.timeout_seconds,
        streaming_enabled: legacy.streaming_enabled,
        last_test_status: legacy.last_test_status,
        last_test_message: legacy.last_test_message,
        last_test_time: legacy.last_test_time,
        updated_time: legacy.updated_time,
      },
    },
  }
}

const loading = ref(true)
const acting = ref(false)
const configAction = ref<'test' | 'activate' | ''>('')
const activeTab = ref('calls')
const calls = ref<AiCallLog[]>([])
const config = ref<AiUnifiedConfig | null>(null)
const presets = ref<AiProviderPreset[]>([])
const testResults = ref<Partial<Record<AiCapabilityName, AiCapabilityOperationResult>>>({})
const activationResults = ref<Partial<Record<AiCapabilityName, AiCapabilityOperationResult>>>({})
const savedEmbeddingSignature = ref('')
const summary = ref<AiOperationSummary>({
  total_24h: 0,
  success_24h: 0,
  failed_24h: 0,
  running: 0,
  average_latency_ms: null,
  success_rate: 1,
  active_model: '—',
  config_source: 'environment',
  prompt_tokens_24h: null,
  completion_tokens_24h: null,
  total_tokens_24h: null,
  tokenized_calls_24h: 0,
  model_token_usage_24h: [],
})
const filters = reactive({ status: '', feature: '' })
const form = reactive<UnifiedConfigForm>({
  provider_name: 'dashscope',
  api_key: '',
  capabilities: defaultCapabilities(),
})

const features = computed(() => Array.from(new Set(calls.value.map((item) => item.feature))).sort())
const modelTokenUsage = computed(() => summary.value.model_token_usage_24h || [])
const enabledCapabilityCount = computed(() => AI_CAPABILITY_NAMES.filter((name) => form.capabilities[name].enabled).length)
const recommendedPreset = computed(() => presets.value.find((item) => item.id === 'dashscope') || null)
const selectedProviderPreset = computed(() => presets.value.find((item) => item.id === form.provider_name) || null)
const maskedApiKey = computed(() => config.value?.api_key_masked || null)
const embeddingChanged = computed(() => Boolean(savedEmbeddingSignature.value)
  && embeddingSignature(form.capabilities.embedding) !== savedEmbeddingSignature.value)

const featureLabels: Record<string, string> = {
  learning_assist: '学习辅助/笔记写作',
  agent_planning: 'Agent 规划',
  agent_response: 'Agent 总结',
  lesson_outline: '课纲生成',
  lesson_artifacts: '教学成果生成',
  ppt_design: 'PPT 设计',
  ppt_quality_review: 'PPT 质量检查',
  ppt_slide_revision: 'PPT 单页修改',
  material_association: '资料教材关联',
  embedding: '向量嵌入',
  vision: '图片理解',
  asr: '语音识别',
  image_generation: '图片生成',
}

function featureLabel(value: string) { return featureLabels[value] || value }
function statusLabel(value: string) { return ({ running: '运行中', success: '成功', failed: '失败' } as Record<string, string>)[value] || value }
function statusType(value: string): SemanticStatus { return value === 'success' ? 'success' : value === 'failed' ? 'danger' : 'info' }
function formatDateTime(value: string | null | undefined) {
  return value ? formatBeijingDateTime(value) : '—'
}
function formatTokenCount(value: number | null | undefined) {
  return value == null ? '—' : new Intl.NumberFormat('zh-CN').format(value)
}
function callTokenUsage(call: AiCallLog) {
  if (call.prompt_tokens == null && call.completion_tokens == null) return '—'
  return `${formatTokenCount(call.prompt_tokens)} + ${formatTokenCount(call.completion_tokens)}`
}
function embeddingSignature(value: AiCapabilityInput) {
  return JSON.stringify({
    enabled: value.enabled,
    base_url: value.base_url.trim(),
    model_name: value.model_name.trim(),
    dimensions: value.dimensions,
  })
}
function providerLabel(provider: string | null | undefined) {
  if (provider === 'dashscope') return '阿里云百炼'
  if (provider === 'custom') return '自定义兼容服务'
  return provider || '尚未配置'
}
function capabilityConfig(capability: AiCapabilityName) {
  return config.value?.capabilities[capability] || null
}
function capabilityStatus(capability: AiCapabilityName): { label: string; status: SemanticStatus } {
  const current = capabilityConfig(capability)
  if (!current) return { label: '未配置', status: 'neutral' }
  if (!current.enabled || current.last_test_status === 'disabled') return { label: '已停用', status: 'neutral' }
  if (current.last_test_status === 'success' || current.last_test_status === 'passed') return { label: '连接正常', status: 'success' }
  if (current.last_test_status === 'validated') return { label: '参数已校验', status: 'info' }
  if (current.last_test_status === 'failed') return { label: '连接失败', status: 'danger' }
  return { label: '等待测试', status: 'warning' }
}
function resultStatus(result: AiCapabilityOperationResult): SemanticStatus {
  if (result.skipped) return 'neutral'
  return result.success ? 'success' : 'danger'
}
function resultLabel(result: AiCapabilityOperationResult) {
  if (result.skipped) return '已跳过'
  if (result.success) return '成功'
  return result.kept_previous ? '失败，已保留原配置' : '失败'
}

function assignConfig(nextConfig: AiUnifiedConfig, clearOperationResults = true) {
  config.value = nextConfig
  form.provider_name = nextConfig.provider_name === 'dashscope' ? 'dashscope' : 'custom'
  form.api_key = ''
  for (const capability of AI_CAPABILITY_NAMES) {
    Object.assign(
      form.capabilities[capability],
      normalizedCapability(capability, nextConfig.capabilities?.[capability]),
    )
  }
  savedEmbeddingSignature.value = embeddingSignature(form.capabilities.embedding)
  if (clearOperationResults) {
    testResults.value = {}
    activationResults.value = {}
  }
}

function applyRecommendedConfig() {
  const preset = recommendedPreset.value
  if (!preset) return ElMessage.warning('推荐配置尚未加载，请稍后刷新页面重试')
  form.provider_name = 'dashscope'
  for (const capability of AI_CAPABILITY_NAMES) {
    Object.assign(
      form.capabilities[capability],
      normalizedCapability(capability, preset.capabilities?.[capability]),
    )
  }
  testResults.value = {}
  activationResults.value = {}
  ElMessage.success('已填入阿里云百炼推荐配置，请填写或沿用共享 API Key 后测试')
}

function capabilityPayload(capability: AiCapabilityName): AiCapabilityInput {
  const value = form.capabilities[capability]
  const apiKey = value.api_key?.trim()
  const payload: AiCapabilityInput = {
    enabled: value.enabled,
    base_url: value.base_url.trim(),
    model_name: value.model_name.trim(),
    ...(apiKey ? { api_key: apiKey } : {}),
    timeout_seconds: Number(value.timeout_seconds),
  }
  if (capability === 'embedding') payload.dimensions = Number(value.dimensions)
  if (capability === 'text') {
    payload.temperature = Number(value.temperature)
    payload.streaming_enabled = Boolean(value.streaming_enabled)
  }
  return payload
}

function unifiedPayload(): AiUnifiedConfigInput {
  const apiKey = form.api_key.trim()
  return {
    provider_name: form.provider_name,
    ...(apiKey ? { api_key: apiKey } : {}),
    capabilities: {
      text: capabilityPayload('text'),
      embedding: capabilityPayload('embedding'),
      vision: capabilityPayload('vision'),
      asr: capabilityPayload('asr'),
      image_generation: capabilityPayload('image_generation'),
    },
  }
}

function validationMessage() {
  if (!enabledCapabilityCount.value) return '请至少启用一项 AI 能力'
  for (const capability of AI_CAPABILITY_NAMES) {
    const value = form.capabilities[capability]
    if (!value.enabled) continue
    const label = capabilityMeta[capability].label
    if (!value.base_url.trim()) return `请填写${label}的接口地址`
    if (!/^https:\/\/[^\s]+$/i.test(value.base_url.trim())) return `${label}的接口地址必须使用 https:// 安全连接`
    if (!value.model_name.trim()) return `请填写${label}的模型名称`
    if (!Number.isFinite(value.timeout_seconds) || value.timeout_seconds < 5 || value.timeout_seconds > 600) {
      return `${label}的超时时间应为 5～600 秒`
    }
    if (capability === 'embedding' && (!Number.isInteger(value.dimensions) || Number(value.dimensions) < 1 || Number(value.dimensions) > 8192)) {
      return '向量维度必须是 1～8192 的整数'
    }
  }
  return ''
}

async function loadCalls() {
  const response = await aiOperationsApi.calls({
    status: filters.status || undefined,
    feature: filters.feature || undefined,
    limit: 200,
  })
  calls.value = response.data.data
}

async function load() {
  loading.value = true
  try {
    const [summaryResult, presetResult, configResult, callsResult] = await Promise.allSettled([
      aiOperationsApi.summary(),
      aiOperationsApi.configPresets(),
      aiOperationsApi.allConfig(),
      aiOperationsApi.calls({ limit: 200 }),
    ])
    if (summaryResult.status === 'fulfilled') summary.value = summaryResult.value.data.data
    if (presetResult.status === 'fulfilled') presets.value = presetResult.value.data.data.presets || []
    if (callsResult.status === 'fulfilled') calls.value = callsResult.value.data.data

    if (configResult.status === 'fulfilled') {
      assignConfig(configResult.value.data.data)
    } else {
      try {
        const legacy = await aiOperationsApi.config()
        assignConfig(legacyUnifiedConfig(legacy.data.data))
        ElMessage.warning('统一能力接口暂不可用，已加载旧版文本模型配置')
      } catch (error: unknown) {
        ElMessage.error(getErrorMessage(error, '统一 AI 配置加载失败'))
      }
    }
    if (summaryResult.status === 'rejected' || callsResult.status === 'rejected') {
      ElMessage.warning('部分 AI 运行数据暂时无法加载，可稍后刷新')
    }
  } finally {
    loading.value = false
  }
}

async function refreshCalls() {
  acting.value = true
  try {
    await Promise.all([
      loadCalls(),
      aiOperationsApi.summary().then((result) => { summary.value = result.data.data }),
    ])
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '调用记录刷新失败'))
  } finally {
    acting.value = false
  }
}

async function testConfig() {
  const invalid = validationMessage()
  if (invalid) return ElMessage.warning(invalid)
  configAction.value = 'test'
  testResults.value = {}
  try {
    const response = await aiOperationsApi.testAllConfig(unifiedPayload())
    testResults.value = { ...(response.data.data.capabilities || {}) }
    const results = Object.values(testResults.value).filter((item): item is AiCapabilityOperationResult => Boolean(item))
    const failures = results.filter((item) => !item.success && !item.skipped)
    if (failures.length) ElMessage.warning(`${failures.length} 项能力测试未通过，请查看能力卡结果`)
    else ElMessage.success('已完成逐项连接测试，当前生效配置未被修改')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '统一 AI 能力测试失败'))
  } finally {
    configAction.value = ''
  }
}

async function activateConfig() {
  const invalid = validationMessage()
  if (invalid) return ElMessage.warning(invalid)
  configAction.value = 'activate'
  activationResults.value = {}
  try {
    const response = await aiOperationsApi.activateAllConfig(unifiedPayload())
    const operation = response.data.data
    activationResults.value = { ...(operation.capabilities || {}) }

    const mergedCapabilities = { ...(config.value?.capabilities || {}) }
    for (const capability of AI_CAPABILITY_NAMES) {
      const activated = activationResults.value[capability]?.config
      if (activated) mergedCapabilities[capability] = activated
    }
    if (Object.keys(mergedCapabilities).length) {
      config.value = {
        provider_name: operation.provider_name,
        api_key_masked: config.value?.api_key_masked || maskedApiKey.value,
        capabilities: mergedCapabilities,
      }
    }
    form.api_key = ''
    for (const capability of AI_CAPABILITY_NAMES) form.capabilities[capability].api_key = ''

    try {
      const current = await aiOperationsApi.allConfig()
      assignConfig(current.data.data, false)
    } catch {
      const embeddingResult = activationResults.value.embedding
      if (embeddingResult?.success && !embeddingResult.kept_previous) {
        savedEmbeddingSignature.value = embeddingSignature(form.capabilities.embedding)
      }
    }

    const results = Object.values(activationResults.value).filter((item): item is AiCapabilityOperationResult => Boolean(item))
    const kept = results.filter((item) => item.kept_previous)
    const failures = results.filter((item) => !item.success && !item.skipped)
    if (failures.length) {
      ElMessage.warning(`${failures.length} 项能力未能启用${kept.length ? '，原可用配置已保留' : ''}`)
    } else {
      ElMessage.success('统一 AI 配置已启用，后续请求将使用新能力配置')
    }
    await refreshCalls()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '统一 AI 配置启用失败'))
  } finally {
    configAction.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="ai-operations-page">
    <UiPageHeader eyebrow="AI OPERATIONS" title="AI 运行中心" description="统一管理文本、向量、多模态与图片生成能力；调用日志不记录完整提示词或回答正文。">
      <template #actions>
        <el-button :icon="Refresh" :loading="acting" @click="refreshCalls">刷新运行状态</el-button>
      </template>
    </UiPageHeader>

    <section class="operation-metrics">
      <UiCard><span>近 24 小时调用</span><strong>{{ summary.total_24h }}</strong><small>成功率 {{ Math.round(summary.success_rate * 100) }}%</small></UiCard>
      <UiCard><span>失败调用</span><strong :class="{ danger: summary.failed_24h }">{{ summary.failed_24h }}</strong><small>{{ summary.running }} 项正在执行</small></UiCard>
      <UiCard><span>平均耗时</span><strong>{{ summary.average_latency_ms === null ? '—' : `${summary.average_latency_ms} ms` }}</strong><small>仅统计已完成请求</small></UiCard>
      <UiCard><span>当前文本模型</span><strong class="model-name">{{ summary.active_model }}</strong><small>{{ summary.config_source === 'database' ? '管理员配置' : '环境变量配置' }}</small></UiCard>
      <UiCard class="token-metric"><span>近 24 小时 Token</span><strong>{{ formatTokenCount(summary.total_tokens_24h) }}</strong><small>输入 {{ formatTokenCount(summary.prompt_tokens_24h) }} · 输出 {{ formatTokenCount(summary.completion_tokens_24h) }}</small><small>仅统计供应商回传 · 已上报 {{ summary.tokenized_calls_24h ?? 0 }} 次调用</small></UiCard>
    </section>

    <UiCard class="operations-shell">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="调用记录" name="calls">
          <div class="filter-row">
            <el-select v-model="filters.status" clearable placeholder="全部状态" @change="loadCalls"><el-option label="成功" value="success" /><el-option label="失败" value="failed" /><el-option label="运行中" value="running" /></el-select>
            <el-select v-model="filters.feature" clearable placeholder="全部功能" @change="loadCalls"><el-option v-for="item in features" :key="item" :label="featureLabel(item)" :value="item" /></el-select>
          </div>
          <el-table v-if="calls.length" :data="calls" stripe>
            <el-table-column label="时间" min-width="170"><template #default="{ row }">{{ formatDateTime(row.started_time) }}</template></el-table-column>
            <el-table-column label="功能" min-width="150"><template #default="{ row }">{{ featureLabel(row.feature) }}</template></el-table-column>
            <el-table-column label="用户" min-width="110"><template #default="{ row }">{{ row.username || '系统任务' }}</template></el-table-column>
            <el-table-column prop="model_name" label="模型" min-width="140" />
            <el-table-column label="调用方式" width="100"><template #default="{ row }">{{ row.streaming ? '流式' : '完整响应' }}</template></el-table-column>
            <el-table-column label="字符数" width="120"><template #default="{ row }">{{ row.input_chars }} / {{ row.output_chars }}</template></el-table-column>
            <el-table-column label="Token（输入 + 输出）" min-width="165"><template #default="{ row }"><span class="token-cell" title="输入 Token + 输出 Token">{{ callTokenUsage(row) }}</span></template></el-table-column>
            <el-table-column label="耗时" width="105"><template #default="{ row }">{{ row.latency_ms === null ? '—' : `${row.latency_ms} ms` }}</template></el-table-column>
            <el-table-column label="状态" width="95"><template #default="{ row }"><StatusChip :label="statusLabel(row.status)" :status="statusType(row.status)" /></template></el-table-column>
            <el-table-column label="错误" min-width="220"><template #default="{ row }"><span class="error-line" :title="row.error_message || ''">{{ row.error_message || '—' }}</span></template></el-table-column>
          </el-table>
          <UiEmptyState v-else title="暂无 AI 调用记录" description="接入统一运行配置后的模型请求会显示在这里。" />
          <section class="model-token-usage">
            <header>
              <div><p class="config-eyebrow">MODEL TOKEN USAGE · 24H</p><h2>调用模型与 Token 消耗</h2><p>仅汇总供应商实际回传 usage 的调用，不使用输入输出字符数推算。</p></div>
              <StatusChip :label="modelTokenUsage.length ? `${modelTokenUsage.length} 个模型` : '暂无用量'" :status="modelTokenUsage.length ? 'info' : 'neutral'" />
            </header>
            <el-table v-if="modelTokenUsage.length" :data="modelTokenUsage" stripe class="model-token-table">
              <el-table-column prop="model_name" label="模型" min-width="190"><template #default="{ row }"><strong class="usage-model-name">{{ row.model_name || '未标识模型' }}</strong></template></el-table-column>
              <el-table-column prop="call_count" label="调用次数" width="105" />
              <el-table-column prop="tokenized_calls" label="已上报次数" width="115" />
              <el-table-column label="输入 Token" min-width="120"><template #default="{ row }">{{ formatTokenCount(row.prompt_tokens) }}</template></el-table-column>
              <el-table-column label="输出 Token" min-width="120"><template #default="{ row }">{{ formatTokenCount(row.completion_tokens) }}</template></el-table-column>
              <el-table-column label="总 Token" min-width="130"><template #default="{ row }"><strong class="usage-total">{{ formatTokenCount(row.total_tokens) }}</strong></template></el-table-column>
            </el-table>
            <UiEmptyState v-else title="暂无按模型 Token 用量" description="旧版服务或供应商未回传 usage 时不会生成估算值。" />
          </section>
        </el-tab-pane>

        <el-tab-pane label="服务状态" name="health">
          <section class="provider-status">
            <div><span>当前供应商</span><strong>{{ providerLabel(config?.provider_name) }}</strong></div>
            <div><span>共享 API Key</span><strong>{{ maskedApiKey || '尚未配置' }}</strong><small>密钥仅在服务端保存，前端永不回显原文</small></div>
            <div><span>已启用能力</span><strong>{{ AI_CAPABILITY_NAMES.filter((name) => capabilityConfig(name)?.enabled).length }} / {{ AI_CAPABILITY_NAMES.length }}</strong></div>
          </section>
          <div class="capability-status-grid">
            <article v-for="capability in AI_CAPABILITY_NAMES" :key="capability" class="capability-status-card">
              <header><div><span>{{ capabilityMeta[capability].shortLabel }}</span><strong>{{ capabilityMeta[capability].label }}</strong></div><StatusChip :label="capabilityStatus(capability).label" :status="capabilityStatus(capability).status" /></header>
              <template v-if="capabilityConfig(capability)">
                <p>{{ capabilityConfig(capability)?.model_name || '未填写模型' }}</p>
                <small>{{ capabilityConfig(capability)?.base_url || '未填写接口地址' }}</small>
                <dl>
                  <div><dt>配置来源</dt><dd>{{ capabilityConfig(capability)?.source === 'database' ? '管理员配置' : '环境变量' }}</dd></div>
                  <div><dt>超时</dt><dd>{{ capabilityConfig(capability)?.timeout_seconds }} 秒</dd></div>
                  <div v-if="capability === 'embedding'"><dt>向量维度</dt><dd>{{ capabilityConfig(capability)?.dimensions || '—' }}</dd></div>
                </dl>
                <p class="last-test-message">{{ capabilityConfig(capability)?.last_test_message || '尚未执行连接测试' }}</p>
                <time>{{ formatDateTime(capabilityConfig(capability)?.last_test_time) }}</time>
              </template>
              <p v-else class="empty-capability">尚未读取到该能力配置</p>
            </article>
          </div>
        </el-tab-pane>

        <el-tab-pane label="统一能力配置" name="config">
          <el-form class="config-form" label-position="top" @submit.prevent>
            <section class="provider-config-panel">
              <div class="provider-config-heading">
                <div><p class="config-eyebrow">PROVIDER & CREDENTIAL</p><h2>供应商与共享密钥</h2><p>同一供应商可共用一份 API Key；使用不同供应商时，可在下方每张能力卡中填写独立密钥。</p></div>
                <el-button type="primary" plain :disabled="!recommendedPreset" @click="applyRecommendedConfig">一键应用百炼推荐配置</el-button>
              </div>
              <el-form-item label="供应商预设">
                <el-radio-group v-model="form.provider_name" size="large">
                  <el-radio-button value="dashscope">阿里云百炼</el-radio-button>
                  <el-radio-button value="custom">自定义兼容服务</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <p class="provider-description">{{ selectedProviderPreset?.description || (form.provider_name === 'custom' ? '文本、向量、图片理解和语音可使用 HTTPS 兼容服务；PPT 图片生成当前仍须使用百炼 Wan 原生接口，也可以单独停用。' : '使用百炼预设快速填入推荐地址、模型和超时参数。') }}</p>
              <el-form-item label="共享 API Key">
                <el-input v-model="form.api_key" type="password" show-password autocomplete="new-password" :placeholder="maskedApiKey ? `留空继续使用 ${maskedApiKey}` : '请输入供应商 API Key'" />
                <p class="key-hint">作为未填写独立密钥时的批量兜底；密钥不会从服务端回传，留空时系统会尝试沿用各能力原有密钥。</p>
              </el-form-item>
            </section>

            <el-alert
              :title="embeddingChanged ? '向量配置已发生变化：启用后必须重建知识库索引，旧索引不会自动兼容。' : '修改向量模型或维度后，需要重建知识库索引。'"
              :type="embeddingChanged ? 'warning' : 'info'"
              :closable="false"
              show-icon
            />

            <div class="capability-form-grid">
              <section v-for="capability in AI_CAPABILITY_NAMES" :key="capability" class="capability-form-card" :class="{ disabled: !form.capabilities[capability].enabled }">
                <header>
                  <div class="capability-heading"><span>{{ capabilityMeta[capability].shortLabel }}</span><div><h3>{{ capabilityMeta[capability].label }}</h3><p>{{ capabilityMeta[capability].description }}</p></div></div>
                  <el-switch v-model="form.capabilities[capability].enabled" inline-prompt active-text="启" inactive-text="停" :aria-label="`${capabilityMeta[capability].label}启用状态`" />
                </header>
                <div class="capability-fields">
                  <el-form-item label="接口地址" class="full-field"><el-input v-model="form.capabilities[capability].base_url" placeholder="https://example.com/v1" /></el-form-item>
                  <el-form-item label="独立 API Key" class="full-field">
                    <el-input
                      v-model="form.capabilities[capability].api_key"
                      type="password"
                      show-password
                      autocomplete="new-password"
                      :placeholder="capabilityConfig(capability)?.api_key_masked ? `留空沿用 ${capabilityConfig(capability)?.api_key_masked}` : '留空使用上方共享 API Key'"
                    />
                    <p class="key-hint">本项密钥优先于共享密钥，仅提交给本项配置的接口主机。</p>
                  </el-form-item>
                  <el-form-item label="模型名称"><el-input v-model="form.capabilities[capability].model_name" :placeholder="capabilityMeta[capability].modelPlaceholder" /></el-form-item>
                  <el-form-item label="超时（秒）"><el-input-number v-model="form.capabilities[capability].timeout_seconds" :min="5" :max="600" controls-position="right" /></el-form-item>
                  <el-form-item v-if="capability === 'embedding'" label="向量维度"><el-input-number v-model="form.capabilities.embedding.dimensions" :min="1" :max="8192" controls-position="right" /></el-form-item>
                  <el-form-item v-if="capability === 'text'" label="默认温度"><el-input-number v-model="form.capabilities.text.temperature" :min="0" :max="2" :step="0.1" controls-position="right" /></el-form-item>
                  <el-form-item v-if="capability === 'text'" label="流式输出"><el-switch v-model="form.capabilities.text.streaming_enabled" active-text="允许" inactive-text="关闭" /></el-form-item>
                </div>
                <div v-if="testResults[capability] || activationResults[capability]" class="operation-results">
                  <div v-if="testResults[capability]" class="operation-result">
                    <div><strong>连接测试</strong><StatusChip :label="resultLabel(testResults[capability]!)" :status="resultStatus(testResults[capability]!)" /><span v-if="testResults[capability]?.latency_ms != null">{{ testResults[capability]?.latency_ms }} ms</span></div>
                    <p>{{ testResults[capability]?.message }}</p>
                  </div>
                  <div v-if="activationResults[capability]" class="operation-result">
                    <div><strong>启用结果</strong><StatusChip :label="resultLabel(activationResults[capability]!)" :status="resultStatus(activationResults[capability]!)" /><span v-if="activationResults[capability]?.latency_ms != null">{{ activationResults[capability]?.latency_ms }} ms</span></div>
                    <p>{{ activationResults[capability]?.message }}</p>
                    <small v-if="activationResults[capability]?.kept_previous">本项新配置未生效，系统继续使用此前可用配置。</small>
                  </div>
                </div>
              </section>
            </div>

            <footer class="config-actions">
              <div><strong>将测试 {{ enabledCapabilityCount }} 项已启用能力</strong><span>停用项会保留配置参数，但不会参与连接测试或后续调用。</span></div>
              <div><el-button :loading="configAction === 'test'" :disabled="Boolean(configAction)" @click="testConfig">仅测试，不启用</el-button><el-button type="primary" :loading="configAction === 'activate'" :disabled="Boolean(configAction)" @click="activateConfig">测试并启用全部配置</el-button></div>
            </footer>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </UiCard>
  </div>
</template>

<style scoped>
.ai-operations-page { display: grid; gap: var(--space-6); }
.operation-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-3); }
.operation-metrics > :deep(.ui-card) { display: grid; align-content: start; gap: var(--space-2); min-width: 0; }
.operation-metrics span, .operation-metrics small { color: var(--ink-400); }
.operation-metrics strong { color: var(--ink-900); font-size: 30px; overflow-wrap: anywhere; }
.operation-metrics .model-name { font-size: 20px; }
.operation-metrics .danger { color: var(--danger); }
.operation-metrics .token-metric strong { color: var(--action-blue); }
.operation-metrics .token-metric small { line-height: 1.45; }
.operations-shell { min-width: 0; }
.filter-row { display: flex; gap: var(--space-3); margin-bottom: var(--space-4); }
.filter-row .el-select { width: 210px; }
.error-line { display: block; overflow: hidden; color: var(--danger); text-overflow: ellipsis; white-space: nowrap; }
.token-cell { color: var(--ink-600); font-variant-numeric: tabular-nums; white-space: nowrap; }
.model-token-usage { margin-top: var(--space-6); padding-top: var(--space-5, 20px); border-top: 1px solid var(--line); }
.model-token-usage > header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-4); }
.model-token-usage h2 { margin: 2px 0 var(--space-1); color: var(--ink-900); font-size: var(--fs-card-title); }
.model-token-usage header p { margin: 0; color: var(--ink-400); font-size: var(--fs-meta); line-height: 1.6; }
.model-token-usage header .config-eyebrow { color: var(--action-blue); font-size: 10px; font-weight: var(--fw-bold); letter-spacing: .12em; }
.model-token-table { border: 1px solid var(--line); border-radius: var(--radius-input); }
.usage-model-name { color: var(--ink-900); overflow-wrap: anywhere; }
.usage-total { color: var(--action-blue); font-variant-numeric: tabular-nums; }
.provider-status { display: grid; grid-template-columns: 1fr 1.5fr 1fr; gap: var(--space-3); margin-bottom: var(--space-4); }
.provider-status > div { display: grid; align-content: start; gap: var(--space-2); padding: var(--space-4); background: var(--surface-muted); border-radius: var(--radius-input); }
.provider-status span, .provider-status small { color: var(--ink-400); }
.provider-status strong { color: var(--ink-900); font-size: 18px; overflow-wrap: anywhere; }
.capability-status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.capability-status-card { min-width: 0; padding: var(--space-4); background: #fff; border: 1px solid var(--line); border-radius: var(--radius-card); }
.capability-status-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.capability-status-card header > div { display: grid; gap: 3px; }
.capability-status-card header span { color: var(--action-blue); font-size: 10px; font-weight: var(--fw-bold); letter-spacing: .12em; }
.capability-status-card p { margin: var(--space-3) 0 var(--space-1); color: var(--ink-900); font-weight: var(--fw-medium); }
.capability-status-card > small { display: block; overflow: hidden; color: var(--ink-400); text-overflow: ellipsis; white-space: nowrap; }
.capability-status-card dl { display: flex; flex-wrap: wrap; gap: var(--space-3); margin: var(--space-3) 0; }
.capability-status-card dl div { display: grid; gap: 2px; }
.capability-status-card dt { color: var(--ink-400); font-size: var(--fs-meta); }
.capability-status-card dd { margin: 0; color: var(--ink-600); font-size: var(--fs-aux); }
.capability-status-card .last-test-message { color: var(--ink-600); font-size: var(--fs-aux); font-weight: var(--fw-regular); }
.capability-status-card time { color: var(--ink-400); font-size: var(--fs-meta); }
.capability-status-card .empty-capability { color: var(--ink-400); font-weight: var(--fw-regular); }
.config-form { display: grid; gap: var(--space-4); padding-top: var(--space-2); }
.provider-config-panel { padding: var(--space-6); background: linear-gradient(135deg, #f7faff, #f4f7fb); border: 1px solid var(--action-line); border-radius: var(--radius-card); }
.provider-config-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-4); }
.provider-config-heading h2 { margin: 2px 0 var(--space-2); color: var(--ink-900); font-size: var(--fs-section); }
.provider-config-heading p { max-width: 720px; margin: 0; color: var(--ink-600); line-height: 1.65; }
.provider-config-heading .config-eyebrow { color: var(--action-blue); font-size: 10px; font-weight: var(--fw-bold); letter-spacing: .14em; }
.provider-description, .key-hint { margin: calc(var(--space-2) * -1) 0 var(--space-4); color: var(--ink-400); font-size: var(--fs-meta); line-height: 1.6; }
.key-hint { margin: var(--space-2) 0 0; }
.capability-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.capability-form-card { min-width: 0; padding: var(--space-5, 20px); background: #fff; border: 1px solid var(--line); border-radius: var(--radius-card); box-shadow: var(--shadow-1); transition: border-color .18s ease, opacity .18s ease; }
.capability-form-card.disabled { opacity: .72; box-shadow: none; }
.capability-form-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-4); }
.capability-heading { display: flex; min-width: 0; align-items: flex-start; gap: var(--space-3); }
.capability-heading > span { flex: none; padding: 5px 7px; color: var(--action-blue); background: var(--action-soft); border: 1px solid var(--action-line); border-radius: 6px; font-size: 9px; font-weight: var(--fw-bold); letter-spacing: .08em; }
.capability-heading h3 { margin: 0 0 4px; color: var(--ink-900); font-size: var(--fs-card-title); }
.capability-heading p { margin: 0; color: var(--ink-400); font-size: var(--fs-meta); line-height: 1.55; }
.capability-fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(150px, .55fr); gap: 0 var(--space-3); }
.capability-fields .full-field { grid-column: 1 / -1; }
.capability-fields :deep(.el-input-number) { width: 100%; }
.operation-results { display: grid; gap: var(--space-2); margin-top: var(--space-2); padding-top: var(--space-3); border-top: 1px dashed var(--line); }
.operation-result { padding: var(--space-3); background: var(--surface-muted); border-radius: var(--radius-input); }
.operation-result > div { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.operation-result > div > span:last-child { color: var(--ink-400); font-size: var(--fs-meta); }
.operation-result p, .operation-result small { display: block; margin: var(--space-2) 0 0; color: var(--ink-600); font-size: var(--fs-aux); line-height: 1.55; }
.operation-result small { color: var(--highlight-gold); }
.config-actions { position: sticky; z-index: 2; bottom: 0; display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4); background: rgb(255 255 255 / 96%); border: 1px solid var(--line); border-radius: var(--radius-card); box-shadow: 0 -8px 24px rgb(32 33 36 / 8%); backdrop-filter: blur(12px); }
.config-actions > div:first-child { display: grid; gap: 3px; }
.config-actions span { color: var(--ink-400); font-size: var(--fs-meta); }
.config-actions > div:last-child { display: flex; gap: var(--space-2); }
@media (max-width: 1023px) {
  .operation-metrics, .capability-status-grid, .capability-form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .operation-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .provider-status { grid-template-columns: 1fr; }
}
@media (max-width: 767px) {
  .operation-metrics, .capability-status-grid, .capability-form-grid { grid-template-columns: 1fr; }
  .filter-row, .provider-config-heading, .config-actions { align-items: stretch; flex-direction: column; }
  .model-token-usage > header { align-items: stretch; flex-direction: column; }
  .filter-row .el-select { width: 100%; }
  .provider-config-panel { padding: var(--space-4); }
  .provider-config-heading .el-button { width: 100%; }
  .capability-fields { grid-template-columns: 1fr; }
  .capability-fields .full-field { grid-column: auto; }
  .config-actions { position: static; }
  .config-actions > div:last-child { display: grid; }
}
</style>

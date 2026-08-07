<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { aiOperationsApi, type AiCallLog, type AiOperationSummary, type AiProviderConfig } from '@/api/aiOperations'
import StatusChip from '@/components/ui/StatusChip.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { getErrorMessage } from '@/utils/error'

const loading = ref(true)
const acting = ref(false)
const activeTab = ref('calls')
const calls = ref<AiCallLog[]>([])
const config = ref<AiProviderConfig | null>(null)
const summary = ref<AiOperationSummary>({ total_24h: 0, success_24h: 0, failed_24h: 0, running: 0, average_latency_ms: null, success_rate: 1, active_model: '—', config_source: 'environment' })
const filters = reactive({ status: '', feature: '' })
const form = reactive({ base_url: '', model_name: '', api_key: '', temperature: 0.2, timeout_seconds: 60, streaming_enabled: true })

const features = computed(() => Array.from(new Set(calls.value.map((item) => item.feature))).sort())
const featureLabels: Record<string, string> = {
  learning_assist: '学习辅助/笔记写作', agent_planning: 'Agent 规划', agent_response: 'Agent 总结',
  lesson_outline: '课纲生成', lesson_artifacts: '教学成果生成', ppt_design: 'PPT 设计',
  ppt_quality_review: 'PPT 质量检查', ppt_slide_revision: 'PPT 单页修改', material_association: '资料教材关联',
}

function featureLabel(value: string) { return featureLabels[value] || value }
function statusLabel(value: string) { return ({ running: '运行中', success: '成功', failed: '失败' } as Record<string, string>)[value] || value }
function statusType(value: string) { return value === 'success' ? 'success' : value === 'failed' ? 'danger' : 'info' }
function formatDateTime(value: string | null) { return value ? new Date(`${value}${/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? '' : 'Z'}`).toLocaleString('zh-CN', { hour12: false }) : '—' }
function payload() {
  return {
    base_url: form.base_url.trim(), model_name: form.model_name.trim(),
    api_key: form.api_key.trim() || undefined, temperature: form.temperature,
    timeout_seconds: form.timeout_seconds, streaming_enabled: form.streaming_enabled,
  }
}

async function loadCalls() {
  const response = await aiOperationsApi.calls({ status: filters.status || undefined, feature: filters.feature || undefined, limit: 200 })
  calls.value = response.data.data
}

async function load() {
  loading.value = true
  try {
    const [summaryResult, configResult] = await Promise.all([aiOperationsApi.summary(), aiOperationsApi.config()])
    summary.value = summaryResult.data.data
    config.value = configResult.data.data
    Object.assign(form, {
      base_url: config.value.base_url || '', model_name: config.value.model_name,
      api_key: '', temperature: config.value.temperature, timeout_seconds: config.value.timeout_seconds,
      streaming_enabled: config.value.streaming_enabled,
    })
    await loadCalls()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, 'AI 运行数据加载失败')) }
  finally { loading.value = false }
}

async function refreshCalls() {
  acting.value = true
  try { await Promise.all([loadCalls(), aiOperationsApi.summary().then((result) => { summary.value = result.data.data })]) }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '调用记录刷新失败')) }
  finally { acting.value = false }
}

async function testConfig() {
  acting.value = true
  try {
    const response = await aiOperationsApi.testConfig(payload())
    ElMessage.success(response.data.data.message)
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '模型连接测试失败')) }
  finally { acting.value = false }
}

async function activateConfig() {
  acting.value = true
  try {
    const response = await aiOperationsApi.activateConfig(payload())
    config.value = response.data.data
    form.api_key = ''
    ElMessage.success('新配置已测试并启用，将影响后续所有 AI 请求')
    await refreshCalls()
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, 'AI 服务配置启用失败')) }
  finally { acting.value = false }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="ai-operations-page">
    <UiPageHeader eyebrow="AI OPERATIONS" title="AI 运行中心" description="集中查看模型调用、失败原因和服务配置；不记录完整提示词或回答正文。">
      <template #actions><el-button :icon="Refresh" :loading="acting" @click="refreshCalls">刷新状态</el-button></template>
    </UiPageHeader>

    <section class="operation-metrics">
      <UiCard><span>近 24 小时调用</span><strong>{{ summary.total_24h }}</strong><small>成功率 {{ Math.round(summary.success_rate * 100) }}%</small></UiCard>
      <UiCard><span>失败调用</span><strong :class="{ danger: summary.failed_24h }">{{ summary.failed_24h }}</strong><small>{{ summary.running }} 项正在执行</small></UiCard>
      <UiCard><span>平均耗时</span><strong>{{ summary.average_latency_ms === null ? '—' : `${summary.average_latency_ms} ms` }}</strong><small>仅统计已完成请求</small></UiCard>
      <UiCard><span>当前模型</span><strong class="model-name">{{ summary.active_model }}</strong><small>{{ summary.config_source === 'database' ? '管理员配置' : '环境变量配置' }}</small></UiCard>
    </section>

    <UiCard>
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
            <el-table-column label="输入/输出" width="130"><template #default="{ row }">{{ row.input_chars }} / {{ row.output_chars }} 字符</template></el-table-column>
            <el-table-column label="耗时" width="105"><template #default="{ row }">{{ row.latency_ms === null ? '—' : `${row.latency_ms} ms` }}</template></el-table-column>
            <el-table-column label="状态" width="95"><template #default="{ row }"><StatusChip :label="statusLabel(row.status)" :status="statusType(row.status)" /></template></el-table-column>
            <el-table-column label="错误" min-width="220"><template #default="{ row }"><span class="error-line" :title="row.error_message || ''">{{ row.error_message || '—' }}</span></template></el-table-column>
          </el-table>
          <UiEmptyState v-else title="暂无 AI 调用记录" description="接入统一运行配置后的模型请求会显示在这里。" />
        </el-tab-pane>

        <el-tab-pane label="服务状态" name="health">
          <div class="health-grid">
            <div><span>配置来源</span><strong>{{ summary.config_source === 'database' ? '管理员已启用配置' : '服务器环境变量' }}</strong></div>
            <div><span>接口地址</span><strong>{{ config?.base_url || '尚未配置' }}</strong></div>
            <div><span>API Key</span><strong>{{ config?.api_key_masked || '尚未配置' }}</strong></div>
            <div><span>最近测试</span><strong>{{ config?.last_test_message || '尚未通过管理端测试' }}</strong></div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="服务配置" name="config">
          <el-alert title="保存时会先执行最小对话测试；测试失败不会覆盖当前可用配置。留空 API Key 表示继续使用当前密钥。" type="info" :closable="false" show-icon />
          <el-form class="config-form" label-position="top">
            <el-form-item label="OpenAI 兼容接口地址"><el-input v-model="form.base_url" placeholder="例如：https://example.com/v1" /></el-form-item>
            <el-form-item label="模型名称"><el-input v-model="form.model_name" /></el-form-item>
            <el-form-item label="API Key"><el-input v-model="form.api_key" type="password" show-password :placeholder="config?.api_key_masked ? `留空继续使用 ${config.api_key_masked}` : '请输入 API Key'" /></el-form-item>
            <div class="form-grid"><el-form-item label="默认温度"><el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" /></el-form-item><el-form-item label="超时（秒）"><el-input-number v-model="form.timeout_seconds" :min="5" :max="600" /></el-form-item></div>
            <el-form-item><el-switch v-model="form.streaming_enabled" active-text="允许流式输出" inactive-text="统一使用完整响应" /></el-form-item>
            <div class="form-actions"><el-button :loading="acting" @click="testConfig">测试连接</el-button><el-button type="primary" :loading="acting" @click="activateConfig">测试并启用</el-button></div>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </UiCard>
  </div>
</template>

<style scoped>
.ai-operations-page { display: grid; gap: var(--space-6); }
.operation-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); }
.operation-metrics :deep(.ui-card__body) { display: grid; gap: var(--space-2); }
.operation-metrics span, .operation-metrics small { color: var(--ink-500); }
.operation-metrics strong { font-size: 30px; overflow-wrap: anywhere; }
.operation-metrics .model-name { font-size: 20px; }
.operation-metrics .danger { color: var(--danger); }
.filter-row { display: flex; gap: var(--space-3); margin-bottom: var(--space-4); }
.filter-row .el-select { width: 210px; }
.error-line { display: block; overflow: hidden; color: var(--danger); text-overflow: ellipsis; white-space: nowrap; }
.health-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.health-grid > div { display: grid; gap: var(--space-2); padding: var(--space-4); background: var(--surface-muted); border-radius: var(--radius-input); }
.health-grid span { color: var(--ink-500); }
.health-grid strong { overflow-wrap: anywhere; }
.config-form { max-width: 760px; margin-top: var(--space-5); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); }
.form-actions { display: flex; justify-content: flex-end; gap: var(--space-3); }
@media (max-width: 1023px) { .operation-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 767px) { .operation-metrics, .health-grid, .form-grid { grid-template-columns: 1fr; } .filter-row { flex-direction: column; } .filter-row .el-select { width: 100%; } }
</style>

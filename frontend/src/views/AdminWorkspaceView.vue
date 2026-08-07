<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { knowledgeApi, type CandidateDecisionSummary, type KnowledgeDocument, type MaterialCandidate } from '@/api/knowledge'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import EvidenceCard from '@/components/ui/EvidenceCard.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'

const router = useRouter()
const loading = ref(true)
const materials = ref<KnowledgeDocument[]>([])
const pendingCandidates = ref<MaterialCandidate[]>([])
const candidateSummary = ref<CandidateDecisionSummary>({ pending_review: 0, high_priority: 0, observed: 0, filtered: 0 })
const classes = ref<TeachingClass[]>([])
const failed = computed(() => materials.value.filter((item) => item.status === 'failed'))
const activeClasses = computed(() => classes.value.filter((item) => item.status === 'active'))
const centralMaterials = computed(() => materials.value.filter((item) => item.material_type === 'central' && item.review_status === 'published'))

function openPendingCandidates() {
  router.push('/material-discovery?filter=pending_review#candidate-pool')
}

onMounted(async () => {
  try {
    const [materialResult, classResult, candidateResult, summaryResult] = await Promise.allSettled([
      knowledgeApi.materials(),
      teachingClassApi.list(),
      knowledgeApi.discoveryCandidates({ status: 'pending_review', limit: 4 }),
      knowledgeApi.candidateDecisionSummary(),
    ])
    if (materialResult.status === 'fulfilled') materials.value = materialResult.value.data.data
    if (classResult.status === 'fulfilled') classes.value = classResult.value.data.data
    if (candidateResult.status === 'fulfilled') pendingCandidates.value = candidateResult.value.data.data
    if (summaryResult.status === 'fulfilled') candidateSummary.value = summaryResult.value.data.data
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="admin-workspace">
    <UiPageHeader
      eyebrow="ADMIN WORKSPACE"
      title="平台概览"
      description="集中处理资料审核、来源异常和教学运行事项；高风险操作必须保留确认与审计记录。"
    >
      <template #actions><el-button type="primary" @click="openPendingCandidates">处理待审核资料</el-button></template>
    </UiPageHeader>

    <section class="admin-status-grid">
      <UiCard><div class="admin-metric"><StatusChip label="待审核" status="authority" /><strong>{{ candidateSummary.pending_review }}</strong><span>候选资料</span></div></UiCard>
      <UiCard><div class="admin-metric"><StatusChip label="异常" :status="failed.length ? 'danger' : 'success'" /><strong>{{ failed.length }}</strong><span>解析或索引失败</span></div></UiCard>
      <UiCard><div class="admin-metric"><StatusChip label="运行中" status="info" /><strong>{{ activeClasses.length }}</strong><span>活跃教学班</span></div></UiCard>
      <UiCard><div class="admin-metric"><StatusChip label="已发布" status="success" /><strong>{{ centralMaterials.length }}</strong><span>中央材料</span></div></UiCard>
    </section>

    <section class="admin-main-grid">
      <UiCard>
        <template #title><div><p class="eyebrow">REVIEW QUEUE</p><h2>待审核资料</h2></div></template>
        <template #actions><el-button text type="primary" @click="openPendingCandidates">查看全部</el-button></template>
        <div v-if="pendingCandidates.length" class="admin-evidence-list">
          <EvidenceCard
            v-for="item in pendingCandidates"
            :key="item.id"
            :title="item.title"
            :source="item.publisher || `${item.source_level}级来源`"
            :published-date="item.published_date"
            :excerpt="item.content_preview || undefined"
            :source-url="item.source_url"
            :authority="item.source_level === 'A'"
            status-label="待人工确认"
          />
        </div>
        <UiEmptyState v-else title="没有待审核资料" description="权威来源发现的新材料会先进入候选池，不会直接发布。" action-label="进入资料动态" @action="openPendingCandidates" />
      </UiCard>
      <UiCard>
        <template #title><h2>运行关注</h2></template>
        <div class="admin-attention-list">
          <button type="button" @click="router.push('/knowledge')"><strong>{{ failed.length }}</strong><span>资料处理失败<small>查看失败原因并重试</small></span></button>
          <button type="button" @click="router.push('/classes')"><strong>{{ classes.length }}</strong><span>教学班总数<small>管理教师与学生范围</small></span></button>
          <button type="button" @click="router.push('/assignments')"><strong>→</strong><span>任务监督<small>检查发布与完成状态</small></span></button>
        </div>
      </UiCard>
    </section>
  </div>
</template>

<style scoped>
.admin-workspace { display: grid; gap: var(--space-6); }
.admin-status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); }
.admin-metric { display: grid; gap: var(--space-2); }
.admin-metric strong { font-size: 32px; }
.admin-metric > span:last-child { color: var(--ink-600); }
.admin-main-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(280px, .7fr); gap: var(--space-4); align-items: start; }
.admin-main-grid h2 { margin: var(--space-1) 0 0; font-size: var(--fs-section); }
.admin-evidence-list, .admin-attention-list { display: grid; gap: var(--space-3); }
.admin-attention-list button { display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: var(--space-3); align-items: center; width: 100%; padding: var(--space-3); color: var(--ink-900); background: var(--surface-muted); border: 1px solid var(--line); border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.admin-attention-list strong { color: var(--authority-red); font-size: 22px; text-align: center; }
.admin-attention-list span { display: grid; gap: 3px; font-weight: var(--fw-medium); }
.admin-attention-list small { color: var(--ink-400); font-weight: var(--fw-regular); }
@media (max-width: 1023px) { .admin-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .admin-main-grid { grid-template-columns: 1fr; } }
@media (max-width: 767px) { .admin-status-grid { grid-template-columns: 1fr; } }
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeApi, type KnowledgeDocument } from '@/api/knowledge'
import EvidenceCard from '@/components/ui/EvidenceCard.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'

const router = useRouter()
const loading = ref(true)
const acting = ref(false)
const materials = ref<KnowledgeDocument[]>([])
const selectedId = ref<number>()
const filter = ref<'pending' | 'published' | 'failed' | 'all'>('pending')

const filteredMaterials = computed(() => {
  if (filter.value === 'failed') return materials.value.filter((item) => item.status === 'failed')
  if (filter.value === 'all') return materials.value
  return materials.value.filter((item) => item.review_status === filter.value)
})
const selected = computed(() =>
  filteredMaterials.value.find((item) => item.id === selectedId.value)
  || filteredMaterials.value[0]
  || null,
)
const centralPendingCount = computed(() =>
  materials.value.filter((item) => item.material_type === 'central' && item.review_status === 'pending').length,
)

async function load() {
  loading.value = true
  try {
    const response = await knowledgeApi.materials()
    materials.value = response.data.data
    selectedId.value = filteredMaterials.value[0]?.id
  } finally {
    loading.value = false
  }
}

async function publish() {
  if (!selected.value) return
  await ElMessageBox.confirm(
    '发布后该资料可进入教学检索与 AI 引用范围。请确认来源、正文和适用范围均已核验。',
    '确认发布资料',
    { confirmButtonText: '确认发布', cancelButtonText: '继续核验', type: 'warning' },
  )
  acting.value = true
  try {
    await knowledgeApi.publishMaterial(selected.value.id)
    ElMessage.success('资料已发布')
    await load()
  } finally {
    acting.value = false
  }
}

async function archive() {
  if (!selected.value) return
  await ElMessageBox.confirm('归档后该资料将退出当前教学检索范围。', '归档资料', {
    confirmButtonText: '确认归档',
    cancelButtonText: '取消',
    type: 'warning',
  })
  acting.value = true
  try {
    await knowledgeApi.archiveMaterial(selected.value.id)
    ElMessage.success('资料已归档')
    await load()
  } finally {
    acting.value = false
  }
}

function chooseFilter(value: typeof filter.value) {
  filter.value = value
  selectedId.value = filteredMaterials.value[0]?.id
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="material-review-page">
    <UiPageHeader
      eyebrow="MATERIAL GOVERNANCE"
      title="资料审核"
      description="候选资料先核验、后发布。中央材料只表示来源等级，不代表可以跳过人工确认。"
    >
      <template #actions>
        <el-button @click="router.push('/current-affairs')">查看时政线索</el-button>
        <el-button type="primary" @click="router.push('/knowledge')">进入资料中心</el-button>
      </template>
    </UiPageHeader>

    <section class="review-summary">
      <UiCard><div class="review-metric"><span>待审核中央材料</span><strong>{{ centralPendingCount }}</strong></div></UiCard>
      <UiCard><div class="review-metric"><span>全部待审核</span><strong>{{ materials.filter(item => item.review_status === 'pending').length }}</strong></div></UiCard>
      <UiCard><div class="review-metric"><span>索引异常</span><strong>{{ materials.filter(item => item.status === 'failed').length }}</strong></div></UiCard>
    </section>

    <div class="review-filter" role="group" aria-label="资料状态筛选">
      <el-button :type="filter === 'pending' ? 'primary' : 'default'" @click="chooseFilter('pending')">待审核</el-button>
      <el-button :type="filter === 'published' ? 'primary' : 'default'" @click="chooseFilter('published')">已发布</el-button>
      <el-button :type="filter === 'failed' ? 'primary' : 'default'" @click="chooseFilter('failed')">索引异常</el-button>
      <el-button :type="filter === 'all' ? 'primary' : 'default'" @click="chooseFilter('all')">全部</el-button>
    </div>

    <section v-if="filteredMaterials.length" class="review-grid">
      <UiCard class="review-list">
        <template #title><h2>候选资料</h2></template>
        <button
          v-for="item in filteredMaterials"
          :key="item.id"
          type="button"
          :class="['review-list-item', { active: selected?.id === item.id }]"
          @click="selectedId = item.id"
        >
          <StatusChip
            :label="item.material_type === 'central' ? '中央材料' : item.material_type === 'textbook' ? '教材' : '地方材料'"
            :status="item.material_type === 'central' ? 'authority' : 'info'"
          />
          <strong>{{ item.source_title }}</strong>
          <span>{{ item.publisher || item.original_filename }} · {{ item.published_date || '日期待核验' }}</span>
        </button>
      </UiCard>

      <UiCard class="review-evidence">
        <template #title><h2>原文证据</h2></template>
        <EvidenceCard
          v-if="selected"
          :title="selected.source_title"
          :source="selected.publisher || selected.original_filename"
          :published-date="selected.published_date"
          :authority="selected.material_type === 'central'"
          :source-url="selected.source_url"
          :excerpt="selected.applicable_scope || '尚未填写适用范围，请在发布前完成核验。'"
        />
        <dl v-if="selected" class="evidence-metadata">
          <div><dt>索引状态</dt><dd>{{ selected.status }}</dd></div>
          <div><dt>正文分块</dt><dd>{{ selected.chunk_count }}</dd></div>
          <div><dt>知识标签</dt><dd>{{ selected.knowledge_tags.join('、') || '待补充' }}</dd></div>
          <div><dt>版本标识</dt><dd>{{ selected.version_label || '未标注' }}</dd></div>
          <div><dt>内容快照</dt><dd>{{ selected.snapshot_time || '未记录' }}</dd></div>
        </dl>
      </UiCard>

      <UiCard class="review-decision">
        <template #title><h2>审核决定</h2></template>
        <div v-if="selected" class="decision-stack">
          <StatusChip
            :label="selected.review_status === 'pending' ? '等待人工确认' : selected.review_status"
            :status="selected.review_status === 'pending' ? 'warning' : 'success'"
          />
          <p>发布前请确认来源主体、发布日期、正文抓取结果、适用范围与知识标签。</p>
          <el-alert
            v-if="selected.status === 'failed' || !selected.chunk_count"
            title="该资料尚未形成可检索正文，不建议发布"
            type="error"
            :closable="false"
            show-icon
          />
          <el-button
            v-if="selected.review_status === 'pending'"
            type="primary"
            :loading="acting"
            :disabled="selected.status !== 'ready' || !selected.chunk_count"
            @click="publish"
          >
            确认发布
          </el-button>
          <el-button v-if="selected.review_status !== 'archived'" :loading="acting" @click="archive">归档资料</el-button>
          <el-button plain @click="router.push('/knowledge')">编辑分类与适用范围</el-button>
        </div>
      </UiCard>
    </section>

    <UiEmptyState
      v-else
      title="当前筛选下没有资料"
      description="候选资料可以从资料中心上传，或由后续权威材料发现任务进入审核队列。"
      action-label="进入资料中心"
      @action="router.push('/knowledge')"
    />
  </div>
</template>

<style scoped>
.material-review-page { display: grid; gap: var(--space-5); }
.review-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.review-metric { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); color: var(--ink-600); }
.review-metric strong { color: var(--ink-900); font-size: 30px; }
.review-filter { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.review-grid { display: grid; grid-template-columns: minmax(240px, .8fr) minmax(320px, 1.2fr) minmax(240px, .75fr); gap: var(--space-4); align-items: start; }
.review-grid h2 { margin: 0; font-size: var(--fs-section); }
.review-list { display: grid; gap: var(--space-2); max-height: 680px; overflow: auto; }
.review-list-item { display: grid; justify-items: start; gap: var(--space-2); width: 100%; padding: var(--space-3); color: var(--ink-900); background: transparent; border: 1px solid var(--line); border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.review-list-item:hover, .review-list-item.active { background: var(--action-soft); border-color: var(--action-line); }
.review-list-item strong { line-height: 1.55; }
.review-list-item span:last-child { color: var(--ink-400); font-size: var(--fs-meta); }
.evidence-metadata { display: grid; gap: 0; margin: var(--space-4) 0 0; }
.evidence-metadata div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: var(--space-2); padding: var(--space-3) 0; border-bottom: 1px solid var(--line); }
.evidence-metadata dt { color: var(--ink-400); }
.evidence-metadata dd { margin: 0; color: var(--ink-900); overflow-wrap: anywhere; }
.decision-stack { display: grid; justify-items: stretch; gap: var(--space-3); }
.decision-stack p { margin: 0; color: var(--ink-600); line-height: 1.7; }
.decision-stack > :first-child { justify-self: start; }
@media (max-width: 1023px) { .review-grid { grid-template-columns: minmax(230px, .75fr) minmax(0, 1.25fr); } .review-decision { grid-column: 1 / -1; } }
@media (max-width: 767px) { .review-summary, .review-grid { grid-template-columns: 1fr; } .review-decision { grid-column: auto; } }
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, Collection, DocumentChecked, Reading } from '@element-plus/icons-vue'
import { assignmentApi, type TeacherAssignment } from '@/api/assignments'
import { knowledgeApi, type KnowledgeDocument } from '@/api/knowledge'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import StatusChip from '@/components/ui/StatusChip.vue'
import TaskCard from '@/components/ui/TaskCard.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmptyState from '@/components/ui/UiEmptyState.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'

const router = useRouter()
const loading = ref(true)
const assignments = ref<TeacherAssignment[]>([])
const materials = ref<KnowledgeDocument[]>([])
const classes = ref<TeachingClass[]>([])

const activeAssignments = computed(() => assignments.value.filter((item) => item.status === 'published'))
const pendingMaterials = computed(() => materials.value.filter((item) => item.review_status === 'pending'))
const readyMaterials = computed(() => materials.value.filter((item) => item.status === 'ready'))
const activeClass = computed(() => classes.value.find((item) => item.is_default) || classes.value.find((item) => item.status === 'active') || classes.value[0])
const completionRate = computed(() => {
  const total = activeAssignments.value.reduce((sum, item) => sum + item.total_count, 0)
  const completed = activeAssignments.value.reduce((sum, item) => sum + item.completed_count, 0)
  return total ? Math.round(completed / total * 100) : 0
})

onMounted(async () => {
  try {
    const [assignmentResult, materialResult, classResult] = await Promise.allSettled([
      assignmentApi.teacher(),
      knowledgeApi.materials(),
      teachingClassApi.list(),
    ])
    if (assignmentResult.status === 'fulfilled') assignments.value = assignmentResult.value.data.data
    if (materialResult.status === 'fulfilled') materials.value = materialResult.value.data.data
    if (classResult.status === 'fulfilled') classes.value = classResult.value.data.data
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="role-workspace">
    <UiPageHeader
      eyebrow="TEACHER WORKSPACE"
      title="教学工作台"
      :description="`${activeClass?.name || '当前教学班'} · 今天只呈现需要备课、发布和审核的事项。`"
    >
      <template #actions>
        <el-button type="primary" @click="router.push('/lesson-prep')">开始智能备课</el-button>
      </template>
    </UiPageHeader>

    <section class="workspace-summary-grid" aria-label="教学概况">
      <UiCard><div class="summary-metric"><span>进行中任务</span><strong>{{ activeAssignments.length }}</strong><small>进入课堂教学查看明细</small></div></UiCard>
      <UiCard><div class="summary-metric"><span>学生平均完成率</span><strong>{{ completionRate }}%</strong><small>按真实学习行为统计</small></div></UiCard>
      <UiCard><div class="summary-metric"><span>待审核资料</span><strong>{{ pendingMaterials.length }}</strong><small>发布前必须人工确认</small></div></UiCard>
      <UiCard><div class="summary-metric"><span>可用证据资料</span><strong>{{ readyMaterials.length }}</strong><small>教材与权威材料合计</small></div></UiCard>
    </section>

    <section class="workspace-main-grid">
      <UiCard class="workspace-primary-panel">
        <template #title>
          <p class="eyebrow">TODAY</p>
          <h2>今日待办</h2>
        </template>
        <template #actions><el-button text type="primary" @click="router.push('/assignments')">查看全部</el-button></template>
        <div v-if="activeAssignments.length" class="workspace-task-list">
          <TaskCard
            v-for="item in activeAssignments.slice(0, 3)"
            :key="item.id"
            eyebrow="课堂任务"
            :title="item.title"
            :description="`${item.chapter_title} · ${item.completed_count}/${item.total_count} 人完成`"
            :status-label="item.overdue_count ? `${item.overdue_count} 人逾期` : '进行中'"
            :status="item.overdue_count ? 'danger' : 'info'"
            :progress="item.total_count ? Math.round(item.completed_count / item.total_count * 100) : 0"
            action-label="查看完成情况"
            @action="router.push('/assignments')"
          />
        </div>
        <UiEmptyState
          v-else
          title="今天没有进行中的课堂任务"
          description="可以从当前课程专题创建一次预习、讨论或笔记任务。"
          action-label="布置任务"
          @action="router.push('/assignments')"
        />
      </UiCard>

      <aside class="workspace-side-stack">
        <UiCard>
          <template #title><h2>资料变化</h2></template>
          <div class="workspace-change-count">
            <StatusChip label="需人工确认" status="authority" />
            <strong>{{ pendingMaterials.length }}</strong>
            <p>候选资料不会直接影响教学内容，确认后才进入正式资料范围。</p>
            <el-button plain type="primary" @click="router.push('/material-review')">进入资料审核</el-button>
          </div>
        </UiCard>
        <UiCard>
          <template #title><h2>快速开始</h2></template>
          <nav class="workspace-quick-actions" aria-label="教师快速操作">
            <button type="button" @click="router.push('/lesson-prep')"><el-icon><Reading /></el-icon><span>准备一节课<small>选择专题并构建证据包</small></span></button>
            <button type="button" @click="router.push('/assignments')"><el-icon><Bell /></el-icon><span>发布课堂任务<small>确认教学班与截止时间</small></span></button>
            <button type="button" @click="router.push('/interaction')"><el-icon><DocumentChecked /></el-icon><span>审核学生观点<small>查看讨论与共建内容</small></span></button>
            <button type="button" @click="router.push('/courses')"><el-icon><Collection /></el-icon><span>查看教材专题<small>定位章节与知识点</small></span></button>
          </nav>
        </UiCard>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.role-workspace { display: grid; gap: var(--space-6); }
.workspace-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); }
.summary-metric { display: grid; gap: var(--space-2); }
.summary-metric span, .summary-metric small { color: var(--ink-600); }
.summary-metric strong { color: var(--ink-900); font-size: 30px; line-height: 1; }
.workspace-main-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, .8fr); gap: var(--space-4); align-items: start; }
.workspace-primary-panel h2, .workspace-side-stack h2 { margin: var(--space-1) 0 0; font-size: var(--fs-section); }
.workspace-task-list, .workspace-side-stack { display: grid; gap: var(--space-3); }
.workspace-change-count { display: grid; gap: var(--space-3); }
.workspace-change-count strong { color: var(--authority-red); font-size: 38px; }
.workspace-change-count p { margin: 0; color: var(--ink-600); line-height: 1.65; }
.workspace-quick-actions { display: grid; gap: var(--space-2); }
.workspace-quick-actions button { display: flex; width: 100%; align-items: center; gap: var(--space-3); padding: var(--space-3); color: var(--ink-900); background: transparent; border: 1px solid transparent; border-radius: var(--radius-input); cursor: pointer; text-align: left; }
.workspace-quick-actions button:hover { background: var(--action-soft); border-color: var(--action-line); }
.workspace-quick-actions .el-icon { flex: 0 0 34px; height: 34px; color: var(--action-blue); background: var(--action-soft); border-radius: var(--radius-input); }
.workspace-quick-actions span { display: grid; gap: 3px; font-weight: var(--fw-medium); }
.workspace-quick-actions small { color: var(--ink-400); font-weight: var(--fw-regular); }
@media (max-width: 1023px) { .workspace-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .workspace-main-grid { grid-template-columns: 1fr; } }
@media (max-width: 767px) { .workspace-summary-grid { grid-template-columns: 1fr; } }
</style>


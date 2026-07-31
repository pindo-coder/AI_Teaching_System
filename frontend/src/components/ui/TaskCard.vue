<script setup lang="ts">
import { ArrowRight } from '@element-plus/icons-vue'
import StatusChip from './StatusChip.vue'
import type { SemanticStatus } from '@/types/workspace'

withDefaults(defineProps<{
  eyebrow?: string
  title: string
  description?: string
  statusLabel?: string
  status?: SemanticStatus
  meta?: string
  actionLabel?: string
  progress?: number
}>(), {
  status: 'neutral',
  actionLabel: '进入处理',
})

defineEmits<{ action: [] }>()
</script>

<template>
  <article class="task-card">
    <div class="task-card__body">
      <div class="task-card__topline">
        <span v-if="eyebrow" class="task-card__eyebrow">{{ eyebrow }}</span>
        <StatusChip v-if="statusLabel" :label="statusLabel" :status="status" />
      </div>
      <h3>{{ title }}</h3>
      <p v-if="description">{{ description }}</p>
      <small v-if="meta">{{ meta }}</small>
      <el-progress v-if="typeof progress === 'number'" :percentage="progress" :show-text="false" />
    </div>
    <el-button type="primary" plain @click="$emit('action')">
      {{ actionLabel }}<el-icon><ArrowRight /></el-icon>
    </el-button>
  </article>
</template>

<style scoped>
.task-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--surface-card);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}

.task-card__body {
  display: grid;
  min-width: 0;
  gap: var(--space-2);
}

.task-card__topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.task-card__eyebrow {
  color: var(--ink-400);
  font-size: var(--fs-meta);
  font-weight: var(--fw-medium);
}

.task-card h3,
.task-card p {
  margin: 0;
}

.task-card h3 {
  font-size: var(--fs-card-title);
  line-height: 1.45;
}

.task-card p,
.task-card small {
  color: var(--ink-600);
  line-height: 1.6;
}

.task-card small {
  font-size: var(--fs-meta);
}

@media (max-width: 767px) {
  .task-card {
    grid-template-columns: 1fr;
  }

  .task-card .el-button {
    width: 100%;
  }
}
</style>


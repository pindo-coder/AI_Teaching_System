<script setup lang="ts">
import { Link } from '@element-plus/icons-vue'
import StatusChip from './StatusChip.vue'

withDefaults(defineProps<{
  title: string
  source: string
  publishedDate?: string | null
  excerpt?: string
  authority?: boolean
  statusLabel?: string
  sourceUrl?: string | null
}>(), {
  authority: false,
})
</script>

<template>
  <article class="evidence-card">
    <div class="evidence-card__source">
      <StatusChip :label="statusLabel || (authority ? '中央材料' : '课程资料')" :status="authority ? 'authority' : 'info'" />
      <span>{{ source }}</span>
      <time v-if="publishedDate">{{ publishedDate }}</time>
    </div>
    <h3>{{ title }}</h3>
    <p v-if="excerpt">{{ excerpt }}</p>
    <a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener noreferrer">
      <el-icon><Link /></el-icon>核验原文
    </a>
    <slot />
  </article>
</template>

<style scoped>
.evidence-card {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--surface-card);
  border: 1px solid var(--line);
  border-left: 3px solid var(--authority-red);
  border-radius: var(--radius-card);
}

.evidence-card__source {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-400);
  font-size: var(--fs-meta);
}

.evidence-card h3,
.evidence-card p {
  margin: 0;
}

.evidence-card h3 {
  font-size: var(--fs-card-title);
  line-height: 1.55;
}

.evidence-card p {
  color: var(--ink-600);
  line-height: 1.7;
}

.evidence-card a {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-aux);
  font-weight: var(--fw-medium);
  text-decoration: none;
}
</style>


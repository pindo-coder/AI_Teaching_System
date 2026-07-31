<script setup lang="ts">
import type { SemanticStatus } from '@/types/workspace'

withDefaults(defineProps<{
  label: string
  status?: SemanticStatus
}>(), {
  status: 'neutral',
})
</script>

<template>
  <span :class="['status-chip', `status-chip--${status}`]">
    <span class="status-chip__dot" aria-hidden="true"></span>
    {{ label }}
  </span>
</template>

<style scoped>
.status-chip {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 10px;
  color: var(--ink-600);
  background: var(--surface-muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: var(--fs-meta);
  font-weight: var(--fw-medium);
  line-height: 1;
  white-space: nowrap;
}

.status-chip__dot {
  width: 7px;
  height: 7px;
  background: currentcolor;
  border-radius: 50%;
}

.status-chip--authority { color: var(--authority-red); background: var(--authority-soft); border-color: var(--authority-line); }
.status-chip--info { color: var(--action-blue); background: var(--action-soft); border-color: var(--action-line); }
.status-chip--warning { color: var(--highlight-gold); background: var(--highlight-soft); border-color: var(--highlight-line); }
.status-chip--success { color: var(--color-success); background: var(--color-success-bg); border-color: #b7dfc4; }
.status-chip--danger { color: var(--color-danger); background: var(--color-danger-bg); border-color: #f2b8b5; }
</style>


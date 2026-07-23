<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  description?: string
}>()
</script>

<template>
  <div class="ui-stat-card">
    <div v-if="$slots.icon" class="ui-stat-card__icon"><slot name="icon" /></div>
    <div>
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
      <small v-if="description">{{ description }}</small>
    </div>
  </div>
</template>

<style scoped>
.ui-stat-card {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  color: var(--ink-900);
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}

.ui-stat-card > div:last-child {
  display: grid;
  min-width: 0;
  gap: var(--space-1);
}

.ui-stat-card span,
.ui-stat-card small {
  color: var(--ink-400);
  font-size: var(--fs-meta);
}

.ui-stat-card strong {
  color: var(--ink-900);
  font-size: var(--fs-section);
}

.ui-stat-card__icon {
  display: grid;
  flex: 0 0 36px;
  height: 36px;
  place-items: center;
  color: var(--color-primary);
  background: var(--blue-50);
  border-radius: var(--radius-input);
}
</style>

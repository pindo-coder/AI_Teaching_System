<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  description: string
  actionLabel?: string
}>(), {})

defineEmits<{ action: [] }>()
</script>

<template>
  <div class="ui-empty-state">
    <div class="ui-empty-state__mark" aria-hidden="true">—</div>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <el-button v-if="actionLabel" type="primary" plain @click="$emit('action')">{{ actionLabel }}</el-button>
  </div>
</template>

<style scoped>
.ui-empty-state {
  display: grid;
  min-height: 220px;
  place-items: center;
  align-content: center;
  gap: var(--space-2);
  padding: var(--space-8);
  color: var(--ink-600);
  background: var(--surface-muted);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-card);
  text-align: center;
}

.ui-empty-state__mark {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  color: var(--action-blue);
  background: var(--action-soft);
  border-radius: var(--radius-input);
  font-size: 24px;
}

.ui-empty-state h3,
.ui-empty-state p {
  max-width: 440px;
  margin: 0;
}

.ui-empty-state p {
  line-height: 1.65;
}
</style>

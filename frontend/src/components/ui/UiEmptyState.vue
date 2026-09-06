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
    <div class="ui-empty-state__illustration" aria-hidden="true"></div>
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

.ui-empty-state__illustration {
  width: min(210px, 100%);
  height: 145px;
  background: url('../../assets/empty-state-original.svg') center / contain no-repeat;
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

<script setup lang="ts">
withDefaults(defineProps<{
  interactive?: boolean
  padded?: boolean
}>(), {
  interactive: false,
  padded: true,
})
</script>

<template>
  <article :class="['ui-card', { 'ui-card--interactive': interactive, 'ui-card--padded': padded }]">
    <header v-if="$slots.title || $slots.actions" class="ui-card__header">
      <div><slot name="title" /></div>
      <div v-if="$slots.actions" class="ui-card__actions"><slot name="actions" /></div>
    </header>
    <slot />
  </article>
</template>

<style scoped>
.ui-card {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}

.ui-card--padded {
  padding: var(--space-6);
}

.ui-card--interactive {
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.ui-card--interactive:hover {
  box-shadow: var(--shadow-1);
  transform: translateY(-2px);
}

.ui-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.ui-card__actions {
  flex: none;
}
</style>

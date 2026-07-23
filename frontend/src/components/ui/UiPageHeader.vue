<script setup lang="ts">
defineProps<{
  eyebrow?: string
  title: string
  description?: string
}>()
</script>

<template>
  <header class="ui-page-header">
    <div class="ui-page-header__copy">
      <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p v-if="description" class="ui-page-header__description">{{ description }}</p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="ui-page-header__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.ui-page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
  margin-bottom: var(--space-6);
}

.ui-page-header h1 {
  margin: var(--space-1) 0 var(--space-2);
  font-size: var(--fs-page-title);
  line-height: 1.3;
}

.ui-page-header p {
  margin: 0;
}

.ui-page-header__description {
  max-width: 720px;
  color: var(--ink-600);
  line-height: 1.7;
}

.ui-page-header__actions {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  gap: var(--space-2);
}

@media (max-width: 767px) {
  .ui-page-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

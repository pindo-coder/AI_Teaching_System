<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'dashboard' | 'course' | 'auth'
}>(), {
  variant: 'dashboard',
})
</script>

<template>
  <section :class="['ui-hero', `ui-hero--${variant}`, { 'ui-hero--single': !$slots.visual }]">
    <div class="ui-hero__copy"><slot /></div>
    <div v-if="$slots.visual" class="ui-hero__visual"><slot name="visual" /></div>
  </section>
</template>

<style scoped>
.ui-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.7fr);
  align-items: center;
  gap: var(--space-8);
  min-height: 260px;
  padding: clamp(28px, 4vw, 44px);
  overflow: hidden;
  color: #fff;
  background: var(--hero-gradient);
  border-radius: var(--radius-overlay);
}

.ui-hero--course {
  grid-template-columns: minmax(0, 1.5fr) minmax(250px, 0.55fr);
}

.ui-hero--auth {
  min-height: 420px;
}

.ui-hero--single {
  grid-template-columns: 1fr;
}

.ui-hero :deep(h1),
.ui-hero :deep(h2),
.ui-hero :deep(h3) {
  color: #fff;
}

.ui-hero__copy,
.ui-hero__visual {
  min-width: 0;
}

@media (max-width: 1023px) {
  .ui-hero {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .ui-hero {
    gap: var(--space-6);
    min-height: 0;
    padding: var(--space-6);
    border-radius: var(--radius-card);
  }

  .ui-hero :deep(h1) {
    font-size: 24px;
  }
}
</style>

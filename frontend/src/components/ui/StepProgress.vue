<script setup lang="ts">
defineProps<{
  steps: string[]
  current: number
}>()
</script>

<template>
  <ol class="step-progress" aria-label="任务步骤">
    <li
      v-for="(step, index) in steps"
      :key="step"
      :class="{ active: index === current, completed: index < current }"
      :aria-current="index === current ? 'step' : undefined"
    >
      <span>{{ index < current ? '✓' : index + 1 }}</span>
      <strong>{{ step }}</strong>
    </li>
  </ol>
</template>

<style scoped>
.step-progress {
  display: grid;
  grid-template-columns: repeat(var(--step-count, 5), minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-progress li {
  position: relative;
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  color: var(--ink-400);
  font-size: var(--fs-meta);
  text-align: center;
}

.step-progress li::before {
  position: absolute;
  z-index: 0;
  top: 15px;
  right: 50%;
  left: -50%;
  height: 2px;
  content: "";
  background: var(--line);
}

.step-progress li:first-child::before {
  display: none;
}

.step-progress span {
  z-index: 1;
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  background: var(--surface-card);
  border: 2px solid var(--line);
  border-radius: 50%;
  font-weight: var(--fw-bold);
}

.step-progress li.active,
.step-progress li.completed {
  color: var(--action-blue);
}

.step-progress li.active span,
.step-progress li.completed span {
  color: #fff;
  background: var(--action-blue);
  border-color: var(--action-blue);
}

.step-progress li.completed::before,
.step-progress li.active::before {
  background: var(--action-blue);
}

@media (max-width: 767px) {
  .step-progress {
    grid-template-columns: 1fr;
    gap: var(--space-3);
  }

  .step-progress li {
    grid-template-columns: 32px minmax(0, 1fr);
    align-items: center;
    justify-items: start;
    text-align: left;
  }

  .step-progress li::before {
    top: -12px;
    right: auto;
    bottom: calc(100% - 2px);
    left: 15px;
    width: 2px;
    height: auto;
  }
}
</style>


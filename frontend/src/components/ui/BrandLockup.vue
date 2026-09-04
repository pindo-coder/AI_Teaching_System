<script setup lang="ts">
import logoUrl from '@/assets/logo1.svg'

withDefaults(defineProps<{
  title?: string
  subtitle?: string
  tone?: 'dark' | 'light'
  compact?: boolean
}>(), {
  title: '思政红芯',
  subtitle: '思政智教 · 思政教学平台',
  tone: 'dark',
  compact: false,
})
</script>

<template>
  <span class="brand-lockup" :class="[`brand-lockup--${tone}`, { 'brand-lockup--compact': compact }]">
    <img class="brand-lockup__mark" :src="logoUrl" alt="" aria-hidden="true" />
    <span class="brand-lockup__copy">
      <strong>{{ title }}</strong>
      <small v-if="subtitle">{{ subtitle }}</small>
    </span>
  </span>
</template>

<style scoped>
.brand-lockup {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  color: var(--ink-900, #552b31);
  text-decoration: none;
}

.brand-lockup__mark {
  display: block;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  padding: 4px;
  object-fit: contain;
  background: #fff5f2;
  border: 1px solid #ffd0cc;
  border-radius: 12px;
}

.brand-lockup__copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.brand-lockup__copy strong {
  overflow: hidden;
  color: var(--ink-900, #552b31);
  font-size: 18px;
  font-weight: 750;
  letter-spacing: .04em;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brand-lockup__copy small {
  overflow: hidden;
  color: var(--ink-400, #7b8188);
  font-size: 10px;
  letter-spacing: .08em;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brand-lockup--light .brand-lockup__mark {
  background: rgb(255 255 255 / 92%);
  border-color: rgb(255 255 255 / 72%);
  box-shadow: 0 8px 22px rgb(120 0 20 / 16%);
}

.brand-lockup--light .brand-lockup__copy strong { color: #fff; text-shadow: 0 2px 12px rgb(120 0 20 / 20%); }
.brand-lockup--light .brand-lockup__copy small { color: rgb(255 255 255 / 82%); }

.brand-lockup--compact { gap: 8px; }
.brand-lockup--compact .brand-lockup__mark { width: 36px; height: 36px; padding: 3px; border-radius: 10px; }
.brand-lockup--compact .brand-lockup__copy strong { font-size: 16px; }
.brand-lockup--compact .brand-lockup__copy small { font-size: 9px; }
</style>

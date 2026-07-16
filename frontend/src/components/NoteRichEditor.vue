<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { sanitizeNoteHtml } from '@/utils/noteContent'

const props = defineProps<{ modelValue: string; fontScale?: number; lineHeight?: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const editable = ref<HTMLElement | null>(null)

function syncFromModel() {
  if (!editable.value || document.activeElement === editable.value) return
  const safe = sanitizeNoteHtml(props.modelValue)
  if (editable.value.innerHTML !== safe) editable.value.innerHTML = safe
}
function emitContent() {
  if (editable.value) emit('update:modelValue', sanitizeNoteHtml(editable.value.innerHTML))
}
function command(name: string, value?: string) {
  editable.value?.focus()
  document.execCommand(name, false, value)
  emitContent()
}
function setBlock(tag: 'p' | 'h2' | 'h3') { command('formatBlock', tag) }
function setFontSize(size: number) {
  editable.value?.focus()
  document.execCommand('fontSize', false, '7')
  editable.value?.querySelectorAll('font[size="7"]').forEach((font) => {
    const span = document.createElement('span')
    span.style.fontSize = `${size}px`
    span.innerHTML = font.innerHTML
    font.replaceWith(span)
  })
  emitContent()
}
function highlight(color: string) { command('hiliteColor', color) }
function onPaste(event: ClipboardEvent) {
  event.preventDefault()
  command('insertText', event.clipboardData?.getData('text/plain') || '')
}

defineExpose({ command, setBlock, setFontSize, highlight, focus: () => editable.value?.focus() })
watch(() => props.modelValue, () => void nextTick(syncFromModel))
onMounted(syncFromModel)
</script>

<template>
  <div class="rich-note-shell">
    <div
      ref="editable"
      class="rich-note-editor"
      contenteditable="true"
      role="textbox"
      aria-multiline="true"
      data-placeholder="按照章节主旨、核心观点、概念关系和现实意义整理笔记……"
      :style="{ fontSize: `${16 * (fontScale || 1)}px`, lineHeight: String(lineHeight || 1.9) }"
      @input="emitContent"
      @blur="emitContent"
      @paste="onPaste"
    ></div>
  </div>
</template>

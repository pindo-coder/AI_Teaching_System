<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { sanitizeNoteHtml } from '@/utils/noteContent'

const props = defineProps<{ modelValue: string; fontScale?: number; lineHeight?: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const editable = ref<HTMLElement | null>(null)
let savedRange: Range | null = null

function rememberSelection() {
  const root = editable.value
  const selection = window.getSelection()
  if (!root || !selection?.rangeCount || !selection.anchorNode || !root.contains(selection.anchorNode)) return
  savedRange = selection.getRangeAt(0).cloneRange()
}
function rememberSelectionBeforeBlur(event: MouseEvent) {
  const root = editable.value
  const target = event.target
  if (!root || !(target instanceof Node) || root.contains(target)) return
  rememberSelection()
}
function restoreSelection() {
  if (!savedRange || !editable.value) return
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(savedRange)
}

function syncFromModel() {
  if (!editable.value || document.activeElement === editable.value) return
  const safe = sanitizeNoteHtml(props.modelValue)
  if (editable.value.innerHTML !== safe) editable.value.innerHTML = safe
}
function emitContent() {
  if (editable.value) emit('update:modelValue', sanitizeNoteHtml(editable.value.innerHTML))
}
function command(name: string, value?: string) {
  restoreSelection()
  editable.value?.focus()
  restoreSelection()
  document.execCommand(name, false, value)
  emitContent()
}
function setBlock(tag: 'p' | 'h2' | 'h3') { command('formatBlock', tag) }
function setFontSize(size: number) {
  restoreSelection()
  editable.value?.focus()
  restoreSelection()
  document.execCommand('fontSize', false, '7')
  editable.value?.querySelectorAll('font[size="7"]').forEach((font) => {
    const span = document.createElement('span')
    span.style.fontSize = `${size}px`
    span.innerHTML = font.innerHTML
    font.replaceWith(span)
  })
  emitContent()
}
function toggleItalic() {
  const root = editable.value
  if (!root) return
  restoreSelection()
  root.focus()
  restoreSelection()
  const selection = window.getSelection()
  if (!selection?.rangeCount) return
  if (selection.isCollapsed) {
    // 保留“先点斜体、再输入”的编辑习惯：折叠光标时交给浏览器维护输入状态。
    document.execCommand('italic', false)
    emitContent()
    return
  }
  const range = selection.getRangeAt(0)
  if (!root.contains(range.commonAncestorContainer)) return

  let ancestor: HTMLElement | null = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer as HTMLElement
    : range.commonAncestorContainer.parentElement
  while (ancestor && ancestor !== root && !['EM', 'I'].includes(ancestor.tagName)) ancestor = ancestor.parentElement

  if (ancestor && ancestor !== root && ['EM', 'I'].includes(ancestor.tagName)) {
    const fragment = document.createDocumentFragment()
    while (ancestor.firstChild) fragment.appendChild(ancestor.firstChild)
    ancestor.replaceWith(fragment)
  } else {
    const italic = document.createElement('em')
    italic.appendChild(range.extractContents())
    range.insertNode(italic)
    const nextRange = document.createRange()
    nextRange.selectNodeContents(italic)
    selection.removeAllRanges()
    selection.addRange(nextRange)
  }
  emitContent()
}
function highlight(color: string) { command('hiliteColor', color) }
function onPaste(event: ClipboardEvent) {
  event.preventDefault()
  command('insertText', event.clipboardData?.getData('text/plain') || '')
}

function scrollToHeading(index: number) {
  const heading = editable.value?.querySelectorAll<HTMLElement>('h2, h3')[index]
  heading?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

defineExpose({ command, setBlock, setFontSize, toggleItalic, highlight, scrollToHeading, rememberSelection, focus: () => editable.value?.focus() })
watch(() => props.modelValue, () => void nextTick(syncFromModel))
onMounted(syncFromModel)
onMounted(() => document.addEventListener('selectionchange', rememberSelection))
onMounted(() => document.addEventListener('mousedown', rememberSelectionBeforeBlur, true))
onBeforeUnmount(() => {
  document.removeEventListener('selectionchange', rememberSelection)
  document.removeEventListener('mousedown', rememberSelectionBeforeBlur, true)
})
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
